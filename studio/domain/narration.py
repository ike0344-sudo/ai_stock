"""명세 → 한국어 문장 (조건 풀이 패널, §5.4). 순수 함수, 계산·체결 없음.

예: 종가가 20일 최고가를 넘고 거래량이 거래량 20일 이동평균의 1.5배 이상이면 다음 날 시가에 산다.
조사(이/가·을/를)는 마지막 글자 받침으로 고른다. 중첩 그룹은 괄호 안에 평서문으로 풀어 쓴다.
"""
from __future__ import annotations

from typing import Any

from .conditions.ast import (
    Condition, ConstOperand, ExprOperand, FieldOperand, Group, IndOperand, MarketOperand, ParamRef, PosOperand,
    iter_operands,
)
from .conditions.catalog import INDICATORS, MINUTE_TIMEFRAMES, resolve_params
from .spec import BuilderStrategy, LegacyStrategy, Spec

FIELD_KO = {"open": "시가", "high": "고가", "low": "저가", "close": "종가", "volume": "거래량", "value": "거래대금"}
INDEX_KO = {"kospi": "코스피", "kosdaq": "코스닥"}
POS_KO = {
    "return_pct": "보유 수익률", "bars_held": "보유 봉 수", "minutes_held": "보유 분", "max_return_pct": "보유 중 최고 수익률",
    "drawdown_pct": "보유 중 최고가 대비 하락률", "entry_price": "매수가",  # drawdown_pct 는 양수 % = 최고가보다 N% 아래
}
_EOK_IND = {"value_eok", "value_sum_eok"}  # 값이 억 원 단위인 지표(c9)
_PCT_POS = {"return_pct", "max_return_pct", "drawdown_pct"}  # 상수와 비교하면 오른쪽에 % 를 붙인다("보유 수익률이 5% 이상")
TF_PREFIX = {"daily_prev": "일봉(전일 확정) ", "daily_live": "일봉(장중 실시간) "}
# 봉 개수 창으로 굴러가는 지표 — 분봉 모드에선 날 경계를 넘어 이어진다(lead 판정 2026-09-25, 리셋 옵션 없음)
_ROLLING = {"sma", "ema", "rsi", "rsi_wilder", "highest", "lowest", "change_pct", "atr", "bb_upper", "bb_lower", "vol_ratio"}
_WINDOW_PARAMS = {"n", "n1", "fast", "slow", "conv_n", "span_n"}  # 창 길이를 받는 파라미터 이름 — 카탈로그의 다른 롤링 지표도 잡는다


def _won(v: float) -> str:
    """원 단위 금액 → '5억'·'3000만'·'500원'."""
    return f"{v / 1e8:g}억" if v >= 1e8 else f"{v / 1e4:g}만" if v >= 1e4 else f"{v:g}원"


def _is_rolling(name: str) -> bool:
    d = INDICATORS.get(name)
    return name in _ROLLING or bool(d and d.category in ("trend", "oscillator", "volume") and any(p.name in _WINDOW_PARAMS for p in d.params))
LEGACY_KO = {
    "ma_crossover": "이동평균 크로스", "rsi": "RSI 과매도·과매수", "envelope": "엔벨로프 평균회귀",
    "new_high_swing": "N일 신고가 스윙", "pullback_reentry": "눌림목 재돌파(폐기됨)",
    "vcp_breakout": "변동성 수축 신고가 돌파", "new_high_leg_exit": "신고가 스윙(청산: 최근 구간 저점 이탈)",
    "new_high_volume_divergence_exit": "신고가 스윙(청산: 거래량 다이버전스)",
}
_NO_BATCHIM_DIGITS = "2459"  # 이·사·오·구 는 받침 없음, 영·일·삼·육·칠·팔 은 있음


def _batchim(word: str) -> bool:
    ch = word.rstrip()[-1:] if word.strip() else ""
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    if ch.isdigit():
        return ch not in _NO_BATCHIM_DIGITS
    return False


def josa(word: str, pair: str) -> str:
    a, b = pair.split("/")
    return a if _batchim(word) else b


