"""module-2 허브 핵심: H5 정책 · H10 상태 · H11 장부 밖 쓰기 · H12 소피증권 · H14 알림 · H15 체결 계획 · P7 · 품질 · 수집 명령."""
import json
import os
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from datahub import alerts, catalog, collectors, ledger, policy, quality, sophie, status
from datahub.calendar import Calendar

from .conftest import REPO

HOURS = policy.Hours("08:20", "09:00", "15:30", "20:10")
# 2026-09-21(월)~09-23(수) 거래, 09-24·25 추석(카탈로그 휴장일), 09-26 토, 09-27 일, 09-28 월
CAL = Calendar(index_dates={date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)},
               holidays={date(2026, 9, 24), date(2026, 9, 25)})
ENV_KEYS = {"KIWOOM_BATCH_APPKEY": "a", "KIWOOM_BATCH_SECRETKEY": "b"}


# ---------- H5 정책 행렬 ----------


@pytest.mark.parametrize("when,win", [
    (datetime(2026, 9, 23, 10, 0), "market"), (datetime(2026, 9, 23, 8, 30), "sophie_live"),
    (datetime(2026, 9, 23, 16, 0), "sophie_live"), (datetime(2026, 9, 23, 21, 0), "night"),
    (datetime(2026, 9, 23, 3, 0), "night"), (datetime(2026, 9, 26, 10, 0), "holiday"),    # 토
    (datetime(2026, 9, 24, 10, 0), "holiday"),                                            # 휴장일
])
def test_h5_window(when, win):
    assert policy.window(when, HOURS, CAL) == win


@pytest.mark.parametrize("win_time,heavy,light", [
    (datetime(2026, 9, 23, 10, 0), "schedule_only", "needs_confirm"),     # 정규장
    (datetime(2026, 9, 23, 16, 0), "needs_confirm", "allow_now"),         # 소피증권 가동
    (datetime(2026, 9, 23, 21, 0), "allow_now", "allow_now"),             # 야간
    (datetime(2026, 9, 26, 10, 0), "allow_now", "allow_now"),             # 주말
    (datetime(2026, 9, 24, 10, 0), "allow_now", "allow_now"),             # 휴장일
])
def test_h5_matrix(win_time, heavy, light):
    h = policy.decide("collect_ticks", now=win_time, hours=HOURS, cal=CAL, env=ENV_KEYS)
    l = policy.decide("collect_daily", "codes", n_codes=3, now=win_time, hours=HOURS, cal=CAL, env=ENV_KEYS)
    assert (h.weight, h.decision, l.weight, l.decision) == ("heavy", heavy, "light", light)
    if heavy != "allow_now":
        assert h.suggest_at == win_time.replace(hour=20, minute=10, second=0)      # 제안 시각 = connect_to


def test_h5_weights_and_warnings(hub_root):
    assert policy.weight("collect_daily", "codes", 20) == "light" and policy.weight("collect_daily", "codes", 21) == "heavy"
    assert policy.weight("collect_minute_al", "sophie_baseline") == "heavy"
    assert policy.weight("archive_minute_al") == "local"
    night = datetime(2026, 9, 26, 10, 0)
    assert policy.decide("archive_minute_al", now=night, hours=HOURS, cal=CAL, env={}).warnings == []
    d = policy.decide("collect_daily", "all", now=night, hours=HOURS, cal=CAL, env={}, hub_busy=True)
    assert d.busy and any("배치 앱키" in w for w in d.warnings) and any("1개" in w for w in d.warnings)
    early = datetime(2026, 9, 23, 19, 0)            # NXT 마감(20:00) 전 통합 분봉 경고
    assert any("NXT" in w for w in policy.decide("collect_minute_al", "codes", 5, early, HOURS, CAL, env=ENV_KEYS).warnings)
    assert policy.stop_at(HOURS) == "08:10"
    assert policy.cpu_workers("market", 16) == 4 and policy.cpu_workers("night", 16) == 8
    assert policy.is_night_start(datetime(2026, 9, 23, 20, 15), HOURS, CAL) and not policy.is_night_start(datetime(2026, 9, 23, 10, 0), HOURS, CAL)


def test_sophie_hours_follow_config(hub_root):
    assert policy.sophie_hours().source.startswith("기본값")
    cfg = hub_root / "kospi-theme-engine" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('market:\n  open: "09:05:00"\n  close: "15:20:00"\n  connect_from: "08:00:00"\n  connect_to: "21:00:00"\n', encoding="utf-8")
    h = policy.sophie_hours()
    assert (h.open, h.close, h.connect_from, h.connect_to) == ("09:05", "15:20", "08:00", "21:00") and h.source.endswith("config.yaml")
    assert policy.stop_at(h) == "07:50"


# ---------- H10 상태 ----------


