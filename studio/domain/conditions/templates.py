"""조건 템플릿 — 문장 빈칸 채우기 (설계서 §5.5, c10). 순수 도메인(IO 없음).

템플릿 하나 = 쉬운 문장 + 빈칸(숫자·시간 단위·선택지) + **조건 뼈대**(빈칸 자리를 `M("이름")` 표지로 둔 조건 dict).
  build(id, 빈칸값)  → 뼈대의 표지를 값으로 채워 조건 AST(dict, 명세에 그대로 들어감).
  match(조건 dict)   → 뼈대와 맞춰 보고 표지에 걸린 값을 되읽어 (id, 빈칸값). 문장으로 만든 조건은 다시 문장 카드로 보인다.
둘이 같은 뼈대에서 나오므로 되돌리기(build→match)가 어긋날 수 없다 — 템플릿마다 역변환을 따로 쓰지 않는다.
카탈로그(INDICATORS)가 유일한 출처: 모드·"오늘 지금까지(daily_live)" 지원·거래량 계열 제한은 지표 정의에서 읽어 온다(여기서 다시 정하지 않는다).
표지 변환: `M("x", mul=-1, add=100)` = 값 × mul + add (예: "낮다" 는 100 − x, 억 → 원은 × 1e8). 부동소수 잡음은 9자리에서 반올림.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping

from .ast import Condition
from .catalog import INDICATORS, MINUTE_TIMEFRAMES, resolve_params

DAILY_MODES = ("daily_single", "daily_portfolio")
BARS = ("bar", *MINUTE_TIMEFRAMES)                  # 이 봉 · N분봉
DAILY_TFS = ("daily_prev", "daily_live")
SCOPES = {"bars": BARS, "daily": DAILY_TFS, "any": (*BARS, *DAILY_TFS)}

CATEGORIES = {
    "breakout": "신고가·돌파", "ma": "이동평균선", "volume": "거래량·거래대금", "candle": "오르내림·캔들",
    "indicator": "보조지표", "time": "시간대", "theme": "테마·업종", "exit": "팔 때(청산)",
}


class TemplateError(ValueError):
    """사용자가 채운 빈칸이 잘못됐을 때 — slot 은 그 빈칸 이름(화면이 그 칸을 강조), 메시지는 쉬운 말."""

    def __init__(self, slot: str, message: str) -> None:
        super().__init__(message)
        self.slot, self.message = slot, message


# ---------------------------------------------------------------- 뼈대 도우미
def M(name: str, mul: float | None = None, add: float | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"$": name}
    if mul is not None:
        d["mul"] = mul
    if add is not None:
        d["add"] = add
    return d


def fld(name: str = "close", tf: Any = None) -> dict[str, Any]:
    return {"kind": "field", "name": name, **({"tf": tf} if tf is not None else {})}


def ind(name: str, tf: Any = None, **params: Any) -> dict[str, Any]:
    return {"kind": "ind", "name": name, "params": params, **({"tf": tf} if tf is not None else {})}


def const(v: Any) -> dict[str, Any]:
    return {"kind": "const", "value": v}


def pos(name: str) -> dict[str, Any]:
    return {"kind": "pos", "name": name}


def cond(left: dict, op: Any, right: dict | None = None) -> dict[str, Any]:
    return {"left": left, "op": op, **({"right": right} if right is not None else {})}


# ---------------------------------------------------------------- 빈칸
@dataclass(frozen=True)
class Slot:
    name: str
    kind: str                       # number | tf | choice
    label: str                      # 화면에 보이는 이름(쉬운 말)
    unit: str = ""
    default: Any = None
    lo: float | None = None
    hi: float | None = None
    integer: bool = False
    choices: tuple[tuple[str, str], ...] = ()   # choice: (값, 보이는 말)
    scope: str = ""                 # tf: bars | daily | any


def num(name: str, label: str, default: float, lo: float, hi: float, unit: str = "", integer: bool = False) -> Slot:
    return Slot(name, "number", label, unit, default, lo, hi, integer)


def days(name: str = "n", label: str = "며칠", default: int = 20, lo: int = 2, hi: int = 250) -> Slot:
    return num(name, label, default, lo, hi, "일", True)


def bars(name: str = "n", label: str = "몇 봉", default: int = 20, lo: int = 2, hi: int = 500) -> Slot:
    return num(name, label, default, lo, hi, "봉", True)


def pct(name: str = "x", label: str = "몇 %", default: float = 5, lo: float = 0.1, hi: float = 100) -> Slot:
    return num(name, label, default, lo, hi, "%")


def tfslot(scope: str = "bars", name: str = "tf") -> Slot:
    label = "어떤 봉으로 볼까요?" if scope != "daily" else "일봉을 어떻게 볼까요?"
    return Slot(name, "tf", label, scope=scope)


def choice(name: str, label: str, *choices: tuple[str, str]) -> Slot:
    return Slot(name, "choice", label, default=choices[0][0], choices=tuple(choices))


CMP_HL = choice("cmp", "이상 / 이하", ("gte", "이상이다"), ("lte", "이하다"))
CMP_ABOVE = choice("cmp", "위 / 아래", ("gt", "위에 있다"), ("lt", "아래에 있다"))
BY = choice("by", "무엇으로 줄 세울까요?", ("value", "거래대금"), ("change", "상승률"))


@dataclass(frozen=True)
class Template:
    id: str
    category: str
    sentence: str                   # "{tf}거래대금이 {x}억 {cmp}" — {슬롯이름}, {봉}(일/봉 자동)
    slots: tuple[Slot, ...]
    skeleton: Mapping[str, Any]     # 모든 모드 공통 뼈대, 또는 {"daily": 뼈대, "intraday": 뼈대}(variants=True)
    hint: str = ""                  # 한 줄 쉬운 설명(왜 쓰는지)
    role: str = "both"              # entry | exit | both
    only: tuple[str, ...] = ()      # 지원 모드를 이것으로 제한(비면 지표 정의가 정한다)
    tags: tuple[str, ...] = ()      # 검색어
    warn: str = ""
    check: Callable[[dict[str, Any]], tuple[str, str] | None] | None = None   # 값끼리의 관계(예: 짧은 선 < 긴 선) — 틀리면 (강조할 빈칸, 쉬운 말)
    variants: bool = False

    def skel(self, mode: str | None) -> Mapping[str, Any]:
        if not self.variants:
            return self.skeleton
        return self.skeleton["daily" if mode in DAILY_MODES else "intraday"]


def _short_long(a: str, b: str) -> Callable[[dict[str, Any]], tuple[str, str] | None]:
    return lambda v: None if v[a] < v[b] else (b, "짧은 선은 긴 선보다 작은 숫자여야 해요")


_TF, _DTF, _N, _X = M("tf"), M("dtf"), M("n"), M("x")


def _t(id: str, category: str, sentence: str, slots: tuple[Slot, ...], skeleton: Any, **kw: Any) -> Template:
    return Template(id, category, sentence, slots, skeleton, **kw)


TEMPLATES: tuple[Template, ...] = (
    # ---- 신고가·돌파
    _t("high_break", "breakout", "가격이 {n}일 최고가를 넘었다", (days(),),
       {"daily": cond(fld(), "gt", ind("highest", src="high", n=_N)),
        "intraday": cond(fld(), "gt", ind("highest", "daily_prev", src="high", n=_N))}, variants=True,
       hint="최근 며칠 중 가장 높았던 가격(어제까지)을 지금 가격이 뚫으면 참이에요. 신고가 매매의 기본 조건이에요.",
       tags=("신고가", "돌파", "고점", "최고가")),
    _t("high_break_bars", "breakout", "{tf}가격이 직전 {n}봉 최고가를 넘었다", (tfslot("bars"), bars()),
       cond(fld("close", _TF), "gt", ind("highest", _TF, src="high", n=_N)), only=("intraday",),
       hint="분봉 안에서 최근 몇 봉의 최고가를 뚫는 순간을 잡아요.", tags=("신고가", "돌파", "고점", "분봉")),
    _t("near_high52", "breakout", "가격이 {dtf}52주(약 1년) 최고가보다 {x}% 이내로 가까워졌다", (pct(default=5, hi=50), tfslot("daily", "dtf")),
       {"daily": cond(ind("high52_pct"), "gte", const(M("x", mul=-1))),
        "intraday": cond(ind("high52_pct", _DTF), "gte", const(M("x", mul=-1)))}, variants=True,
       hint="1년 중 가장 높았던 가격 근처까지 올라온 종목을 골라요.", tags=("신고가", "52주", "근접", "1년")),
    _t("low_break", "breakout", "가격이 {n}일 최저가 아래로 내려갔다", (days(),),
       {"daily": cond(fld(), "lt", ind("lowest", src="low", n=_N)),
        "intraday": cond(fld(), "lt", ind("lowest", "daily_prev", src="low", n=_N))}, variants=True,
       hint="최근 며칠 중 가장 낮았던 가격을 깨고 내려가면 참이에요. 팔 때(손절)에도 써요.", tags=("신저가", "이탈", "저점", "하락")),
    _t("low_break_bars", "breakout", "{tf}가격이 직전 {n}봉 최저가 아래로 내려갔다", (tfslot("bars"), bars(default=10)),
       cond(fld("close", _TF), "lt", ind("lowest", _TF, src="low", n=_N)), only=("intraday",),
       hint="분봉 안에서 최근 몇 봉의 최저가를 깨고 내려가면 참이에요. 팔 때(손절)의 기본 조건이에요.", tags=("신저가", "이탈", "저점", "하락", "손절", "분봉")),
    _t("prev_high_break", "breakout", "전날 고가를 넘었다", (), cond(ind("prev_high_break"), "is_true"),
       hint="어제 가장 높았던 가격을 오늘 넘으면 참이에요.", tags=("전일", "전날", "고가", "돌파")),
    _t("day_high_break", "breakout", "오늘 장이 열린 뒤 가장 높은 가격을 새로 넘었다", (), cond(ind("day_high_break"), "is_true"),
       hint="오늘 지금까지의 최고가를 이번 봉이 뚫으면 참이에요.", tags=("당일", "고점", "돌파", "신고가")),
    _t("limit_up_near", "breakout", "상한가까지 {x}% 이내로 다가갔다", (pct(default=5, hi=29),),
       cond(ind("limit_up_pct"), "lte", const(_X)), hint="상한가(하루 최대로 오를 수 있는 가격)가 가까워진 종목이에요.", tags=("상한가", "근접")),

    # ---- 이동평균선
    _t("above_ma", "ma", "{tf}가격이 {n}{봉} 이동평균선 {cmp}", (tfslot("bars"), bars(default=20), CMP_ABOVE),
       cond(fld("close", _TF), M("cmp"), ind("sma", _TF, src="close", n=_N)),
       hint="이동평균선은 최근 며칠(몇 봉) 가격의 평균이에요. 가격이 그 위에 있으면 오르는 흐름으로 봐요.", tags=("이평", "이동평균", "평균선", "위", "아래")),
    _t("above_daily_ma", "ma", "지금 가격이 {dtf}{n}일 이동평균선 {cmp}", (days(default=20), tfslot("daily", "dtf"), CMP_ABOVE),
       cond(fld("close"), M("cmp"), ind("sma", _DTF, src="close", n=_N)), only=("intraday",),
       hint="분봉으로 매매하면서 '일선(20일선 등)' 위인지 아래인지 볼 때 써요.", tags=("일선", "이평", "이동평균", "20일선")),
    _t("ma_cross_up", "ma", "{tf}{a}{봉}선이 {b}{봉}선을 아래에서 위로 뚫고 올라갔다(골든크로스)",
       (tfslot("bars"), bars("a", "짧은 선", 5, 1), bars("b", "긴 선", 20, 2)),
       cond(ind("sma", _TF, src="close", n=M("a")), "cross_above", ind("sma", _TF, src="close", n=M("b"))), check=_short_long("a", "b"),
       hint="짧은 평균선이 긴 평균선을 뚫고 올라가는 순간이에요. 오르기 시작하는 신호로 봐요.", tags=("골든크로스", "교차", "이평", "상향")),
    _t("ma_cross_down", "ma", "{tf}{a}{봉}선이 {b}{봉}선을 위에서 아래로 뚫고 내려갔다(데드크로스)",
       (tfslot("bars"), bars("a", "짧은 선", 5, 1), bars("b", "긴 선", 20, 2)),
       cond(ind("sma", _TF, src="close", n=M("a")), "cross_below", ind("sma", _TF, src="close", n=M("b"))), check=_short_long("a", "b"),
       hint="짧은 평균선이 긴 평균선 아래로 내려가는 순간이에요. 팔 때 신호로도 써요.", tags=("데드크로스", "교차", "이평", "하향")),
    _t("price_cross_ma_up", "ma", "{tf}가격이 {n}{봉} 이동평균선을 아래에서 위로 뚫고 올라갔다", (tfslot("bars"), bars(default=20)),
       cond(fld("close", _TF), "cross_above", ind("sma", _TF, src="close", n=_N)),
       hint="가격이 평균선 아래에 있다가 처음 위로 올라온 그 봉만 참이에요('위에 있다'는 계속 참).", tags=("이평", "돌파", "상향", "20일선")),
    _t("price_cross_ma_down", "ma", "{tf}가격이 {n}{봉} 이동평균선을 위에서 아래로 뚫고 내려갔다(이탈)", (tfslot("bars"), bars(default=20)),
       cond(fld("close", _TF), "cross_below", ind("sma", _TF, src="close", n=_N)),
       hint="가격이 평균선 위에 있다가 처음 아래로 내려온 그 봉만 참이에요. 팔 때 자주 써요.", tags=("이평", "이탈", "하향", "손절", "20일선")),
    _t("ma_above_ma", "ma", "{tf}{a}{봉}선이 {b}{봉}선 위에 있다", (tfslot("bars"), bars("a", "짧은 선", 5, 1), bars("b", "긴 선", 20, 2)),
       cond(ind("sma", _TF, src="close", n=M("a")), "gt", ind("sma", _TF, src="close", n=M("b"))), check=_short_long("a", "b"),
       hint="짧은 평균선이 긴 평균선보다 위에 있으면 최근 흐름이 더 강하다는 뜻이에요.", tags=("이평", "정배열", "위")),
    _t("ma_aligned", "ma", "{tf}{n1}·{n2}·{n3}{봉}선이 짧은 선일수록 위에 나란히 있다(정배열)",
       (tfslot("bars"), bars("n1", "가장 짧은 선", 5, 1), bars("n2", "중간 선", 20, 2), bars("n3", "가장 긴 선", 60, 3)),
       cond(ind("ma_aligned", _TF, n1=M("n1"), n2=M("n2"), n3=M("n3")), "is_true"),
       check=lambda v: None if v["n1"] < v["n2"] < v["n3"] else ("n1", "선 길이는 짧은 것부터 차례로 커져야 해요(예: 5 < 20 < 60)"),
       hint="평균선이 위에서부터 짧은 것 → 긴 것 순서로 쌓여 있으면 꾸준히 오르는 모양이에요.", tags=("정배열", "이평", "추세")),
    _t("ma_slope_up", "ma", "{tf}{n}{봉} 이동평균선이 최근 {k}{봉} 동안 {x}% 이상 올랐다",
       (tfslot("bars"), bars(default=20), bars("k", "몇 봉 동안", 5, 1), pct(default=1, hi=50)),
       cond(ind("ma_slope", _TF, n=_N, k=M("k")), "gte", const(_X)), hint="평균선이 위를 향해 기울어져 있는지 봐요.", tags=("이평", "기울기", "상승")),
    _t("ma_disparity_high", "ma", "{tf}가격이 {n}{봉} 이동평균선보다 {x}% 이상 높다", (tfslot("bars"), bars(default=20), pct(default=5)),
       cond(ind("ma_disparity", _TF, src="close", n=_N, ma="sma"), "gte", const(M("x", add=100))),
       hint="가격이 평균선에서 많이 위로 떨어져 있으면(과열) 참이에요.", tags=("이격도", "과열", "이평")),
    _t("ma_disparity_low", "ma", "{tf}가격이 {n}{봉} 이동평균선보다 {x}% 이상 낮다", (tfslot("bars"), bars(default=20), pct(default=5)),
       cond(ind("ma_disparity", _TF, src="close", n=_N, ma="sma"), "lte", const(M("x", mul=-1, add=100))),
       hint="가격이 평균선에서 많이 아래로 떨어져 있으면(급락) 참이에요.", tags=("이격도", "급락", "이평")),

    # ---- 거래량·거래대금
    _t("value_eok", "volume", "{tf}거래대금이 {x}억 {cmp}", (tfslot("any"), num("x", "몇 억", 20, 0.1, 100000, "억"), CMP_HL),
       cond(ind("value_eok", _TF), M("cmp"), const(_X)), hint="한 봉(또는 하루) 동안 오간 돈이에요. 클수록 사람들이 몰린 종목이에요.",
       tags=("거래대금", "억", "거래", "돈")),
    _t("value_sum_eok", "volume", "{tf}최근 {n}{봉} 거래대금 합이 {x}억 {cmp}",
       (tfslot("any"), bars(default=3, lo=2), num("x", "몇 억", 50, 0.1, 100000, "억"), CMP_HL),
       cond(ind("value_sum_eok", _TF, n=_N), M("cmp"), const(_X)), hint="최근 몇 봉 동안 오간 돈을 다 더한 값이에요.", tags=("거래대금", "합", "누적", "억")),
    _t("vol_ratio", "volume", "{tf}거래량이 최근 {n}{봉} 평균의 {x}배 이상이다", (tfslot("any"), bars(default=20, lo=1), num("x", "몇 배", 3, 0.5, 1000, "배")),
       cond(ind("vol_ratio", _TF, n=_N), "gte", const(_X)), hint="평소보다 거래가 몇 배 터졌는지 봐요. 3배면 평소의 세 배예요.", tags=("거래량", "급증", "배", "폭발")),
    _t("value_ratio", "volume", "{tf}거래대금이 최근 {n}{봉} 평균의 {x}배 이상이다", (tfslot("any"), bars(default=20, lo=1), num("x", "몇 배", 3, 0.5, 1000, "배")),
       cond(ind("value_ratio", _TF, n=_N), "gte", const(_X)), hint="평소보다 돈이 몇 배 몰렸는지 봐요.", tags=("거래대금", "급증", "배")),
    _t("value_rank", "volume", "{dtf}거래대금 순위가 {n}위 안이다", (num("n", "몇 위", 20, 1, 500, "위", True), tfslot("daily", "dtf")),
       {"daily": cond(ind("value_rank", lookback=1), "lte", const(_N)),
        "intraday": cond(ind("value_rank", _DTF, lookback=1), "lte", const(_N))}, variants=True,
       hint="그날 시장 전체에서 거래대금이 큰 순서로 몇 등인지 봐요.", tags=("순위", "거래대금", "상위", "대금")),
    _t("cum_value", "volume", "오늘 지금까지 거래대금이 {x}억 {cmp}", (num("x", "몇 억", 100, 1, 100000, "억"), CMP_HL),
       cond(ind("cum_value"), M("cmp"), const(M("x", mul=1e8))), only=("intraday",),
       hint="오늘 장이 열린 뒤 지금까지 오간 돈의 합이에요.", tags=("거래대금", "누적", "당일", "억")),
    _t("cum_value_rank", "volume", "오늘 지금까지 거래대금이 {n}위 안이다", (num("n", "몇 위", 20, 1, 500, "위", True),),
       cond(ind("cum_value_rank"), "lte", const(_N)), only=("intraday",),
       hint="오늘 지금까지 거래대금이 큰 순서로 몇 등인지 봐요.", tags=("순위", "거래대금", "누적", "당일")),
    _t("first_n_value", "volume", "장이 열린 뒤 {m}분 동안 거래대금이 {x}억 이상이다", (num("m", "몇 분", 5, 1, 390, "분", True), num("x", "몇 억", 30, 0.1, 100000, "억")),
       cond(ind("first_n_value", n=M("m")), "gte", const(M("x", mul=1e8))), only=("intraday",),
       hint="장 시작 직후 큰돈이 몰렸는지 봐요.", tags=("장초반", "거래대금", "시초")),

    # ---- 오르내림·캔들
    _t("change_up", "candle", "{tf}가격이 직전 봉보다 {x}% 이상 올랐다", (tfslot("any"), pct(default=3, hi=30)),
       cond(ind("change_pct", _TF, n=1), "gte", const(_X)), hint="바로 앞 봉보다 몇 % 올랐는지 봐요.", tags=("상승", "등락률", "급등", "올랐다")),
    _t("change_down", "candle", "{tf}가격이 직전 봉보다 {x}% 이상 내렸다", (tfslot("any"), pct(default=3, hi=30)),
       cond(ind("change_pct", _TF, n=1), "lte", const(M("x", mul=-1))), hint="바로 앞 봉보다 몇 % 내렸는지 봐요.", tags=("하락", "등락률", "급락", "내렸다")),
    _t("change_n_up", "candle", "{tf}가격이 {n}{봉} 전보다 {x}% 이상 올랐다", (tfslot("any"), bars(default=5, lo=2), pct(default=5, hi=100)),
       cond(ind("change_pct", _TF, n=_N), "gte", const(_X)), hint="몇 봉 전과 비교해 많이 오른 종목을 골라요.", tags=("상승", "등락률", "올랐다")),
    _t("change_n_down", "candle", "{tf}가격이 {n}{봉} 전보다 {x}% 이상 내렸다", (tfslot("any"), bars(default=5, lo=2), pct(default=5, hi=100)),
       cond(ind("change_pct", _TF, n=_N), "lte", const(M("x", mul=-1))), hint="몇 봉 전과 비교해 많이 떨어진 종목을 골라요.", tags=("하락", "등락률", "내렸다")),
    _t("day_change_up", "candle", "어제 마지막 가격보다 {x}% 이상 올라 있다", (pct(default=5, hi=30),),
       cond(ind("day_change_pct"), "gte", const(_X)), only=("intraday",), hint="어제 마지막 가격 대비 오늘 얼마나 올랐는지 봐요.", tags=("당일", "등락률", "상승", "올랐다")),
    _t("day_change_down", "candle", "어제 마지막 가격보다 {x}% 이상 내려 있다", (pct(default=5, hi=30),),
       cond(ind("day_change_pct"), "lte", const(M("x", mul=-1))), only=("intraday",), hint="어제 마지막 가격 대비 오늘 얼마나 내렸는지 봐요.", tags=("당일", "등락률", "하락", "내렸다")),
    _t("open_change_up", "candle", "오늘 시작가보다 {x}% 이상 올라 있다", (pct(default=3, hi=30),),
       cond(ind("open_change_pct"), "gte", const(_X)), only=("intraday",), hint="오늘 장이 열릴 때 가격 대비 얼마나 올랐는지 봐요.", tags=("시가", "당일", "상승")),
    _t("open_change_down", "candle", "오늘 시작가보다 {x}% 이상 내려 있다", (pct(default=3, hi=30),),
       cond(ind("open_change_pct"), "lte", const(M("x", mul=-1))), only=("intraday",), hint="오늘 장이 열릴 때 가격 대비 얼마나 내렸는지 봐요.", tags=("시가", "당일", "하락")),
    _t("gap_up", "candle", "시작가가 어제 마지막 가격보다 {x}% 이상 높게 시작했다(갭 상승)", (pct(default=3, hi=30),),
       cond(ind("gap_pct"), "gte", const(_X)), hint="장이 열리자마자 어제보다 높은 가격에서 시작한 종목이에요.", tags=("갭", "갭상승", "시가", "상승")),
    _t("gap_held", "candle", "{x}% 이상 갭 상승한 뒤 갭을 메우지 않고 버티고 있다", (pct(default=2, hi=30),),
       cond(ind("gap_held", min_gap_pct=_X), "is_true"), hint="높게 시작한 뒤에도 시작 전 가격 아래로 안 내려온 종목이에요.", tags=("갭", "유지", "버팀")),
    _t("long_bull", "candle", "{tf}몸통이 {x}% 이상인 긴 양봉이다", (tfslot("any"), pct(default=5, lo=0.5, hi=30)),
       cond(ind("long_bull", _TF, min_body_pct=_X), "is_true"), hint="한 봉이 크게 오른 채 끝난 모양이에요(빨간 큰 봉).", tags=("장대양봉", "양봉", "캔들", "상승")),
    _t("long_bear", "candle", "{tf}몸통이 {x}% 이상인 긴 음봉이다", (tfslot("any"), pct(default=5, lo=0.5, hi=30)),
       cond(ind("long_bear", _TF, min_body_pct=_X), "is_true"), hint="한 봉이 크게 내린 채 끝난 모양이에요(파란 큰 봉).", tags=("장대음봉", "음봉", "캔들", "하락")),
    _t("up_streak", "candle", "{tf}{n}{봉} 연속으로 올랐다", (tfslot("bars"), num("n", "몇 번", 3, 2, 30, "봉", True)),
       cond(ind("up_streak", _TF), "gte", const(_N)), hint="봉이 계속 앞 봉보다 높게 끝난 횟수예요.", tags=("연속", "상승", "양봉")),
    _t("down_streak", "candle", "{tf}{n}{봉} 연속으로 내렸다", (tfslot("bars"), num("n", "몇 번", 3, 2, 30, "봉", True)),
       cond(ind("down_streak", _TF), "gte", const(_N)), hint="봉이 계속 앞 봉보다 낮게 끝난 횟수예요.", tags=("연속", "하락", "음봉")),
    _t("vwap_side", "candle", "가격이 오늘 평균 체결가(VWAP)보다 {cmp}", (CMP_ABOVE,), cond(fld(), M("cmp"), ind("vwap")), only=("intraday",),
       hint="VWAP은 오늘 거래된 가격의 거래량 가중 평균이에요. 그 위면 오늘 산 사람들이 평균적으로 이익 중이에요.", tags=("vwap", "평균가", "체결가")),

    # ---- 보조지표
    _t("rsi_level", "indicator", "{tf}RSI({n})가 {x} {cmp}", (tfslot("any"), bars(default=14, lo=2, hi=100), num("x", "몇", 30, 0, 100), choice(
        "cmp", "이상 / 이하", ("lte", "이하다"), ("gte", "이상이다"))),
       cond(ind("rsi", _TF, n=_N), M("cmp"), const(_X)),
       hint="RSI는 최근 얼마나 많이 올랐는지를 0~100으로 보여줘요. 30 이하면 많이 떨어진 상태, 70 이상이면 많이 오른 상태로 봐요.",
       tags=("rsi", "과열", "침체", "과매도", "과매수")),
    _t("rsi_cross_up", "indicator", "{tf}RSI({n})가 {x} 아래에서 위로 올라왔다", (tfslot("any"), bars(default=14, lo=2, hi=100), num("x", "몇", 30, 0, 100)),
       cond(ind("rsi", _TF, n=_N), "cross_above", const(_X)), hint="많이 떨어졌다가 다시 올라오기 시작하는 순간을 잡아요(반등).", tags=("rsi", "반등", "상향")),
    _t("rsi_cross_down", "indicator", "{tf}RSI({n})가 {x} 위에서 아래로 내려왔다", (tfslot("any"), bars(default=14, lo=2, hi=100), num("x", "몇", 70, 0, 100)),
       cond(ind("rsi", _TF, n=_N), "cross_below", const(_X)), hint="많이 올랐다가 식기 시작하는 순간을 잡아요.", tags=("rsi", "하락", "하향")),
    _t("macd_cross_up", "indicator", "{tf}MACD선이 신호선을 아래에서 위로 뚫고 올라갔다", (tfslot("any"),),
       cond(ind("macd", _TF), "cross_above", ind("macd_signal", _TF)), hint="MACD는 흐름이 바뀌는 시점을 알려주는 지표예요. 이 교차는 오르는 쪽으로 바뀐다는 신호로 봐요.", tags=("macd", "교차", "상향")),
    _t("macd_cross_down", "indicator", "{tf}MACD선이 신호선을 위에서 아래로 뚫고 내려갔다", (tfslot("any"),),
       cond(ind("macd", _TF), "cross_below", ind("macd_signal", _TF)), hint="내리는 쪽으로 바뀐다는 신호예요. 팔 때 써요.", tags=("macd", "교차", "하향")),
    _t("stoch_level", "indicator", "{tf}스토캐스틱 %K가 {x} {cmp}", (tfslot("any"), num("x", "몇", 20, 0, 100), choice(
        "cmp", "이상 / 이하", ("lte", "이하다"), ("gte", "이상이다"))),
       cond(ind("stoch_k", _TF), M("cmp"), const(_X)), hint="최근 가격 범위에서 지금 어디쯤인지(0=맨 아래, 100=맨 위)를 보여줘요. 20 이하면 바닥권이에요.",
       tags=("스토캐스틱", "바닥", "과열")),
    _t("bb_upper_break", "indicator", "{tf}가격이 볼린저밴드 위쪽 선을 넘었다", (tfslot("any"), bars(default=20), num("k", "폭 배수", 2, 0.1, 10, "배")),
       cond(fld("close", _TF), "gt", ind("bb_upper", _TF, n=_N, k=M("k"))),
       hint="볼린저밴드는 평균선 위아래로 그은 '보통 움직이는 범위'예요. 위쪽 선을 넘으면 평소보다 강하게 오른 거예요.", tags=("볼린저", "밴드", "돌파", "상단")),
    _t("bb_lower_break", "indicator", "{tf}가격이 볼린저밴드 아래쪽 선 밑으로 내려갔다", (tfslot("any"), bars(default=20), num("k", "폭 배수", 2, 0.1, 10, "배")),
       cond(fld("close", _TF), "lt", ind("bb_lower", _TF, n=_N, k=M("k"))),
       hint="아래쪽 선 밑이면 평소보다 강하게 떨어진 거예요.", tags=("볼린저", "밴드", "이탈", "하단")),
    _t("bb_width_low", "indicator", "{tf}볼린저밴드 폭이 {x}% 이하로 좁아졌다", (tfslot("any"), bars(default=20), num("x", "몇 %", 10, 0.1, 100, "%")),
       cond(ind("bb_width", _TF, n=_N, k=2.0), "lte", const(_X)), hint="가격 움직임이 좁게 눌려 있는 상태예요. 이런 뒤에 크게 움직이는 일이 많아요.", tags=("볼린저", "수축", "스퀴즈", "횡보")),

    # ---- 시간대
    _t("minutes_since_open", "time", "장이 열린 지 {m}분 {cmp}", (num("m", "몇 분", 30, 1, 390, "분", True), choice(
        "cmp", "이내 / 이후", ("lte", "이내다"), ("gte", "이후다"))),
       cond(ind("minutes_since_open"), M("cmp"), const(M("m"))), only=("intraday",), hint="오전 9시에 장이 열린 뒤 지난 시간이에요. 시작 30분 안에만 사고 싶을 때 써요.", tags=("시간", "장초반", "시초", "오전")),

    # ---- 테마·업종
    _t("theme_rank", "theme", "{dtf}소속 테마의 {by} 순위가 {n}위 안이다", (num("n", "몇 위", 5, 1, 100, "위", True), BY, tfslot("daily", "dtf")),
       {"daily": cond(ind("theme_rank", by=M("by")), "lte", const(_N)),
        "intraday": cond(ind("theme_rank", _DTF, by=M("by")), "lte", const(_N))}, variants=True,
       warn="테마 구성은 '현재' 기준이라, 과거 백테스트 결과는 실제와 다를 수 있어요.", hint="종목이 속한 테마가 그날 시장에서 몇 등인지 봐요.", tags=("테마", "순위", "주도")),
    _t("rank_in_theme", "theme", "{dtf}테마 안에서 {by} 순위가 {n}위 안이다(대장주 후보)", (num("n", "몇 위", 3, 1, 100, "위", True), BY, tfslot("daily", "dtf")),
       {"daily": cond(ind("rank_in_theme", by=M("by")), "lte", const(_N)),
        "intraday": cond(ind("rank_in_theme", _DTF, by=M("by")), "lte", const(_N))}, variants=True,
       warn="테마 구성은 '현재' 기준이라, 과거 백테스트 결과는 실제와 다를 수 있어요.", hint="같은 테마 종목들 중에서 몇 등인지 봐요. 1~3등이 대장주예요.", tags=("테마", "대장주", "순위")),

    # ---- 팔 때(청산)
    _t("pos_profit", "exit", "산 가격보다 {x}% 이상 올랐다(수익)", (pct(default=5, hi=1000),), cond(pos("return_pct"), "gte", const(_X)), role="exit",
       hint="산 가격 대비 수익이 이만큼 나면 팔아요(이익 실현).", tags=("익절", "수익", "매수가")),
    _t("pos_loss", "exit", "산 가격보다 {x}% 이상 내렸다(손실)", (pct(default=3, hi=100),), cond(pos("return_pct"), "lte", const(M("x", mul=-1))), role="exit",
       hint="산 가격 대비 손실이 이만큼 나면 팔아요(손절).", tags=("손절", "손실", "매수가")),
    _t("pos_drawdown", "exit", "가지고 있는 동안 가장 높았던 값에서 {x}% 이상 내려왔다", (pct(default=3, hi=100),), cond(pos("drawdown_pct"), "gte", const(_X)), role="exit",
       hint="오른 만큼 반납하기 시작하면 팔아요(고점 대비 하락).", tags=("트레일링", "고점", "하락", "이익 보호")),
    _t("pos_bars", "exit", "산 지 {n}{봉}이 지났다", (num("n", "몇 봉", 5, 1, 500, "봉", True),), cond(pos("bars_held"), "gte", const(_N)), role="exit",
       hint="오래 들고 있어도 안 오르면 시간이 지난 뒤 정리해요.", tags=("보유", "시간", "기간")),
    _t("pos_minutes", "exit", "산 지 {n}분이 지났다", (num("n", "몇 분", 30, 1, 1000, "분", True),), cond(pos("minutes_held"), "gte", const(_N)), role="exit", only=("intraday",),
       hint="분봉 매매에서 일정 시간이 지나면 정리해요.", tags=("보유", "시간", "분")),
)

BY_ID: dict[str, Template] = {t.id: t for t in TEMPLATES}
assert len(BY_ID) == len(TEMPLATES), "템플릿 id 중복"


# ---------------------------------------------------------------- 뼈대 읽기
def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if "$" in node:
            return
        if node.get("kind") in ("field", "ind", "pos", "const"):
            yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _marker_name(x: Any) -> str | None:
    return x["$"] if isinstance(x, dict) and "$" in x else None


def _tf_reason(op: dict[str, Any], tf: str, source: str) -> str | None:
    """이 피연산자를 그 시간 단위로 쓸 수 있으면 None, 못 쓰면 쉬운 말 이유(카탈로그 지표 정의에서 읽는다)."""
    if op["kind"] != "ind":
        return None
    d = INDICATORS[op["name"]]
    if tf == "bar" or tf in MINUTE_TIMEFRAMES:
        return None if "intraday" in d.modes else "이 조건은 일봉으로만 볼 수 있어요"
    if tf == "daily_prev":
        return None if set(d.modes) & set(DAILY_MODES) else "이 조건은 분봉으로만 볼 수 있어요"
    if not d.live:
        return "'오늘 지금까지' 값은 만들 수 없어서 '어제까지 확정된 일봉'만 쓸 수 있어요"
    if d.volume_based and source != "krx":
        return "거래량·거래대금은 통합(AL) 분봉과 KRX 일봉을 섞으면 부풀려져서, KRX 분봉을 고른 경우에만 '오늘 지금까지'를 쓸 수 있어요"
    return None


def _tf_choices(t: Template, slot: Slot, mode: str, bar_minutes: int, source: str) -> list[dict[str, Any]]:
    """tf 빈칸의 선택지 — 모드·봉 길이·출처에 맞게 켜고 끄고, 끈 것은 이유를 붙인다."""
    ops = [op for op in _walk(t.skel(mode)) if op["kind"] in ("ind", "field") and _marker_name(op.get("tf")) == slot.name]
    out = []
    for tf in SCOPES[slot.scope]:
        reason = None
        if tf in MINUTE_TIMEFRAMES and not (MINUTE_TIMEFRAMES[tf] > bar_minutes and MINUTE_TIMEFRAMES[tf] % bar_minutes == 0):
            reason = f"실행 봉({bar_minutes}분)보다 길고 그 배수인 분봉만 쓸 수 있어요"
        for op in ops:
            reason = reason or _tf_reason(op, tf, source)
        out.append({"value": tf, "label": tf_label(tf, mode, bar_minutes, slot.scope), "enabled": reason is None, "reason": reason})
    return out


def tf_label(tf: str, mode: str, bar_minutes: int, scope: str = "any") -> str:
    if tf == "bar":
        return "일봉" if mode in DAILY_MODES else f"지금 보는 봉({bar_minutes}분봉)"
    if tf in MINUTE_TIMEFRAMES:
        return f"{MINUTE_TIMEFRAMES[tf]}분봉"
    return "어제까지 확정된 일봉" if tf == "daily_prev" else "오늘 지금까지 반영한 일봉"


def _tf_prefix(tf: str, mode: str, bar_minutes: int, scope: str) -> str:
    if tf == "bar":
        return "" if mode in DAILY_MODES else f"{bar_minutes}분봉 "
    if tf in MINUTE_TIMEFRAMES:
        return f"{MINUTE_TIMEFRAMES[tf]}분봉 "
    if scope == "daily":
        return "어제까지 확정된 " if tf == "daily_prev" else "오늘 지금까지 반영한 "
    return "어제까지 확정된 일봉 " if tf == "daily_prev" else "오늘 지금까지의 일봉 "


def visible_slots(t: Template, mode: str) -> tuple[Slot, ...]:
    """일봉 모드에서는 시간 단위를 고를 필요가 없다(전부 일봉)."""
    return tuple(s for s in t.slots if not (s.kind == "tf" and mode in DAILY_MODES)) if mode else t.slots


def availability(t: Template, mode: str, source: str = "al", bar_minutes: int = 5) -> tuple[bool, str]:
    """(쓸 수 있나, 못 쓰는 이유). 지원 모드는 지표 정의가 정하고, `only` 로 더 좁힐 수 있다."""
    if mode not in (*DAILY_MODES, "intraday"):
        return False, "이 실행 방식에서는 문장으로 만드는 조건을 쓸 수 없어요"
    if t.only and not (mode in t.only or (mode in DAILY_MODES and "daily" in t.only)):
        return False, "분봉 실행에서만 쓸 수 있어요" if "intraday" in t.only else "일봉 실행에서만 쓸 수 있어요"
    skel = t.skel(mode)
    for op in _walk(skel):
        if op["kind"] == "ind" and mode in DAILY_MODES and mode not in INDICATORS[op["name"]].modes:
            return False, "분봉 실행에서만 쓸 수 있어요"
        if op["kind"] == "ind" and mode == "intraday":
            fixed = op.get("tf")
            if fixed is None or _marker_name(fixed):
                fixed = "bar" if fixed is None else None
            if fixed and (r := _tf_reason(op, fixed, source)):
                return False, r
    if mode == "intraday":
        for s in t.slots:
            if s.kind == "tf" and not any(c["enabled"] for c in _tf_choices(t, s, mode, bar_minutes, source)):
                why = next((c["reason"] for c in _tf_choices(t, s, mode, bar_minutes, source) if c["reason"]), "")
                return False, why or "지금 설정에서는 쓸 수 없어요"
    return True, ""


def defaults(t: Template, mode: str, source: str = "al", bar_minutes: int = 5) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for s in t.slots:
        if s.kind == "tf":
            if mode in DAILY_MODES:
                out[s.name] = "bar"
                continue
            ok = [c["value"] for c in _tf_choices(t, s, mode, bar_minutes, source) if c["enabled"]]
            prefer = ("daily_live", "daily_prev") if s.scope == "daily" else ("bar",)
            out[s.name] = next((p for p in prefer if p in ok), ok[0] if ok else prefer[-1])
        else:
            out[s.name] = s.default
    return out


# ---------------------------------------------------------------- 문장
def _fmt(v: Any) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def sentence(t: Template, values: Mapping[str, Any], mode: str = "daily_portfolio", bar_minutes: int = 5) -> str:
    """빈칸을 값으로 채운 쉬운 문장. 값이 빠진 칸은 기본값."""
    v = {**defaults(t, mode, bar_minutes=bar_minutes), **values}
    tf_slots = {s.name: s for s in t.slots if s.kind == "tf"}
    bong_daily = mode in DAILY_MODES or any(str(v.get(n, "")).startswith("daily") for n in tf_slots)

    def fill(m: re.Match[str]) -> str:
        k = m.group(1)
        if k == "봉":
            return "일" if bong_daily else "봉"
        if k in tf_slots:
            return _tf_prefix(v[k], mode, bar_minutes, tf_slots[k].scope)
        s = next(s for s in t.slots if s.name == k)
        if s.kind == "choice":
            return dict(s.choices).get(v[k], str(v[k]))
        return _fmt(v[k])

    return re.sub(r"\{([^{}]+)\}", fill, t.sentence)


# ---------------------------------------------------------------- 검증·build
def _validate_values(t: Template, values: Mapping[str, Any], mode: str, source: str, bar_minutes: int) -> dict[str, Any]:
    known = {s.name: s for s in t.slots}
    for k in values:
        if k not in known:
            raise TemplateError(k, f"'{k}' 는 이 조건에 없는 빈칸이에요")
    v = {**defaults(t, mode, source, bar_minutes), **values}
    for s in t.slots:
        x = v[s.name]
        if s.kind == "number":
            if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x:
                raise TemplateError(s.name, f"'{s.label}' 칸에는 숫자를 적어 주세요")
            if s.integer and float(x) != int(x):
                raise TemplateError(s.name, f"'{s.label}' 칸에는 소수점 없는 숫자를 적어 주세요")
            if not (s.lo <= x <= s.hi):
                raise TemplateError(s.name, f"'{s.label}' 칸은 {_fmt(s.lo)}~{_fmt(s.hi)}{s.unit} 사이로 적어 주세요")
            v[s.name] = int(x) if s.integer else x
        elif s.kind == "choice":
            if x not in dict(s.choices):
                raise TemplateError(s.name, f"'{s.label}' 은 {' / '.join(lbl for _, lbl in s.choices)} 중에서 골라 주세요")
        else:
            if mode in DAILY_MODES:
                v[s.name] = "bar"
                continue
            ch = {c["value"]: c for c in _tf_choices(t, s, mode, bar_minutes, source)}
            if x not in ch:
                raise TemplateError(s.name, f"'{s.label}' 에서 고를 수 있는 값이 아니에요")
            if not ch[x]["enabled"]:
                raise TemplateError(s.name, ch[x]["reason"])
    if t.check and (bad := t.check(v)):
        raise TemplateError(*bad)
    return v


def _subst(node: Any, v: Mapping[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$" in node:
            x = v[node["$"]]
            if isinstance(x, (int, float)) and not isinstance(x, bool) and ("mul" in node or "add" in node):
                x = round(x * node.get("mul", 1) + node.get("add", 0), 9)
            return x
        return {k: _subst(val, v) for k, val in node.items()}
    return node


def build_card(template_id: str, values: Mapping[str, Any] | None = None, *, mode: str = "daily_portfolio", bar_minutes: int = 5,
               source: str = "al") -> dict[str, Any]:
    """빈칸 값 → {condition: 조건 AST(dict, 기본값 생략 — 명세에 그대로 들어간다), sentence: 채운 문장, values: 기본값까지 채운 빈칸값}.
    잘못된 값은 TemplateError(쉬운 말, slot 으로 어느 칸인지), 없는 id 는 KeyError."""
    t = BY_ID[template_id]
    ok, why = availability(t, mode, source, bar_minutes)
    if not ok:
        raise TemplateError("", why)
    v = _validate_values(t, values or {}, mode, source, bar_minutes)
    c = Condition.model_validate(_subst(t.skel(mode), v)).model_dump(mode="json", exclude_defaults=True)
    return {"condition": c, "sentence": sentence(t, v, mode, bar_minutes), "values": {s.name: v[s.name] for s in visible_slots(t, mode)}}


def build(template_id: str, values: Mapping[str, Any] | None = None, *, mode: str = "daily_portfolio", bar_minutes: int = 5,
          source: str = "al") -> dict[str, Any]:
    """`build_card` 의 조건 AST 만."""
    return build_card(template_id, values, mode=mode, bar_minutes=bar_minutes, source=source)["condition"]


# ---------------------------------------------------------------- match (되돌리기)
def _norm(x: Any) -> Any:
    """지표·피연산자의 기본값을 채워 같은 뜻이면 같은 모양으로 — 뼈대와 실제 조건을 나란히 놓기 위해."""
    if not isinstance(x, dict) or "$" in x:
        return x
    k = x.get("kind")
    if k == "field":
        return {"kind": k, "name": x["name"], "offset": x.get("offset", 0), "mul": x.get("mul", 1.0), "tf": x.get("tf", "bar")}
    if k == "ind":
        return {"kind": k, "name": x["name"], "params": resolve_params(x["name"], dict(x.get("params") or {})),
                "offset": x.get("offset", 0), "mul": x.get("mul", 1.0), "tf": x.get("tf", "bar")}
    if k in ("const", "pos"):
        return dict(x)
    if "op" in x and "left" in x:
        return {"left": _norm(x["left"]), "op": x["op"], "right": _norm(x.get("right")), "hold": x.get("hold", 1), "within": x.get("within")}
    return x


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _unify(sk: Any, obs: Any, bound: dict[str, Any]) -> bool:
    if (name := _marker_name(sk)) is not None:
        raw = obs
        if _is_num(obs) and ("mul" in sk or "add" in sk):
            raw = (obs - sk.get("add", 0)) / sk.get("mul", 1)
        if _is_num(raw):
            raw = round(float(raw), 9)
            raw = int(raw) if raw == int(raw) else raw
        if name in bound:
            return bound[name] == raw
        bound[name] = raw
        return True
    if isinstance(sk, dict):
        return isinstance(obs, dict) and sk.keys() == obs.keys() and all(_unify(sk[k], obs[k], bound) for k in sk)
    if _is_num(sk) and _is_num(obs):
        return float(sk) == float(obs)
    return sk == obs


def _slot_ok(s: Slot, x: Any) -> bool:
    if s.kind == "number":
        return _is_num(x) and s.lo <= x <= s.hi and (not s.integer or float(x) == int(x))
    if s.kind == "choice":
        return x in dict(s.choices)
    return x in SCOPES[s.scope]


def match(condition: Mapping[str, Any], mode: str | None = None) -> tuple[str, dict[str, Any]] | None:
    """조건 dict → (템플릿 id, 빈칸값), 어느 문장과도 안 맞으면 None(화면은 풀이 문장 + [고급에서 편집]).
    mode 를 주면 그 모드의 뼈대만 본다(일봉 모드에서는 시간 단위 빈칸을 값에 넣지 않는다)."""
    obs = _norm(dict(condition))
    variants = ("daily", "intraday") if mode is None else ("daily" if mode in DAILY_MODES else "intraday",)
    for t in TEMPLATES:
        for skel in ([t.skeleton[v] for v in variants] if t.variants else [t.skeleton]):
            bound: dict[str, Any] = {}
            if not _unify(_norm(skel), obs, bound):
                continue
            slots = {s.name: s for s in t.slots}
            if not all(_slot_ok(slots[k], x) for k, x in bound.items()) or (t.check and set(bound) == set(slots) and t.check(bound)):
                continue
            return t.id, {s.name: bound[s.name] for s in t.slots if s.name in bound}
    return None


# ---------------------------------------------------------------- 화면용 목록
def describe(mode: str, *, bar_minutes: int = 5, source: str = "al") -> list[dict[str, Any]]:
    """`GET /api/meta/condition-templates` 본문 — 템플릿마다 문장·빈칸(선택지는 켜짐/꺼짐+이유)·쓸 수 있는지·기본 문장."""
    out = []
    for t in TEMPLATES:
        ok, why = availability(t, mode, source, bar_minutes)
        d: dict[str, Any] = {"id": t.id, "category": t.category, "category_label": CATEGORIES[t.category], "sentence": t.sentence, "role": t.role,
                             "hint": t.hint, "warn": t.warn, "tags": list(t.tags), "available": ok, "reason": why}
        if ok:
            dv = defaults(t, mode, source, bar_minutes)
            d["example"] = sentence(t, dv, mode, bar_minutes)
            d["slots"] = [_slot_view(t, s, mode, bar_minutes, source, dv[s.name]) for s in visible_slots(t, mode)]
        else:
            d["example"], d["slots"] = "", []
        out.append(d)
    return out


def _slot_view(t: Template, s: Slot, mode: str, bar_minutes: int, source: str, default: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"name": s.name, "kind": s.kind, "label": s.label, "default": default}
    if s.kind == "number":
        d.update(unit=s.unit if not (s.unit == "봉" and mode in DAILY_MODES) else "일", lo=s.lo, hi=s.hi, integer=s.integer)
    elif s.kind == "choice":
        d["choices"] = [{"value": v, "label": lbl, "enabled": True, "reason": None} for v, lbl in s.choices]
    else:
        d["choices"] = _tf_choices(t, s, mode, bar_minutes, source)
    return d
