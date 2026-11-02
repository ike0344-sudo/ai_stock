"""매매 데스크 실시간 체결 흐름 — C 사다리 · 지금 신호 · 시장가 매수 세기(11-01 사용자 "C 중심으로", "시장가 매수 검증은 체결데이터로").

고른 종목 0B 푸시 하나하나를 시장가 매수/매도로 가른다:
  ① 15(체결량)에 +/− 부호가 오면 그것 ② 아니면 27·28(그 순간 매도·매수 1호가)과 체결가 비교 ③ 그것도 없으면 직전 체결가 비교.
  어느 방법으로 갈랐는지 세어 둔다(how) — 월요일 장에서 ①이 실제로 오는지 확인용.
평소 = 전 거래일 정규장 5분 시장가 매수 평균(체결 파일 data/stocks/tick_al). 없으면 전 거래일 1분봉 대금의 절반.
신호(3개월 체결로 확인한 것만, scratchpad tk_*.py · 메모리 market-buy-flow-findings):
  과열 매수 = 정규장 5분 시장가 매수가 평소 3배 이상 + 그 5분 오름 → 60분 뒤 −0.30%, −2% 먼저 29%·+2% 먼저 25%(평소 15·11%, 앞·뒤 같음 — 11-01 정규장 C·통합 전체로 다시) → 15분 '사지 말 것'
  헛오름 = 전날로 맞춘 '힘→가격' 기울기보다 더 오른 몫이 전날 상위 20% + 힘도 상위 20% → 30분 뒤 내림 61% → 15분
  C 첫 깨짐 = 그날 C 위에 있다가 처음 아래로 → 매도 몰림(대금 3.2배) → 30분
자동 매수에는 쓰지 않는다 — 화면·알림·기록만. 기록: state/trader/flow_events.jsonl
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TICK = ROOT / "data" / "stocks" / "tick_al"
LOG = ROOT / "state" / "trader" / "flow_events.jsonl"
EDGES = [9, .10, .07, .05, .03, .01, 0, -.01, -.02, -.03, -.04, -.05, -.06, -.08, -.10, -9]   # C 대비, 위에서 아래로
LABELS = ["+10%↑", "+7~10%", "+5~7%", "+3~5%", "+1~3%", "0~+1%", "−1~0%", "−2~−1%", "−3~−2%", "−4~−3%", "−5~−4%", "−6~−5%", "−8~−6%", "−10~−8%", "−10%↓"]
HEAT_X, REG0, REG1 = 3.0, 540, 930                                    # 과열 = 평소 3배 · 정규장 09:00~15:30(분)
BLOCK = {"heat": 15, "hot": 15, "cbreak": 30}
_lock = threading.Lock()
_st: dict[str, dict] = {}                                             # 종목 → 오늘 상태
_base: dict[tuple, dict] = {}                                         # (종목, 오늘, C 날) → 평소·과거(하루 한 번)
_c: dict[str, int] = {}                                               # 종목 → 지금 C(화면 폴링이 넣는다 — C 깨짐 판단용)
notify = None                                                         # desk.note — 과열·C 깨짐·헛오름을 데스크 알림으로


def _int(raw) -> int:
    try:
        return int(str(raw).strip().replace("+", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0


def side_of(values: dict, px: int, prev_px: int, last: int) -> tuple[int, str]:
    """(+1 매수 / −1 매도, 방법). 15 부호 → 호가 비교 → 직전가 비교. 같은 값이면 앞 방향."""
    raw = str(values.get("15") or "").strip()
    if raw[:1] in "+-" and raw[1:2].isdigit():
        return (1 if raw[0] == "+" else -1), "sign15"
    ask, bid = abs(_int(values.get("27"))), abs(_int(values.get("28")))
    if ask and px >= ask:
        return 1, "quote"
    if bid and px <= bid:
        return -1, "quote"
    if prev_px and px != prev_px:
        return (1 if px > prev_px else -1), "tick"
    return last or 1, "tick"


def _new(day: str) -> dict:
    # pp: 가격 → [시장가매수, 시장가매도, 받아낸 매도(값 안 움직임), 받아낸 매수] 대금 · m1: 분 → [매수, 매도] · b5: 5분 → [매수, 매도, 시가, 종가]
    return {"day": day, "px": 0, "cum": 0, "side": 0, "how": {"sign15": 0, "quote": 0, "tick": 0}, "tside": 0, "agree": [0, 0], "pp": {}, "m1": {}, "b5": {},
            "done5": set(), "above": False, "cbreak": None, "until": {}, "ev": [], "t": 0}


def _log(code: str, kind: str, text: str, t: int) -> dict:
    e = {"ts": datetime.now().isoformat(timespec="seconds"), "code": code, "kind": kind, "t": f"{t // 60:02d}:{t % 60:02d}", "text": text}
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return e


def _emit(code: str, s: dict, kind: str, text: str, t: int) -> None:
    s["ev"].append(_log(code, kind, text, t))
    s["ev"] = s["ev"][-40:]
    if kind in BLOCK:
        s["until"][kind] = t + BLOCK[kind]
    if notify:
        try:
            notify(text, "warn" if kind in ("heat", "cbreak", "hot") else "info")
        except Exception:                                              # noqa: BLE001 — 알림 실패로 수신이 멈추면 안 된다
            pass


def on_tick(code: str, values: dict) -> None:
    """0B 푸시 하나. feed 스레드에서 불린다 — 가볍게."""
    px = abs(_int(values.get("10")))
    hhmmss = str(values.get("20") or "").strip()
    if not px or len(hhmmss) < 4 or not hhmmss[:4].isdigit():
        return
    t = int(hhmmss[:2]) * 60 + int(hhmmss[2:4])
    today = date.today().isoformat()
    with _lock:
        s = _st.get(code)
        if not s or s["day"] != today:
            s = _st[code] = _new(today)
        cum = abs(_int(values.get("13")))
        q = cum - s["cum"] if s["cum"] and cum > s["cum"] else (abs(_int(values.get("15"))) if not s["cum"] else 0)
        s["cum"] = max(s["cum"], cum)
        prev = s["px"]
        if q > 0:
            side, how = side_of(values, px, prev, s["side"])
            s["how"][how] += 1
            s["side"] = side
            ts = (1 if px > prev else -1) if prev and px != prev else (s["tside"] or 1)
            s["tside"] = ts
            if how == "sign15":                                        # 저장 체결 분석이 쓴 직전가 규칙이 진짜 부호와 몇 % 맞나
                s["agree"][0] += ts == side; s["agree"][1] += 1
            v = float(px * q)
            a = s["pp"].setdefault(px, [0.0, 0.0, 0.0, 0.0])
            a[0 if side > 0 else 1] += v
            if px == prev:
                a[2 if side < 0 else 3] += v                           # 값을 못 움직인 체결 = 반대편 지정가가 받아냄
            m = s["m1"].setdefault(t, [0.0, 0.0]); m[0 if side > 0 else 1] += v
            b = s["b5"].setdefault(t // 5, [0.0, 0.0, px, px])
            b[0 if side > 0 else 1] += v
            b[3] = px
            s["rhi"] = max(s.get("rhi", 0), px)                        # 오늘 고가 — HC(통합 · 정규장)
            if REG0 <= t < REG1:
                s["rhi_reg"] = max(s.get("rhi_reg", 0), px)
        s["px"], s["t"] = px, t
        C = _c.get(code)
        if C:
            if px >= C:
                s["above"] = True
            elif s["above"] and s["cbreak"] is None:
                s["cbreak"] = t
                _emit(code, s, "cbreak", f"{code} BC 깨짐 {px:,} (BC {C:,}) — 30분 사지 말 것 · 매도 몰림", t)
        _close5(code, s, t // 5)


def replay(base: Path, day: str | None = None) -> int:
    """데스크를 다시 켰을 때 오늘 저장된 0B(trader/rec.py live_al)를 다시 흘려 오늘 상태(HC 오늘 고가·사다리 오늘 몫·매수 세기)를 되살린다.
    피드 시작 전에 부른다(새 체결이 섞이면 누적 체결량 비교가 꼬인다). 켤 때는 평소·BC 가 아직 없어 과열·헛오름·BC 깨짐 알림이 다시 나지 않는다.
    11-02: 08:17 재시작 뒤 08:00 고가 129,400 이 빠져 HC 가 127,400 으로 나왔다."""
    import gzip
    n, day = 0, day or date.today().isoformat()
    for p in base.glob(f"*/{day}.jsonl.gz"):
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                for line in f:
                    if '"k": "0B"' in line:                             # 호가(0D)는 json 풀기 전에 거른다 — 줄의 60%, 풀기가 시간 대부분
                        on_tick(p.parent.name, json.loads(line)["v"])
                        n += 1
        except (OSError, EOFError, ValueError):                         # 쓰다 꺼져 끝이 잘린 파일 — 읽은 데까지
            pass
    return n


def _close5(code: str, s: dict, cur: int) -> None:
    """끝난 5분(정규장)마다 과열·헛오름 판정 — 평소는 전 거래일 기준(미리 보기 없음)."""
    base = _base.get((code, s["day"]))
    for w in sorted(k for k in s["b5"] if k < cur and k not in s["done5"]):
        s["done5"].add(w)
        if not base or not (REG0 <= w * 5 < REG1):
            continue
        bv, sv, o, c = s["b5"][w]
        end = w * 5 + 5
        if base.get("a1") and bv >= HEAT_X * base["a1"] and c > o and bv > sv:
            _emit(code, s, "heat", f"{code} 과열 매수 — 평소의 {bv / base['a1']:.1f}배 · 따라 사지 말 것(60분 뒤 −0.3%, 위아래로 크게 흔들림)", end)
        prev = s["b5"].get(w - 1)
        if base.get("bb") is not None and prev and bv + sv:
            ret, flow = c / prev[3] - 1, (bv - sv) / (bv + sv)
            if flow >= base["fq"] and ret > 0 and ret - np.polyval(base["bb"], flow) >= base["rq"]:
                _emit(code, s, "hot", f"{code} 헛오름 — 매수 힘보다 {ret * 100:+.1f}% 더 튐 · 따라 사지 말 것(30분 뒤 내림 59%)", end)


def _tick_days(code: str, today: str) -> list[str]:
    d = TICK / code
    return sorted({p.name[:10] for p in d.iterdir() if p.suffix in (".parquet", ".csv") and p.name[:10] < today}) if d.exists() else []


def read_ticks(code: str, day: str):
    """그날 체결(최근 먼저) — 압축본(parquet: time·cur_prc·trde_qty) 또는 압축 전 원본(csv: cntr_tm 14자리). 읽기만.
    허브 압축이 이미 압축한 종목의 새 날짜를 건너뛰어 csv 로 남는 일이 있다(11-01 발견 — 10월 712개)."""
    import pandas as pd
    pq, cv = TICK / code / f"{day}.parquet", TICK / code / f"{day}.csv"
    if pq.exists():
        t = pd.read_parquet(pq, columns=["time", "cur_prc", "trde_qty"])
    elif cv.exists():
        t = pd.read_csv(cv, usecols=["cur_prc", "trde_qty", "cntr_tm"], dtype={"cntr_tm": str}, encoding="utf-8-sig")
        t = pd.DataFrame({"time": t.cntr_tm.str[8:14], "cur_prc": t.cur_prc, "trde_qty": t.trde_qty})
    else:
        return None
    return t


def _load_ticks(code: str, day: str):
    import pandas as pd
    t = read_ticks(code, day).iloc[::-1].reset_index(drop=True)
    hm = t.time.str[:4].astype(int).to_numpy()
    px = t.cur_prc.abs().to_numpy(float); v = px * t.trde_qty.abs().to_numpy(float)
    dp = np.sign(np.diff(px, prepend=px[0]))
    sd = pd.Series(dp).replace(0, np.nan).ffill().fillna(0).to_numpy()     # 저장된 체결엔 매수·매도 표시가 없어 직전가 비교
    return (hm // 100) * 60 + hm % 100, px, v, sd, dp == 0


def baseline(code: str, cday: str | None) -> dict:
    """평소(전 거래일)·헛오름 기울기·C 날부터 지난날 칸별 흐름·물린 % 용 가격별 대금. 하루 한 번(종목·C 날마다)."""
    today = date.today().isoformat()
    key = (code, today, cday)
    if key in _base:
        return _base[key]
    out: dict = {"a1": None, "src": None, "bb": None, "fq": None, "rq": None, "past": [], "vap_px": np.array([]), "vap_v": np.array([]), "cv": 0.0, "mday": []}
    days = _tick_days(code, today)
    raw = None
    try:
        from backtesting.value_ledger import _load_minute
        raw = _load_minute(code, "all")[0]
        if raw is not None and not raw.empty:
            raw.columns = [c.lower() for c in raw.columns]
        else:
            raw = None
    except Exception:                                                  # noqa: BLE001
        raw = None
    prev_day = raw.index[raw.index.strftime("%Y-%m-%d") < today][-1].strftime("%Y-%m-%d") if raw is not None and (raw.index.strftime("%Y-%m-%d") < today).any() else None
    try:
        if days and days[-1] == prev_day:                              # 체결 파일이 바로 전 거래일 것일 때만 '평소'로(한 달 전 파일을 쓰던 것 11-01)
            mins, px, v, sd, z0 = _load_ticks(code, days[-1])
            reg = (mins >= REG0) & (mins < REG1)
            w = mins[reg] // 5
            if reg.sum() > 100:
                bvw = np.bincount(w - w.min(), weights=(v * (sd > 0))[reg]); svw = np.bincount(w - w.min(), weights=(v * (sd < 0))[reg])
                lastp = np.array([px[reg][w == k][-1] if (w == k).any() else np.nan for k in range(w.min(), w.max() + 1)])
                tot = bvw + svw
                ok = tot > 0
                out["a1"], out["src"] = float(bvw[ok].mean()), f"{days[-1]} 체결"
                ret = np.diff(lastp) / lastp[:-1]; flow = ((bvw - svw) / np.where(ok, tot, np.nan))[1:]
                m = np.isfinite(ret) & np.isfinite(flow)
                if m.sum() >= 20 and np.std(flow[m]) > 0 and np.std(ret[m]) > 0:
                    out["bb"] = np.polyfit(flow[m], ret[m], 1)
                    out["fq"] = float(np.quantile(flow[m], 0.8)); out["rq"] = float(np.quantile(ret[m] - np.polyval(out["bb"], flow[m]), 0.8))
        for d in (x for x in days if cday and x >= cday):             # C 날부터 어제까지 — 칸 색(오늘 것과 합친다)
            mins, px, v, sd, z0 = _load_ticks(code, d)
            buy, sell = sd > 0, sd < 0
            if not buy.any() or not sell.any():
                continue
            out["past"].append({"d": d, "mins": mins, "px": px, "v": v, "buy": buy, "sell": sell, "z0": z0})
    except Exception:                                                  # noqa: BLE001 — 체결 파일이 깨졌으면 그 부분만 없이
        pass
    try:
        if raw is not None:
            if out["a1"] is None:                                      # 체결 파일이 없으면 전 거래일 1분봉 대금의 절반을 평소 매수로
                prev = raw[raw.index.strftime("%Y-%m-%d") < today]
                if len(prev):
                    last = prev[prev.index.normalize() == prev.index[-1].normalize()].between_time("09:00", "15:29")
                    if len(last):
                        out["a1"] = float((last.close * last.volume).resample("5min").sum().mean() / 2); out["src"] = "전날 1분봉(대금 절반)"
            if cday:
                mm = raw[(raw.index.strftime("%Y-%m-%d") >= cday) & (raw.index.strftime("%Y-%m-%d") < today)]
                out["vap_px"], out["vap_v"] = mm.close.to_numpy(float), (mm.close * mm.volume).to_numpy(float)
                # HC = C 날부터 어제까지 최고가 — 통합(11-01 사용자 "안랩 HC −4.95%" = 10-30 애프터 127,400) · 정규장(차트에서 '정규장' 누르면)
                rg = mm.between_time("09:00", "15:29")
                out["chi"], out["chi_reg"] = (float(mm.high.max()) if len(mm) else None), (float(rg.high.max()) if len(rg) else None)
                # 세력 읽기(날마다)는 1분봉으로 — 체결 파일은 고른 뒤에만 있어 오르던 날이 빠진다(HT로보틱스 10-14~10-21)
                for d, g in mm.groupby(mm.index.strftime("%Y-%m-%d")):
                    val = (g.close * g.volume).to_numpy(float)
                    if d == cday:
                        out["cv"] = float(val.sum())
                        rd = g.between_time("09:00", "15:29")          # BC 날 고점 — 통합 · 정규장(11-01 사용자 "신고대금일 기준의 고점도 선으로")
                        out["dhi"], out["dhi_reg"] = float(g.high.max()), (float(rd.high.max()) if len(rd) else None)
                    else:
                        out["mday"].append((d, (g.index.hour * 60 + g.index.minute).to_numpy(), g.close.to_numpy(float), val))
    except Exception:                                                  # noqa: BLE001
        pass
    with _lock:
        _base[key] = out
        _base[(code, today)] = out                                     # _close5 가 C 날 없이 찾는다
    return out


_ma_fb: dict[tuple, float] = {}


def ma_fallback(code: str, base: str) -> int:
    """키움 15분봉을 못 받았을 때 — 받아 둔 1분봉으로 15분봉 60선(끝난 봉 60개). 하루 한 번."""
    key = (code, base, date.today().isoformat())
    if key not in _ma_fb:
        v = 0.0
        try:
            from backtesting.value_ledger import _load_minute
            raw = _load_minute(code, "regular" if base == "reg" else "all")[0]
            if raw is not None and not raw.empty:
                cl = raw[[x for x in raw.columns if x.lower() == "close"][0]].resample("15min").last().dropna()
                v = float(cl.iloc[-60:].mean()) if len(cl) >= 60 else 0.0
        except Exception:                                              # noqa: BLE001
            pass
        _ma_fb[key] = v
    return int(round(_ma_fb[key]))


def _band(r: float) -> int:
    for i in range(len(EDGES) - 1):
        if EDGES[i + 1] <= r < EDGES[i]:
            return i
    return len(EDGES) - 2


def _zone(a) -> str:
    """칸 하나 [시장가매수 차이 합, 매도받음 차이 합, 매수받음 차이 합, 대금] → B 매수 우세 · S 매도 우세 · U 매물 · G 받침 · M 보통 · T 거래 적음."""
    if a[3] < 10e8:
        return "T"
    dbs, das, dab = a[0] / a[3] * 100, a[1] / a[3] * 100, a[2] / a[3] * 100
    if dbs >= 2: return "B"
    if dbs <= -2: return "S"
    if dab >= 1.5 and dab >= das: return "U"
    if das >= 1.5: return "G"
    return "M"


def _bands(px, C) -> np.ndarray:
    return np.array([_band(p / C - 1) for p in px], int) if len(px) < 5000 else np.clip(np.searchsorted(-np.array(EDGES[1:-1]), -(px / C - 1), side="left"), 0, len(EDGES) - 2)   # 경계값은 위 칸(EDGES[i+1] <= r)


def _bars5(mins, px, v) -> tuple[np.ndarray, np.ndarray]:
    """시간순 체결 → 5분 종가·대금."""
    w = mins // 5
    u, first = np.unique(w, return_index=True)
    return px[np.r_[first[1:] - 1, len(w) - 1]], np.bincount(np.searchsorted(u, w), weights=v)


def _op_day(c5, v5, prev, C, cv) -> dict:
    """하루를 세력 입장에서(11-01 사용자 "사다리는 세력 입장에서", 안랩 10-29 털기 → 10-30 C 회복 · HT로보틱스 "많이 흔들면서 올랐다") — 검증 전, 보기만.
    전날 종가 대비 −2% 넘게 내린 날: 대금이 C 날의 절반 이하면 털기 쪽(거래 없이 흘려 개인이 던지게), C 날 이상이면 넘기기 쪽(큰 손이 실어 판다).
    +2% 넘게 오른 날인데 그날 고점에서 4% 넘게 눌렸다 올렸으면 흔들며 올림(따라붙은 개인을 떼어 내며 올린다)."""
    r = float(v5.sum()) / cv
    chg = float(c5[-1]) / prev - 1
    dd = float((c5 / np.maximum.accumulate(c5) - 1).min())
    # 11-01 검증(scratchpad op_read_bt.py, 장부 460날 · 다음 날 09:00 사서 15:30, 비용 뺌): 평소 −0.39% · 털기 쪽 −0.67%(173) · 흔들며 올림 −0.68%(70, 앞 −2.65 뒤 +1.54)
    # · 큰 대금 하락(C날 50% 이상) −1.55%(14, 이긴 29%) — 털기·흔들기는 살 근거가 못 되고, 큰 대금 하락만 조심 쪽
    k = ("털기 쪽" if r <= 0.5 else "넘기기 쪽" if r >= 1 else "큰 대금 하락") if chg < -0.02 else "흔들며 올림" if chg > 0.02 and dd <= -0.04 else ""
    return {"k": k, "val": round(r * 100), "chg": round(chg * 100, 1), "dd": round(dd * 100, 1), "cl": float(c5[-1]), "vs_c": round((float(c5[-1]) / C - 1) * 100, 1)}


def _agg_day(px, v, buy, sell, z0, C, acc) -> None:
    tb, ts = v[buy].sum(), v[sell].sum()
    if not tb or not ts:
        return
    bs0, as0, ab0 = tb / (tb + ts), v[sell & z0].sum() / ts, v[buy & z0].sum() / tb
    bi = _bands(px, C)
    for i in np.unique(bi):
        mk = bi == i; bv, sv = v[mk & buy].sum(), v[mk & sell].sum(); w = bv + sv
        if not w:
            continue
        acc[i] += [(bv / w - bs0) * w, ((v[mk & sell & z0].sum() / sv - as0) * w) if sv else 0, ((v[mk & buy & z0].sum() / bv - ab0) * w) if bv else 0, w]


def _amt_sp(p, v, sv, C, amt, sp) -> None:
    """칸별 체결 대금(amt 에 더함) · 값별 시장가 매도(sp 에 더함)."""
    np.add.at(amt, _bands(p, C), v)
    u, inv = np.unique(p, return_inverse=True)
    for x, y in zip(u, np.bincount(inv, weights=sv)):
        sp[x] = sp.get(x, 0.0) + y


def view(code: str, C: int | None, cday: str | None, ma: int | None = None, px_hint: int | None = None) -> dict | None:
    """화면용 — 사다리 칸(구간 색·물린 %), 지금 위치, 벽, 매수 세기, 막힘, 최근 신호, 매수·매도 가른 방법."""
    if not C:
        return None
    with _lock:
        _c[code] = int(C)
        s = _st.get(code)
        s = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in s.items()} if s else None
    base = baseline(code, cday)
    nb = len(EDGES) - 1
    pc = base.setdefault("pc", {})                                     # 지난날 체결 몫은 하루 동안 안 변한다 — C 마다 한 번만(11-01 폴링마다 31만 체결 다시 셈 30ms → 캐시)
    if C not in pc:
        acc0, amt0, sp0 = np.zeros((nb, 4)), np.zeros(nb), {}
        for d in base["past"]:
            _agg_day(d["px"], d["v"], d["buy"], d["sell"], d["z0"], C, acc0)
        # C = 정규장 종가라 C 날 15:30 뒤 애프터 체결도 'C 뒤'(11-01 사용자 "정규장 끝나고 애프터장에서는 계산해야")
        for d in base["past"]:
            if cday and d["d"] >= cday:
                k = slice(None) if d["d"] > cday else d["mins"] >= REG1
                _amt_sp(d["px"][k], d["v"][k], (d["v"] * d["sell"])[k], C, amt0, sp0)
        pc[C] = (acc0, amt0, sp0)
    acc, amt, sp = pc[C][0].copy(), pc[C][1].copy(), dict(pc[C][2])
    px =(s or {}).get("px") or px_hint or 0                         # 체결이 아직 없으면(장 밖·주말) 마지막 시세
    vap_px, vap_v = base["vap_px"], base["vap_v"]
    if s and s["pp"]:
        pp = s["pp"]; prices = np.array(list(pp), float); arr = np.array(list(pp.values()))
        tb, ts = arr[:, 0].sum(), arr[:, 1].sum()
        if tb and ts:
            bs0, as0, ab0 = tb / (tb + ts), arr[:, 2].sum() / ts, arr[:, 3].sum() / tb
            bi = np.array([_band(p / C - 1) for p in prices])
            for i in np.unique(bi):
                a = arr[bi == i].sum(0); w = a[0] + a[1]
                if w:
                    acc[i] += [(a[0] / w - bs0) * w, ((a[2] / a[1] - as0) * w) if a[1] else 0, ((a[3] / a[0] - ab0) * w) if a[0] else 0, w]
        vap_px = np.concatenate([vap_px, prices]); vap_v = np.concatenate([vap_v, arr[:, 0] + arr[:, 1]])
    tot = vap_v.sum()
    rows = []
    for i in range(nb):
        hi = None if EDGES[i] >= 9 else round(C * (1 + EDGES[i]))
        lo = None if EDGES[i + 1] <= -9 else round(C * (1 + EDGES[i + 1]))
        mid = C * (1 + (max(EDGES[i + 1], -0.12) + min(EDGES[i], 0.12)) / 2)
        rows.append({"lab": LABELS[i], "lo": lo, "hi": hi, "z": _zone(acc[i]), "trap": round(float(vap_v[vap_px > mid].sum() / tot * 100)) if tot else None})
    # 세력 읽기 — C 날 뒤(오늘 포함) 칸마다 체결 대금 ÷ C 날 대금, 시장가 매도가 한 값에 몰렸나(개인 지정가 벽이 먹힘) 여러 값에 나눠 받았나(세력은 나눠 받는다)
    cv = base["cv"]
    today = s and s["pp"] and cday and s["day"] > cday
    if today:
        _amt_sp(prices, arr[:, 0] + arr[:, 1], arr[:, 1], C, amt, sp)
    if sp:
        spx = np.array(list(sp)); ssv = np.array(list(sp.values())); sb = _bands(spx, C)
    for i, r in enumerate(rows):
        r["amt"], r["op"], r["op_px"] = (round(amt[i] / cv * 100) if cv else None), "", None
        if cv and sp and amt[i] >= 0.02 * cv:
            m = (sb == i) & (ssv > 0)
            if m.sum() >= 3:
                j = np.argmax(np.where(m, ssv, -1))
                r["op"], r["op_px"] = ("몰림" if ssv[j] / ssv[m].sum() >= 0.25 else "나눠"), int(spx[j])
    op_days, prev = [], C
    if cv:
        for d, mi, cl, val in base["mday"]:
            op_days.append({"d": d[5:], **_op_day(*_bars5(mi, cl, val), prev, C, cv)}); prev = op_days[-1]["cl"]
        if today and s["b5"]:
            b5 = [s["b5"][k] for k in sorted(s["b5"])]
            op_days.append({"d": s["day"][5:], **_op_day(np.array([b[3] for b in b5], float), np.array([b[0] + b[1] for b in b5]), prev, C, cv)})
    op_days = op_days[-6:]
    wall = None
    if s and s["pp"]:
        ab = {p: a[2] for p, a in s["pp"].items() if a[2] > 0}
        day_v = sum(a[0] + a[1] for a in s["pp"].values())
        if ab and day_v and max(ab.values()) / day_v >= 0.01:
            wall = max(ab, key=ab.get)
    t = (s or {}).get("t") or 0
    heat = None
    if s and base["a1"] and REG0 <= t < REG1:
        bv5 = sum(v[0] for k, v in s["m1"].items() if t - 5 < k <= t)
        heat = round(bv5 / base["a1"], 1)
    blocks = []
    if s:
        names = {"heat": "과열 매수 뒤 15분", "hot": "헛오름 뒤 15분", "cbreak": "BC 깨진 뒤 30분"}
        blocks = [{"kind": k, "text": names[k], "until": f"{u // 60:02d}:{u % 60:02d}"} for k, u in s["until"].items() if t < u]
    how = (s or {}).get("how") or {}
    n = sum(how.values())
    return {"C": int(C), "px": px, "band": _band(px / C - 1) if px else None, "rows": rows,
            "trap_now": round(float(vap_v[vap_px > px].sum() / tot * 100)) if tot and px else None,
            "wall": wall, "ma": ma, "heat": heat, "base_src": base["src"], "hot_ready": base["bb"] is not None,
            "zone_days": len(base["past"]) + (1 if s and s["pp"] else 0),   # 구간 색 근거 = 체결 며칠(1일이면 흔들림이 크다)
            "op_days": op_days, **{k: max(base.get(k) or 0, s.get(r, 0) if s and cday and s["day"] >= cday else 0) or None for k, r in (("chi", "rhi"), ("chi_reg", "rhi_reg"))},
            **{k: base.get(k) or (s.get(r) if s and s["day"] == cday else None) for k, r in (("dhi", "rhi"), ("dhi_reg", "rhi_reg"))},
            "blocks": blocks, "events": list(reversed((s or {}).get("ev") or []))[:8],
            "how": {k: round(v / n * 100) for k, v in how.items()} if n else None, "n": n, "cbreak": (s or {}).get("cbreak"),
            "tick_ok": round(s["agree"][0] / s["agree"][1] * 100) if s and s["agree"][1] else None}


if __name__ == "__main__":                                            # 강제 확인: 매수·매도 가르기 · 과열 · C 첫 깨짐 · 벽
    assert side_of({"15": "+120"}, 100, 99, 0) == (1, "sign15") and side_of({"15": "-5"}, 100, 101, 0) == (-1, "sign15")
    assert side_of({"27": "101", "28": "100"}, 101, 100, 0) == (1, "quote") and side_of({"27": "101", "28": "100"}, 100, 101, 0) == (-1, "quote")
    assert side_of({}, 102, 101, 0) == (1, "tick") and side_of({}, 101, 101, -1) == (-1, "tick")
    import tempfile
    LOG = Path(tempfile.gettempdir()) / "flow_selfcheck.jsonl"          # 실제 기록에 시험 줄을 남기지 않게
    code, today = "999999", date.today().isoformat()
    _base[(code, today)] = {"a1": 1_000_000.0, "bb": None}
    got = []
    notify = lambda text, lv: got.append(text)                         # noqa: E731
    _c[code] = 10_000
    cum = 0
    def push(hhmm, px, q, sign="+"):
        global cum
        cum += q
        on_tick(code, {"10": str(px), "13": str(cum), "15": f"{sign}{q}", "20": hhmm + "00"})
    push("0900", 10_100, 10); push("0901", 10_200, 400)               # 09:00~09:05 매수 4,080,000 = 평소 4배, 오름
    push("0905", 10_200, 1, "-")                                       # 다음 5분 첫 체결에 앞 5분 판정
    assert any("과열" in x for x in got), got
    push("0906", 9_900, 50, "-")                                       # C 위 → 아래: 첫 깨짐
    push("0907", 10_100, 5); push("0908", 9_800, 5, "-")               # 두 번째 깨짐은 안 울림
    assert sum("BC 깨짐" in x for x in got) == 1, got
    push("0909", 9_800, 300, "-"); push("0910", 9_800, 300, "-")       # 같은 값에서 매도를 받아냄 → 벽 9,800
    v = view(code, 10_000, None)
    assert v["wall"] == 9_800 and v["how"]["sign15"] == 100 and v["tick_ok"] == 88 and any(b["kind"] == "cbreak" for b in v["blocks"]), v
    print("ok", len(got), "알림 ·", v["blocks"])
