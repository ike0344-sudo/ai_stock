"""지표 단위 테스트 공용 — 한 종목("A")짜리 작은 Panel 대역을 손으로 만든 배열에서 만든다."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from studio.domain.conditions.indicators import compute


def mk(c, o=None, h=None, l=None, v=None, prev=None, code="A") -> SimpleNamespace:
    """c(종가)만 주면 o=h=l=c, v=1000. prev(전일 종가)를 안 주면 close.shift(1)."""
    c = np.asarray(c, dtype=float)
    idx = pd.bdate_range("2026-01-05", periods=len(c))

    def f(x, default):
        return pd.DataFrame({code: np.asarray(default if x is None else x, dtype=float)}, index=idx)

    close = f(c, c)
    return SimpleNamespace(
        open=f(o, c), high=f(h, c), low=f(l, c), close=close, volume=f(v, np.full(len(c), 1000.0)),
        value=f(None, c * (1000.0 if v is None else np.asarray(v, dtype=float))),
        prev_close=f(prev, close[code].shift(1).to_numpy()),
    )


def val(panel, name, **params) -> np.ndarray:
    """지표 값(첫 종목 열)을 numpy 로."""
    return compute(panel, name, params).iloc[:, 0].to_numpy()


def head(panel, k: int) -> SimpleNamespace:
    """앞 k 행만 — 미래 봉이 없을 때의 값과 대조(prefix 불변 카나리아)."""
    return SimpleNamespace(**{f: getattr(panel, f).iloc[:k] for f in
                              ("open", "high", "low", "close", "volume", "value", "prev_close")})


def nan_eq(a, b, **kw):
    np.testing.assert_allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), equal_nan=True, **kw)
