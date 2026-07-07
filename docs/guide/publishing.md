# Publishing & Registration

## publish() — the primary flow

`publish()` takes a validated local cfdb file, pushes it to *your* S3 storage, and writes the catalogue entry:

```python
cat = envlib.Catalogue(remotes=[rcg_conn])
cat.publish('era5_temp_v1.cfdb', data_conn, rcg_conn, num_groups=101)
```

Internally, in order: validate → write the derived attributes into the file (`envlib_dataset_id`, `envlib_dataset_version_id`, and the auto-populated `standard_name`) → push the cfdb data → write the catalogue entry → push the catalogue. The data goes up **before** the entry, so the catalogue never references incomplete data.

- `data_conn` is where the dataset lives (an `ebooklet.S3Connection` with your credentials). Set its `db_url` to the dataset's public HTTPS location if you host it publicly — that URL rides into the entry as `data_url` so consumers can open the dataset credential-free. It must be a *plain* public URL: no `user:pass@`, no query string (presigned URLs are rejected — their signatures must never land in a catalogue).
- `rcg_conn` is the catalogue's own S3 location. A catalogue that doesn't exist yet is created on first publish.
- `num_groups` tunes the S3 object layout for a **new** remote dataset (see [cfdb's S3 guide](https://mullenkamp.github.io/cfdb/guide/s3-remote/)); it's ignored for existing ones. **It's best to use a prime number**.

**Failure handling**: if publish dies between the data push and the catalogue push, just run it again — the data push is idempotent and the entry write is an upsert.

**Updating a dataset** is the same call: append new time steps to your local file, `publish()` again. The catalogue entry's extents refresh; `modified_at` bumps *only if something actually changed* (a byte-identical re-publish is a no-op and leaves `modified_at` alone, so it stays a meaningful recency signal). `created_at` is set once, at first registration, forever.

## register() — data pushed outside envlib

If a pipeline already manages the S3 side (or you're cataloguing legacy remote data), `register()` does everything publish does *except* the data push:

```python
cat.register(data_conn, rcg_conn)
```

`data_conn` must carry write credentials: first registration writes the self-identification attributes (and any derived `standard_name`) into the remote dataset — a small metadata-only push.

## Concurrent producers

Multiple producers registering into one shared catalogue is safe: the catalogue holds an exclusive lock from open through push, so a second writer blocks (up to ~5 minutes) and then lands its entry on top of the refreshed index.

!!! danger "Never force the lock on a shared catalogue"
    `force_lock=True` bypasses that serialization and **will destroy the other writer's entries**. Use it only when you are certain the competing lock is dead (a crashed process), never against a live shared catalogue.

## Deregistration

```python
cat.deregister(dataset_version_id, rcg_conn)                    # delist
cat.deregister(dataset_version_id, rcg_conn,                    # retract
               delete_data=True,
               access_key_id='...', access_key='...')
```

**Delist** (the default) removes only the catalogue entry — the hosted data stays up for existing consumers; the dataset just stops being discoverable. This is also step one of fixing a typo'd identity field: deregister, fix the file's attributes, re-register (a new id).

**Retract** (`delete_data=True`) is for data known to be wrong: it also deletes the hosted cfdb file, using the owner credentials you inject. Before deleting anything, envlib verifies that **no other catalogue entry references the same storage target** — if one does (say you re-published a corrected version to the same S3 path), the call refuses rather than destroy the other entry's data.

### Deleting data after a plain delist

Once an entry is delisted, envlib no longer tracks the dataset — so removing the hosted data later happens one of two ways:

1. **Re-register, then retract** *(recommended)*: `cat.register(...)` the still-live remote back into the catalogue, then `deregister(..., delete_data=True)`. The shared-target safety check stays in force.
2. **Direct storage deletion**: open the remote with your own credentials and call ebooklet's `delete_remote()` (or delete the objects at the bucket level). envlib is not involved and no safety check applies.

There is no tombstone: after retraction the id simply resolves to nothing. If you've published DOIs pointing at a dataset, prefer delisting over retraction.
