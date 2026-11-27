"""THROWAWAY SPIKE: a read-only cfdb store that reads an ebooklet remote and caches compressed
chunks in MongoDB. Not production code. Answers: do ebooklet's remote fetchers drop in, and what
do cold/warm reads cost?

Cache entries are keyed by (db_url, chunk key, remote per-key timestamp), so they are immutable:
a revised chunk gets a new id and the stale one is simply never asked for again.
"""
import collections
import datetime
import os
import pathlib
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import booklet
import ebooklet
from bson.binary import Binary
from cfdb import main as cmain
from ebooklet import utils as eu
from pymongo.errors import BulkWriteError

MONGO_DOC_LIMIT = 16 * 1024 * 1024 - 64 * 1024   # leave room for the other fields


class _Sink:
    """Stands in for ebooklet's local booklet file: the fetchers only ever call .set()."""

    def __init__(self):
        self.items = {}
        self._lock = threading.Lock()

    def set(self, key, value, timestamp=None, encode_value=False):
        with self._lock:
            self.items[key] = (int(timestamp), bytes(value))


class _LRU:
    """Bounded in-RAM cache of compressed chunk bytes (per process)."""

    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self._d = collections.OrderedDict()
        self._n = 0
        self._lock = threading.Lock()

    def get(self, k):
        with self._lock:
            v = self._d.get(k)
            if v is not None:
                self._d.move_to_end(k)
            return v

    def put(self, k, v):
        if self.max_bytes <= 0:
            return
        with self._lock:
            if k in self._d:
                return
            self._d[k] = v
            self._n += len(v)
            while self._n > self.max_bytes and self._d:
                _, old = self._d.popitem(last=False)
                self._n -= len(old)


