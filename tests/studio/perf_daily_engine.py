"""성능 실측(설계서 §8.9: 전 종목 x 5년 일봉 <= 30초) - 수동 실행: python tests/studio/perf_daily_engine.py"""
import time, sys
sys.path.insert(0, '.')
import pandas as pd, numpy as np
from studio.domain.models import Panel
from studio.domain.costs import CostModel
from studio.domain.engine.fills import ExitRules, FillRules
from studio.domain.engine.portfolio import PortfolioRules, run_portfolio
from studio.domain.metrics import standard_metrics
t0 = time.time()
d = pd.read_parquet('data/cache/daily_all.parquet'); d = d[d.date >= '2021-09-01']
d['date'] = pd.to_datetime(d['date'])
w = {k: d.pivot(index='date', columns='code', values=k).astype(float) for k in ['open','high','low','close','volume']}
val = w['close'] * w['volume']
pn = Panel(w['open'], w['high'], w['low'], w['close'], w['volume'], val, w['close'].shift(1))
t1 = time.time()
ent = (pn.close > pn.high.shift(1).rolling(20).max()) & (pn.volume > pn.volume.shift(1).rolling(20).mean() * 1.5)
ext = pn.close < pn.low.shift(1).rolling(10).min()
t2 = time.time()
r = run_portfolio(pn, ent, ext, CostModel(), ExitRules(stop_loss_pct=7, trailing_stop_pct=10, max_holding_bars=20),
                  FillRules(volume_cap_pct=10), PortfolioRules(max_positions=5, sizing='equal_slot_compound', max_weight_pct=25))
t3 = time.time()
m = standard_metrics(r, 10_000_000)
print(pn.close.shape, 'load+pivot %.1fs, signals %.1fs, ENGINE %.1fs' % (t1-t0, t2-t1, t3-t2))
print(len(r.trades), r.skipped, {k: round(v,2) for k,v in m.items() if not isinstance(v, dict)})
