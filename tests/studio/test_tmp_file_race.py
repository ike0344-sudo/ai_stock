"""같은 프로세스의 스레드 여럿이 같은 파일을 동시에 쓸 때(FastAPI 동기 라우트는 스레드풀) 임시 파일 이름이 겹쳐 죽지 않는다.
data-agent 가 jobrunner/store.py 에서 찾은 것과 같은 결함(임시 파일 이름이 pid 만) — 스튜디오 쪽 저장소·하트비트를 같은 방식으로 시험한다."""
import json
import threading

from studio.api.heartbeat import write_beat
from studio.infrastructure.preset_store import FilePresetStore
from studio.infrastructure.run_files import FileRunFiles

THREADS, ROUNDS = 6, 120


def hammer(fn):
    errors: list[BaseException] = []

    def work():
        for _ in range(ROUNDS):
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 — 어떤 실패든 센다
                errors.append(exc)

    ts = [threading.Thread(target=work) for _ in range(THREADS)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return errors


def test_preset_put_same_name_from_many_threads(tmp_path):
    store = FilePresetStore(tmp_path)
    assert hammer(lambda: store.put("동시저장", {"name": "x", "n": 1})) == []
    assert store.get("동시저장")["n"] == 1
    assert not list(tmp_path.glob(".*.tmp"))  # tmp 잔재 없음


def test_patch_meta_same_run_from_many_threads(tmp_path):
    rid = "20260926-000000-abcdef"
    d = tmp_path / rid
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"name": "a"}), encoding="utf-8")
    files = FileRunFiles(tmp_path)
    assert hammer(lambda: files.patch_meta(rid, {"starred": True})) == []
    assert json.loads((d / "meta.json").read_text(encoding="utf-8"))["starred"] is True
    assert not list(d.glob(".meta.*.tmp"))


def test_heartbeat_write_from_many_threads(tmp_path):
    hb = tmp_path / "state" / "hb.json"
    fails: list[bool] = []
    errs = hammer(lambda: fails.append(write_beat(hb)))
    assert errs == [] and json.loads(hb.read_text(encoding="utf-8"))["pid"] > 0
    assert not list(hb.parent.glob(".*.tmp"))
