import math

import pandas as pd
import pytest

from studio.domain.metrics import standard_metrics
from studio.domain.models import BacktestResult, Fill, Trade


def _t(pnl, pct, day):
    ts = pd.Timestamp("2024-01-0" + str(day))
    return Trade("A", ts, 100, ts, 100 + pnl, 1, pnl, 0, 0, 0, pnl, pct, None, 1, None, None)


def test_standard_metrics_hand_computed():
    eq = pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=3), "cash": [0, 0, 0],
                       "positions_value": [110.0, 99.0, 108.9], "equity": [110.0, 99.0, 108.9],
                       "n_positions": [1, 1, 0]})
    trades = [_t(10, 0.10, 1), _t(-11, -0.10, 2), _t(9.9, 0.10, 3), _t(-1, -0.01, 4)]
    r = BacktestResult(trades, eq, [Fill(eq.ts[0], "A", "buy", 1, 100, 100, 0.5, 0, 0, "entry")], {"cash": 2})
    m = standard_metrics(r, 100.0)
    assert m["total_return_pct"] == pytest.approx(8.9)
    assert m["max_drawdown_pct"] == pytest.approx(10.0) and m["mdd_duration_bars"] == 2
    assert m["win_rate_pct"] == 50 and m["num_trades"] == 4
    assert m["profit_factor"] == pytest.approx(19.9 / 12)
    assert m["max_consec_losses"] == 1
    assert m["exposure_pct"] == pytest.approx(200 / 3)
    assert m["skipped"] == {"cash": 2} and m["commission_total"] == 0.5
    assert not math.isnan(m["sharpe"])