def _write_daily(root, code, last, days=("2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23"), vol=100):
    d = root / "data/stocks/daily"
    d.mkdir(parents=True, exist_ok=True)
    rows = ["date,open,high,low,close,volume"] + [f"{x},10,11,9,10,{vol}" for x in days if x <= last]
    (d / f"{code}.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture
def daily_root(hub_root):
    idx = hub_root / "data/index/daily"
    idx.mkdir(parents=True)
    (idx / "001.csv").write_text("date,open,high,low,close,volume\n" + "\n".join(
        f"2026-09-{d},1,1,1,1,1" for d in (18, 21, 22, 23)) + "\n", encoding="utf-8")
    for c in ("AAA111", "BBB222", "CCC333"):
        _write_daily(hub_root, c, "2026-09-23")
    _write_daily(hub_root, "DDD444", "2026-09-22")            # 소피증권 유니버스 종목이 밀림
    _write_daily(hub_root, "EEE555", "2026-09-22")            # 밀렸지만 거래정지로 확인된 종목
    ref = hub_root / "kospi-theme-engine/dist/data/reference"
    ref.mkdir(parents=True)
    (ref / "universe.csv").write_text("code,name\nAAA111,a\nDDD444,d\nEEE555,e\n", encoding="utf-8")
    return hub_root


def test_h10_daily_verdicts(daily_root):
    now = datetime(2026, 9, 24, 10, 0)                         # 휴장일 아침 — 기대일은 09-22
    s = status.dataset_status("daily", now, CAL)
    assert (s["reference_date"], s["expected_date"], s["stale_count"], s["sophie_stale_count"]) == ("2026-09-23", "2026-09-22", 2, 2)
    assert s["verdict"] == "bad" and "소피증권" in s["reason"]
    (daily_root / "state/datahub").mkdir(parents=True)
    (daily_root / "state/datahub/inactive_codes.json").write_text(
        json.dumps({"codes": {"EEE555": {"reason": "거래정지"}, "DDD444": {"reason": "거래정지"}}}), encoding="utf-8")
    s = status.dataset_status("daily", now, CAL)
    assert s["sophie_stale_count"] == 0 and s["stale_inactive_count"] == 2 and s["verdict"] == "good"
    rows = {r["code"]: r for r in status.stale("daily")}
    assert rows["DDD444"]["sophie"] and rows["DDD444"]["inactive"] == "거래정지" and "AAA111" not in rows
    assert [r["code"] for r in status.stale("daily", sophie_only=True)] == ["DDD444", "EEE555"]


def test_h10_deadline_rules(daily_root):
    """기한 전 밀림은 주의, 기한(다음 거래일 07:30) 후 밀림은 나쁨."""
    for c in ("AAA111", "BBB222", "CCC333"):
        _write_daily(daily_root, c, "2026-09-22")               # 모두 09-22 까지만 — 09-23 이 안 들어왔다
    (daily_root / "kospi-theme-engine/dist/data/reference/universe.csv").write_text("code,name\n", encoding="utf-8")
    early = status.dataset_status("daily", datetime(2026, 9, 24, 10, 0), CAL)          # 기대일 09-22 = 기준일 -> 기한 전
    assert early["verdict"] == "warn"
    late = status.dataset_status("daily", datetime(2026, 9, 28, 8, 0), CAL)            # 09-23 기한(09-28 07:30) 지남
    assert late["expected_date"] == "2026-09-23" and late["verdict"] == "bad"


def test_h10_max_age_and_gaps_and_archive(hub_root):
    dates = {f"{i:06d}": "2026-09-04" for i in range(9)} | {"000099": "2026-08-20"}
    v = status.verdict_max_age(dates, date(2026, 9, 25))
    assert v["verdict"] == "warn" and v["age_days"] == 21 and v["behind_share"] == 0.1
    assert status.verdict_max_age(dates, date(2026, 10, 10))["verdict"] == "bad"
    assert status.verdict_max_age(dates, date(2026, 9, 10))["verdict"] == "good"
    cdir = catalog.path("minute_al", code="x").parent
    cdir.mkdir(parents=True)
    (cdir / "AAA111.csv").write_text("date,open,high,low,close,volume\n2026-09-04 09:00:00,1,1,1,1,1\n", encoding="utf-8")
    assert status.archive_coverage()["missing_vs_cache"] == 1
    from datahub import minute_al_archive as arch
    arch.merge("AAA111", arch.read_cache("AAA111"))
    time.sleep(0.05)
    assert status.archive_coverage()["verdict"] == "good"
    os.utime(cdir / "AAA111.csv", (time.time() + 5, time.time() + 5))      # 캐시가 보관소보다 새로워짐
    assert status.archive_coverage()["missing_vs_cache"] == 1


def test_h10_gaps_and_quality(hub_root):
    df = pd.DataFrame({"code": ["A"] * 3 + ["B"] * 2, "date": ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-22", "2026-09-23"],
                       "open": 10, "high": 11, "low": 9, "close": 10, "volume": 5})
    g = {r["date"]: r["share"] for r in status.gaps(df, days=3, now=datetime(2026, 9, 24, 10), cal=CAL)}
    assert g == {"2026-09-21": 0.5, "2026-09-22": 1.0, "2026-09-23": 1.0}


def test_quality_five_kinds():
    days = pd.date_range("2026-01-05", periods=12, freq="B").strftime("%Y-%m-%d")
    def frame(code, close=10.0, vol=100):
        return pd.DataFrame({"code": code, "date": days, "open": close, "high": close + 1, "low": close - 1,
                             "close": close, "volume": vol})
    ok = frame("OK")
    bad_ohlc = frame("OHLC"); bad_ohlc.loc[2, "high"] = 5                    # 고가 < 종가
    nonpos = frame("NEG"); nonpos.loc[3, "low"] = 0
    dup = pd.concat([frame("DUP"), frame("DUP").iloc[[4]]])
    jump = frame("JMP"); jump.loc[6:, ["open", "high", "low", "close"]] = [[20, 21, 19, 20]] * 6   # +100%
    zero = frame("ZER"); zero.loc[3:8, "volume"] = 0                          # 6일 연속 거래량 0
    q = quality.daily_quality(pd.concat([ok, bad_ohlc, nonpos, dup, jump, zero], ignore_index=True))
    assert q["counts"] == {"ohlc": 1, "nonpositive": 1, "duplicate_date": 1, "jump": 1, "zero_volume_run": 1}
    assert {i["code"] for i in q["issues"]} == {"OHLC", "NEG", "DUP", "JMP", "ZER"}


# ---------- P7 체결 조회창 기대 종목 == daily_top_n_from_local ----------


def _synthetic_daily(root, n_days=24, n_codes=45, seed=7):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2026-08-03", periods=n_days).strftime("%Y-%m-%d")
    d = root / "data/stocks/daily"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n_codes):
        vol = rng.integers(1, 40, size=n_days) * 1000            # 일부러 겹치는 값(동점)이 나오게 작은 범위
        pd.DataFrame({"date": days, "open": 10, "high": 11, "low": 9, "close": 10, "volume": vol}).to_csv(
            d / f"{i:06d}.csv", index=False)
    return d, days


