"""홀드아웃(8/04~8/28 틱, 117종목) 순수 틱 백테스트 — 메커니즘 검증 전용.

목적: 파라미터 선택/전략 채택이 아니라 "분봉 근사가 얼마나 왜곡했는가"를 재는 것.
사용자 지시(2026-08-30)로 이 구간을 열었다 — 최종 검증 때 이미 본 구간이라는 걸
기억할 것(다시 홀드아웃으로 쓸 수 없음).

## 데이터 범위 확정 (사용자 실측 확인, 2026-08-30)
- **8/03 전체 제외**: 108/108종목 전부 15시 이후에나 첫 체결(사실상 장마감 30분
  조각만 남음, data-agent가 원인 확인: base_dt 무시+목표일 도달시 중단으로 인한
  경계일 절단). 8/04~8/28 18거래일은 전 종목 09시 시작, 절단 없음(전수 실측 확인).
- **196170(태성) 8/04 제외**: 수정주가 미반영으로 체결가가 실제보다 ~1.3배 높게
  기록됨(data-agent 확인).
- 확정 범위: **2026-08-04 ~ 2026-08-28, 18거래일**. 근거는
  data/stocks/tick/KNOWN_ISSUES.md(data-agent 기록)와 여기 둘 다에 남긴다.

## 조건별 계산 출처 (사용자 확정)
틱으로 계산: 3분 거래대금(조건1) · 3분 수익률(조건2) · 당일 신고가(조건4) ·
             고점대비 낙폭(조건5)
일봉으로 계산(분봉 아니므로 지시 위배 아님): 전일 종가 대비 당일등락률(조건3)
기존 D-1 일봉 근사 유지: top35 유니버스(조건8, 아래 "설계 판단" 참고)
명시적으로 끔(이번 한정, 데이터 한계): 코스피 레짐(조건7 — 지수 틱 없음),
             ML 게이트(피처가 분봉 기반이라 틱으로 재계산 필요, 이번엔 생략)

## 설계 판단

**(반박) top35 유니버스는 틱으로 안 옮긴다.** lead 원안은 틱 기반 누적거래대금
랭킹을 제안했으나, 우리가 가진 틱은 117종목뿐이다. 시장 전체(약 2,700종목) 대비
순위를 매기려면 시장 전체의 실시간 누적거래대금이 있어야 하는데, 117종목 틱으로는
기존 D-1 일봉 근사(전체 로컬 일봉 유니버스 기준)보다 좁은 표본이 된다 — 좁은
표본으로 순위를 매기면 더 정확해지는 게 아니라 더 틀리게 된다. 그래서 top35는
기존 daily_top_n_from_local(전체 로컬 일봉 유니버스, D-1)을 그대로 쓴다.

**(판단) 진입 판정 주기 = 30초, 실제 라이브 poll_interval_seconds(30.0,
trading_loop.py:446)와 일치.** 조건1(3분 롤링합)·조건2(3분 전 대비)는 이론적으로는
"새 체결"에서만 값이 바뀌어(시간만 지나 오래된 체결이 빠지는 방향은 값을 줄이기만
하지 새로 조건을 충족시키지 못한다) 틱 이벤트 시점만 평가해도 신호를 놓치지 않는다.
하지만 **실제 라이브 시스템은 30초마다만 재평가한다** — 틱마다 평가하면 실제로는
절대 낼 수 없는 결정 빈도로 백테스트하는 셈이라, 라이브가 실제로 낼 수 있는 결정
빈도를 기준으로 30초 그리드를 썼다(SQL의 time_bucket으로 구현, 각 30초 구간의
마지막 틱 상태로 그 구간의 "폴링 시점" 판단을 대표시킨다).
**부수 발견**: 분봉(1분) 백테스트는 이 실제 30초 주기보다도 2배 성글다 — 가격경로
근사뿐 아니라 판단 빈도 자체도 라이브보다 성기게 근사해왔다는 뜻.

**(판단) 체결가 = 그 폴링 시점의 마지막 체결가를 그대로 체결가로 쓴다(슬리피지만
적용).** 분봉 방식은 "다음 봉 시가"로 지연시키는데, 이는 분봉의 종가가 그 분이
끝나야만 확정되기 때문이다(미확정 정보 참조 방지). 틱은 그 반대다 — 폴링 시점에
알려진 마지막 체결가는 그 시점에 이미 시장에서 실현된, 완전히 알려진 값이다.
그러니 그 값 자체로 체결해도 미래참조가 아니다.

**(판단) 3분 창 = 정확히 직전 180초(시각 경계, 봉 3개 아님).** 사용자 지시대로.
SQL RANGE 윈도우로 구현 — 분 경계가 아니라 진짜 직전 180초.

**(설계 판단, lead 지시 확인) 진입 판정은 SQL(DuckDB), 청산 시뮬레이션은 파이썬.**
detect_final_entries 67%는 SQL 후보/simulate_trade_path 15%는 순차의존이라 제외한
오늘의 구분과 같은 원칙 — 익절 4단계+손절+본전청산은 이전 상태에 의존하는 순차
로직이라 SQL로 안 풀린다. 진입이 확정된 거래에 대해서만 파이썬으로 청산을 돈다
(대상이 크게 줄어 감당됨).

## 동시각 틱 처리 (알려진 한계)
원본 데이터가 초 단위 해상도라 같은 초 안의 여러 체결의 진짜 순서는 알 수 없다
— 캔들 내부 경로 문제와 같은 종류의 한계. 두 가지 서로 다른 처리를 실제로
검증해 차이를 확인했다:
1. 3분 거래대금 합(RANGE 윈도우): 동시각 틱은 SQL RANGE 표준대로 "동시 발생"으로
   취급해 같은 창에 함께 포함한다(양끝 포함, pandas rolling과는 다른 컨벤션 —
   자체 제작한 접두합+searchsorted 정답셋과 대조해 0건 불일치 확인).
2. 당일 신고가(cummax) 등 ROWS 기반 계산은 결정론적 타이브레이크(ORDER BY
   time, cur_prc, trde_qty)를 쓴다 — MAX라서 순서 자체는 결과에 영향 없지만
   재현성을 위해 고정했다(2회 재실행 결과 동일 확인).
**주의**: 최초 구현에서 "동시각 틱에 마이크로초 오프셋을 줘서 순서를 강제"하는
접근을 시도했다가 RANGE 윈도우 경계가 현재 행 자신의 오프셋만큼 밀리는 버그를
만들었다(직접 발견·재현·수정) — 지금은 RANGE 윈도우엔 순수 ts만 쓴다.

## 청산
익절 4단계(+2.5/4/5.5/7%, 각 25%)+손절(-2.5%)+무장후 본전청산 로직은
final_strategy._compute_exit_legs를 그대로 재사용한다(판단 로직 불변). 입력만
분봉 경로 대신 틱 경로로 바꾼다.

## 비용 모델
breakout_reversal.DEFAULT_COMMISSION_RATE/SLIPPAGE_RATE/TAX_RATE 그대로(기존과 동일).

실행: python -m backtesting.tick_holdout_verification
"""
import os