class MongoReadStore:
    """Read-only store with the subset of the booklet/ebooklet API that cfdb's read path calls."""

    writable = False

    def __init__(self, db_url, coll, lru_bytes=256 * 2**20, stats=None):
        self._db_url = db_url
        self._conn = ebooklet.S3Connection(db_url=db_url)
        self._session = self._conn.open('r')
        self._coll = coll
        self._lock = threading.RLock()
        self._tmpdir = tempfile.mkdtemp(prefix='mstore-')
        self._index = None
        self._lru = _LRU(lru_bytes)
        self.stats = stats if stats is not None else collections.Counter()
        self.refresh()

    # ── snapshot: index + manifest + metadata from ONE db object ──────────────────────────────
    def refresh(self):
        t0 = time.perf_counter()
        with self._lock:
            self._session._load_db_metadata()       # also the too-new format gate
            kind = self._session.storage_kind
            if kind not in (eu.STORAGE_GROUPED, eu.STORAGE_PER_KEY):
                raise eu.UnsupportedFormatError(f'storage kind {kind!r} is not readable')
            resp = self._session.get_object()
            if resp.status not in (200, 206):
                raise RuntimeError(f'db object fetch failed: {resp.status} {resp.error}')
            manifest, meta_section, index_bytes = eu.parse_db_payload(resp.data)
            path = os.path.join(self._tmpdir, f'index-{time.time_ns()}.blt')
            with open(path, 'wb') as f:
                f.write(index_bytes)
            new_index = booklet.FixedLengthValue(path, 'r')
            old = self._index
            self._index = new_index
            self._manifest = manifest
            self._meta = eu.parse_meta_section(meta_section)[1]
            self._remote_ts = self._session.timestamp
            self._kind = kind
            if old is not None:
                old.close()
        self.stats['refresh'] += 1
        self.stats['refresh_s'] += time.perf_counter() - t0
        self.stats['index_bytes'] = len(index_bytes)

    # ── the cfdb-facing API ───────────────────────────────────────────────────────────────────
    def get_metadata(self, include_timestamp=False):
        return self._meta

    def get(self, key, default=None):
        out = self._get_many([key])
        return out.get(key, default)

    def load_items(self, keys=None):
        if keys is None:
            raise NotImplementedError('spike: whole-dataset load is not supported')
        self._get_many(list(keys))
        return {}

    def sync(self):
        pass

    def close(self):
        """No-op: one store is shared by every per-request cfdb object. Use shutdown()."""

    def shutdown(self):
        with self._lock:
            if self._index is not None:
                self._index.close()
                self._index = None
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def map(self, *a, **k):
        raise NotImplementedError('spike: map is not supported')

    # ── internals ─────────────────────────────────────────────────────────────────────────────
    def _cid(self, key, ts):
        return f'{self._db_url}|{key}|{ts}'

    def _entries(self, keys):
        with self._lock:
            ents = {}
            for k in keys:
                if k == eu.metadata_key_str:
                    continue
                v = self._index.get(k)
                if v is not None:                 # absent from the index = genuinely absent
                    ents[k] = eu.decode_index_entry(v)
            return ents, dict(self._manifest)

    def _get_many(self, keys, _retry=True):
        ents, manifest = self._entries(keys)
        out = {}
        need = {}
        for k, (ts, gid, off, ln) in ents.items():
            v = self._lru.get(self._cid(k, ts))
            if v is not None:
                out[k] = v
                self.stats['lru_hit'] += 1
            else:
                need[k] = (ts, gid, off, ln)
        if not need:
            return out

        # MongoDB
        t0 = time.perf_counter()
        ids = {self._cid(k, e[0]): k for k, e in need.items()}
        for doc in self._coll.find({'_id': {'$in': list(ids)}}, {'v': 1}):
            k = ids[doc['_id']]
            out[k] = bytes(doc['v'])
            self._lru.put(doc['_id'], out[k])
            del need[k]
        self.stats['mongo_hit'] += len(ids) - len(need)
        self.stats['mongo_s'] += time.perf_counter() - t0
        if not need:
            return out

        # the remote (B2), with ebooklet's own fetchers
        t0 = time.perf_counter()
        sink = _Sink()
        groups, per_key, failures = {}, [], {}
        for k, (ts, gid, off, ln) in need.items():
            if gid is None:
                per_key.append(k)
            else:
                groups.setdefault(gid, []).append((k, off, ln, ts))
        with ThreadPoolExecutor(max_workers=max(1, self._session.threads)) as ex:
            futs = {}
            for gid, infos in groups.items():
                gen = manifest.get(gid)
                if gen is None:
                    failures[f'_group_{gid}'] = eu.MissingRemoteObject(f'{gid}.<unmanifested>', [i[0] for i in infos])
                    continue
                futs[ex.submit(eu.get_remote_group_values, gid, gen, infos, sink, self._session)] = f'_group_{gid}'
            for k in per_key:
                futs[ex.submit(eu.get_remote_value, sink, k, self._session)] = k
            for f in as_completed(futs):
                err = f.result()
                if err:
                    failures[futs[f]] = err
        self.stats['remote_groups'] += len(groups)
        self.stats['remote_keys'] += len(need)
        self.stats['remote_s'] += time.perf_counter() - t0

        # store what arrived, under the snapshot's timestamp for that key
        docs = []
        now = datetime.datetime.now(datetime.timezone.utc)
        for k, (ts_sink, v) in sink.items.items():
            ts = need[k][0] if k in need else ts_sink
            if len(v) > MONGO_DOC_LIMIT:
                raise ValueError(f'chunk {k!r} is {len(v)} bytes: over the MongoDB document limit')
            cid = self._cid(k, ts)
            docs.append({'_id': cid, 'v': Binary(v), 'n': len(v), 't': now})
            out[k] = v
            self._lru.put(cid, v)
            self.stats['bytes_fetched'] += len(v)
        if docs:
            t0 = time.perf_counter()
            try:
                self._coll.insert_many(docs, ordered=False)
            except BulkWriteError as e:
                bad = [w for w in e.details.get('writeErrors', []) if w.get('code') != 11000]
                if bad:
                    raise
                self.stats['dup_inserts'] += len(e.details.get('writeErrors', []))
            self.stats['mongo_insert_s'] += time.perf_counter() - t0

        missing = [k for k in need if k not in sink.items]
        if failures or missing:
            healable = all(isinstance(f, eu.MissingRemoteObject) for f in failures.values())
            if _retry and healable:
                # A writer may have committed and GC'd the generation we were reading:
                # re-pull the snapshot ONCE and retry; a second failure is loud.
                self.stats['heal'] += 1
                self.refresh()
                out.update(self._get_many(missing, _retry=False))
                return out
            raise RuntimeError(f'remote fetch failed for {len(missing)} key(s): {failures or missing}')
        return out


_TYPES = {
    'grid': cmain.Grid,
    'ts_ortho': cmain.TimeSeriesOrtho,
    'ts_forecast': cmain.TimeSeriesForecast,
    'grid_forecast': cmain.GridForecast,
}


def open_dataset(store):
    """A per-request cfdb dataset object on the store's current snapshot."""
    meta = store.get_metadata()
    dt = meta['dataset_type']
    return _TYPES[dt](pathlib.Path('mongo-store'), store, False, 'zstd', None, dt)