def test_p7_expected_codes_equal_daily_top_n_from_local(hub_root):
    from backtesting.daily_cache import load_daily_all
    from backtesting.universe import daily_top_n_from_local
    d, days = _synthetic_daily(hub_root)
    ref = daily_top_n_from_local(str(d), top_n=35)
    daily = load_daily_all(daily_dir=str(d), cache_path=str(hub_root / "c.parquet"))
    dates = [date.fromisoformat(x) for x in days]
    exp = status.expected_tick_codes(daily, dates, 35)
    assert set(exp) == {k.date() for k in ref}
    for k, v in ref.items():
        assert exp[k.date()] == v, k
    # 초대형주 제외 + 보충
    ex = status.expected_tick_codes(daily, dates, 35, extra={"999999"}, exclude={"000001"})
    k = dates[5]
    assert ex[k] == (ref[pd.Timestamp(k)] - {"000001"}) | {"999999"}


def test_p7_collector_extra_codes_match_catalog():
    """카탈로그의 보충 종목·초대형주가 실제 수집기 상수와 같다(어긋나면 기대 종목이 실제 수집 대상과 달라진다)."""
    import subprocess, sys
    r = subprocess.run([sys.executable, "-c", "import tick_collect_804_828_al as t; print(sorted(t.EXTRA_CODES), sorted(t.EXCLUDE))"],
                       cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"{sorted(catalog.dataset('tick_al').freshness['extra_codes'])} ['000660', '005930']"


def test_h10_tick_window(hub_root):
    """조회창 20거래일 — 날짜별 기대/수집, days_left, 판정."""
    cal = Calendar(index_dates={d.date() for d in pd.bdate_range("2026-08-03", periods=24)}, holidays=set())
    d, days = _synthetic_daily(hub_root)
    from backtesting.daily_cache import load_daily_all
    daily = load_daily_all(daily_dir=str(d), cache_path=str(hub_root / "c.parquet"))
    now = datetime(2026, 9, 7, 21, 0)                             # 마지막 거래일 09-04 다음 월요일 밤 — 창 = 마지막 20거래일
    dates = [date.fromisoformat(x) for x in days]
    extra = set(catalog.dataset('tick_al').freshness['extra_codes'])
    exp = status.expected_tick_codes(daily, dates + [date(2026, 9, 4), date(2026, 9, 7)], 35, extra, set())
    slots = [x for x in dates + [date(2026, 9, 4), date(2026, 9, 7)]][-20:]
    # 전부 수집된 상태
    collected = {}
    for day in slots:
        for c in exp.get(day, ()):
            collected.setdefault(c, set()).add(day.isoformat())
    w = status.tick_window(now, cal, daily, collected, exclude=set())
    assert w["verdict"] == "good" and len(w["dates"]) == 20 and w["missing_pairs"] == []
    assert w["dates"][-1]["date"] == "2026-09-07" and w["dates"][-1]["days_left"] == 19
    before_close = status.tick_window(datetime(2026, 9, 7, 15, 0), cal, daily, {}, exclude=set())    # 오늘 체결은 20:10 전엔 pending
    assert before_close["dates"][-1]["status"] == "pending" and all(p[1] != "2026-09-07" for p in before_close["missing_pairs"])
    # 가장 오래된 날짜를 통째로 빼면 days_left 0 -> 나쁨
    oldest = slots[0].isoformat()
    lost = {c: {x for x in v if x != oldest} for c, v in collected.items()}
    w2 = status.tick_window(now, cal, daily, lost, exclude=set())
    row = w2["dates"][0]
    assert row["date"] == oldest and row["days_left"] == 0 and row["status"] in ("missing", "partial")
    assert w2["verdict"] == "bad" and w2["min_days_left"] == 0
    # 최근 날짜만 빠지면 여유가 있어 주의
    newest = slots[-1].isoformat()
    lost2 = {c: {x for x in v if x != newest} for c, v in collected.items()}
    w3 = status.tick_window(now, cal, daily, lost2, exclude=set())
    assert w3["verdict"] == "warn" and w3["dates"][-1]["days_left"] == 19


# ---------- H11 장부 밖 쓰기 ----------


def test_h11_unledgered_write_detected(hub_root):
    from datahub import gate
    _write_daily(hub_root, "AAA111", "2026-09-23")
    t10 = time.time() - 10
    os.utime(hub_root / "data/stocks/daily/AAA111.csv", (t10, t10))         # 잠금 구간(±2초 여유) 밖의 시각
    since = datetime.now() - timedelta(seconds=30)
    assert [w["dataset"] for w in status.unledgered_writes(since)] == ["daily"]           # 관문 없이 쓴 파일
    with gate.write("daily_minute", writer="t"):
        _write_daily(hub_root, "BBB222", "2026-09-23")                                     # 관문 안에서 쓴 파일
    files = {os.path.basename(w["file"]) for w in status.unledgered_writes(since)}
    assert files == {"AAA111.csv"}


# ---------- H12 소피증권 ----------


def test_h12_engine_state():
    tues, holiday = datetime(2026, 9, 23, 9, 30), datetime(2026, 9, 24, 9, 30)
    yesterday = datetime(2026, 9, 22, 22, 0).timestamp()
    today = datetime(2026, 9, 23, 0, 6).timestamp()
    e = sophie.engine(tues, CAL, lambda u: 401, [(100, yesterday + 5), (101, yesterday)])
    assert e["up"] and e["healthz"] == 401 and e["pid"] == 101 and e["stale_day"] is True    # 부모 프로세스 시작이 기준
    assert sophie.engine(tues, CAL, lambda u: 200, [(100, today)])["stale_day"] is False
    assert sophie.engine(holiday, CAL, lambda u: 401, [(100, yesterday)])["stale_day"] is False   # 휴장일엔 어제 상태가 정상
    down = sophie.engine(tues, CAL, lambda u: None, [])
    assert down == {"up": False, "healthz": None, "pid": None, "started_at": None, "stale_day": False}


def test_h12_markers_logs_and_baseline(hub_root):
    d = hub_root / "state/minute_refresh"
    d.mkdir(parents=True)
    t0 = datetime(2026, 9, 19, 19, 46).timestamp()
    (d / "last_run_started.json").write_text(json.dumps({"started_at": t0}), encoding="utf-8-sig")            # PowerShell 은 BOM 을 붙인다
    (d / "last_run_finished.json").write_text(json.dumps({"finished_at": t0 + 5000}), encoding="utf-8-sig")
    logs = hub_root / "kospi-theme-engine/logs"
    logs.mkdir(parents=True)
    (logs / "minute_refresh.log").write_text("2026-09-19 21:12:00 완료 · 실패 13종목 · 보유 2041종목\n2026-09-19 21:13:13 완료 — 소피증권을 다시 켜면\n", encoding="utf-8")
    (logs / "restart_after_midnight.log").write_text("2026-09-07 00:05:22  종료 PID 1\n2026-09-07 00:05:25  재기동 PID 2\n2026-09-07 00:06:04  완료\n", encoding="utf-8")
    (logs / "rebuild.log").write_text("2026-09-19 20:06:55  완료\n2026-09-19 20:32:09  교체 완료 (0초 대기)\n2026-09-19 20:32:09  완료\n", encoding="utf-8")
    m = sophie.minute_refresh()
    assert m["running"] is False and m["last_result"] == "완료 · 실패 13종목 · 보유 2041종목"
    assert m["next_due"] == "2026-10-03 (토) 09:00 이후"                       # 완료 9/19(토) + 13일 = 10/2(금) -> 다음 토요일
    r = sophie.restarts(datetime(2026, 9, 25, 12, 0))
    assert r["last_midnight"] == "2026-09-07T00:05:25" and r["days_since"] == 18 and r["last_rebuild"] == "2026-09-19T20:32:09"
    (d / "last_run_finished.json").unlink()
    assert sophie.minute_refresh()["running"] is False                     # 시작이 6시간 넘게 옛날이면 멈춘 것으로 본다
    (d / "last_run_started.json").write_text(json.dumps({"started_at": time.time() - 60}), encoding="utf-8-sig")
    assert sophie.minute_refresh()["running"] is True
    # data ↔ dist 동기: 내용이 다르면 알린다, 수정 시각이 다르기만 한 건 무시
    a, b = hub_root / "kospi-theme-engine/data/reference", hub_root / "kospi-theme-engine/dist/data/reference"
    a.mkdir(parents=True); b.mkdir(parents=True)
    (a / "themes.csv").write_text("x", encoding="utf-8"); (b / "themes.csv").write_text("x", encoding="utf-8")
    os.utime(b / "themes.csv", (1, 1))
    assert status.verdict_dist_sync()["in_sync"] is True
    (a / "themes.csv").write_text("y", encoding="utf-8")
    v = status.verdict_dist_sync()
    assert v["in_sync"] is False and v["diff_files"] == ["themes.csv"] and v["verdict"] == "warn"


def test_h12_reference_freshness_uses_newest_file_not_directory(hub_root):
    """폴더 mtime 은 안의 파일을 고쳐도 안 바뀐다(G6: 08-16 으로 보이던 것)."""
    a = hub_root / "kospi-theme-engine/data/reference"
    a.mkdir(parents=True)
    f = a / "themes.csv"
    f.write_text("x", encoding="utf-8")
    old = datetime(2026, 8, 16).timestamp()
    os.utime(a, (old, old))
    assert datetime.fromtimestamp(status.newest_mtime(a)).date() == date.today()


# ---------- H14 알림 ----------


def _ctx(**kw):
    base = {"trading_day": True, "daily": {"reference_date": "2026-09-23", "expected_date": "2026-09-23", "sophie_stale_count": 0},
            "tick": {"dates": []}, "archive": {"missing_vs_cache": 0}, "locks": [], "engine": {"stale_day": False},
            "night_log": [], "given_up": [], "catchup": None, "unledgered": 0}
    return base | kw


def test_h14_rules_fire_and_respect_time_and_switch():
    now = datetime(2026, 9, 28, 8, 30)
    assert alerts.evaluate(_ctx(), now) == []
    ids = lambda ctx, n=now, en=None: sorted(a.id for a in alerts.evaluate(ctx, n, en))
    assert ids(_ctx(daily={"reference_date": "2026-09-22", "expected_date": "2026-09-23", "sophie_stale_count": 0})) == ["daily_stale_before_open"]
    assert ids(_ctx(daily={"reference_date": "2026-09-23", "expected_date": "2026-09-23", "sophie_stale_count": 3})) == ["daily_stale_before_open"]
    assert ids(_ctx(daily={"reference_date": "2026-09-22", "expected_date": "2026-09-23", "sophie_stale_count": 0}), datetime(2026, 9, 28, 7, 0)) == []     # 07:30 전
    assert ids(_ctx(daily={"reference_date": "2026-09-22", "expected_date": "2026-09-23", "sophie_stale_count": 0}, trading_day=False)) == []
    assert ids(_ctx(tick={"dates": [{"date": "2026-09-01", "status": "partial", "days_left": 2, "missing": ["A"]}]})) == ["tick_window_loss"]
    assert ids(_ctx(tick={"dates": [{"date": "2026-09-01", "status": "partial", "days_left": 3, "missing": ["A"]}]})) == []
    assert ids(_ctx(archive={"missing_vs_cache": 2041})) == ["archive_behind"]
    long_ago = (now - timedelta(minutes=31)).timestamp()
    assert ids(_ctx(locks=[{"resource": "tick_al", "dead": True, "since": long_ago, "cmdline": ""}])) == ["dead_lock_owner"]
    assert ids(_ctx(locks=[{"resource": "tick_al", "dead": True, "since": now.timestamp() - 60, "cmdline": ""}])) == []
    assert ids(_ctx(engine={"stale_day": True, "started_at": "2026-09-27T00:05"})) == ["sophie_stale_day"]
    assert ids(_ctx(engine={"stale_day": True}), datetime(2026, 9, 28, 8, 0)) == []                                   # 08:20 전
    assert ids(_ctx(night_log=[{"night": "2026-09-26", "remaining": 3, "deferred": 0}, {"night": "2026-09-27", "remaining": 2, "deferred": 0}])) == ["tick_nightly_failed"]
    assert ids(_ctx(night_log=[{"night": "2026-09-26", "remaining": 3, "deferred": 0}, {"night": "2026-09-27", "remaining": 2, "deferred": 2}])) == []      # 미룬 것뿐
    assert ids(_ctx(night_log=[{"night": "2026-09-24", "remaining": 3, "deferred": 0}, {"night": "2026-09-27", "remaining": 2, "deferred": 0}])) == []      # 연속 아님
    assert ids(_ctx(given_up=[{"pair": "386380|2026-09-01", "given_up_at": "2026-09-27"}])) == ["tick_given_up"]
    assert ids(_ctx(given_up=[{"pair": "386380|2026-09-01", "given_up_at": "2026-09-10"}])) == []                     # 새로 들어간 게 아님
    assert ids(_ctx(catchup={"deadline_passed": True, "remaining": 12, "sophie_remaining": 1})) == ["daily_catchup_incomplete"]
    assert ids(_ctx(catchup={"deadline_passed": False, "remaining": 12})) == []
    assert ids(_ctx(unledgered=2)) == []                                    # 기본 꺼짐
    assert ids(_ctx(unledgered=2), en={"unledgered_write": True}) == ["unledgered_write"]
    assert ids(_ctx(archive={"missing_vs_cache": 5}), en={"archive_behind": False}) == []                          # 규칙별 끄기


def test_h14_dispatch_once_per_day_and_retry_on_failure(hub_root):
    now = datetime(2026, 9, 28, 8, 30)
    a = alerts.Alert("archive_behind", "minute_al_archive", "보관 누락")
    sent = []
    assert [x.id for x in alerts.dispatch([a], now, lambda m: sent.append(m) or True)] == ["archive_behind"]
    assert alerts.dispatch([a], now, lambda m: sent.append(m) or True) == []                  # 같은 날 두 번째 — 안 보냄
    assert len(sent) == 1
    assert len(alerts.dispatch([a], now + timedelta(days=1), lambda m: sent.append(m) or True)) == 1   # 다음 날은 다시
    b = alerts.Alert("dead_lock_owner", "tick_al", "죽은 잠금")
    assert alerts.dispatch([b], now, lambda m: False) == []                                   # 발송 실패
    assert len(alerts.dispatch([b], now, lambda m: True)) == 1                                # -> 기록 안 됐으니 다음 점검이 재시도
    assert len(alerts.dispatch([alerts.Alert("dead_lock_owner", "minute_al", "x")], now, lambda m: True)) == 1   # 다른 대상은 별개


def test_h14_overrides_switch_rules(hub_root):
    assert alerts.enabled_rules()["unledgered_write"] is False and alerts.enabled_rules()["archive_behind"] is True
    (hub_root / "state/datahub").mkdir(parents=True)
    (hub_root / "state/datahub/overrides.json").write_text(json.dumps({"alerts": {"unledgered_write": True, "archive_behind": False}}), encoding="utf-8")
    on = alerts.enabled_rules()
    assert on["unledgered_write"] is True and on["archive_behind"] is False


# ---------- H15 빠진 체결 쌍 계획 · H18 포기 ----------


def _window(missing):
    """missing: {날짜: [종목]} — days_left 는 날짜 순서대로 0,1,2…"""
    dates = sorted(missing)
    return {"dates": [{"date": d, "days_left": i} for i, d in enumerate(dates)],
            "missing_pairs": [(c, d) for d in dates for c in missing[d]]}


def test_h15_plan_range_and_order(hub_root):
    w = _window({"2026-09-01": ["ZZZ", "BBB"], "2026-09-02": ["AAA", "BBB"], "2026-09-04": ["CCC"]})
    p = collectors.plan_tick_catch_up(w)
    assert (p.start, p.end) == ("2026-09-01", "2026-09-04")
    assert p.codes == ["BBB", "ZZZ", "AAA", "CCC"]                # 먼저 사라질 날짜(09-01) 걸린 종목부터, 같으면 코드순
    assert collectors.plan_tick_catch_up(_window({})) is None
    collectors.record_night([("ZZZ", "2026-09-01")], date(2026, 9, 5))            # 포기 목록 제외 확인용은 아래 H18


def test_h18_three_nights_gives_up_and_retry(hub_root):
    pair = ("386380", "2026-09-01")
    assert collectors.record_night([pair], date(2026, 9, 21)) == [] and collectors.record_night([pair], date(2026, 9, 22)) == []
    assert collectors.record_night([pair], date(2026, 9, 22)) == []                # 같은 밤 재시도는 한 번으로 센다
    assert collectors.record_night([pair], date(2026, 9, 23)) == [pair]            # 3일 밤 -> 새로 포기
    assert collectors.record_night([pair], date(2026, 9, 24)) == []                # 이미 포기 — 또 알리지 않는다
    w = _window({"2026-09-01": ["386380", "AAA"]})
    assert collectors.plan_tick_catch_up(w).codes == ["AAA"]                       # 포기 목록은 계획에서 뺀다
    assert collectors.retry([pair]) == 1
    assert collectors.plan_tick_catch_up(w).codes == ["386380", "AAA"]             # 되돌린 뒤 다시 포함
    collectors.record_night([], date(2026, 9, 25))
    assert collectors.load_attempts()["pairs"] == {}                               # 채워진 쌍은 기록에서 사라진다
    assert collectors.load_attempts()["nights_log"][-1] == {"night": "2026-09-25", "remaining": 0, "deferred": 0}


# ---------- 수집 명령 조립 ----------


def test_collect_commands(hub_root):
    d = collectors.collect_daily("codes", codes=["005930", "000660"], stop_at="08:10")
    assert d.argv[1:] == ["backfill_universe.py", "--codes=005930,000660", "--stop-at", "08:10"]
    assert collectors.collect_daily("all").argv[-1] == "--all" and collectors.collect_daily("stale").argv[1:] == ["backfill_universe.py"]
    with pytest.raises(ValueError):
        collectors.collect_daily("codes")
    t = collectors.collect_ticks("2026-09-01", "2026-09-03", "jobs/x/codes.txt", 4, "08:10")
    assert t.argv[1:] == ["tick_collect_804_828_al.py", "--start", "2026-09-01", "--end", "2026-09-03", "--concurrency", "4",
                          "--codes", "@jobs/x/codes.txt", "--batch-key", "--stop-at", "08:10"]
    with pytest.raises(ValueError):
        collectors.collect_ticks("2026-09-01", "2026-09-03", "f", 7)
    b = collectors.collect_minute_al("sophie_baseline")
    assert b.argv[-1] == "-Now" and b.argv[-2].endswith("run_minute_refresh.ps1") and b.cwd.endswith("kospi-theme-engine")
    c = collectors.collect_minute_al("codes", ["005930"])
    assert c.argv[-3:] == ["scripts.fetch_minute", "--codes", "005930"] and c.argv[1:4] == ["-X", "utf8", "-u"]
    deep = collectors.collect_minute_al("deep_archive", ["005930"], 60)
    assert deep.argv[-4:] == ["005930", "--days", "60", "--archive-only"]
    for bad in (dict(mode="deep_archive", codes=["005930"], days=10), dict(mode="codes", codes=[]), dict(mode="codes", codes=["X"] * 501), dict(mode="nope")):
        with pytest.raises(ValueError):
            collectors.collect_minute_al(**bad)
    cdir = catalog.path("minute_al", code="x").parent
    cdir.mkdir(parents=True)
    for c_ in ("000001", "000002"):
        (cdir / f"{c_}.csv").write_text("date\n", encoding="utf-8")
    assert collectors.collect_minute_al("all_cached").argv[-1] == "000001,000002"
    j = d.with_job("20260925-201000-a1b2c3")
    assert j.env == {"DATAHUB_TRIGGER": "hub", "DATAHUB_JOB_ID": "20260925-201000-a1b2c3"}
    assert collectors.archive_minute_al().argv[-1] == "--all"
    assert collectors.tick_compact("state/x.json").argv[-2:] == ["--main-progress", "state/x.json"]


def test_tick_progress_path_matches_collector_tag():
    """수집기가 `--start/--end/--codes` 로 돌 때 만드는 진행 파일 이름과 같아야 압축기가 그 파일을 읽는다."""
    import subprocess, sys
    code = ("import sys,zlib,tick_collect_804_828_al as t\n"
            "a=t.parse_args.__globals__\n"
            "codes=['AAA','BBB']\n"
            "tag=f\"20260901_20260903_c{zlib.crc32(','.join(codes).encode()):08x}\"\n"
            "print(f'state/tick_collection/progress_al_{tag}.json')\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert collectors.tick_progress_path("2026-09-01", "2026-09-03", ["BBB", "AAA"]) == r.stdout.strip()
    assert collectors.tick_progress_path("2026-09-01", "2026-09-03") == "state/tick_collection/progress_al_20260901_20260903.json"


def test_calendar_2026_remaining_holidays_from_catalog():
    cal = Calendar(index_dates={date(2026, 9, 23)})
    days = cal.trading_days(date(2026, 9, 24), date(2026, 12, 31))
    for closed in ("2026-09-24", "2026-09-25", "2026-10-05", "2026-10-09", "2026-12-25", "2026-12-31"):
        assert date.fromisoformat(closed) not in days, closed
    assert date(2026, 9, 28) in days and date(2026, 10, 1) in days             # 추석 대체·국군의날은 거래일로 둠(보고서에 명시)


def test_h10_backup_exists_either_location(hub_root):
    """실제 안전망은 워치독 backups/*.gz — 재빌드 robocopy 폴더만 보면 멀쩡한 날을 '백업 없음'으로 오판한다."""
    now = datetime(2026, 9, 23, 21, 0)
    assert status.verdict_backup_exists(now, CAL)["verdict"] == "bad"
    b = hub_root / "kospi-theme-engine/backups"
    b.mkdir(parents=True)
    (b / "surge_20260923.jsonl.gz").write_bytes(b"x")
    v = status.verdict_backup_exists(now, CAL)
    assert v["verdict"] == "good" and [x.replace("\\", "/").rsplit("/", 1)[-1] for x in v["found"]] == ["surge_20260923.jsonl.gz"]
    assert status.verdict_backup_exists(datetime(2026, 9, 24, 12, 0), CAL)["backup_date"] == "2026-09-23"   # 휴장일엔 전 거래일 것
    (hub_root / "data/backup/kospi-theme-engine/20260922").mkdir(parents=True)
    assert status.verdict_backup_exists(datetime(2026, 9, 23, 12, 0), CAL)["verdict"] == "good"             # 20:10 전엔 전 거래일(09-22)


def test_write_inactive_classifies_and_replaces(hub_root):
    lst = {"AAA": {"state": "증거금100%|거래정지", "auditInfo": "정상"}, "BBB": {"state": "관리종목", "auditInfo": "거래정지"},
           "CCC": {"state": "관리종목", "auditInfo": "관리종목"}}
    got = status.write_inactive(lst, ["AAA", "BBB", "CCC", "DDD"], date(2026, 9, 25))
    assert {c: v["reason"] for c, v in got.items()} == {"AAA": "거래정지", "BBB": "거래정지", "DDD": "상장폐지"}   # CCC: 관리종목일 뿐 정지 아님
    assert set(status.inactive_codes()) == {"AAA", "BBB", "DDD"}
    est = status.write_inactive(lst, ["CCC", "EEE"], date(2026, 9, 26), api_empty={"CCC"})
    assert est["CCC"]["reason"] == "거래정지(추정)" and "EEE" in est                       # 목록에 없는 EEE 는 상장폐지
    status.write_inactive(lst, ["CCC"], date(2026, 9, 26))
    assert status.inactive_codes()["CCC"]["reason"] == "거래정지(추정)"                     # 추정 항목은 이어 간다
    status.write_inactive(lst, [], date(2026, 9, 27))                                       # 밀림이 풀려 후보에서 빠지면 사라진다
    assert status.inactive_codes() == {}


def test_batch_key_check_reads_env_file_names_only(hub_root):
    """서버 환경변수에 키가 없어도 .env 에 배치키가 있으면 경고하지 않는다(값은 읽어 쓰지 않는다)."""
    assert policy.batch_keys_configured({}) is False                                # .env 없음
    (hub_root / ".env").write_text("KIWOOM_APPKEY=a\nKIWOOM_BATCH_APPKEY=x\n", encoding="utf-8")
    assert policy.batch_keys_configured({}) is False                                # 하나만
    (hub_root / ".env").write_text("KIWOOM_BATCH_APPKEY=x\nKIWOOM_BATCH_SECRETKEY=\n", encoding="utf-8")
    assert policy.batch_keys_configured({}) is False                                # 값이 빈 것
    (hub_root / ".env").write_bytes(b"\xef\xbb\xbfKIWOOM_BATCH_APPKEY=x\r\n  KIWOOM_BATCH_SECRETKEY = y\r\n")
    assert policy.batch_keys_configured({}) is True                                 # BOM·CRLF·공백 허용
    assert not any("배치 앱키" in w for w in policy.decide("collect_daily", "all", now=datetime(2026, 9, 26, 10, 0), hours=HOURS, cal=CAL, env={}).warnings)
    assert policy.batch_keys_configured({"KIWOOM_BATCH_APPKEY": "a", "KIWOOM_BATCH_SECRETKEY": "b"}) is True


def test_minute_refresh_next_expected_is_iso(hub_root):
    from datahub import scheduler
    d = hub_root / "state/minute_refresh"
    d.mkdir(parents=True)
    t0 = datetime(2026, 9, 19, 19, 46).timestamp()
    (d / "last_run_finished.json").write_text(json.dumps({"finished_at": t0 + 5000}), encoding="utf-8-sig")
    (d / "last_run_started.json").write_text(json.dumps({"started_at": t0}), encoding="utf-8-sig")
    row = scheduler._observe("minute_refresh", datetime(2026, 9, 25, 12, 0), CAL, date(2026, 9, 25))
    assert row["next_expected"] == "2026-10-03T09:00"                              # ISO — 계약은 ISO 또는 null
    assert sophie.minute_refresh()["next_due"] == "2026-10-03 (토) 09:00 이후"       # /sophie 의 문장 값은 그대로


def test_inactive_list_expires_and_keeps_estimates(hub_root):
    """정지는 풀린다 — 8일 넘게 갱신 안 된 목록은 믿지 않고, 갱신할 때 '추정' 항목은 이어 간다."""
    lst = {"AAA": {"state": "정상", "auditInfo": "정상"}, "EEE": {"state": "관리종목", "auditInfo": "관리종목"}}
    status.write_inactive(lst, ["EEE"], date(2026, 9, 25), api_empty={"EEE"})                    # EEE: 추정
    assert set(status.inactive_codes(date(2026, 9, 25))) == {"EEE"}
    assert set(status.inactive_codes(date(2026, 10, 3))) == {"EEE"}                                # 8일째까지는 유효
    assert status.inactive_codes(date(2026, 10, 4)) == {}                                          # 9일째 — 만료(다시 받아 본다)
    got = status.write_inactive(lst, ["EEE", "AAA"], date(2026, 10, 1))                            # 갱신: EEE 는 이어 가고 정상 종목은 안 넣는다
    assert set(got) == {"EEE"} and got["EEE"]["reason"] == "거래정지(추정)"




def test_p7_real_data_window_equals_collector_universe():
    """§8.7 P7 — 실제 일봉으로: 허브 조회창의 기대 종목 합집합 == 체결 수집기가 실제로 쓰는 유니버스(`build_universe`)
    (초대형주 제외·보충 2종목 포함, 최근 20거래일). 로컬 일봉이 없으면 건너뛴다."""
    import subprocess
    import sys
    from datahub import jobs
    if not (REPO / "data/stocks/daily").is_dir():
        pytest.skip("로컬 일봉 없음")
    w = status.tick_window(datetime.now())
    dates = [r["date"] for r in w["dates"] if r["expected_codes"]]
    assert len(dates) >= 15
    fresh = catalog.dataset("tick_al").freshness
    exp = status.expected_tick_codes(jobs._daily(), [date.fromisoformat(d) for d in dates], fresh["top_n"], set(fresh["extra_codes"]), {"005930", "000660"})
    win = set().union(*exp.values())
    code = ("import json, tick_collect_804_828_al as t"+chr(10)+
            f"t.START_DATE, t.END_DATE = {dates[0]!r}, {dates[-1]!r}"+chr(10)+
            "print(json.dumps(sorted(t.build_universe())))")
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    coll = set(json.loads(r.stdout.strip().splitlines()[-1]))
    assert win == coll, (sorted(win - coll)[:5], sorted(coll - win)[:5])