import duckdb
import pandas as pd

from .breakout_reversal import DEFAULT_COMMISSION_RATE, DEFAULT_SLIPPAGE_RATE, DEFAULT_TAX_RATE
from .final_strategy import (
    DAY_RETURN_CEILING,
    DAY_RETURN_FLOOR,
    DRAWDOWN_THRESHOLD,
    MIN_RETURN_PCT,
    MIN_TRADE_VALUE,
    RECOMMENDED_MAX_CONCURRENT_POSITIONS,
    TOP_N,
    _compute_exit_legs,
)
from .risk_manager import STOP_LOSS_PCT, TIERS
from .universe import daily_top_n_from_local

TICK_DIR = "data/stocks/tick"
DAILY_DIR = "data/stocks/daily"

# 데이터 품질 조사로 확정한 사용 범위 - 알려진 결측/이상 원칙에 따라 사용 전 제외.
EXCLUDED_DATES = {"2026-08-03"}  # 전종목(108/108) 15시 이후만 남은 절단(data-agent도 확인)
EXCLUDED_PAIRS = {("196170", "2026-08-04")}  # 수정주가 미반영(~1.3배 고평가, data-agent 확인)


def _entry_candidates_sql(
    tick_dir: str = TICK_DIR, daily_dir: str = DAILY_DIR, day_return_ceiling: float = DAY_RETURN_CEILING
) -> pd.DataFrame:
    """DuckDB로 진입 후보를 낸다 - top35(조건8)/레짐(조건7)/ML은 여기 없음, 별도 처리."""
    minute_glob = os.path.join(tick_dir, "*", "*.parquet").replace("\\", "/")
    daily_glob = os.path.join(daily_dir, "*.csv").replace("\\", "/")
    excl_date = next(iter(EXCLUDED_DATES))
    excl_code, excl_date2 = next(iter(EXCLUDED_PAIRS))

    query = f"""
    WITH daily AS (
        SELECT
            parse_filename(filename, true) AS code,
            date::DATE AS d,
            LAG(close) OVER (PARTITION BY filename ORDER BY date) AS prev_close
        FROM read_csv('{daily_glob}', filename=true, union_by_name=true)
    ),
    tick_raw AS (
        SELECT
            row_number() OVER (PARTITION BY filename ORDER BY time, cur_prc, trde_qty) - 1 AS seq,
            split_part(replace(filename, chr(92), chr(47)), chr(47), -2) AS code,
            parse_filename(filename, true) AS date_str,
            (parse_filename(filename, true) || ' ' ||
             substr(lpad(time, 6, '0'), 1, 2) || ':' ||
             substr(lpad(time, 6, '0'), 3, 2) || ':' ||
             substr(lpad(time, 6, '0'), 5, 2))::TIMESTAMP AS ts,
            cur_prc::DOUBLE AS cur_prc, trde_qty::DOUBLE AS trde_qty
        FROM read_parquet('{minute_glob}', filename=true, union_by_name=true)
        WHERE parse_filename(filename, true) != '{excl_date}'
          AND NOT (split_part(replace(filename, chr(92), chr(47)), chr(47), -2) = '{excl_code}'
                   AND parse_filename(filename, true) = '{excl_date2}')
    ),
    windowed AS (
        SELECT
            code, date_str, ts, seq, cur_prc,
            SUM(cur_prc * trde_qty) OVER w180 AS trailing_value,
            FIRST_VALUE(cur_prc) OVER w180 AS price_3min_ago,
            MIN(ts) OVER (PARTITION BY code, date_str) AS day_first_ts,
            MAX(cur_prc) OVER (PARTITION BY code, date_str ORDER BY ts, seq ROWS UNBOUNDED PRECEDING) AS day_high
        FROM tick_raw
        WINDOW w180 AS (PARTITION BY code, date_str ORDER BY ts RANGE BETWEEN INTERVAL 180 SECONDS PRECEDING AND CURRENT ROW)
    ),
    joined AS (
        SELECT w.*, d.prev_close
        FROM windowed w
        LEFT JOIN daily d ON d.code = w.code AND d.d = w.date_str::DATE
    ),
    flagged AS (
        SELECT *,
            (day_high - cur_prc) / day_high AS drawdown,
            (ts >= day_first_ts + INTERVAL 180 SECONDS) AS window_ready
        FROM joined
    ),
    sticky AS (
        SELECT *,
            MAX(CASE WHEN drawdown >= {DRAWDOWN_THRESHOLD} THEN 1 ELSE 0 END) OVER (
                PARTITION BY code, date_str ORDER BY ts, seq ROWS UNBOUNDED PRECEDING
            ) AS ever_dd
        FROM flagged
    ),
    bucketed AS (
        SELECT *, time_bucket(INTERVAL 30 SECOND, ts) AS bucket
        FROM sticky
    ),
    polled AS (
        SELECT * FROM bucketed
        QUALIFY ROW_NUMBER() OVER (PARTITION BY code, date_str, bucket ORDER BY ts DESC, seq DESC) = 1
    )
    SELECT
        code, date_str, ts AS entry_time, cur_prc AS price
    FROM polled
    WHERE window_ready
      AND prev_close IS NOT NULL
      AND (cur_prc / prev_close - 1) >= {DAY_RETURN_FLOOR}
      AND (cur_prc / prev_close - 1) < {day_return_ceiling}
      AND trailing_value >= {MIN_TRADE_VALUE}
      AND (cur_prc / price_3min_ago - 1) >= {MIN_RETURN_PCT}
      AND cur_prc >= day_high
      AND ever_dd = 0
    ORDER BY code, entry_time
    """
    return duckdb.sql(query).df()


