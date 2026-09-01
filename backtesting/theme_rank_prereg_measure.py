"""장시작 60분 테마순위 3축 측정 — strategy-agent 사전등록
(`state/agent_reports/strategy-agent_20260831-2240_theme_rank_prereg.md`,
2026-08-31 잠정재개 배너 포함) 그대로 실행. **이 결과는 잠정이다** —
data-agent가 41일을 일관된 상태로 재생성하면 같은 사전등록으로 재측정한다.

## 데이터
`kospi-theme-engine/results/rank_timeline_YYYYMMDD.json`(41거래일,
2026-07-01~08-28), 프레임 스키마 `{t, chgtop, rows[]}`,
`rows[i]={theme,score,rise,speed,leader,lead_pct,top}`(`top`=[name,pct]).
**제외 7일**(오염, 사전등록 배너): 0701,0702,0703,0706,0707,0708(IS),
0813(OOS) - `EXCLUDED_DATES`. 유효 IS 21일 / OOS 13일.

청산가/전일종가는 전부 `data/stocks/daily/<code>.csv`(일봉, 틱 파생 아님 -
`ret_eod` staleness 문제와 무관, 사전등록에서 이미 확인된 사항). 종목명→코드
매핑은 `kospi-theme-engine/data/reference/universe.csv`(996종목, 이름 중복
0건 직접 확인) - 이 파일은 날짜버전 없는 단일 스냅샷이라 **이름→코드
매핑 용도로만** 쓴다(가격은 절대 안 씀, 가격은 전부 일봉에서).

## 비용
사전등록이 명시한 **고정 0.52%**(왕복, `backtest-agent_20260831-182932`
2번 인용) 그대로 - 이번 스터디는 `t0_forward_return.round_trip_cost_pct`
(가격별 정률)가 아니라 사전등록에 박힌 상수를 쓴다(사전등록 이탈 방지).

## 표본 단위
일(day), 하루 1개 관측(테마/종목 겹침 없음) - 날짜 간 공통 시장충격 자기상관은
한계로 남는다(사전등록 명시).

## H1 — Δrank(09:01→10:00) vs 레벨
- 변화-신호: 09:01·10:00 둘 다에 존재하는 테마 중 Δrank(=rank0901-rank1000,
  양수=개선) 최대인 테마. 매수: 그 테마의 **10:00 시점** leader.
- 레벨-신호(대조군): 09:01 시점 rank1 테마. 매수 타이밍을 변화-신호와
  맞추려고(둘 다 forward return 창을 "10:00→당일종가"로 통일) 그 테마의
  **10:00 시점** leader를 산다(선정은 09:01 레벨, 체결은 10:00 필드) -
  사전등록이 레벨-신호의 매수 타이밍을 명시 안 해서 이렇게 정했다(해석
  판단, 명시).

## H2 — chgtop 고정성
그날 60프레임의 chgtop[0](종목명) 최빈값 = mode, mode_share=최빈 등장수/
non-null 프레임수. IS 중앙값으로 고정군(>=)/변동군(<) 분리(그 문턱을 OOS에도
그대로 적용). 매수: 그 mode 종목이 **마지막으로 chgtop에 등장한 프레임**의
pct로 진입가 역산.

## H3 — leader vs top(가격모멘텀 1위, 원 지시 "2등주"의 데이터 제약 재정의)
09:01 rank1 테마의 leader/top을 **둘 다 09:01 프레임 값으로** 진입(사전등록
명시). `top`이 빈 문자열인 날은 제외.

## 진입가 역산
`전일종가 x (1+발표등락률/100)`. 전일종가 = 그 코드의 `data/stocks/daily`에서
해당 날짜 **바로 앞 거래일**의 close(달력일 아님, 그 종목 자체의 거래일
캘린더 기준 - 상장일 근처 등으로 종목마다 결측일이 다를 수 있어 종목별로
계산).

실행: python -m backtesting.theme_rank_prereg_measure
"""
import glob
import json
import os

import numpy as np
import pandas as pd
from scipy import stats

RANK_TIMELINE_DIR = "kospi-theme-engine/results"
UNIVERSE_PATH = "kospi-theme-engine/data/reference/universe.csv"
DAILY_DIR = "data/stocks/daily"
COST = 0.0052  # 사전등록에 박힌 왕복비용 상수(고정, 재계산 안 함)
T_CRIT = 1.65  # 단측 5%

EXCLUDED_DATES = {"2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07",
                   "2026-07-08", "2026-08-13"}
