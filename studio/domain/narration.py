"""명세 → 한국어 문장 (조건 풀이 패널, §5.4). 순수 함수, 계산·체결 없음.

예: 종가가 20일 최고가를 넘고 거래량이 거래량 20일 이동평균의 1.5배 이상이면 다음 날 시가에 산다.
조사(이/가·을/를)는 마지막 글자 받침으로 고른다. 중첩 그룹은 괄호 안에 평서문으로 풀어 쓴다.
"""
from __future__ import annotations

from typing import Any

from .conditions.ast import (
    Condition, ConstOperand, FieldOperand, Group, IndOperand, MarketOperand, ParamRef, iter_operands,
)
from .conditions.catalog import INDICATORS, resolve_params
from .spec import BuilderStrategy, LegacyStrategy, Spec

FIELD_KO = {"open": "시가", "high": "고가", "low": "저가", "close": "종가", "volume": "거래량", "value": "거래대금"}
INDEX_KO = {"kospi": "코스피", "kosdaq": "코스닥"}
# 봉 개수 창으로 굴러가는 지표 — 분봉 모드에선 날 경계를 넘어 이어진다(lead 판정 2026-09-25, 리셋 옵션 없음)
_ROLLING = {"sma", "ema", "rsi", "rsi_wilder", "highest", "lowest", "change_pct", "atr", "bb_upper", "bb_lower", "vol_ratio"}
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
    return INDICATORS[op.name].label_ko


def _operand(op: Any, unit: str) -> str:
    if isinstance(op, ConstOperand):
        return _fmt(op.value)
    if isinstance(op, MarketOperand):
        n = _fmt(op.params.get("n", 20 if op.name == "sma" else 1))
        what = {"close": "종가", "sma": f"{n}일 이동평균", "change_pct": f"{n}일 등락률(%)"}[op.name]  # 지수는 일봉 자료
        return f"{'전일 ' if unit == '봉' else ''}{INDEX_KO[op.index]} {what}"  # 분봉·틱 모드는 D−1 값
    text = FIELD_KO[op.name] if isinstance(op, FieldOperand) else _ind(op, unit)
    if op.offset:
        text = f"{op.offset}{unit} 전 {text}"
    if not (isinstance(op.mul, (int, float)) and op.mul == 1):
        text = f"{text}의 {_fmt(op.mul)}배"
    return text


def _cond(c: Condition, unit: str) -> tuple[str, bool, str]:
    """(연결 전 어간, 명사형 여부, 평서문). 동사형은 '고/면', 명사형은 '이고/이면' 이 붙는다."""
    left, right = _operand(c.left, unit), _operand(c.right, unit)
    subj = f"{left}{josa(left, '이/가')}"
    obj = f"{right}{josa(right, '을/를')}"
    if c.op == "gt":
        stem = f"{subj} {obj} 넘"
        return stem, False, stem + "는다"
    if c.op == "cross_above":
        stem = f"{subj} {obj} 상향 돌파하"
        return stem, False, stem[:-1] + "한다"
    if c.op == "cross_below":
        stem = f"{subj} {obj} 하향 이탈하"
        return stem, False, stem[:-1] + "한다"
    word = {"gte": "이상", "lt": "미만", "lte": "이하"}[c.op]
    stem = f"{subj} {right} {word}"
    return stem, True, stem + "이다"


def _plain(g: Group, unit: str) -> str:
    joiner = " 그리고 " if g.logic == "all" else " 또는 "
    return joiner.join(_item(i, unit)[2] for i in g.items)


def _item(i: Condition | Group, unit: str) -> tuple[str, bool, str]:
    if isinstance(i, Group):
        inner = "(" + _plain(i, unit) + ")"
        return inner, True, inner
    return _cond(i, unit)


def narrate_group(g: Group, unit: str = "일") -> str:
    """'A를 넘고 B 이상이면' 꼴. 빈 그룹은 빈 문자열."""
    parts = [_item(i, unit) for i in g.items]
    mid = "고" if g.logic == "all" else "거나"
    out = []
    for k, (stem, noun, _) in enumerate(parts):
        last = k == len(parts) - 1
        end = "면" if last else mid
        out.append(stem + ("이" + end if noun else end))
    return " ".join(out)


def _exits_text(spec: Spec) -> str:
    e = spec.exits
    parts = []
    if e.stop_loss_pct is not None:
        parts.append(f"손절 -{_fmt(e.stop_loss_pct)}%")
    if e.take_profit_pct is not None:
        parts.append(f"익절 +{_fmt(e.take_profit_pct)}%")
    if e.trailing_stop_pct is not None:
        parts.append(f"고점 대비 -{_fmt(e.trailing_stop_pct)}% 트레일링")
    if e.max_holding_bars is not None:
        parts.append(f"최대 {_fmt(e.max_holding_bars)}봉 보유")
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
    if intra and isinstance(s, BuilderStrategy) and any(
        isinstance(o, IndOperand) and o.name in _ROLLING
        for g in (s.entry, s.exit) for o in iter_operands(g)
    ):
        lines.append("※ 분봉 N봉 지표(이동평균·최고가 등)는 전날 봉을 포함해 계산하므로 장 시작 직후 신호는 전날 흐름의 영향을 받는다.")
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
        lines.append(f"{c.time_from}~{c.time_to} 사이 " + " 그리고 ".join(conds) + " 이면 다음 체결에 산다.")
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
