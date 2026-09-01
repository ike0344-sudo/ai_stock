"""대금 (20)위 안 등락률 1등 — 슈팅 관성 (사용자 직접지시 2026-09-01, 큐 상단).

## 통합(AL) 기준 — 어떻게 보장했나
데이터 소스는 `kospi-theme-engine/results/rank_timeline_full_*.json`(41일) 뿐이다 -
data-agent가 `MINUTE_STORE=al`로 재생성 완료(STATUS.md 2026-08-31 22:25) 확인,
이 리포트 작성 중 직접 `rank_timeline.py` 소스를 다시 읽어 재검증: `all_codes()`(참조
밖 종목까지 포함한 시장 전체) 유니버스를 쓰고, 실행 시 저장소가 "통합(KRX+NXT)"인지
"KRX 전용"인지 매번 로그로 찍게 돼 있다(41일 재생성 로그가 전부 통합이었다고
data-agent 보고 - 여기서 로그를 다시 볼 수는 없어 소스 코드 경로가 AL을 강제하는
구조인지만 직접 확인했다). 이 스크립트는 그 산출물을 읽기만 한다 -
MINUTE_STORE 환경변수를 직접 켤 필요가 없다(이미 만들어진 결과 소비).

## 명명 불일치 - 직접 확인해 정정
큐 제목은 "대금 25위"라 썼지만, `rank_timeline.py`를 직접 열어보니 `chgtop`은
`config.yaml`의 `value_rank_top: 20` 기준이다(25가 아니라 20). 리포트 전체에서
**"대금 20위"로 통일**한다 - 기존 CEILING/TAKEOVER 실험(그쪽은 진짜 25위, 별도
SQL)과 기준 종목수가 다르므로 절대 직접 비교하지 않는다.

## 순방향수익률 - 데이터 갭을 어떻게 메웠나
`chgtop`은 "그 순간의 1등 코드"만 담아, 그 코드가 순위에서 밀려나면 이후
가격을 이 파일 안에서 더 못 따라간다. 로컬 AL 분봉 캐시는 사실상 없다
(`data/stocks/minute_combined/`엔 파일 3개뿐, 부분적). 그래서 순방향수익률은
`data/stocks/minute/<code>.csv`(**KRX전용** 1분봉, 41일 전체 커버, 여기서 확인)로
근사했다 - **1등 판정(AL)과 수익률 측정(KRX전용) 기준이 다르다.** 이 근사가
실제로 얼마나 어긋나는지 `data/stocks/tick_al`(AL 원틱, 118종목, 08-04~08-28)이
겹치는 OOS 날짜·종목에서 직접 대조해 §5에 보고한다.

## 항목4(AL vs KRX 순위차이)는 판정보류 - 이유
"통합 기준 25(20)위 안인데 KRX 기준으로는 밖인 종목"을 가르려면 KRX전용 가격으로
**시장 전체(약 2,400종목) x 41일 x 390분의 누적거래대금 순위**를 새로 계산해야
한다 - `rank_timeline.py`의 라이브 엔진을 KRX전용 분봉으로 통째로 재현하는 별도
인프라 작업이라 이번 항목 범위 밖으로 판단했다(§6에 근거·후속 제안 명시).

실행: python -X utf8 -m backtesting.chgtop_leader_persistence
"""
import glob
import json
import os

import numpy as np
import pandas as pd

from _precursor_fastpath import SESSION_START, to_grid
from backtesting.t0_forward_return import round_trip_cost_pct
from backtesting.theme_rank_prereg_measure import (
    is_dates_valid,
    load_name_to_code,
    oos_dates_valid,
)

RANK_TIMELINE_FULL_DIR = "kospi-theme-engine/results"
MINUTE_DIR = "data/stocks/minute"
TICK_AL_DIR = "data/stocks/tick_al"
FORWARD_MIN = [1, 3, 5, 10]
MAX_STALE_SEC = 300  # 이보다 오래 체결이 없으면 그 시점 가격을 무효 처리(저유동성 근사오류 방지)