def _fmt(v: Any) -> str:
    if isinstance(v, ParamRef):
        return f"[{v.param}]"  # 최적화 변수 자리
    if isinstance(v, bool):
        return "예" if v else "아니오"
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _ind(op: IndOperand, unit: str) -> str:
    p = resolve_params(op.name, dict(op.params))
    f = {k: _fmt(v) for k, v in p.items()}
    src = FIELD_KO.get(p.get("src", ""), "")
    n = f.get("n", "")
    if op.name == "sma":
        return f"{src} {n}{unit} 이동평균"
    if op.name == "ema":
        return f"{src} {n}{unit} 지수이동평균"
    if op.name == "rsi":
        return f"{n}{unit} RSI"
    if op.name == "rsi_wilder":
        return f"{n}{unit} RSI(와일더)"
    if op.name in ("highest", "lowest"):
        top = op.name == "highest"
        base = f"{n}{unit} " + (("최고가" if p["src"] == "high" else f"{src} 최고값") if top else
                                ("최저가" if p["src"] == "low" else f"{src} 최저값"))
        return base + (" (오늘 포함)" if p["include_current"] is True else "")
    if op.name == "change_pct":
        return f"{n}{unit} 전 대비 등락률(%)"
    if op.name == "gap_pct":
        return "시가 갭(%)"
    if op.name == "atr":
        return f"{n}{unit} ATR"
    if op.name in ("bb_upper", "bb_lower"):
        return f"{n}{unit} 볼린저 {'상단' if op.name == 'bb_upper' else '하단'}({f['k']}배)"
    if op.name == "vol_ratio":
        return f"거래량의 {n}{unit} 평균 대비 배수"
    if op.name == "value_rank":
        return "그날 거래대금 순위" if p["lookback"] == 1 else f"{f['lookback']}일 평균 거래대금 순위"
    if op.name == "value_eok":  # 값은 억 원 — 비교하는 상수 쪽에 '억' 을 붙인다(`_cond`)
        return "거래대금"
    if op.name == "value_sum_eok":
        return f"최근 {n}{unit} 거래대금 합"
    d = INDICATORS[op.name]  # 그 밖의 지표: 이름 + 기본값과 다른 파라미터(예: MACD 선(fast=8, slow=21))
    extra = [f"{k}={f[k]}" for k in p if p[k] != d.param(k).default]
    return d.label_ko + (f"({', '.join(extra)})" if extra else "")


def _tf_unit(tf: str, unit: str) -> str:
    """그 시간 단위 자신의 봉 단위 — N분봉은 '봉', 일봉 계열은 '일', bar 는 실행 모드 단위."""
    return "봉" if tf in MINUTE_TIMEFRAMES else "일" if tf in TF_PREFIX else unit


def _tf_prefix(tf: str) -> str:
    return f"{MINUTE_TIMEFRAMES[tf]}분봉 " if tf in MINUTE_TIMEFRAMES else TF_PREFIX.get(tf, "")


def _operand(op: Any, unit: str) -> str:
    if isinstance(op, ConstOperand):
        return _fmt(op.value)
    if isinstance(op, PosOperand):
        return POS_KO[op.name]
    if isinstance(op, ExprOperand):
        sym = {"+": "+", "-": "−", "*": "×", "/": "÷"}[op.op]
        return f"({_operand(op.left, unit)} {sym} {_operand(op.right, unit)})"
    if isinstance(op, MarketOperand):
        n = _fmt(op.params.get("n", 20 if op.name == "sma" else 1))
        what = {"close": "종가", "sma": f"{n}일 이동평균", "change_pct": f"{n}일 등락률(%)"}[op.name]  # 지수는 일봉 자료
        return f"{'전일 ' if unit == '봉' else ''}{INDEX_KO[op.index]} {what}"  # 분봉·틱 모드는 D−1 값
    u = _tf_unit(op.tf, unit)
    text = FIELD_KO[op.name] if isinstance(op, FieldOperand) else _ind(op, u)
    if op.offset:
        text = f"{op.offset}{u} 전 {text}"  # 며칠·몇 봉 전은 그 피연산자 자신의 시간 단위로
    text = _tf_prefix(op.tf) + text
    if not (isinstance(op.mul, (int, float)) and op.mul == 1):
        text = f"{text}의 {_fmt(op.mul)}배"
    return text


# 조건 하나의 어간 종류 — verb: 어간+고/면 · noun: 어간+이고/이면 · past(받침 끝 어간: 넘·-했·않): 어간+고/으면
def _cond(c: Condition, unit: str) -> tuple[str, str, str]:
    """(연결 전 어간, 종류, 평서문)."""
    left = _operand(c.left, unit)
    subj = f"{left}{josa(left, '이/가')}"
    hold = f"{c.hold}{unit} 연속으로 " if c.hold > 1 else ""
    if c.op == "is_true":
        stem, kind, plain = f"{subj} 성립하", "verb", f"{subj} 성립한다"
    elif c.op == "is_false":
        stem, kind, plain = f"{subj} 성립하지 않", "past", f"{subj} 성립하지 않는다"
    else:
        right = _operand(c.right, unit)
        if isinstance(c.left, PosOperand) and c.left.name in _PCT_POS and isinstance(c.right, ConstOperand):
            right += "%"
        elif isinstance(c.left, IndOperand) and c.left.name in _EOK_IND and isinstance(c.right, ConstOperand):
            right += "억"  # 거래대금(억 원) 지표는 상수도 억 단위
        obj = f"{right}{josa(right, '을/를')}"
        if c.op == "gt":
            stem, kind, plain = f"{subj} {obj} 넘", "past", f"{subj} {obj} 넘는다"  # 받침 있는 어간 → 끝에서 '넘으면'
        elif c.op == "cross_above":
            stem, kind, plain = f"{subj} {obj} 상향 돌파하", "verb", f"{subj} {obj} 상향 돌파한다"
        elif c.op == "cross_below":
            stem, kind, plain = f"{subj} {obj} 하향 이탈하", "verb", f"{subj} {obj} 하향 이탈한다"
        elif c.op == "cross_above_within":
            stem = f"최근 {c.within}{unit} 안에 {subj} {obj} 상향 돌파했"
            kind, plain = "past", stem + "다"
        elif c.op == "cross_below_within":
            stem = f"최근 {c.within}{unit} 안에 {subj} {obj} 하향 이탈했"
            kind, plain = "past", stem + "다"
        else:
            word = {"gte": "이상", "lt": "미만", "lte": "이하"}[c.op]
            stem, kind, plain = f"{subj} {right} {word}", "noun", f"{subj} {right} {word}이다"
    return hold + stem, kind, hold + plain