def _rank1_winners_sql(
    tick_dir: str = TICK_DIR, daily_dir: str = DAILY_DIR, rank_n: int = 25
) -> pd.DataFrame:
    """25위+상승률1등을 top35 대체로 틱에서 계산한다(사용자 지시 2026-08-30).

    (설계 판단) 30초 그리드가 아니라 **1분 그리드**로 계산한다 - 진짜 이유는 순위가
    117종목 "전체를 가로질러" 매겨져야 하는데(같은 시각 다른 종목들과 비교), 30초
    단위로 전 종목 상태를 교차비교하려면 각 종목의 최근 상태를 조용한(그 30초에
    체결이 없는) 구간까지 이월시키는 전방채움이 필요해 구현이 크게 복잡해진다.
    1분 단위(사실상 기존 분봉 rank1 조건과 같은 평가주기, 다만 값 자체는 틱에서
    구한 정확한 누적거래대금/등락률)로 낮추면 "그 분의 마지막 틱" 하나로 각 종목
    상태를 대표시킬 수 있어 단순해진다. 진입 판정 자체(30초 그리드)보다 성긴
    평가주기라는 한계는 있다 - 알려진 근사로 명시한다.

    (반박, top35와 같은 이유) "25위"는 117종목(틱 커버) 안에서의 순위이지 시장
    전체(~2,700종목) 대비 순위가 아니다 - 틱이 없는 종목이 실제로는 25위 안에
    있었을 수 있는데 그건 여기서 반영이 안 된다. top35 조건에서 이미 지적한 것과
    동일한 한계다.
    """
    minute_glob = os.path.join(tick_dir, "*", "*.parquet").replace("\\", "/")
    daily_glob = os.path.join(daily_dir, "*.csv").replace("\\", "/")
    excl_date = next(iter(EXCLUDED_DATES))
    excl_code, excl_date2 = next(iter(EXCLUDED_PAIRS))

    query = f"""
    WITH daily AS (
        SELECT
            parse_filename(filename, true) AS code,
            date::DATE AS d,
            LAG(close) OVER (PARTITION BY filename ORDER BY date) AS prev_close
        FROM read_csv('{daily_glob}', filename=true, union_by_name=true)
    ),
    tick_raw AS (
        SELECT
            row_number() OVER (PARTITION BY filename ORDER BY time, cur_prc, trde_qty) - 1 AS seq,
            split_part(replace(filename, chr(92), chr(47)), chr(47), -2) AS code,
            parse_filename(filename, true) AS date_str,
            (parse_filename(filename, true) || ' ' ||
             substr(lpad(time, 6, '0'), 1, 2) || ':' ||
             substr(lpad(time, 6, '0'), 3, 2) || ':' ||
             substr(lpad(time, 6, '0'), 5, 2))::TIMESTAMP AS ts,
            cur_prc::DOUBLE AS cur_prc, trde_qty::DOUBLE AS trde_qty
        FROM read_parquet('{minute_glob}', filename=true, union_by_name=true)
        WHERE parse_filename(filename, true) != '{excl_date}'
          AND NOT (split_part(replace(filename, chr(92), chr(47)), chr(47), -2) = '{excl_code}'
                   AND parse_filename(filename, true) = '{excl_date2}')
    ),
    joined AS (
        SELECT t.*, d.prev_close,
            SUM(t.cur_prc * t.trde_qty) OVER (
                PARTITION BY t.code, t.date_str ORDER BY t.ts, t.seq ROWS UNBOUNDED PRECEDING
            ) AS day_cum_value
        FROM tick_raw t
        LEFT JOIN daily d ON d.code = t.code AND d.d = t.date_str::DATE
    ),
    minute_bucketed AS (
        SELECT *, time_bucket(INTERVAL 1 MINUTE, ts) AS minute
        FROM joined
        WHERE prev_close IS NOT NULL
    ),
    minute_last AS (
        SELECT * FROM minute_bucketed
        QUALIFY ROW_NUMBER() OVER (PARTITION BY code, date_str, minute ORDER BY ts DESC, seq DESC) = 1
    ),
    ranked AS (
        SELECT *,
            (cur_prc / prev_close - 1) AS day_return,
            ROW_NUMBER() OVER (PARTITION BY date_str, minute ORDER BY day_cum_value DESC, code ASC) AS value_rank
        FROM minute_last
    )
    SELECT date_str, minute, code AS winner_code
    FROM ranked
    WHERE value_rank <= {rank_n}
    QUALIFY ROW_NUMBER() OVER (PARTITION BY date_str, minute ORDER BY day_return DESC, code ASC) = 1
    ORDER BY date_str, minute
    """
    return duckdb.sql(query).df()