IS_RANGE = ("2026-07-01", "2026-08-07")
OOS_RANGE = ("2026-08-10", "2026-08-28")


def _yyyymmdd_to_iso(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def available_dates() -> list[str]:
    files = sorted(glob.glob(os.path.join(RANK_TIMELINE_DIR, "rank_timeline_*.json")))
    dates = []
    for f in files:
        raw = os.path.basename(f)[len("rank_timeline_"):-len(".json")]
        iso = _yyyymmdd_to_iso(raw)
        if IS_RANGE[0] <= iso <= IS_RANGE[1] or OOS_RANGE[0] <= iso <= OOS_RANGE[1]:
            dates.append(iso)
    return sorted(dates)


def is_dates_valid(exclude: bool = True) -> list[str]:
    """exclude=True(기본, 잠정 라운드와 동일 재현용): 오염 7일 제외.
    exclude=False(41일 재정비본 재측정용): 전량 재생성돼 균일하니 제외 없이 41일 전부."""
    return [d for d in available_dates()
            if IS_RANGE[0] <= d <= IS_RANGE[1] and (not exclude or d not in EXCLUDED_DATES)]


def oos_dates_valid(exclude: bool = True) -> list[str]:
    return [d for d in available_dates()
            if OOS_RANGE[0] <= d <= OOS_RANGE[1] and (not exclude or d not in EXCLUDED_DATES)]


def load_frames(date_iso: str) -> list[dict] | None:
    path = os.path.join(RANK_TIMELINE_DIR, f"rank_timeline_{date_iso.replace('-', '')}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["frames"]


def frame_at(frames: list[dict], t: str) -> dict | None:
    for fr in frames:
        if fr["t"] == t:
            return fr
    return None


def theme_ranks(frame: dict) -> dict[str, int]:
    """frame['rows']를 score 내림차순으로 매겨 {테마명: 순위(1부터)}."""
    rows = sorted(frame["rows"], key=lambda r: (-r["score"], r["theme"]))
    return {r["theme"]: i + 1 for i, r in enumerate(rows)}


def theme_row(frame: dict, theme: str) -> dict | None:
    for r in frame["rows"]:
        if r["theme"] == theme:
            return r
    return None


def load_name_to_code() -> dict[str, str]:
    df = pd.read_csv(UNIVERSE_PATH)
    assert df["name"].duplicated().sum() == 0, "종목명 중복 - 매핑 신뢰 불가"
    return dict(zip(df["name"], df["code"].astype(str).str.zfill(6)))


class DailyPriceLookup:
    """종목코드별 일봉 close를 date-indexed Series로 캐싱 - 전일종가/당일종가
    조회를 반복 파일읽기 없이 O(1)에 가깝게."""

    def __init__(self, daily_dir: str = DAILY_DIR):
        self._daily_dir = daily_dir
        self._cache: dict[str, pd.Series] = {}

    def _series(self, code: str) -> pd.Series | None:
        if code not in self._cache:
            path = os.path.join(self._daily_dir, f"{code}.csv")
            if not os.path.exists(path):
                self._cache[code] = None
            else:
                s = pd.read_csv(path).set_index("date")["close"]
                self._cache[code] = s
        return self._cache[code]

    def close(self, code: str, date_iso: str) -> float | None:
        s = self._series(code)
        if s is None or date_iso not in s.index:
            return None
        return float(s.loc[date_iso])

    def prev_close(self, code: str, date_iso: str) -> float | None:
        """date_iso 이전 마지막 거래일의 close(그 종목 자체의 거래일 캘린더
        기준 - 달력일이 아니다). date_iso가 인덱스에 있든 없든 "그보다
        앞선 마지막 행"을 찾는다."""
        s = self._series(code)
        if s is None:
            return None
        pos = s.index.searchsorted(date_iso, side="left")  # idx[pos] >= date_iso인 첫 위치
        if pos == 0:
            return None
        return float(s.iloc[pos - 1])


def entry_price(prices: DailyPriceLookup, name_to_code: dict, name: str, pct: float, date_iso: str):
    code = name_to_code.get(name)
    if code is None:
        return None, None
    prev = prices.prev_close(code, date_iso)
    if prev is None:
        return code, None
    return code, prev * (1 + pct / 100.0)


def forward_return(prices: DailyPriceLookup, code: str, date_iso: str, entry: float) -> float | None:
    close = prices.close(code, date_iso)
    if close is None or entry is None or entry == 0:
        return None
    return close / entry - 1


def one_sample_ttest(x: np.ndarray) -> tuple[float, float, int]:
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 2:
        return float("nan"), float("nan"), n
    mean = x.mean()
    se = x.std(ddof=1) / np.sqrt(n)
    t = mean / se if se > 0 else float("inf") if mean > 0 else float("-inf")
    return float(mean), float(t), n


def two_sample_ttest(a: np.ndarray, b: np.ndarray) -> tuple[float, float, int, int]:
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan"), len(a), len(b)
    t, _ = stats.ttest_ind(a, b, equal_var=False)
    return float(a.mean() - b.mean()), float(t), len(a), len(b)


# ---------------------------------------------------------------------------
# H1 — Δrank(09:01→10:00) vs 레벨
# ---------------------------------------------------------------------------

def h1_daily_record(date_iso: str, prices: DailyPriceLookup, name_to_code: dict) -> dict | None:
    frames = load_frames(date_iso)
    if frames is None:
        return None
    f0901, f1000 = frame_at(frames, "09:01"), frame_at(frames, "10:00")
    if f0901 is None or f1000 is None:
        return None
    ranks0901, ranks1000 = theme_ranks(f0901), theme_ranks(f1000)
    common = set(ranks0901) & set(ranks1000)
    if not common:
        return None

    change_theme = max(sorted(common), key=lambda th: ranks0901[th] - ranks1000[th])
    level_theme = min(ranks0901, key=lambda th: ranks0901[th])  # rank1 @ 09:01

    change_row = theme_row(f1000, change_theme)
    change_code, change_entry = entry_price(prices, name_to_code, change_row["leader"], change_row["lead_pct"], date_iso)
    change_net = None
    if change_code:
        r = forward_return(prices, change_code, date_iso, change_entry)
        change_net = r - COST if r is not None else None

    level_net = None
    level_row = theme_row(f1000, level_theme)  # 10:00 필드로 체결(docstring 설계판단)
    if level_row is not None:
        level_code, level_entry = entry_price(prices, name_to_code, level_row["leader"], level_row["lead_pct"], date_iso)
        if level_code:
            r = forward_return(prices, level_code, date_iso, level_entry)
            level_net = r - COST if r is not None else None

    return {"date": date_iso, "change_theme": change_theme, "level_theme": level_theme,
            "change_net": change_net, "level_net": level_net}


def h1_measure(dates: list[str], prices: DailyPriceLookup, name_to_code: dict) -> pd.DataFrame:
    rows = [r for d in dates if (r := h1_daily_record(d, prices, name_to_code)) is not None]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# H2 — chgtop 고정성
# ---------------------------------------------------------------------------

def h2_daily_record(date_iso: str, prices: DailyPriceLookup, name_to_code: dict) -> dict | None:
    frames = load_frames(date_iso)
    if frames is None:
        return None
    chgtops = [fr["chgtop"] for fr in frames if fr.get("chgtop")]
    if len(chgtops) < 30:  # 최소표본(non-null>=30/60)
        return None
    names = [c[0] for c in chgtops]
    mode_name = pd.Series(names).value_counts().idxmax()
    mode_share = names.count(mode_name) / len(chgtops)
    last_pct = next(c[1] for c in reversed(chgtops) if c[0] == mode_name)  # 마지막 등장 프레임의 pct

    code, entry = entry_price(prices, name_to_code, mode_name, last_pct, date_iso)
    net = None
    if code:
        r = forward_return(prices, code, date_iso, entry)
        net = r - COST if r is not None else None
    return {"date": date_iso, "mode_name": mode_name, "mode_share": mode_share, "net": net}


def h2_measure(dates: list[str], prices: DailyPriceLookup, name_to_code: dict) -> pd.DataFrame:
    rows = [r for d in dates if (r := h2_daily_record(d, prices, name_to_code)) is not None]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# H3 — leader vs top(가격모멘텀 1위)
# ---------------------------------------------------------------------------

def h3_daily_record(date_iso: str, prices: DailyPriceLookup, name_to_code: dict) -> dict | None:
    frames = load_frames(date_iso)
    if frames is None:
        return None
    f0901 = frame_at(frames, "09:01")
    if f0901 is None:
        return None
    ranks = theme_ranks(f0901)
    if not ranks:
        return None
    rank1_theme = min(ranks, key=ranks.get)
    row = theme_row(f0901, rank1_theme)
    top = row.get("top") or []
    if not top or top[0] == "":
        return None  # top 빈 문자열인 날 제외(사전등록 명시)

    leader_code, leader_entry = entry_price(prices, name_to_code, row["leader"], row["lead_pct"], date_iso)
    top_code, top_entry = entry_price(prices, name_to_code, top[0], top[1], date_iso)
    if not leader_code or not top_code:
        return None
    leader_ret = forward_return(prices, leader_code, date_iso, leader_entry)
    top_ret = forward_return(prices, top_code, date_iso, top_entry)
    if leader_ret is None or top_ret is None:
        return None
    return {"date": date_iso, "theme": rank1_theme, "leader": row["leader"], "top": top[0],
            "same_stock": row["leader"] == top[0], "leader_ret": leader_ret, "top_ret": top_ret,
            "diff": leader_ret - top_ret}


def h3_measure(dates: list[str], prices: DailyPriceLookup, name_to_code: dict) -> pd.DataFrame:
    rows = [r for d in dates if (r := h3_daily_record(d, prices, name_to_code)) is not None]
    return pd.DataFrame(rows)


def _verdict(passed: bool, reason: str) -> str:
    return f"{'PASS' if passed else 'REJECT'} - {reason}"


def evaluate_h1(is_df: pd.DataFrame, oos_df: pd.DataFrame) -> list[str]:
    lines = [f"[H1] 유효일 IS={len(is_df)} (최소표본 20일 {'충족' if len(is_df) >= 20 else '미달-판단보류'})"]
    if len(is_df) < 20:
        return lines + ["[H1] 판단보류 (표본부족)"]
    change_mean, change_t, n = one_sample_ttest(is_df["change_net"].to_numpy(dtype=float))
    lines.append(f"[H1] IS 변화-신호 순수익 평균={change_mean*100:.3f}% t={change_t:.2f} n={n}")
    cond1 = change_mean > 0 and change_t >= T_CRIT
    lines.append(f"[H1] 기각조건1(순수익>0,t>={T_CRIT}): {_verdict(cond1, 'PASS' if cond1 else '기각')}")
    if not cond1:
        return lines

    diff = is_df["change_net"].to_numpy(dtype=float) - is_df["level_net"].to_numpy(dtype=float)
    diff_mean, diff_t, n2 = one_sample_ttest(diff)
    lines.append(f"[H1] IS 쌍대차(변화-레벨) 평균={diff_mean*100:.3f}% t={diff_t:.2f} n={n2}")
    cond2 = diff_mean > 0 and diff_t >= T_CRIT
    lines.append(f"[H1] 기각조건2(쌍대차 유의): {_verdict(cond2, 'PASS' if cond2 else '기각')}")
    if not cond2:
        return lines

    oos_mean, oos_t, n3 = one_sample_ttest(oos_df["change_net"].to_numpy(dtype=float))
    lines.append(f"[H1] OOS 변화-신호 순수익 평균={oos_mean*100:.3f}% t={oos_t:.2f} n={n3}")
    cond3 = oos_mean > 0 and np.sign(oos_mean) == np.sign(change_mean)
    lines.append(f"[H1] 기각조건3(OOS 부호유지+비용회복): {_verdict(cond3, 'PASS(잠정 채택)' if cond3 else '기각')}")
    return lines


def evaluate_h2(is_df: pd.DataFrame, oos_df: pd.DataFrame) -> list[str]:
    lines = [f"[H2] 유효일 IS={len(is_df)}"]
    if len(is_df) < 20:
        return lines + ["[H2] 판단보류 (표본부족)"]
    thresh = is_df["mode_share"].median()
    lines.append(f"[H2] 고정/변동 분리 문턱(IS mode_share 중앙값) = {thresh:.3f}")

    def split(df):
        fixed = df[df["mode_share"] >= thresh]["net"].to_numpy(dtype=float)
        varying = df[df["mode_share"] < thresh]["net"].to_numpy(dtype=float)
        return fixed, varying

    is_fixed, is_varying = split(is_df)
    fixed_mean, fixed_t, nf = one_sample_ttest(is_fixed)
    lines.append(f"[H2] IS 고정군 순수익 평균={fixed_mean*100:.3f}% t={fixed_t:.2f} n={nf}")
    cond1 = fixed_mean > 0 and fixed_t >= T_CRIT
    lines.append(f"[H2] 기각조건1: {_verdict(cond1, 'PASS' if cond1 else '기각')}")
    if not cond1:
        return lines

    diff_mean, diff_t, na, nb = two_sample_ttest(is_fixed, is_varying)
    lines.append(f"[H2] IS 고정군-변동군 차이={diff_mean*100:.3f}% t={diff_t:.2f} n_fixed={na} n_varying={nb}")
    cond2 = diff_mean > 0 and diff_t >= T_CRIT
    lines.append(f"[H2] 기각조건2: {_verdict(cond2, 'PASS' if cond2 else '기각')}")
    if not cond2:
        return lines

    oos_fixed, _ = split(oos_df)
    oos_mean, oos_t, n3 = one_sample_ttest(oos_fixed)
    lines.append(f"[H2] OOS 고정군 순수익 평균={oos_mean*100:.3f}% t={oos_t:.2f} n={n3}")
    cond3 = oos_mean > 0 and np.sign(oos_mean) == np.sign(fixed_mean)
    lines.append(f"[H2] 기각조건3: {_verdict(cond3, 'PASS(잠정 채택)' if cond3 else '기각')}")
    return lines


def evaluate_h3(is_df: pd.DataFrame, oos_df: pd.DataFrame) -> list[str]:
    lines = [f"[H3] 유효일 IS={len(is_df)} (최소표본 20일 {'충족' if len(is_df) >= 20 else '미달-판단보류'})"]
    if len(is_df) < 20:
        return lines + ["[H3] 판단보류 (표본부족)"]
    same_share = is_df["same_stock"].mean()
    lines.append(f"[H3] leader==top 동일종목 비율(IS, 보조통계) = {same_share*100:.1f}%")

    diff_mean, diff_t, n = one_sample_ttest(is_df["diff"].to_numpy(dtype=float))
    lines.append(f"[H3] IS (leader-top) 평균={diff_mean*100:.3f}% t={diff_t:.2f} n={n}")
    cond1 = diff_mean > 0 and diff_t >= T_CRIT
    lines.append(f"[H3] 기각조건1: {_verdict(cond1, 'PASS' if cond1 else '기각')}")
    cond2 = abs(diff_mean) >= COST
    lines.append(f"[H3] 기각조건2(|차이|>=비용 {COST*100:.2f}%): {_verdict(cond2, 'PASS' if cond2 else '기각')}")
    if not (cond1 and cond2):
        return lines

    oos_mean, oos_t, n3 = one_sample_ttest(oos_df["diff"].to_numpy(dtype=float))
    lines.append(f"[H3] OOS (leader-top) 평균={oos_mean*100:.3f}% t={oos_t:.2f} n={n3}")
    cond3 = np.sign(oos_mean) == np.sign(diff_mean)
    lines.append(f"[H3] 기각조건3(OOS 부호유지): {_verdict(cond3, 'PASS(잠정 채택)' if cond3 else '기각')}")
    return lines


def main():
    print("[잠정] 테마순위 3축 측정 - 오염 7일 제외(0701,02,03,06,07,08,0813)", flush=True)
    prices = DailyPriceLookup()
    name_to_code = load_name_to_code()
    is_dates, oos_dates = is_dates_valid(), oos_dates_valid()
    print(f"IS {len(is_dates)}일 / OOS {len(oos_dates)}일", flush=True)

    os.makedirs("results", exist_ok=True)
    h1_is, h1_oos = h1_measure(is_dates, prices, name_to_code), h1_measure(oos_dates, prices, name_to_code)
    h2_is, h2_oos = h2_measure(is_dates, prices, name_to_code), h2_measure(oos_dates, prices, name_to_code)
    h3_is, h3_oos = h3_measure(is_dates, prices, name_to_code), h3_measure(oos_dates, prices, name_to_code)
    h1_is.to_csv("results/theme_rank_h1_is.csv", index=False)
    h1_oos.to_csv("results/theme_rank_h1_oos.csv", index=False)
    h2_is.to_csv("results/theme_rank_h2_is.csv", index=False)
    h2_oos.to_csv("results/theme_rank_h2_oos.csv", index=False)
    h3_is.to_csv("results/theme_rank_h3_is.csv", index=False)
    h3_oos.to_csv("results/theme_rank_h3_oos.csv", index=False)

    for lines in (evaluate_h1(h1_is, h1_oos), evaluate_h2(h2_is, h2_oos), evaluate_h3(h3_is, h3_oos)):
        for line in lines:
            print(line, flush=True)
        print(flush=True)

    return h1_is, h1_oos, h2_is, h2_oos, h3_is, h3_oos


if __name__ == "__main__":
    main()
