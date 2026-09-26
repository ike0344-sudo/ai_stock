"""일봉 품질 검사 5종 (설계 §2.4.8, 테스트 H10).

OHLC 불일치 · 0 이하 가격 · 중복 날짜 · ±30.5% 초과 변동(수정주가 누락 의심) · 5일 이상 거래량 0.
표는 `backtesting.daily_cache.load_daily_all` 결과(code/date/open/high/low/close/volume) 모양이다.
"""
import pandas as pd

from . import catalog

JUMP_LIMIT = 0.305                 # 상·하한가 ±30% + 호가단위 여유 — 넘으면 액면분할 등 수정주가 누락을 의심
ZERO_VOLUME_RUN = 5
KINDS = ("ohlc", "nonpositive", "duplicate_date", "jump", "zero_volume_run")


def _load():
    from backtesting.daily_cache import load_daily_all
    return load_daily_all(daily_dir=str(catalog.path("daily", code="X").parent),
                          cache_path=str(catalog.path("daily_all_cache")))


def daily_quality(daily: pd.DataFrame | None = None, since: str | None = None, limit: int = 200) -> dict:
    """{'counts': {종류: 건수}, 'issues': [{code, date, kind, detail}...(최대 limit)]}.
    since(YYYY-MM-DD) 이후 날짜만 본다 — 옛 이력의 분할·정정 흔적까지 다 세면 잡음이 크다."""
    df = (_load() if daily is None else daily).copy()
    df["date"] = pd.to_datetime(df["date"])
    if since:
        df = df[df["date"] >= pd.Timestamp(since)]
    df = df.sort_values(["code", "date"], kind="stable").reset_index(drop=True)
    found: dict[str, pd.DataFrame] = {}

    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    found["ohlc"] = df[(h < pd.concat([o, c, l], axis=1).max(axis=1)) | (l > pd.concat([o, h, c], axis=1).min(axis=1))]
    found["nonpositive"] = df[(df[["open", "high", "low", "close"]] <= 0).any(axis=1)]
    found["duplicate_date"] = df[df.duplicated(["code", "date"], keep="first")]

    d1 = df.drop_duplicates(["code", "date"])                      # 변동률은 중복을 걷어낸 뒤에
    prev = d1.groupby("code")["close"].shift(1)
    chg = (d1["close"] / prev - 1).where(prev > 0)
    found["jump"] = d1[chg.abs() > JUMP_LIMIT].assign(change=chg[chg.abs() > JUMP_LIMIT])

    z = (d1["volume"] == 0)
    run_id = (z != z.groupby(d1["code"]).shift(1, fill_value=False)).cumsum()
    run_len = z.groupby([d1["code"], run_id]).transform("sum")
    found["zero_volume_run"] = d1[z & (run_len >= ZERO_VOLUME_RUN)].drop_duplicates("code")   # 종목당 한 줄(시작이 아니라 대표 한 건)

    issues = []
    for kind in KINDS:
        for _, r in found[kind].iterrows():
            det = {"ohlc": "고가<시·종·저 또는 저가>시·고·종", "nonpositive": "0 이하 가격",
                   "duplicate_date": "같은 날짜 중복",
                   "jump": f"전일 대비 {r.get('change', 0):+.1%}", "zero_volume_run": f"거래량 0 이 {ZERO_VOLUME_RUN}일 이상"}[kind]
            issues.append({"code": r["code"], "date": r["date"].strftime("%Y-%m-%d"), "kind": kind, "detail": det})
    return {"counts": {k: len(found[k]) for k in KINDS}, "issues": issues[:limit], "rows_checked": len(df)}