def _simulate_tick_exit(entry_price: float, entry_time: pd.Timestamp, tick_series: pd.Series) -> dict | None:
    """진입 이후 같은 거래일 틱을 따라 4단계 분할익절+손절+본전청산 재현.
    tick_series: index=ts(정렬됨), value=cur_prc, 해당 (code,date) 전체."""
    day = entry_time.normalize()
    future = tick_series[(tick_series.index >= entry_time) & (tick_series.index.normalize() == day)]
    if future.empty:
        return None

    two_way_commission = DEFAULT_COMMISSION_RATE * 2
    path = []
    peak_pct = 0.0
    for ts, cur_prc in future.items():
        exit_price_if_now = cur_prc * (1 - DEFAULT_SLIPPAGE_RATE)
        net_pct = (exit_price_if_now - entry_price) / entry_price - two_way_commission - DEFAULT_TAX_RATE
        peak_pct = max(peak_pct, net_pct)
        path.append((ts, net_pct, peak_pct))

    legs = _compute_exit_legs(path, TIERS, STOP_LOSS_PCT)
    pct = sum(fraction * net_pct for _, _, fraction, net_pct in legs)
    exit_time = legs[-1][0]
    reason_seq = ",".join(leg[1] for leg in legs)
    return {"pct": pct, "exit_time": exit_time, "reason_seq": reason_seq}


