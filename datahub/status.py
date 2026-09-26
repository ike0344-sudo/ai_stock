"""데이터셋 상태 — 신선도 판정·밀린 종목·결측 거래일·체결 조회창·보관소·장부 밖 쓰기 (설계 §2.4.8, 테스트 H10·H11·P7).

판정은 좋음(good) / 주의(warn) / 나쁨(bad) 3단계. 시계·달력·데이터 표를 인자로 받는 순수 함수가 중심이라
테스트가 시각을 주입할 수 있다. 무거운 pandas·pyarrow 는 필요한 함수 안에서만 import 한다.
"""
import threading
import csv
import hashlib
import json
import os
import re
from collections import Counter
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from . import catalog, ledger, locks
from .calendar import Calendar

TICK_WINDOW_DAYS = 20
TICK_CLOSE_TIME = "20:10"          # 이 시각 이후에야 오늘 체결을 받을 수 있다(NXT 마감 20:00 + 여유)
UNIVERSE_CSV = ("kospi-theme-engine/dist/data/reference/universe.csv",
                "kospi-theme-engine/data/reference/universe.csv")


# ---------- 파일 훑기 ----------


def _code_files(dataset_id: str) -> dict[str, Path]:
    """`{code}` 자리가 종목코드인 데이터셋의 (종목 -> 파일). 체결은 종목 폴더."""
    tmpl = catalog.dataset(dataset_id).path
    base = catalog.root() / tmpl.split("{code}")[0]
    suffix = tmpl.split("{code}")[1]
    out: dict[str, Path] = {}
    if not base.is_dir():
        return out
    with os.scandir(base) as it:
        for e in it:
            if suffix.startswith("/"):                     # 종목/날짜 구조(tick_al)
                if e.is_dir():
                    out[e.name] = Path(e.path)
            elif e.is_file() and e.name.endswith(suffix):
                out[e.name[: -len(suffix)]] = Path(e.path)
    return out


def _csv_last_date(p: Path) -> str | None:
    try:
        with open(p, "rb") as f:
            f.seek(max(0, p.stat().st_size - 200))
            tail = f.read().decode("utf-8", errors="ignore").strip().splitlines()
        d = tail[-1][:10]
        return d if re.match(r"\d{4}-\d{2}-\d{2}", d) else None
    except (OSError, IndexError):
        return None


def _parquet_last_date(p: Path) -> str | None:
    try:
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(p)
        names = pf.schema_arrow.names
        i = names.index("date")
        vals = [pf.metadata.row_group(g).column(i).statistics.max for g in range(pf.metadata.num_row_groups)]
        return str(max(vals))[:10]
    except Exception:
        try:
            import pyarrow.parquet as pq
            return str(pq.read_table(p, columns=["date"]).column("date").to_pandas().max())[:10]
        except Exception:
            return None


def latest_dates(dataset_id: str) -> dict[str, str]:
    """종목별 마지막 날짜(YYYY-MM-DD). 종목 단위 데이터셋만."""
    files = _code_files(dataset_id)
    if "{date}" in catalog.dataset(dataset_id).path:       # 체결: 폴더 안 파일명이 날짜
        return {c: max((f.name[:10] for f in d.iterdir() if re.match(r"\d{4}-", f.name)), default="")
                for c, d in files.items()}
    fn = _parquet_last_date if catalog.dataset(dataset_id).path.endswith(".parquet") else _csv_last_date
    return {c: d for c, p in files.items() if (d := fn(p))}


def newest_mtime(path: Path) -> float | None:
    """파일이면 그 mtime, 폴더면 **안의 파일 중 가장 새것**(폴더 자체의 mtime 은 안 바뀌어 옛날로 보인다)."""
    if path.is_file():
        return path.stat().st_mtime
    if path.is_dir():
        ts = [e.stat().st_mtime for e in os.scandir(path) if e.is_file()]
        return max(ts, default=None)
    return None


def universe_codes() -> set[str]:
    """소피증권이 신고가·전일종가를 재는 종목. 돌아가는 앱(dist)의 것을 먼저 본다. 없으면 빈 집합."""
    for rel in UNIVERSE_CSV:
        p = catalog.root() / rel
        if p.is_file():
            with p.open(encoding="utf-8-sig", newline="") as fh:
                return {r["code"] for r in csv.DictReader(fh) if r.get("code")}
    return set()


