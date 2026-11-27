"""Repo-root pytest configuration: the docs example tests (Sybil) and a scratch HOME.

Docs tests: ``uv run pytest README.md docs`` (offline), plus ``--docs-live`` for the blocks that read
the live public commons. The machinery is in ``envlib/tests/docs_support.py``.
"""

import atexit
import os
import shutil
import tempfile

# Before anything imports envlib: envlib.vocabularies computes its overlay directory
# (~/.envlib/vocabularies) at import, and an overlay written there would shadow the bundled
# vocabularies of every later envlib release on this machine. So every pytest run here gets a
# throwaway HOME, unit tests included.
REAL_HOME = os.path.expanduser('~')
_SCRATCH_HOME = tempfile.mkdtemp(prefix='pytest-home-')
atexit.register(shutil.rmtree, _SCRATCH_HOME, ignore_errors=True)
os.environ['HOME'] = _SCRATCH_HOME
for _var in ('XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME'):
    os.environ[_var] = os.path.join(_SCRATCH_HOME, _var.lower())
# A bare Catalogue() must mean the documented public commons, not a local override.
os.environ.pop('ENVLIB_PUBLIC_RCG_URL', None)

import pytest  # noqa: E402

from envlib.tests import docs_support  # noqa: E402

_collect_docs = docs_support.make_sybil().pytest()


def pytest_collect_file(file_path, parent):
    if docs_support.is_doc_file(file_path):
        return _collect_docs(file_path, parent)
    return None


def pytest_addoption(parser):
    parser.addoption(
        '--docs-live',
        action='store_true',
        default=False,
        help='also run the docs blocks that read the live public envlib commons',
    )


def pytest_configure(config):
    docs_support.configure(config, real_home=REAL_HOME)


def pytest_sessionfinish(session):
    docs_support.session_finish(session)


def pytest_collection_modifyitems(items):
    for item in items:
        if docs_support.is_docs_item(item):
            item.add_marker(pytest.mark.timeout(docs_support.EXAMPLE_TIMEOUT, method='signal'))


def pytest_runtest_setup(item):
    # Page fail-fast: after one example on a page fails, the rest of the page is skipped (a leaked
    # dataset lock would otherwise cost the full timeout for every later block).
    if docs_support.is_docs_item(item) and docs_support.page_key(item) in docs_support.STATE.failed_pages:
        pytest.skip('an earlier example on this page failed')


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item):
    outcome = yield
    report = outcome.get_result()
    if docs_support.is_docs_item(item) and report.failed:
        docs_support.STATE.failed_pages.add(docs_support.page_key(item))