def load_full_frames(date_iso: str) -> list[dict] | None:
    path = os.path.join(RANK_TIMELINE_FULL_DIR, f"rank_timeline_full_{date_iso.replace('-', '')}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)["frames"]


def full_dates_available() -> list[str]:
    files = sorted(glob.glob(os.path.join(RANK_TIMELINE_FULL_DIR, "rank_timeline_full_*.json")))
    out = []
    for f in files:
        raw = os.path.basename(f)[len("rank_timeline_full_"):-len(".json")]
        out.append(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
    return sorted(out)


def extract_episodes(frames: list[dict], date_iso: str, name_to_code: dict) -> list[dict]:
    """분마다 chgtop[0](종목명)을 코드로 바꿔 연속런(에피소드)으로 접는다.
    None(그 분에 top20 안 양의 등락 종목이 없음)은 에피소드를 끊되 별도 기록은 안 한다."""
    codes = []
    for fr in frames:
        chgtop = fr.get("chgtop")
        if not chgtop:
            codes.append((None, None, None))
            continue
        name, pct, gap = chgtop
        codes.append((name_to_code.get(name), pct, gap))

    episodes = []
    cur = None
    for i, (code, pct, gap) in enumerate(codes):
        if cur is None or code != cur["code"]:
            if cur is not None:
                episodes.append(cur)
            cur = ({"date": date_iso, "code": code, "start_i": i, "end_i": i,
                    "start_t": frames[i]["t"], "onset_pct": pct, "onset_gap": gap}
                   if code else None)
        else:
            cur["end_i"] = i
    if cur is not None:
        episodes.append(cur)
    return episodes


class MinuteCloseLookup:
    """종목별 1분봉에서 특정 시각의 가격을 찾는다 - 파일당 1회만 읽어 캐싱한다.

    **버그 수정(2026-09-01, AL 재측정 중 자체발견)**: 원래 이 클래스는 `close`
    컬럼을 읽었다. 그런데 이 저장소의 1분봉 행 타임스탬프는 **구간 시작**을
    가리킨다(`09:01:00` 행은 [09:01:00,09:02:00) 구간) - 직접 대조로 확인:
    062040/2026-08-10 09:01 봉의 open=175,600·close=173,500인데, 같은 종목의
    원틱 09:01:00초 가격은 175,900(=open과 근접), 09:02:00초 가격은
    173,700(=close와 근접)이었다. 즉 `close`는 그 행 타임스탬프보다 **~1분
    뒤** 가격이다 - `close`를 쓰면 "09:01에 산다"고 해놓고 실제로는 09:02
    가격에 산 걸로 계산되고, 그다음 1분 뒤 수익률도 같이 1분씩 밀린다(체계적
    시차, KRX/AL 어느 쪽을 읽어도 똑같이 생기는 버그라 근사오차가 안 줄었던
    진짜 원인이었다). **`open`으로 고쳤다** - 그 행 타임스탬프 시점에 가장
    가까운 가격은 그 구간의 첫 체결가다."""

    def __init__(self, minute_dir: str = MINUTE_DIR):
        self._dir = minute_dir
        self._cache: dict[str, pd.DataFrame | None] = {}

    def _frame(self, code: str) -> pd.DataFrame | None:
        if code not in self._cache:
            path = os.path.join(self._dir, f"{code}.csv")
            if os.path.exists(path):
                self._cache[code] = pd.read_csv(path, index_col=0, parse_dates=True)[["open"]]
            else:
                self._cache[code] = None
        return self._cache[code]

    def price_at_or_after(self, code: str, ts: pd.Timestamp) -> float | None:
        """ts 이후 첫 봉의 open(=그 구간 첫 체결가, ts 시점에 가장 가까운 값).
        MAX_STALE_SEC 넘게 비면 무효(None) - 저유동성 종목 근사오류 방지."""
        df = self._frame(code)
        if df is None or len(df) == 0:
            return None
        idx = df.index.searchsorted(ts)
        if idx >= len(df):
            return None
        if (df.index[idx] - ts).total_seconds() > MAX_STALE_SEC:
            return None
        return float(df["open"].iloc[idx])


def forward_returns(lookup: MinuteCloseLookup, code: str, ts: pd.Timestamp) -> tuple[dict, float | None]:
    base = lookup.price_at_or_after(code, ts)
    out = {}
    for k in FORWARD_MIN:
        px = lookup.price_at_or_after(code, ts + pd.Timedelta(minutes=k))
        out[f"ret_{k}m"] = (px / base - 1) if (px is not None and base) else np.nan
    return out, base


def build_onset_dataset(dates: list[str], name_to_code: dict, lookup: MinuteCloseLookup) -> pd.DataFrame:
    """에피소드(연속 1등 유지 구간)마다 시작 시점 1건 - '1등이 되는 순간 산다'."""
    rows = []
    for date_iso in dates:
        frames = load_full_frames(date_iso)
        if frames is None:
            continue
        for ep in extract_episodes(frames, date_iso, name_to_code):
            if ep["code"] is None:
                continue
            held_min = ep["end_i"] - ep["start_i"] + 1
            ts = pd.Timestamp(f"{date_iso} {ep['start_t']}:00")
            fwd, entry_px = forward_returns(lookup, ep["code"], ts)
            rows.append({"date": date_iso, "code": ep["code"], "start_t": ep["start_t"],
                         "held_min": held_min, "onset_pct": ep["onset_pct"],
                         "onset_gap": ep["onset_gap"], "entry_px": entry_px, **fwd})
    return pd.DataFrame(rows)


def build_swap_dataset(dates: list[str], name_to_code: dict, lookup: MinuteCloseLookup,
                        lag_minutes: float = 0) -> pd.DataFrame:
    """교체 순간마다 (신규 1등, 빼앗긴 종목)을 같은 시점 기준으로 나란히 잰다 -
    같은 순간이라 그 시각의 시장 전체 충격은 자동으로 통제된다(쌍대 비교).

    lag_minutes>0: 교체를 "그 순간" 대신 그로부터 lag분 뒤에야 안다고 가정하고,
    진입·순방향수익률 기준 시각을 통째로 lag만큼 민다(실행지연 시뮬레이션 -
    swap_signal_validation.py 재사용)."""
    rows = []
    for date_iso in dates:
        frames = load_full_frames(date_iso)
        if frames is None:
            continue
        episodes = [e for e in extract_episodes(frames, date_iso, name_to_code) if e["code"] is not None]
        for prev_ep, cur_ep in zip(episodes, episodes[1:]):
            ts = pd.Timestamp(f"{date_iso} {cur_ep['start_t']}:00") + pd.Timedelta(minutes=lag_minutes)
            new_fwd, new_entry = forward_returns(lookup, cur_ep["code"], ts)
            old_fwd, old_entry = forward_returns(lookup, prev_ep["code"], ts)
            row = {"date": date_iso, "t": cur_ep["start_t"],
                   "new_code": cur_ep["code"], "old_code": prev_ep["code"],
                   "prev_held_min": prev_ep["end_i"] - prev_ep["start_i"] + 1}
            for k in FORWARD_MIN:
                row[f"new_ret_{k}m"] = new_fwd[f"ret_{k}m"]
                row[f"old_ret_{k}m"] = old_fwd[f"ret_{k}m"]
            rows.append(row)
    return pd.DataFrame(rows)


def validate_against_al_ticks(onset: pd.DataFrame, tick_dir: str = TICK_AL_DIR) -> pd.DataFrame:
    """KRX전용 분봉 근사가 실제 AL 원틱과 얼마나 어긋나는지, 겹치는 종목·일자에서
    직접 대조한다(onset 이벤트를 다시 안 만들고 이미 낸 것만 재측정)."""
    al_codes = {c for c in os.listdir(tick_dir) if os.path.isdir(os.path.join(tick_dir, c))}
    rows = []
    for _, r in onset.iterrows():
        if r["code"] not in al_codes:
            continue
        path = os.path.join(tick_dir, r["code"], f"{r['date']}.parquet")
        if not os.path.exists(path):
            continue
        g = to_grid(path)
        if g is None:
            continue
        px = g["px"]
        h, m = r["start_t"].split(":")
        t0 = int(h) * 3600 + int(m) * 60 - SESSION_START
        if not (0 <= t0 < len(px)):
            continue
        al_entry = px[t0]
        row = {"date": r["date"], "code": r["code"], "start_t": r["start_t"]}
        for k in FORWARD_MIN:
            t_k = t0 + k * 60
            al_ret = px[t_k] / al_entry - 1 if t_k < len(px) else np.nan
            row[f"al_ret_{k}m"] = al_ret
            row[f"krx_ret_{k}m"] = r[f"ret_{k}m"]
            row[f"diff_{k}m"] = al_ret - r[f"ret_{k}m"] if pd.notna(r[f"ret_{k}m"]) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def episode_length_stats(dates: list[str], name_to_code: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """held_min 분포(에피소드 단위) + 날짜별 에피소드 수/평균유지시간(오래지킨날 vs
    자주바뀐날 비교용)."""
    ep_rows, day_rows = [], []
    for date_iso in dates:
        frames = load_full_frames(date_iso)
        if frames is None:
            continue
        episodes = [e for e in extract_episodes(frames, date_iso, name_to_code) if e["code"] is not None]
        for e in episodes:
            ep_rows.append({"date": date_iso, "code": e["code"], "held_min": e["end_i"] - e["start_i"] + 1})
        if episodes:
            helds = [e["end_i"] - e["start_i"] + 1 for e in episodes]
            day_rows.append({"date": date_iso, "n_episodes": len(episodes),
                             "mean_held_min": float(np.mean(helds)), "median_held_min": float(np.median(helds))})
    return pd.DataFrame(ep_rows), pd.DataFrame(day_rows)


def summarize_onset_returns(df: pd.DataFrame, label: str) -> pd.DataFrame:
    valid = df.dropna(subset=["entry_px"])
    if valid.empty:
        return pd.DataFrame([{"set": label, "n": 0}])
    rows = []
    for k in FORWARD_MIN:
        col = f"ret_{k}m"
        sub = valid.dropna(subset=[col])
        if sub.empty:
            rows.append({"set": label, "horizon": f"{k}m", "n": 0})
            continue
        gross = sub[col].to_numpy()
        net = gross - round_trip_cost_pct(sub["entry_px"].to_numpy())
        daily = pd.DataFrame({"date": sub["date"], "gross": gross, "net": net})
        daily_mean = daily.groupby("date")["net"].mean()
        se = daily_mean.std(ddof=1) / np.sqrt(len(daily_mean)) if len(daily_mean) > 1 else np.nan
        rows.append({
            "set": label, "horizon": f"{k}m", "n": len(sub), "n_days": sub["date"].nunique(),
            "gross_mean_pct": gross.mean() * 100, "net_mean_pct": net.mean() * 100,
            "net_se_pct": se * 100 if pd.notna(se) else np.nan,
            "win_rate_pct": (net > 0).mean() * 100,
            "avg_cost_pct": round_trip_cost_pct(sub["entry_px"].to_numpy()).mean() * 100,
        })
    return pd.DataFrame(rows)


def main() -> None:
    name_to_code = load_name_to_code()
    lookup = MinuteCloseLookup()

    is_dates = is_dates_valid(exclude=False)
    oos_dates = oos_dates_valid(exclude=False)
    full_dates = set(full_dates_available())
    is_dates = [d for d in is_dates if d in full_dates]
    oos_dates = [d for d in oos_dates if d in full_dates]
    print(f"IS {len(is_dates)}일 / OOS {len(oos_dates)}일 (rank_timeline_full 존재분만)", flush=True)

    # 1) 유지시간 분포
    ep_is, day_is = episode_length_stats(is_dates, name_to_code)
    ep_oos, day_oos = episode_length_stats(oos_dates, name_to_code)
    print("\n=== 1) 1등 유지시간(분) - 에피소드 단위 ===")
    for label, ep in [("IS", ep_is), ("OOS", ep_oos)]:
        h = ep["held_min"]
        print(f"{label}: n={len(ep)}건 median={h.median():.0f} IQR=[{h.quantile(.25):.0f},{h.quantile(.75):.0f}] max={h.max():.0f}")
    for label, day in [("IS", day_is), ("OOS", day_oos)]:
        med = day["n_episodes"].median()
        few = day[day["n_episodes"] <= med]  # 적게 바뀐(=오래 지킨) 날
        many = day[day["n_episodes"] > med]
        print(f"{label} 날짜중앙값 에피소드수={med:.0f} | 적게바뀐날(n={len(few)}) 평균유지={few['mean_held_min'].mean():.1f}분"
              f" vs 자주바뀐날(n={len(many)}) 평균유지={many['mean_held_min'].mean():.1f}분")

    # 2) 튄 뒤 더 가는가 - onset 순방향수익률
    onset_is = build_onset_dataset(is_dates, name_to_code, lookup)
    onset_oos = build_onset_dataset(oos_dates, name_to_code, lookup)
    print(f"\nonset 이벤트 IS={len(onset_is)}건 / OOS={len(onset_oos)}건", flush=True)
    print("\n=== 2) 1등 진입 시 순방향수익률 (KRX전용 분봉 근사, 비용반영) ===")
    summary_is = summarize_onset_returns(onset_is, "IS")
    summary_oos = summarize_onset_returns(onset_oos, "OOS")
    pd.set_option("display.width", 200)
    print(pd.concat([summary_is, summary_oos]).to_string(index=False))

    # 3) 교체 순간이 신호인가
    swap_is = build_swap_dataset(is_dates, name_to_code, lookup)
    swap_oos = build_swap_dataset(oos_dates, name_to_code, lookup)
    print(f"\n=== 3) 교체 쌍대비교 (같은 순간, 신규1등 vs 빼앗긴종목) IS={len(swap_is)} OOS={len(swap_oos)} ===")
    for label, sw in [("IS", swap_is), ("OOS", swap_oos)]:
        if sw.empty:
            print(f"{label}: 표본 0건")
            continue
        for k in FORWARD_MIN:
            d = (sw[f"new_ret_{k}m"] - sw[f"old_ret_{k}m"]).dropna()
            if d.empty:
                continue
            daily = pd.DataFrame({"date": sw.loc[d.index, "date"], "diff": d}).groupby("date")["diff"].mean()
            se = daily.std(ddof=1) / np.sqrt(len(daily)) if len(daily) > 1 else np.nan
            print(f"{label} {k}m: n={len(d)} 신규-빼앗김 평균차이={d.mean()*100:+.3f}%p SE={se*100 if pd.notna(se) else float('nan'):.3f}%p")

    # 5) AL 원틱 대조(근사오차 정량화)
    val = validate_against_al_ticks(onset_oos)
    print(f"\n=== 5) KRX분봉 근사 vs AL원틱 직접대조 (OOS, 겹치는 {len(val)}건) ===")
    if val.empty:
        print("겹치는 표본 없음")
    else:
        for k in FORWARD_MIN:
            diffs = val[f"diff_{k}m"].dropna()
            if diffs.empty:
                continue
            print(f"  {k}m: n={len(diffs)} 평균오차={diffs.mean()*100:+.3f}%p 절대오차평균={diffs.abs().mean()*100:.3f}%p"
                  f" corr(AL,KRX)={val[[f'al_ret_{k}m', f'krx_ret_{k}m']].corr().iloc[0,1]:.3f}")

    os.makedirs("results", exist_ok=True)
    onset_is.to_csv("results/chgtop_onset_is.csv", index=False)
    onset_oos.to_csv("results/chgtop_onset_oos.csv", index=False)
    swap_is.to_csv("results/chgtop_swap_is.csv", index=False)
    swap_oos.to_csv("results/chgtop_swap_oos.csv", index=False)
    val.to_csv("results/chgtop_al_krx_validation.csv", index=False)
    print("\n저장: results/chgtop_onset_{is,oos}.csv, chgtop_swap_{is,oos}.csv, chgtop_al_krx_validation.csv")


if __name__ == "__main__":
    main()