def _state_dir() -> Path:
    return catalog.state_base() / "state" / "datahub"


INACTIVE_MAX_AGE_DAYS = 8          # 이보다 오래 갱신 안 된 목록은 믿지 않는다 — 정지가 풀린 종목이 영영 제외되는 사고를 막는다


def inactive_codes(today: date | None = None) -> dict[str, dict]:
    """거래정지·상장폐지로 확인된 종목(`state/datahub/inactive_codes.json`). 밀림 계산에서 따로 센다 —
    받을 수 없는 종목이 '수집 누락'으로 섞이면 소피증권 유니버스 판정이 영영 나쁨에 걸린다.
    `as_of` 가 8일보다 오래됐으면 빈 목록(= 다시 다 받아 본다). 정지는 풀리므로 주 1회 `refresh_inactive.py` 로 갱신한다."""
    p = _state_dir() / "inactive_codes.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    as_of = doc.get("as_of")
    if as_of and (today or date.today()) - date.fromisoformat(as_of) > timedelta(days=INACTIVE_MAX_AGE_DAYS):
        return {}
    return doc.get("codes", {})


def write_inactive(stock_list: dict[str, dict], candidates: list[str], as_of: date,
                   api_empty: set[str] | None = None) -> dict[str, dict]:
    """밀린 종목(candidates) 중 받을 수 없는 종목을 `inactive_codes.json` 에 적는다(통째로 새로 씀 — 정지가 풀린 종목은 빠진다).
    stock_list: 키움 ka10099 종목정보 리스트(code -> 행). 목록에 없으면 상장폐지, state/auditInfo 에 '거래정지'가 있으면 거래정지.
    api_empty: 일봉 조회가 빈 응답인 종목(표시는 없지만 정지 중으로 추정) — 직접 확인한 것만 넘긴다."""
    codes = {}
    prev = inactive_codes(as_of)                       # 직전 목록의 '추정' 항목은 이번에도 밀려 있으면 이어 간다(목록만으로는 못 알아내므로)
    for c in sorted(candidates):
        r = stock_list.get(c)
        if r is None:
            codes[c] = {"reason": "상장폐지", "detail": "종목정보 목록에 없음"}
        elif "거래정지" in (r.get("state", "") + r.get("auditInfo", "")):
            codes[c] = {"reason": "거래정지", "detail": f"{r.get('state', '')} / {r.get('auditInfo', '')}"}
        elif c in (api_empty or ()) or prev.get(c, {}).get("reason") == "거래정지(추정)":
            codes[c] = {"reason": "거래정지(추정)", "detail": "일봉 조회가 빈 응답 — 표시는 없지만 받을 데이터가 없음"}
    p = _state_dir() / "inactive_codes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"as_of": as_of.isoformat(), "source": "kiwoom ka10099", "codes": codes},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return codes


# ---------- 신선도 규칙 ----------


def expected_daily_date(now: datetime, cal: Calendar, deadline: str = "07:30") -> date | None:
    """마감 기한(다음 거래일 deadline)이 지난 가장 최근 거래일."""
    hh, mm = (int(x) for x in deadline.split(":"))
    t = now.date() if cal.is_trading_day(now.date()) else cal.prev_trading_day(now.date())
    for _ in range(20):
        if datetime.combine(cal.next_trading_day(t), dtime(hh, mm)) <= now:
            return t
        t = cal.prev_trading_day(t)
    return None


def verdict_last_trading_day(dates: dict[str, str], now: datetime, cal: Calendar, sophie: set[str],
                             inactive: set[str], deadline: str = "07:30") -> dict:
    """기준일(종목별 최신일의 최빈값)과 기대일 비교. 기한 전 밀림 = 주의, 기한 후 밀림·소피증권 유니버스 밀림 = 나쁨."""
    if not dates:
        return {"verdict": "bad", "reason": "데이터 없음", "n_codes": 0, "reference_date": None,
                "expected_date": None, "stale_count": 0, "sophie_stale_count": 0}
    ref = Counter(dates.values()).most_common(1)[0][0]
    exp = expected_daily_date(now, cal, deadline)
    latest_possible = cal.prev_trading_day(now.date())   # 오늘 자료는 장 마감 뒤에야 생기므로 '전 거래일'이 최신 기대치
    stale = [c for c, d in dates.items() if d < ref]
    stale_active = [c for c in stale if c not in inactive]
    sophie_stale = [c for c in stale_active if c in sophie]
    if exp is not None and ref < exp.isoformat():
        v, why = "bad", f"기준일 {ref} < 기대일 {exp} (기한 지남)"
    elif sophie_stale:
        v, why = "bad", f"소피증권 유니버스 {len(sophie_stale)}종목이 기준일보다 오래됨"
    elif ref < latest_possible.isoformat():
        v, why = "warn", f"기준일 {ref} < 전 거래일 {latest_possible} (기한 전)"
    else:
        v, why = "good", "최신"
    return {"verdict": v, "reason": why, "n_codes": len(dates), "reference_date": ref,
            "expected_date": exp.isoformat() if exp else None, "stale_count": len(stale),
            "stale_inactive_count": len(stale) - len(stale_active),
            "sophie_stale_count": len(sophie_stale)}


