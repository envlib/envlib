"""Tests for the publish-time object verification (`verify_objects`).

The streamflow incident: a push "succeeds" while an object never durably landed
(a 2xx-without-persist), leaving the committed index referencing an object the store
does not have; readers then hit `RemoteIntegrityError`, and — before this safeguard —
the catalogue happily advertised the broken dataset for weeks.

`_verify_remote_objects` reuses `ebooklet.fsck(check_objects=True)` between the data
push and the RCG entry write, and refuses to register an inconsistent remote. These
unit tests drive it with crafted `FsckReport`s (no S3 needed — the offline publish
e2e is blocked by ebooklet's test harness not being packaged in the wheel). The
happy-path wiring runs in the live tier, which now defaults `verify_objects=True`.
"""

import ebooklet
import pytest
import urllib3

from envlib import catalogue
from envlib.catalogue import _verify_remote_objects
from envlib.metadata import PublishIntegrityError


class _Conn:
    """Minimal stand-in — `_verify_remote_objects` only reads `.db_key` (for the message)."""

    db_key = 'member/ecan-streamflow'


def _patch_fsck(monkeypatch, report):
    monkeypatch.setattr(ebooklet, 'fsck', lambda conn, **kw: report)


def _report(**overrides):
    base = dict(db_key='member/ecan-streamflow', format_version=2, db_object_exists=True)
    base.update(overrides)
    return ebooklet.FsckReport(**base)


def test_clean_remote_passes(monkeypatch):
    """A consistent remote (nothing missing) does not raise."""
    _patch_fsck(monkeypatch, _report())
    _verify_remote_objects(_Conn())  # no exception


def test_claimed_but_missing_raises(monkeypatch):
    """Per-key over-claim (index references objects absent from the store) -> raise,
    with the missing sample and the real recovery recipe in the message."""
    _patch_fsck(monkeypatch, _report(claimed_but_missing=['streamflow!0.6000', 'streamflow!0.12000']))
    with pytest.raises(PublishIntegrityError) as ei:
        _verify_remote_objects(_Conn())
    msg = str(ei.value)
    assert 'missing' in msg.lower()
    assert 'republish' in msg.lower()  # honest recovery (not "just re-run")
    assert 'streamflow!0.6000' in msg  # a concrete missing key


def test_unmanifested_group_ids_raises(monkeypatch):
    """Grouped over-claim (index references a group id absent from the manifest) -> raise.
    `claimed_but_missing` alone would miss this (Fable M2)."""
    _patch_fsck(monkeypatch, _report(unmanifested_group_ids=[3, 7]))
    with pytest.raises(PublishIntegrityError):
        _verify_remote_objects(_Conn())


def test_absent_db_object_raises(monkeypatch):
    """A report with no committed db object has an empty `claimed_but_missing`; it must
    still be refused, not sail through."""
    _patch_fsck(monkeypatch, _report(format_version=None, db_object_exists=False))
    with pytest.raises(PublishIntegrityError):
        _verify_remote_objects(_Conn())


def test_publish_integrity_error_is_not_httperror():
    """The whole reason for a distinct exception: a transport-retry wrapper keyed on
    urllib3.HTTPError (like ebooklet.RemoteIntegrityError) must NOT catch/retry a
    permanent integrity fault. It stays a ValueError for existing handlers."""
    assert not issubclass(PublishIntegrityError, urllib3.exceptions.HTTPError)
    assert issubclass(PublishIntegrityError, ValueError)


def test_verify_helper_is_wired_into_publish_and_register():
    """Guard the wiring: publish() and register() expose the opt-out and call the
    verifier (a lightweight source check — the runtime happy path is the live tier)."""
    import inspect

    assert 'verify_objects' in inspect.signature(catalogue.Catalogue.publish).parameters
    assert 'verify_objects' in inspect.signature(catalogue.Catalogue.register).parameters
    for fn in (catalogue.Catalogue.publish, catalogue.Catalogue.register):
        src = inspect.getsource(fn)
        assert '_verify_remote_objects(member_conn)' in src
        # the verify must precede the entry write
        assert src.index('_verify_remote_objects') < src.index('_upsert_entry')
