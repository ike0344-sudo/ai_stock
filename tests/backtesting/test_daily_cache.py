"""일봉 캐시 — 낡은 캐시를 조용히 쓰는 것이 이 모듈의 유일한 위험이라 거기만 조인다."""
import time

import pandas as pd

from backtesting.daily_cache import load_daily_all


def _write(dir_, code, close):
    p = dir_ / f"{code}.csv"
    p.write_text(f"date,open,high,low,close,volume\n2026-01-02,1,1,1,{close},10\n", encoding="utf-8")
    return p


def test_합친다_그리고_code_컬럼이_붙는다(tmp_path):
    d = tmp_path / "daily"; d.mkdir()
    _write(d, "005930", 100); _write(d, "000660", 200)
    df = load_daily_all(str(d), str(tmp_path / "c.parquet"))
    assert sorted(df["code"]) == ["000660", "005930"]
    assert sorted(df["close"]) == [100, 200]


def test_원본이_바뀌면_캐시를_다시_만든다(tmp_path):
    """이게 깨지면 낡은 값으로 백테스트가 돌아도 아무도 모른다."""
    d = tmp_path / "daily"; d.mkdir()
    cache = str(tmp_path / "c.parquet")
    _write(d, "005930", 100)
    assert load_daily_all(str(d), cache)["close"].iloc[0] == 100

    time.sleep(0.01)                      # mtime 해상도가 낮은 파일시스템 대비
    _write(d, "005930", 999)              # 원본만 갱신
    assert load_daily_all(str(d), cache)["close"].iloc[0] == 999


def test_새_종목이_생겨도_잡는다(tmp_path):
    d = tmp_path / "daily"; d.mkdir()
    cache = str(tmp_path / "c.parquet")
    _write(d, "005930", 100)
    load_daily_all(str(d), cache)

    time.sleep(0.01)
    _write(d, "000660", 200)
    assert len(load_daily_all(str(d), cache)) == 2


def test_같은_프로세스의_스레드가_동시에_다시_만들어도_깨지지_않는다(tmp_path, monkeypatch):
    """8780 서버 스레드풀에서 두 요청이 동시에 캐시를 재생성 — tmp 이름이 pid 뿐이면 서로의 tmp 를 덮어써 os.replace 가 죽는다."""
    import threading

    from backtesting import daily_cache

    d = tmp_path / "daily"; d.mkdir()
    for i in range(300):
        _write(d, f"{i:06d}", 100 + i)
    cache = tmp_path / "c.parquet"
    monkeypatch.setattr(daily_cache, "CACHE_PATH", str(cache))  # 재생성 판단이 이 경로를 본다
    errs = []
    for _ in range(4):  # 라운드마다 캐시를 지워 모든 스레드가 재생성 경로를 타게 한다
        cache.unlink(missing_ok=True)
        gate = threading.Barrier(6)

        def run():
            gate.wait()
            try:
                assert len(load_daily_all(str(d), str(cache))) == 300
            except Exception as e:  # noqa: BLE001
                errs.append(type(e).__name__)

        ts = [threading.Thread(target=run) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    assert errs == []
    assert len(load_daily_all(str(d), str(cache))) == 300
    assert not list(tmp_path.glob("*.tmp"))  # 임시 파일이 남지 않는다