def verdict_max_age(dates: dict[str, str], today: date, good: int = 14, warn: int = 21) -> dict:
    """통합 분봉 캐시: 최빈 최신일이 오래됐나 + 최빈일보다 5일 넘게 뒤처진 파일 비율."""
    if not dates:
        return {"verdict": "bad", "reason": "파일 없음", "n_codes": 0}
    mode = Counter(dates.values()).most_common(1)[0][0]
    age = (today - date.fromisoformat(mode)).days
    behind = sum(1 for d in dates.values() if (date.fromisoformat(mode) - date.fromisoformat(d)).days > 5)
    v = "good" if age <= good else "warn" if age <= warn else "bad"
    return {"verdict": v, "reason": f"최빈 최신일 {mode} ({age}일 전)", "n_codes": len(dates),
            "last_date_mode": mode, "age_days": age, "behind_share": round(behind / len(dates), 3)}


# ---------- 통합 분봉의 "수집 대상" — fetch_minute.py 의 기본 대상과 같은 규칙(테스트 P9 가 하한 값이 같은지 확인) ----------
_TV_CACHE: dict[tuple[str, int, int], float] = {}


def avg_trading_value(code: str, days: int = 20) -> float:
    """최근 days 거래일 평균 거래대금(종가×거래량, 원). 일봉이 없거나 못 읽으면 무한대(=대상에 남김) — fetch_minute.avg_trading_value 와 같다."""
    p = catalog.path("daily", code=code)
    try:
        st = p.stat()
    except OSError:
        return float("inf")
    key = (str(p), st.st_mtime_ns, days)
    if key in _TV_CACHE:
        return _TV_CACHE[key]
    try:
        with p.open(encoding="utf-8-sig") as fh:
            head = fh.readline().strip().split(",")
            ci, vi = head.index("close"), head.index("volume")
            rows = [ln.strip().split(",") for ln in fh]
    except (OSError, ValueError):
        return float("inf")
    vals = []
    for f in rows[-days:]:
        try:
            vals.append(float(f[ci]) * float(f[vi]))
        except (IndexError, ValueError):
            pass
    v = sum(vals) / len(vals) if vals else float("inf")
    if len(_TV_CACHE) > 20000:
        _TV_CACHE.clear()
    _TV_CACHE[key] = v
    return v


def minute_al_targets(min_value_eok: float) -> set[str]:
    """통합 분봉 수집 대상 = 소피증권 유니버스 ∩ 테마 종목 중 평소(20일) 대금 ≥ min_value_eok 억. 재료를 못 읽으면 빈 집합."""
    uni_p = catalog.root() / UNIVERSE_CSV[1]
    themes_p = catalog.root() / "data" / "themes.csv"
    if not uni_p.is_file() or not themes_p.is_file():
        return set()
    with uni_p.open(encoding="utf-8-sig", newline="") as fh:
        uni = {r["code"] for r in csv.DictReader(fh) if r.get("code")}
    with themes_p.open(encoding="utf-8-sig", newline="") as fh:
        themes = {(r.get("stock_code") or "").strip() for r in csv.DictReader(fh)}
    return {c for c in uni & themes if avg_trading_value(c) >= min_value_eok * 1e8}