def _load_tick_series(code: str, date_str: str, tick_dir: str) -> pd.Series:
    path = os.path.join(tick_dir, code, f"{date_str}.parquet")
    raw = pd.read_parquet(path)
    ts = pd.to_datetime(date_str + " " + raw["time"].str.zfill(6), format="%Y-%m-%d %H%M%S")
    return raw.assign(ts=ts).sort_values("ts", kind="stable").set_index("ts")["cur_prc"]


def _merge_same_code_reentries(candidates: pd.DataFrame, tick_dir: str) -> pd.DataFrame:
    """risk_manager.record_position_opened/record_position_added_to와 같은 원칙 —
    같은 종목에 이미 열린(아직 청산 안 된) 포지션이 있으면 새 슬롯을 쓰지 않고
    기존 포지션에 병합한다(사용자 지시 2026-08-30, 30초 그리드 재진입이 같은
    종목에 슬롯을 여러 개 먹이는 비현실적 결과를 낸 것을 발견하고 요청됨).

    (판단, 사용자 요청대로 근거를 남긴다) risk_manager는 완전 차단이 아니라
    "병합"(피라미딩 허용, 수량가중평균으로 진입가 갱신)이다 — 완전 차단으로
    구현하면 실거래 동작과 달라져 또 이원화가 생긴다. 그래서 병합으로 구현한다.

    (근사, 명시) 진짜 risk_manager는 수량(주식 수) 가중평균인데 이 백테스트는
    체결 수량을 안 다루고 %수익률만 다룬다 — 각 병합 leg를 "동일 배정자본"으로
    가정해 균등가중 평균으로 근사한다(슬롯 크기가 전부 동일하다는 simulate_
    slot_portfolio의 전제와 일치). 그리고 병합된 포지션의 청산 경로는 그룹의
    "첫 진입 시각"부터 "최종 블렌드 가격" 하나로 다시 시뮬레이션한다 — 실제로는
    블렌드 이전 구간은 그때그때의 블렌드 전 가격 기준으로 트리거를 봤어야
    정확하지만, 그 정밀한(레그마다 다른 기준가로 부분청산) 재현은 이번 긴급
    수정 범위 밖으로 판단해 근사로 명시한다.

    (판단) max_symbol_weight_pct(0.25)는 별도로 강제하지 않는다 — 슬롯 크기가
    이미 initial_capital/5=20%로 고정돼 있고, 병합은 "슬롯을 늘리는" 게 아니라
    "같은 슬롯 하나를 유지"하는 것이므로 이 설계에서는 종목당 비중이 20%를 넘지
    않는다(25% 한도 안에 이미 있음) — 추가 코드 없이 한도가 자동으로 지켜진다."""
    result_rows = []
    candidates = candidates.copy()
    candidates["entry_date"] = candidates["entry_time"].dt.date

    for (code, date_str), group in candidates.groupby(["code", "date_str"]):
        group = group.sort_values("entry_time").reset_index(drop=True)
        tick_series = _load_tick_series(code, date_str, tick_dir)

        group_start = None
        group_prices = []
        group_exit_time = None
        group_exit_info = None

        def _flush():
            if group_start is None:
                return
            result_rows.append({
                "code": code, "entry_time": group_start,
                "entry_price": sum(group_prices) / len(group_prices),
                "exit_time": group_exit_info["exit_time"], "pct": group_exit_info["pct"],
                "reason_seq": group_exit_info["reason_seq"], "n_merged_legs": len(group_prices),
            })

        for _, row in group.iterrows():
            entry_price = row["price"] * (1 + DEFAULT_SLIPPAGE_RATE)
            if group_start is not None and row["entry_time"] < group_exit_time:
                # 아직 청산 안 된 기존 포지션에 병합 - 블렌드 가격으로 재시뮬레이션.
                group_prices.append(entry_price)
                blended = sum(group_prices) / len(group_prices)
                info = _simulate_tick_exit(blended, group_start, tick_series)
                if info is not None:
                    group_exit_info = info
                    group_exit_time = info["exit_time"]
                continue
            # 새 포지션(첫 진입이거나, 이전 포지션이 이미 청산됨)
            _flush()
            info = _simulate_tick_exit(entry_price, row["entry_time"], tick_series)
            if info is None:
                group_start = None
                continue
            group_start = row["entry_time"]
            group_prices = [entry_price]
            group_exit_info = info
            group_exit_time = info["exit_time"]
        _flush()

    return pd.DataFrame(result_rows)


