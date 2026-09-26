"""두 명세의 차이를 사람 말로 — 비교 화면 "조건 차이 문장" (§5.4 실행 기록 / 비교).

조건 그룹(진입·청산·시장 필터)은 값 하나하나가 아니라 **풀이 문장**끼리 비교한다("20일 최고가 돌파 → 60일 최고가 돌파").
그 밖의 칸은 경로 라벨과 값. 이름(name)·버전은 비교하지 않는다.
"""
from __future__ import annotations

from typing import Any

from studio.domain.conditions.ast import Group
from studio.domain.narration import narrate_group
from studio.domain.spec import Spec

_GROUPS = {"strategy.entry": "진입 조건", "strategy.exit": "청산 조건", "market_filter": "시장 필터",
           "intraday.prefilter": "일봉 사전 필터"}
LABELS = {
    "mode": "모드", "period.start": "시작일", "period.end": "종료일",
    "universe.type": "유니버스", "universe.n": "거래대금 상위 N", "universe.lookback_days": "순위 평균 일수",
    "universe.markets": "시장", "universe.exclude": "제외", "universe.codes": "종목",
    "strategy.source": "전략 소스", "strategy.name": "기존 전략",
    "exits.stop_loss_pct": "손절(%)", "exits.take_profit_pct": "익절(%)", "exits.trailing_stop_pct": "트레일링(%)",
    "exits.max_holding_bars": "최대 보유 봉",
    "portfolio.initial_capital": "초기자금", "portfolio.max_positions": "최대 보유 종목", "portfolio.sizing": "배분 방식",
    "portfolio.fixed_amount": "고정 금액", "portfolio.risk_pct": "위험 비율(%)", "portfolio.max_weight_pct": "종목당 최대 비중(%)",
    "portfolio.rank_by": "우선순위", "portfolio.random_seed": "무작위 시드",
    "costs.commission_rate": "수수료율", "costs.tax_rate": "세율", "costs.slippage_mode": "슬리피지 방식",
    "costs.slippage_rate": "슬리피지 비율", "costs.slippage_ticks": "슬리피지 호가 수",
    "fills.same_bar_policy": "같은 봉 손절·익절", "fills.volume_cap_pct": "거래량 한도(%)",
    "compat.legacy": "호환 모드",
}


def _flat(d: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(d, dict) and prefix not in _GROUPS:
        out: dict[str, Any] = {}
        for k, v in d.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else k))
        return out
    return {prefix: d}


def _show(v: Any) -> str:
    if v is None:
        return "없음"
    if isinstance(v, bool):
        return "켜짐" if v else "꺼짐"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) or "없음"
    return f"{v:g}" if isinstance(v, float) else str(v)


def _group_text(v: Any) -> str:
    if v is None:
        return "없음"
    try:
        return narrate_group(Group.model_validate(v)) or "없음"
    except Exception:  # 풀이가 안 되는 그룹은 원문 JSON 으로 — 차이는 보여줘야 한다
        return str(v)


def diff_specs(a: Spec, b: Spec) -> list[dict[str, Any]]:
    """a → b 로 바뀐 칸 목록. 항목: {path, label, a, b, text}."""
    fa, fb = _flat(a.model_dump(mode="json")), _flat(b.model_dump(mode="json"))
    for k in ("name", "version"):
        fa.pop(k, None)
        fb.pop(k, None)
    items: list[dict[str, Any]] = []
    for path in sorted(set(fa) | set(fb)):
        va, vb = fa.get(path), fb.get(path)
        if va == vb:
            continue
        if path in _GROUPS:
            ta, tb = _group_text(va), _group_text(vb)
            if ta == tb:
                continue
            label = _GROUPS[path]
            items.append({"path": path, "label": label, "a": ta, "b": tb, "text": f"{label}: {ta} → {tb}"})
            continue
        if path.startswith("params."):
            label = f"변수 {path.split('.', 2)[1]} 범위"
        else:
            label = LABELS.get(path, path)
        sa, sb = _show(va), _show(vb)
        items.append({"path": path, "label": label, "a": sa, "b": sb, "text": f"{label}: {sa} → {sb}"})
    return items
