import json

import pytest

from jobrunner import store as st
from jobrunner.mask import Masker
from tests.jobrunner.conftest import make


def test_create_states_and_id(store):
    a = make(store, "ok")
    b = make(store, "ok", scheduled_at="2099-01-01T00:00:00")
    assert st.JOB_ID_RE.fullmatch(a["job_id"])
    assert (a["status"], b["status"]) == ("queued", "scheduled")
    assert store.read(a["job_id"])["handler"].endswith(":ok")
    with pytest.raises(ValueError):
        store.create("x", "nogroup", "h:f")


@pytest.mark.parametrize("bad", ["../x", "20260925-201000-ZZZZZZ", "", "20260925-201000-a1b2c3/../x"])
def test_job_id_regex_blocks_paths(store, bad):
    with pytest.raises(ValueError):
        store.job_dir(bad)


def test_update_never_reopens_terminal(store):
    j = make(store, "ok")
    store.transition(j["job_id"], {"queued"}, status="succeeded")
    store.update(j["job_id"], status="running", error="x")
    got = store.read(j["job_id"])
    assert got["status"] == "succeeded" and got["error"] == "x"  # status 만 막는다


def test_transition_is_compare_and_set(store):
    j = make(store, "ok")
    assert store.transition(j["job_id"], {"queued"}, status="running")
    assert store.transition(j["job_id"], {"queued"}, status="running") is None  # 두 번째는 물러난다
    assert store.transition("20990101-000000-abcdef", {"queued"}, status="running") is None


def test_list_filters_limit_and_active(store):
    ids = [make(store, "ok", group=g)["job_id"] for g in ("local", "compute", "local")]
    store.transition(ids[0], {"queued"}, status="succeeded")
    assert [j["job_id"] for j in store.list_jobs(status="queued")] == sorted(ids[1:], reverse=True)
    assert len(store.list_jobs(group="local")) == 2
    assert len(store.list_jobs(limit=1)) == 1
    assert {j["job_id"] for j in store.list_active()} == set(ids[1:])
    assert store.list_jobs(kind="nope") == []


def test_no_tmp_left_and_json_valid(store):
    j = make(store, "ok")
    store.update(j["job_id"], pid=5)
    d = store.job_dir(j["job_id"])
    assert sorted(p.name for p in d.iterdir()) == ["job.json"]
    assert json.loads((d / "job.json").read_text(encoding="utf-8"))["pid"] == 5


def test_cancel_flag_written_only_by_request(store):
    j = make(store, "ok")
    assert not store.cancel_requested(j["job_id"])
    store.request_cancel(j["job_id"])
    assert store.cancel_requested(j["job_id"])
    with pytest.raises(FileNotFoundError):
        store.request_cancel("20990101-000000-abcdef")


def test_progress_roundtrip(store):
    j = make(store, "ok")
    assert store.read_progress(j["job_id"]) is None
    store.write_progress(j["job_id"], pct=12.5, stage="수집", message="m")
    p = store.read_progress(j["job_id"])
    assert (p["pct"], p["stage"], p["paused"]) == (12.5, "수집", False)


def test_log_resume_never_splits_utf8(store):
    j = make(store, "ok")
    text = "가나다라마바사\n" * 5
    store.log_path(j["job_id"]).write_bytes(text.encode("utf-8"))
    out, off = b"", 0
    while True:
        chunk, off, eof = store.read_log(j["job_id"], off, limit=7)  # 3바이트 글자 경계를 일부러 어긋나게
        out += chunk
        chunk.decode("utf-8")  # 각 조각이 온전해야 한다
        if eof:
            break
    assert out.decode("utf-8") == text
    assert store.read_log(j["job_id"], 10_000) == (b"", 10_000, True)
    assert store.read_log("20990101-000000-abcdef") == (b"", 0, True)


def test_masker(tmp_path):
    (tmp_path / ".env").write_text(
        '# c\nAPPKEY="abcdef123456"\nSECRETKEY=abcdef123456789 # 주석\nMOCK=true\nPORT=8780\nEMPTY=\n', encoding="utf-8")
    m = Masker.from_env(tmp_path)
    assert m.mask("k=abcdef123456 s=abcdef123456789") == "k=**** s=****"  # 긴 값이 먼저 — 조각이 안 남는다
    assert m.mask("mock=true port 8780") == "mock=true port 8780"          # 짧은 값은 안 가린다
    assert m.mask("Authorization: Bearer abcdefghijklmnop1234") == "Authorization: Bearer ****"
    assert m.mask("bearer  ab") == "bearer  ab"                             # 토큰이 아닌 짧은 글자
    assert Masker.from_env(tmp_path / "nope").mask("x") == "x"


def test_masker_env_by_name(monkeypatch, tmp_path):
    monkeypatch.setenv("SOME_API_TOKEN", "tok-value-9999")
    monkeypatch.setenv("PLAIN_VAR", "plain-value-9999")
    m = Masker.from_env(tmp_path)
    assert m.mask("tok-value-9999 plain-value-9999") == "**** plain-value-9999"


def test_concurrent_writes_from_threads_of_one_process_never_fail(store):
    """진행률 폴링 스레드와 작업 스레드는 같은 progress.json 을 같은 프로세스에서 동시에 쓴다 — 임시 파일 이름이 pid 뿐이면
    서로의 tmp 를 덮어써 os.replace 가 FileNotFoundError/PermissionError 로 죽고 작업이 failed 가 된다(2026-09-26 실측: 1600회 중 70회)."""
    import threading
    a = make(store, "ok")
    errs = []

    def w():
        for i in range(300):
            try:
                store.write_progress(a["job_id"], pct=float(i % 100), stage="x")
            except Exception as e:  # noqa: BLE001
                errs.append(type(e).__name__)

    ts = [threading.Thread(target=w) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errs == []
    assert store.read_progress(a["job_id"])["stage"] == "x"
    assert not [p for p in store.job_dir(a["job_id"]).iterdir() if p.name.endswith(".tmp")]  # 임시 파일이 남지 않는다