def verdict_minute_al(dates: dict[str, str], targets: set[str], today: date, good: int, warn: int,
                      stale_share: float = 0.02) -> dict:
    """수집 대상 종목만 본다(수집기가 일부러 안 받는 저대금 종목의 옛 파일은 판정에서 뺀다).
    최빈 최신일 나이로 좋음/주의/나쁨 → 대상 중 최빈일보다 5일 넘게 뒤처진(또는 파일 없는) 종목이 stale_share 를 넘으면 최소 '주의'."""
    scoped = {c: dates.get(c, "") for c in targets}
    have = {c: d for c, d in scoped.items() if d}
    if not have:
        return {"verdict": "bad", "reason": "수집 대상 파일 없음", "n_codes": 0, "n_targets": len(targets), "stale_codes": sorted(targets)[:50]}
    r = verdict_max_age(have, today, good, warn)
    mode = date.fromisoformat(r["last_date_mode"])
    stale_codes = sorted(c for c, d in scoped.items() if not d or (mode - date.fromisoformat(d)).days > 5)
    share = len(stale_codes) / len(targets)
    r.update(n_targets=len(targets), n_stale=len(stale_codes), stale_codes=stale_codes[:50], stale_share=round(share, 3))
    if stale_codes:
        r["reason"] += f" · 대상 {len(targets)}종목 중 {len(stale_codes)}종목 낡음"
        if share > stale_share and r["verdict"] == "good":
            r["verdict"] = "warn"
    return r


def archive_coverage() -> dict:
    """캐시 ⊆ 보관소 — 캐시 mtime 이 보관소보다 새롭거나 보관소에 없는 종목 = 보관 누락."""
    cache, arch = _code_files("minute_al"), _code_files("minute_al_archive")
    missing = sorted(c for c, p in cache.items()
                     if c not in arch or p.stat().st_mtime > arch[c].stat().st_mtime + 1)
    v = "good" if not missing else "bad"
    return {"verdict": v, "reason": "캐시 ⊆ 보관소" if not missing else f"보관 누락 {len(missing)}종목",
            "codes_cache": len(cache), "codes_archive": len(arch), "missing_vs_cache": len(missing),
            "missing_codes": missing[:50]}


def verdict_dist_sync() -> dict:
    """소피증권 기준 데이터: data 와 dist 의 파일 내용이 같은가(수정 시각은 복사에서 바뀌므로 내용으로 본다)."""
    d = catalog.dataset("sophie_reference")
    src, dst = catalog.root() / d.path, catalog.root() / d.also[0]
    def h(p: Path) -> str:
        m = hashlib.sha1()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                m.update(chunk)
        return m.hexdigest()
    diffs = []
    for f in sorted(src.glob("*")) if src.is_dir() else []:
        g = dst / f.name
        if not g.is_file() or (f.stat().st_size != g.stat().st_size or h(f) != h(g)):
            diffs.append(f.name)
    ts_src, ts_dst = newest_mtime(src), newest_mtime(dst)
    iso = lambda t: datetime.fromtimestamp(t).isoformat(timespec="minutes") if t else None
    return {"verdict": "good" if not diffs else "warn",
            "reason": "dist = data" if not diffs else f"dist 에 반영 안 됨: {', '.join(diffs[:5])}",
            "data_updated": iso(ts_src), "dist_updated": iso(ts_dst), "in_sync": not diffs, "diff_files": diffs}


def verdict_backup_exists(now: datetime, cal: Calendar) -> dict:
    """거래일 20:10 이후, 그날 실시간 기록(surge.jsonl)의 백업이 있으면 좋음.
    백업은 두 곳에서 생긴다: 워치독이 5분마다 부르는 `kospi-theme-engine/backups/surge_YYYYMMDD.jsonl.gz`(실제 안전망),
    재빌드 스크립트의 `data/backup/kospi-theme-engine/YYYYMMDD/`(평일 15:35 이후 한 번). 어느 쪽이든 있으면 된다."""
    d = now.date()
    if not (cal.is_trading_day(d) and now.time() >= dtime(20, 10)):
        d = cal.prev_trading_day(d)
    root = catalog.root()
    where = [p for p in (root / catalog.dataset("sophie_live_logs").also[0] / f"{d:%Y%m%d}",
                         root / "kospi-theme-engine" / "backups" / f"surge_{d:%Y%m%d}.jsonl.gz") if p.exists()]
    return {"verdict": "good" if where else "bad", "reason": f"{d} 백업 {'있음' if where else '없음'}",
            "backup_date": d.isoformat(), "found": [str(p.relative_to(root)) for p in where]}


# ---------- 체결 조회창 ----------