def _plain(g: Group, unit: str) -> str:
    joiner = " 그리고 " if g.logic == "all" else " 또는 "
    return joiner.join(_item(i, unit)[2] for i in g.items)


def _item(i: Condition | Group, unit: str) -> tuple[str, str, str]:
    if isinstance(i, Group):
        if i.negate:  # 그룹 전체 부정 — 값 없음(NaN)인 봉은 참이 되지 않는다(평가기 규칙)
            stem = f"({_plain(i, unit)}) 조건이 성립하지 않"
            return stem, "past", stem + "는다"
        inner = "(" + _plain(i, unit) + ")"
        return inner, "noun", inner
    return _cond(i, unit)


def narrate_group(g: Group, unit: str = "일") -> str:
    """'A를 넘고 B 이상이면' 꼴. 빈 그룹은 빈 문자열."""
    if not g.items:
        return ""
    if g.negate:
        return f"({_plain(g, unit)}) 조건이 성립하지 않으면"
    mid = "고" if g.logic == "all" else "거나"
    out = []
    parts = [_item(i, unit) for i in g.items]
    for k, (stem, kind, _) in enumerate(parts):
        last = k == len(parts) - 1
        if kind == "noun":
            out.append(stem + "이" + ("면" if last else mid))
        elif kind == "past":
            out.append(stem + ("으면" if last else mid))
        else:
            out.append(stem + ("면" if last else mid))
    return " ".join(out)


def _exits_text(spec: Spec) -> str:
    e = spec.exits
    close_note = " (종가가 선을 넘으면 다음 봉 시가에)" if e.take_profit_mode == "close" else ""
    parts = []
    if e.stop_loss_pct is not None:
        parts.append(f"손절 -{_fmt(e.stop_loss_pct)}%")
    if e.breakeven_after_pct is not None:
        parts.append(f"최고 수익률 {_fmt(e.breakeven_after_pct)}% 를 넘으면 손절선을 매수가로")
    if e.take_profit_pct is not None:
        parts.append(f"익절 +{_fmt(e.take_profit_pct)}%{close_note}")
    if e.take_profit_levels:
        steps = []
        for lv in e.take_profit_levels:  # fraction 은 그 선에서 "남은 수량" 중 파는 비율
            rest = "나머지 전부" if lv.fraction >= 1 else f"남은 수량의 {lv.fraction * 100:g}%"
            steps.append(f"+{_fmt(lv.pct)}% 에 {rest}")
        parts.append("분할 익절 " + ", ".join(steps) + close_note)
    if e.trailing_stop_pct is not None:
        act = f"(최고 수익률 {_fmt(e.trail_activate_pct)}% 를 넘은 뒤부터)" if e.trail_activate_pct is not None else ""
        parts.append(f"고점 대비 -{_fmt(e.trailing_stop_pct)}% 트레일링{act}")
    if e.max_holding_bars is not None:
        parts.append(f"최대 {_fmt(e.max_holding_bars)}봉 보유")
    if e.max_holding_minutes is not None:
        parts.append(f"{_fmt(e.max_holding_minutes)}분 보유 후 종가 청산")
    return ", ".join(parts)