def scan_tick_trades(
    tick_dir: str = TICK_DIR, daily_dir: str = DAILY_DIR,
    day_return_ceiling: float = DAY_RETURN_CEILING,
    use_rank1: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """진입은 SQL(DuckDB), 청산은 파이썬(순차의존) - lead 지시 구분 그대로.

    use_rank1=True: top35(D-1 일봉 근사) 대신 25위+상승률1등(틱 기반, _rank1_winners_sql)
    을 유니버스 조건으로 쓴다 - 사용자 지시(2026-08-30)대로 대체 관계(둘 다 켜지 않음)."""
    candidates = _entry_candidates_sql(tick_dir, daily_dir, day_return_ceiling)
    n_before_universe = len(candidates)
    candidates["date_ts"] = pd.to_datetime(candidates["date_str"])

    if use_rank1:
        winners = _rank1_winners_sql(tick_dir, daily_dir)
        winners["minute"] = pd.to_datetime(winners["minute"])
        candidates["minute"] = candidates["entry_time"].dt.floor("min")
        merged = candidates.merge(
            winners, on=["date_str", "minute"], how="left", suffixes=("", "_w")
        )
        candidates["universe_ok"] = merged["winner_code"] == merged["code"]
    else:
        daily_top35 = daily_top_n_from_local(daily_dir, top_n=TOP_N)
        candidates["universe_ok"] = candidates.apply(
            lambda r: r["code"] in daily_top35.get(r["date_ts"], set()), axis=1
        )

    candidates = candidates[candidates["universe_ok"]].reset_index(drop=True)
    n_after_universe = len(candidates)

    # 같은 종목 재진입 병합(risk_manager.record_position_added_to와 같은 원칙) -
    # _merge_same_code_reentries 문서 참고. 이걸 거치면 "같은 종목에 30초마다
    # 재진입"이 하나의 논리적 포지션으로 합쳐진다.
    merged_positions = _merge_same_code_reentries(candidates, tick_dir)
    n_after_merge = len(merged_positions)

    # 동시보유 5슬롯 제약(risk_limits.yaml max_concurrent_positions) - 기존
    # simulate_slot_portfolio를 그대로 재사용한다(새로 안 짬, 분봉 백테스트와
    # 같은 함수 - 사용자 지시). 슬롯 크기 20%(=1/5)가 max_symbol_weight_pct(0.25)
    # 이내라 별도 비중 제약은 필요 없다(_merge_same_code_reentries 문서 참고).
    from .portfolio_sim import simulate_slot_portfolio

    if len(merged_positions):
        portfolio = simulate_slot_portfolio(
            merged_positions[["code", "entry_time", "exit_time", "pct"]],
            initial_capital=10_000_000, max_concurrent_positions=RECOMMENDED_MAX_CONCURRENT_POSITIONS,
        )
        taken = portfolio.taken_trades
        trades = merged_positions[merged_positions.apply(
            lambda r: any(t.code == r["code"] and t.entry_time == r["entry_time"] for t in taken), axis=1
        )].reset_index(drop=True)
        n_skipped_slot_full = portfolio.skipped_count
    else:
        trades = merged_positions
        n_skipped_slot_full = 0

    diag = {
        "n_candidates_pre_universe_filter": n_before_universe,
        "n_candidates_post_universe_filter": n_after_universe,
        "n_excluded_by_universe_filter": n_before_universe - n_after_universe,
        "n_merged_positions": n_after_merge,
        "n_merged_away": n_after_universe - n_after_merge,
        "n_skipped_slot_full": n_skipped_slot_full,
        "n_trades": len(trades),
    }
    return trades, diag


def _demo() -> None:
    """청산 판단 로직 자체검증 - 손절선을 먼저 찍으면 stop_loss로 끝나야 한다."""
    future_ts = pd.date_range("2026-01-02 09:03:00", periods=3, freq="1min")
    future = pd.Series([97.4, 102.6, 105.0], index=future_ts)
    two_way = DEFAULT_COMMISSION_RATE * 2
    path = []
    peak = 0.0
    for ts, p in future.items():
        net = (p * (1 - DEFAULT_SLIPPAGE_RATE) - 100.0) / 100.0 - two_way - DEFAULT_TAX_RATE
        peak = max(peak, net)
        path.append((ts, net, peak))
    legs = _compute_exit_legs(path, TIERS, STOP_LOSS_PCT)
    assert legs[0][1] == "stop_loss", legs
    print("demo ok")


if __name__ == "__main__":
    import sys

    if "--demo" in sys.argv:
        _demo()
    else:
        trades, diag = scan_tick_trades()
        print(diag)
        if len(trades):
            trades.to_csv("results/tick_holdout_trades.csv", index=False)
            print("results/tick_holdout_trades.csv 저장,", len(trades), "건")
