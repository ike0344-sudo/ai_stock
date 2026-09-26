import pytest

from jobrunner import worker
from jobrunner.store import JobStore

HANDLERS = "tests.jobrunner.handlers:"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DATAHUB_ROOT", str(tmp_path))
    (tmp_path / ".env").write_text("KIWOOM_SECRETKEY=sk-test-SECRET-VALUE-123456\nKIWOOM_IS_MOCK=true\n",
                                   encoding="utf-8")
    return tmp_path


@pytest.fixture
def store(root):
    return JobStore(root)


@pytest.fixture(autouse=True)
def allow_test_handlers(monkeypatch):
    monkeypatch.setattr(worker, "ALLOWED_HANDLER_PREFIXES", worker.ALLOWED_HANDLER_PREFIXES + (HANDLERS,))


def make(store, name, *, group="local", **kw):
    return store.create(name, group, f"{HANDLERS}{name}", kw.pop("payload", {}), **kw)