def narrate(spec: Spec) -> str:
    """명세 전체를 여러 줄 한국어로 풀어 쓴다."""
    intra = spec.mode in ("intraday", "tick")
    unit, bar = ("봉", "봉") if intra else ("일", "날")
    lines: list[str] = []
    s = spec.strategy
    if isinstance(s, BuilderStrategy):
        lines.append(f"{narrate_group(s.entry, unit)} 다음 {bar} 시가에 산다.")
        if s.exit.items:
            lines.append(f"{narrate_group(s.exit, unit)} 다음 {bar} 시가에 판다.")
    elif isinstance(s, LegacyStrategy):
        ps = ", ".join(f"{k}={_fmt(v)}" for k, v in s.params.items())
        lines.append(f"기존 전략 '{LEGACY_KO[s.name]}'({s.name}) 규칙을 그대로 쓴다" + (f": {ps}." if ps else "."))
    leaves = [o for g in (s.entry, s.exit) for o in iter_operands(g)] if isinstance(s, BuilderStrategy) else []
    tick_filter = spec.tick.filter if spec.mode == "tick" and spec.tick is not None else None
    if tick_filter is not None:
        leaves += list(iter_operands(tick_filter))  # 틱 모드의 분봉 필터도 롤링 주의문 대상(bar = 1분봉)
    if intra and any(isinstance(o, IndOperand) and o.tf in ("bar", *MINUTE_TIMEFRAMES) and _is_rolling(o.name) for o in leaves):
        lines.append("※ 분봉 N봉 지표(이동평균·최고가 등)는 전날 봉을 포함해 계산하므로 장 시작 직후 신호는 전날 흐름의 영향을 받는다.")
    if any(isinstance(o, IndOperand) and o.name in _EOK_IND for o in leaves):
        lines.append("※ 분봉·일봉 거래대금은 종가×거래량 근사값이다(실제 체결대금과 다를 수 있다).")
    # (daily_prev 는 "오늘 장 시작 전에 알 수 있는 값" — 설계 §3.2 v0.3: highest/lowest(오늘 제외)도 D−N..D−1 이라 별도 주의문 없음)
    if spec.mode == "intraday" and spec.intraday is not None and spec.intraday.source == "krx":
        lines.append("※ KRX 분봉 기준 — NXT 체결이 빠져 거래량·거래대금이 통합보다 20~40% 작다(같은 임계값이 더 엄격해진다).")
    if spec.tick is not None and spec.mode == "tick" and spec.tick.entry_source == "catalog":
        c = spec.tick.catalog
        conds = []
        if c.breakout_min is not None:
            conds.append(f"{c.breakout_min}분 고점 돌파")
        if c.value_speed is not None:
            conds.append(f"체결대금 속도가 평균의 {_fmt(c.value_speed.ratio)}배 이상({c.value_speed.w}분 창)")
        if c.buy_ratio is not None:
            conds.append(f"매수 비중 {_fmt(c.buy_ratio.min)} 이상({c.buy_ratio.w}분 창)")
        if c.trade_strength is not None:
            conds.append(f"최근 {c.trade_strength.w}초 체결강도(매수÷매도 체결량)가 {_fmt(c.trade_strength.min)}% 이상")
        if c.block_trades is not None:
            conds.append(f"최근 {c.block_trades.w}초 안에 {_won(c.block_trades.min_value)} 이상 대량 체결이 {c.block_trades.min_count}건 이상")
        if c.daily_breakout is not None:
            conds.append(f"현재가가 전일까지 {c.daily_breakout.n}일 최고가를 돌파")
        if c.value_window is not None:  # c9 — 가격×수량의 정확한 체결대금(분봉 근사값 아님), 그 초 체결 포함
            conds.append(f"최근 {c.value_window.w}분 체결대금 합이 {_fmt(c.value_window.min_eok)}억 이상(정확한 체결대금, 그 초 체결 포함)")
        lines.append(f"{c.time_from}~{c.time_to} 사이 " + " 그리고 ".join(conds) + " 이면 다음 체결에 산다.")
        if spec.tick.prefilter is not None and spec.tick.prefilter.items:  # 일봉 사전 필터 — 전일(D−1) 확정값 기준
            lines.append(f"전일 일봉 기준으로 {narrate_group(spec.tick.prefilter, '일')} 그 날만 틱을 본다.")
        if tick_filter is not None and tick_filter.items:  # 분봉·일봉 필터 — 체결 시각까지 마감된 마지막 1분봉(bar = 1분봉)
            lines.append(f"단, {narrate_group(tick_filter, unit)} 산다 — 체결 시각까지 마감된 마지막 1분봉 기준(진행 중인 봉은 안 본다).")
            lines.append("※ 분봉이 없는 종목·날은 필터를 못 써서 진입하지 않는다.")
    if spec.market_filter is not None and spec.market_filter.items:
        lines.append(f"단, {narrate_group(spec.market_filter, unit)} 진입한다.")
    ex = _exits_text(spec)
    if ex:
        lines.append(f"청산 규칙: {ex}.")
    if spec.mode == "intraday" and spec.intraday is not None:
        lines.append(f"{spec.intraday.eod_time} 에 남은 물량을 정리한다.")
    if spec.compat.legacy:
        lines.append("(호환 모드: 기존 시뮬레이터 규칙 그대로 — 손절·익절·사이징 없음)")
    return "\n".join(lines)