def expected_tick_codes(daily, dates: list[date], top_n: int = 35, extra: set[str] | None = None,
                        exclude: set[str] | None = None) -> dict[date, set[str]]:
    """날짜별 기대 종목 = 그 날짜의 **전일** 거래대금(종가×거래량) 상위 top_n − 초대형주 + 보충.
    `daily_top_n_from_local` 과 같은 규칙(P7) — 같은 날 종가로 뽑으면 미래참조라 D-1 순위를 쓴다.
    daily: code/date/close/volume 컬럼 표(`backtesting.daily_cache.load_daily_all` 결과)."""
    import pandas as pd
    df = daily[["code", "date", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["tv"] = df["close"] * df["volume"]
    top = df.sort_values("tv", ascending=False, kind="stable").groupby("date").head(top_n)
    ranked = {d.date(): set(g["code"]) for d, g in top.groupby("date")}
    import bisect
    days = sorted(ranked)
    ex, extra = exclude or set(), extra or set()
    out = {}
    for d in dates:
        i = bisect.bisect_left(days, d) - 1          # d 보다 앞선 가장 최근 순위일 — 오늘 일봉이 아직 없어도 어제 순위로 계산된다
        if i >= 0:
            out[d] = (ranked[days[i]] - ex) | extra
    return out


def tick_files() -> dict[str, set[str]]:
    """종목 -> 수집된 날짜 집합(원본 csv 든 압축 parquet 이든 수집된 것으로 친다)."""
    out: dict[str, set[str]] = {}
    for code, d in _code_files("tick_al").items():
        out[code] = {f.name[:10] for f in d.iterdir() if re.match(r"\d{4}-\d{2}-\d{2}", f.name)}
    return out


def tick_window(now: datetime | None = None, cal: Calendar | None = None, daily=None, collected=None,
                exclude: set[str] | None = None) -> dict:
    """체결 조회창(최근 20거래일) 날짜별 상태. days_left = 이 날짜가 조회창에서 밀려나기까지 남은 거래일."""
    now, cal = now or datetime.now(), cal or Calendar()
    cfg = catalog.dataset("tick_al").freshness
    n = cfg.get("window_days", TICK_WINDOW_DAYS)
    if exclude is None:
        from data_exclude import MEGA_CAP_EXCLUDE as exclude  # 틱 수집기와 같은 목록 한 곳
    d = now.date()
    if not cal.is_trading_day(d):
        d = cal.prev_trading_day(d + timedelta(days=1))
    slots = [d]
    while len(slots) < n:
        slots.append(cal.prev_trading_day(slots[-1]))
    slots.reverse()                                        # 오래된 날부터
    if daily is None:
        from backtesting.daily_cache import load_daily_all
        daily = load_daily_all(daily_dir=str(catalog.path("daily", code="X").parent),
                               cache_path=str(catalog.path("daily_all_cache")))
    collected = tick_files() if collected is None else collected
    exp = expected_tick_codes(daily, slots, cfg.get("top_n", 35), set(cfg.get("extra_codes", [])), set(exclude))
    today_open = d == now.date() and now.time() < dtime(*(int(x) for x in TICK_CLOSE_TIME.split(":")))
    rows, pairs = [], []
    for i, day in enumerate(slots):
        codes = exp.get(day, set())
        have = {c for c in codes if day.isoformat() in collected.get(c, ())}
        miss = sorted(codes - have)
        pending = day == d and today_open                   # 오늘 체결은 아직 받을 수 없다
        st = "pending" if pending else ("missing" if codes and not have else "partial" if miss else "collected")
        rows.append({"date": day.isoformat(), "status": st, "collected_codes": len(have),
                     "expected_codes": len(codes), "days_left": i, "missing": miss})
        if not pending:
            pairs += [(c, day.isoformat()) for c in miss]
    lost = [r for r in rows if r["missing"] and r["status"] != "pending"]
    min_left = min((r["days_left"] for r in lost), default=None)
    v = "good" if not lost else "bad" if min_left is not None and min_left <= 2 else "warn"
    return {"verdict": v, "window_days": n, "dates": rows, "missing_pairs": pairs, "min_days_left": min_left,
            "reason": "빠진 체결 없음" if not lost else f"미수집 {len(pairs)}쌍, 가장 급한 날짜 남은 {min_left}거래일"}


def archive_spans() -> dict:
    """보관소 커버리지 — 마지막 병합 시각, 전체 첫/끝 날짜, 종목별 보관 기간(달력일) 분포. 파일 푸터(통계)만 읽어 1초 안팎."""
    import pyarrow.parquet as pq
    first = last = None
    merge_ts = None
    spans = []
    for code, p in _code_files("minute_al_archive").items():
        try:
            pf = pq.ParquetFile(p)
            i = pf.schema_arrow.names.index("date")
            st = [pf.metadata.row_group(g).column(i).statistics for g in range(pf.metadata.num_row_groups)]
            lo, hi = min(x.min for x in st), max(x.max for x in st)
        except Exception:
            continue
        first, last = (lo if first is None or lo < first else first), (hi if last is None or hi > last else last)
        spans.append((hi.date() - lo.date()).days + 1)
        m = p.stat().st_mtime
        merge_ts = m if merge_ts is None or m > merge_ts else merge_ts
    edges = [(20, "1–20일"), (60, "21–60일"), (120, "61–120일"), (10 ** 9, "121일 이상")]
    buckets = [{"label": lab, "codes": sum(1 for d in spans if (edges[i - 1][0] if i else 0) < d <= hi)} for i, (hi, lab) in enumerate(edges)]
    return {"last_merge_at": datetime.fromtimestamp(merge_ts).isoformat(timespec="seconds") if merge_ts else None,
            "first_date": str(first)[:10] if first is not None else None, "last_date": str(last)[:10] if last is not None else None,
            "span_buckets": buckets}


# ---------- 결측 거래일·밀린 종목 ----------


def gaps(daily=None, days: int = 120, now: datetime | None = None, cal: Calendar | None = None) -> list[dict]:
    """최근 days 거래일 각각에 데이터가 있는 종목 비율."""
    import pandas as pd
    now, cal = now or datetime.now(), cal or Calendar()
    if daily is None:
        from backtesting.daily_cache import load_daily_all
        daily = load_daily_all(daily_dir=str(catalog.path("daily", code="X").parent),
                               cache_path=str(catalog.path("daily_all_cache")))
    end = cal.prev_trading_day(now.date() + timedelta(days=1))
    slots = [end]
    while len(slots) < days:
        slots.append(cal.prev_trading_day(slots[-1]))
    n_codes = daily["code"].nunique()
    cnt = pd.to_datetime(daily["date"]).dt.date.value_counts()
    return [{"date": d.isoformat(), "codes": int(cnt.get(d, 0)), "share": round(cnt.get(d, 0) / n_codes, 4)}
            for d in sorted(slots)]


def stale(dataset_id: str = "daily", sophie_only: bool = False) -> list[dict]:
    """기준일(최빈 최신일)보다 오래된 종목. 소피증권 유니버스·거래 중단 종목을 표시한다."""
    dates = latest_dates(dataset_id)
    if not dates:
        return []
    ref = Counter(dates.values()).most_common(1)[0][0]
    sophie, inactive = universe_codes(), inactive_codes()
    rows = [{"code": c, "last": d, "sophie": c in sophie,
             "inactive": inactive[c].get("reason") if c in inactive else None}
            for c, d in sorted(dates.items()) if d < ref]
    return [r for r in rows if r["sophie"]] if sophie_only else rows


# ---------- 데이터셋 종합 ----------


def _last_write(lock: str | None) -> dict | None:
    if not lock:
        return None
    for ev in reversed(ledger.read(30)):
        if ev["event"] == "end" and ev.get("lock") == lock:
            return {"ts": ev["ts"], "writer": ev.get("writer"), "source": ledger.source_label(ev.get("cmd")),
                    "ok": ev.get("ok")}
    return None


def dataset_status(dataset_id: str, now: datetime | None = None, cal: Calendar | None = None, memo: dict | None = None) -> dict:
    """memo: 한 번의 화면 갱신 안에서 무거운 계산(체결 조회창)을 여러 곳이 재사용하게 하는 사전 — 없으면 매번 계산한다."""
    now, cal = now or datetime.now(), cal or Calendar()
    d = catalog.dataset(dataset_id)
    rule = d.freshness.get("rule")
    if rule == "last_trading_day":
        if dataset_id == "index":
            dates = {p.stem: x for p in (catalog.root() / "data/index/daily").glob("*.csv")
                     if "_value" not in p.stem and (x := _csv_last_date(p))}
        else:
            dates = latest_dates(dataset_id) if "{code}" in d.path else \
                {"file": x for p in [catalog.root() / d.path] if (x := _file_date(p))}
        r = verdict_last_trading_day(dates, now, cal, universe_codes(), set(inactive_codes()),
                                     d.freshness.get("deadline", "07:30"))
    elif rule == "max_age_days":
        dates_ = latest_dates(dataset_id)
        if d.freshness.get("min_value_eok"):
            r = verdict_minute_al(dates_, minute_al_targets(d.freshness["min_value_eok"]), now.date(),
                                  d.freshness.get("good", 14), d.freshness.get("warn", 21))
        else:
            r = verdict_max_age(dates_, now.date(), d.freshness.get("good", 14), d.freshness.get("warn", 21))
    elif rule == "archive_superset":
        r = archive_coverage()
    elif rule == "tick_window":
        w = memo_tick_window(memo, now, cal)
        r = {k: w[k] for k in ("verdict", "reason", "min_days_left")} | {
            "window_missing": len(w["missing_pairs"]), "n_codes": len(_code_files("tick_al"))}
    elif rule == "dist_sync":
        r = verdict_dist_sync()
    elif rule == "backup_exists":
        r = verdict_backup_exists(now, cal)
    elif rule == "newer_than_source":
        src = [p.stat().st_mtime for p in _code_files("daily").values()]
        cache = newest_mtime(catalog.root() / d.path)
        ok = cache is not None and src and cache >= max(src)
        r = {"verdict": "good" if ok else "warn", "reason": "원본보다 새것" if ok else "원본보다 낡음(읽을 때 재생성)"}
    else:
        r = {"verdict": "good", "reason": "신선도 규칙 없음"}
    ts = newest_mtime(catalog.root() / d.path) if "{" not in d.path else None
    return {"id": d.id, "label": d.label, "basis": d.basis, **r, "retention": d.retention,
            "last_write": _last_write(d.lock),
            "lock": {"resource": d.lock, "held": bool(d.lock and (o := locks.owner(d.lock)) and o.alive)} if d.lock else None,
            **({"updated": datetime.fromtimestamp(ts).isoformat(timespec="minutes")} if ts else {})}


def _file_date(p: Path) -> str | None:
    t = newest_mtime(p)
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d") if t else None


def memo_tick_window(memo: dict | None, now: datetime, cal: Calendar) -> dict:
    if memo is None:
        return tick_window(now, cal)
    if "tick_window" not in memo:
        memo["tick_window"] = tick_window(now, cal)
    return memo["tick_window"]


def overview(now: datetime | None = None, memo: dict | None = None) -> list[dict]:
    now, cal = now or datetime.now(), Calendar()
    memo = {} if memo is None else memo
    return [dataset_status(d.id, now, cal, memo) for d in catalog.load().datasets]


# ---------- 장부 밖 쓰기 (H11) ----------


def unledgered_writes(since: datetime, until: datetime | None = None, events: list[dict] | None = None) -> list[dict]:
    """(since, until] 사이에 수정된 잠금 데이터셋 파일 중, 같은 잠금의 장부 run 이 그 시각을 덮지 않는 것."""
    until = until or datetime.now()
    events = events if events is not None else ledger.read(max(1, (datetime.now() - since).days + 1))
    spans: dict[str, list[tuple[float, float]]] = {}
    for r in ledger.runs(events):
        start = datetime.fromisoformat(r["ts"]).timestamp()
        end = None
        for ev in events:
            if ev["run"] == r["run"] and ev["event"] == "end":
                end = datetime.fromisoformat(ev["ts"]).timestamp()
        spans.setdefault(r["lock"], []).append((start - 2, (end if end else until.timestamp()) + 2))
    out = []
    t0, t1 = since.timestamp(), until.timestamp()
    for d in catalog.load().datasets:
        if not d.lock or "{code}" not in d.path:
            continue
        for code, p in _code_files(d.id).items():
            files = [p] if p.is_file() else [f for f in p.iterdir() if f.is_file()]
            for f in files:
                m = f.stat().st_mtime
                if t0 < m <= t1 and not any(a <= m <= b for a, b in spans.get(d.lock, [])):
                    out.append({"dataset": d.id, "lock": d.lock, "file": str(f), "mtime": datetime.fromtimestamp(m).isoformat(timespec="seconds")})
    return out
