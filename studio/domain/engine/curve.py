"""엔진 진행 중 중간 곡선 — 실행 화면의 "차트가 지나가는 모습"용(순수, 결과에 영향 없음).

엔진 봉 루프가 `CurveEmitter.emit(...)` 를 봉마다 부르면 **약 `max_points`(200) 점 이하로 솎아** 콜백에 점을 보낸다:
`{date, equity, cash, n_positions, n_trades(=지금까지 진입 건수), last_event, frac}` — frac = 엔진 루프 진행(0~1), last_event = 직전 점 이후 마지막 체결
(`{ts, code, side, qty, price, reason}`, 없으면 None). 엔진은 이 값을 **읽기만** 한다(상태를 안 바꿈) — 콜백을 켜고 꺼도 거래·지표가 같다.
콜백이 예외를 던지면(취소) 그대로 전파돼 실행이 멈춘다.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

import pandas as pd

MAX_POINTS = 200


def fmt_ts(ts: pd.Timestamp) -> str:
    """일봉(자정)은 날짜, 분봉은 `YYYY-MM-DD HH:MM`."""
    return ts.strftime("%Y-%m-%d") if (ts.hour == 0 and ts.minute == 0 and ts.second == 0) else ts.strftime("%Y-%m-%d %H:%M")


class CurveEmitter:
    def __init__(self, cb: Callable[[dict[str, Any]], None], n: int, max_points: int = MAX_POINTS) -> None:
        self.cb, self.n = cb, max(1, n)
        self.step = max(1, -(-self.n // max_points))  # ceil — 점 수 ≤ max_points
        self._nf = 0

    def emit(self, i: int, ts: pd.Timestamp, equity: float, cash: float, n_positions: int, n_trades: int, fills: Sequence[Any]) -> None:
        if (i + 1) % self.step and i != self.n - 1:
            return
        ev = None
        if len(fills) > self._nf:
            f = fills[-1]
            ev = {"ts": fmt_ts(f.ts), "code": f.code, "side": f.side, "qty": int(f.qty), "price": round(float(f.price), 2), "reason": f.reason}
        self._nf = len(fills)
        self.cb({"date": fmt_ts(ts), "equity": round(float(equity), 2), "cash": round(float(cash), 2), "n_positions": int(n_positions),
                 "n_trades": int(n_trades), "last_event": ev, "frac": (i + 1) / self.n})
