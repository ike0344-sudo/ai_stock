"""일봉 2,413개 CSV 를 파일 하나로 합쳐 캐시한다.

실측(2026-09-01): CSV 를 종목별로 여는 데 **21초**, 합친 parquet 하나를 읽는 데 **0.07초**
— 300배다. 파일은 25MB 뿐이다. 일봉을 쓰는 연구가 매번 21초를 버리고 있었다.

    from backtesting.daily_cache import load_daily_all
    df = load_daily_all()          # code/date/open/high/low/close/volume

원본 CSV 중 하나라도 캐시보다 새로우면 알아서 다시 만든다 — 손으로 갱신할 일은 없다.
"""
import glob
import os

import pandas as pd

DAILY_DIR = os.path.join("data", "stocks", "daily")
CACHE_PATH = os.path.join("data", "cache", "daily_all.parquet")


def _needs_rebuild(csvs: list[str]) -> bool:
    if not os.path.exists(CACHE_PATH):
        return True
    cache_mtime = os.path.getmtime(CACHE_PATH)
    # 2,413개 mtime 조회는 0.1초대다 — 캐시가 낡은 채로 쓰이는 것보다 싸다.
    return any(os.path.getmtime(f) > cache_mtime for f in csvs)


def load_daily_all(daily_dir: str = DAILY_DIR, cache_path: str = CACHE_PATH) -> pd.DataFrame:
    """전 종목 일봉을 한 표로. `code` 컬럼이 붙는다."""
    csvs = sorted(glob.glob(os.path.join(daily_dir, "*.csv")))
    if not csvs:
        raise FileNotFoundError(f"일봉이 없다: {daily_dir}")

    if not _needs_rebuild(csvs):
        return pd.read_parquet(cache_path)

    parts = []
    for f in csvs:
        d = pd.read_csv(f)
        d["code"] = os.path.basename(f)[:-4]
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp = cache_path + ".tmp"          # 도중에 죽어도 반쪽 캐시가 안 남게 원자적 교체
    df.to_parquet(tmp, index=False)
    os.replace(tmp, cache_path)
    return df


if __name__ == "__main__":
    import time

    t0 = time.time()
    df = load_daily_all()
    build = time.time() - t0
    t0 = time.time()
    again = load_daily_all()
    cached = time.time() - t0

    print(f"첫 호출 {build:.1f}초 / 캐시 재사용 {cached:.2f}초 · {len(df):,}행 "
          f"· {df['code'].nunique():,}종목")
    assert len(df) == len(again), "캐시가 원본과 행수가 다르다"
    assert cached < build or build < 1.0, "캐시가 안 먹었다"
    assert {"code", "date", "close"} <= set(df.columns), f"컬럼 누락: {df.columns.tolist()}"
    print("자체검사 통과")
