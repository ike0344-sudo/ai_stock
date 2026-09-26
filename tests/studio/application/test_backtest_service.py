"""backtest_service — 합성 데이터로 흐름·워밍업·유니버스·카나리아·저장 왕복."""
import numpy as np
import pandas as pd
import pytest

from studio.application.backtest_service import (
    BacktestError, ModeNotSupportedError, eligible_codes, is_preferred, is_spac, run_backtest,
    spec_hash, structure_hash, to_engine_rules,
)
from studio.domain.models import Panel
from studio.domain.spec import Spec, bind_params
from studio.infrastructure.run_store import FileRunStore

from .fakes import CODES, FakeMarketData, make_panel, spec_dict


def test_portfolio_smoke():
    md = FakeMarketData()
    spec = Spec.model_validate(spec_dict())
    rec = run_backtest(spec, md)
    idx = md.panel.close.index
    period = idx[(idx >= "2022-12-01") & (idx <= "2023-07-31")]
    assert len(rec.equity) == len(period) and rec.summary["n_bars"] == len(period)
    assert len(rec.trades) > 3 and rec.summary["metrics"]["num_trades"] == rec.summary["n_closed"]
    assert {"code", "name", "sector", "net_pct", "exit_reason"} <= set(rec.trades.columns)
    assert {"drawdown_pct", "benchmark_kospi", "benchmark_kosdaq"} <= set(rec.equity.columns)
    assert rec.equity["benchmark_kospi"].iloc[0] == pytest.approx(10_000_000)
    assert any("생존 편향" in w for w in rec.warnings)
    assert rec.trades["entry_ts"].min() >= pd.Timestamp("2022-12-01")
    # 제외 규칙: 스팩·우선주·초대형주는 절대 거래 안 됨
    assert not set(rec.trades["code"]) & {"000020", "000045", "005930"}
    assert rec.meta["spec_hash"] and rec.meta["structure_hash"] and rec.meta["elapsed_sec"] >= 0


def test_warmup_no_fill_before_period_and_first_bar_signal():
    """워밍업: 기간 첫날부터 sma(50) 가 채워져 있다(신호가 첫 봉부터 나온다), 기간 앞 봉으로는 체결 0건."""
    up = make_panel(n=200, trend=0.0, codes=["000010"])
    c = pd.DataFrame({"000010": np.linspace(10_000, 20_000, 200)}, index=up.close.index)
    panel = Panel(c * 0.999, c * 1.001, c * 0.998, c, up.volume, c * up.volume, c.shift(1))
    md = FakeMarketData(panel)
    start = panel.close.index[100]
    d = spec_dict(period={"start": str(start.date()), "end": str(panel.close.index[-1].date())},
                  universe={"type": "codes", "codes": ["000010"]}, mode="daily_single")
    d["strategy"] = {"source": "builder", "exit": {"logic": "any", "items": []}, "entry": {"logic": "all", "items": [
        {"left": {"kind": "field", "name": "close"}, "op": "gt",
         "right": {"kind": "ind", "name": "sma", "params": {"src": "close", "n": 50}}}]}}
    d["portfolio"] = {"max_positions": 1, "max_weight_pct": 100}
    rec = run_backtest(Spec.model_validate(d), md)
    (t,) = rec.trades.to_dict("records")
    # 신호는 기간 첫 봉(100) 종가 → 체결은 봉 101 시가. 워밍업이 없었다면 첫 신호는 봉 150 이후.
    assert t["entry_ts"] == panel.close.index[101]
    assert (rec.equity["ts"] >= start).all()


def test_universe_exclusion_rules():
    info = FakeMarketData().info
    spec = Spec.model_validate(spec_dict())
    codes, stats = eligible_codes(spec, info, frozenset({"005930"}), CODES)
    assert codes == ["000010", "000030", "000050", "000060", "000070"]  # 성우(코드 끝 0)는 보통주
    assert stats["spac"] == 1 and stats["preferred"] == 1 and stats["mega_cap"] == 1
    assert is_spac("KB제32호스팩") and not is_spac("삼성전자")
    assert is_preferred("005935", "삼성전자우") and is_preferred("00104K", "두산2우B")
    assert not is_preferred("458650", "성우") and not is_preferred("005930", "삼성전자")
    # 시장 하나만 고르면 그 시장만, 시장 미상은 뺀다
    only_kosdaq = Spec.model_validate(spec_dict(universe={"type": "all", "markets": ["코스닥"], "exclude": []}))
    assert eligible_codes(only_kosdaq, info, frozenset(), CODES)[0] == ["000030"]
    info2 = info.copy()
    info2.loc["000060", "market"] = np.nan
    both = eligible_codes(spec, info2, frozenset(), CODES)[0]
    assert "000060" in both  # 두 시장 다 고르면 미상도 통과
    assert "000060" not in eligible_codes(only_kosdaq, info2, frozenset(), CODES)[0]
    # 종목 직접 지정은 제외 규칙보다 우선
    explicit = Spec.model_validate(spec_dict(universe={"type": "codes", "codes": ["005930"]}))
    assert eligible_codes(explicit, info, frozenset({"005930"}), CODES)[0] == ["005930"]


def test_top_value_universe_limits_entries():
    md = FakeMarketData()
    d = spec_dict(universe={"type": "top_value", "n": 2, "lookback_days": 1, "exclude": []})
    rec = run_backtest(Spec.model_validate(d), md)
    rank = md.panel.value.rank(axis=1, ascending=False, method="min")
    # 진입 체결 봉의 전 봉에서 그 종목이 거래대금 2위 안이어야 한다
    idx = list(md.panel.close.index)
    assert len(rec.trades)
    for _, t in rec.trades.iterrows():
        assert rank.loc[idx[idx.index(t["entry_ts"]) - 1], t["code"]] <= 2
    assert any("거래대금은 KRX" in w for w in rec.warnings)


def test_service_canary_tampering_tail_keeps_early_trades():
    """기간 끝쪽 데이터를 ×10 으로 망가뜨려도 그 시점 이전에 끝난 거래·평가금은 그대로."""
    base_md = FakeMarketData()
    spec = Spec.model_validate(spec_dict(universe={"type": "top_value", "n": 4, "exclude": []}))
    base = run_backtest(spec, base_md)
    idx = base_md.panel.close.index
    T = idx[(idx <= "2023-05-01")][-1]
    p = base_md.panel
    f = lambda df: df.where(pd.DataFrame(np.broadcast_to((df.index <= T)[:, None], df.shape),  # noqa: E731
                                          index=df.index, columns=df.columns), df * 10)
    bad_md = FakeMarketData(Panel(*(f(getattr(p, k)) for k in
                                    ("open", "high", "low", "close", "volume", "value", "prev_close"))))
    bad = run_backtest(spec, bad_md)
    early = lambda r: r.trades[r.trades["exit_ts"] <= T].reset_index(drop=True)  # noqa: E731
    pd.testing.assert_frame_equal(early(base), early(bad))
    assert len(early(base)) > 0
    assert not base.equity.equals(bad.equity)  # 변조가 뒤쪽 결과는 실제로 바꿨다 — 카나리아가 둔감하지 않다
    pd.testing.assert_frame_equal(base.equity[base.equity.ts <= T].reset_index(drop=True),
                                  bad.equity[bad.equity.ts <= T].reset_index(drop=True)[base.equity.columns])


def test_errors_and_mode_rejection():
    md = FakeMarketData()
    # 분봉 모드는 이제 지원한다(module-6) — 분봉 데이터 범위 정보가 없는 시장 데이터면 조용히 돌지 않고 오류
    with pytest.raises(BacktestError, match="범위 정보가 없음"):
        run_backtest(Spec.model_validate(spec_dict(
            mode="intraday", intraday={"bar_minutes": 5})), md)
    out = spec_dict(period={"start": "2030-01-02", "end": "2030-06-30"})
    with pytest.raises(BacktestError, match="겹치지 않음"):
        run_backtest(Spec.model_validate(out), md)
    partial = run_backtest(Spec.model_validate(spec_dict(period={"start": "2021-01-04", "end": "2022-06-30"})), md)
    assert any("그 이전" in w for w in partial.warnings)


def test_params_and_hashes():
    d = spec_dict()
    d["strategy"]["entry"]["items"][0]["right"]["params"]["n"] = {"param": "n_high"}
    d["params"] = {"n_high": {"default": 20, "min": 5, "max": 60, "step": 5}}
    spec = Spec.model_validate(d)
    a, b = bind_params(spec, {"n_high": 20}), bind_params(spec, {"n_high": 40})
    assert spec_hash(a) != spec_hash(b)
    assert structure_hash(spec) == structure_hash(spec.model_copy(update={"name": "다른 이름"}))
    r20 = run_backtest(spec, FakeMarketData())
    r40 = run_backtest(spec, FakeMarketData(), overrides={"n_high": 40})
    assert r20.meta["params"] == {"n_high": 20} and r40.meta["params"] == {"n_high": 40}
    assert r20.meta["structure_hash"] == r40.meta["structure_hash"] and r20.meta["spec_hash"] != r40.meta["spec_hash"]


def test_engine_rules_mapping_one_to_one():
    d = spec_dict(exits={"stop_loss_pct": 7, "take_profit_pct": 20, "trailing_stop_pct": 10, "max_holding_bars": 20},
                  portfolio={"max_positions": 4, "sizing": "risk_pct", "risk_pct": 1, "max_weight_pct": 30,
                             "rank_by": "change_pct", "initial_capital": 5_000_000, "random_seed": 7},
                  costs={"slippage_mode": "ticks", "slippage_ticks": 2}, fills={"same_bar_policy": "target_first",
                                                                                "volume_cap_pct": 5})
    cost, ex, fl, po = to_engine_rules(Spec.model_validate(d))
    assert (cost.slippage_mode, cost.slippage_ticks, cost.commission_rate) == ("ticks", 2.0, 0.00015)
    assert (ex.stop_loss_pct, ex.take_profit_pct, ex.trailing_stop_pct, ex.max_holding_bars) == (7, 20, 10, 20)
    assert (fl.same_bar_policy, fl.volume_cap_pct) == ("target_first", 5)
    assert (po.max_positions, po.sizing, po.risk_pct, po.max_weight_pct, po.rank_by, po.initial_capital,
            po.random_seed) == (4, "risk_pct", 1, 30, "change_pct", 5_000_000, 7)
    rec = run_backtest(Spec.model_validate(d), FakeMarketData())  # 전부 켠 채로 끝까지 돈다
    assert len(rec.trades) > 0


def test_run_store_roundtrip(tmp_path):
    rec = run_backtest(Spec.model_validate(spec_dict()), FakeMarketData())
    store = FileRunStore(tmp_path)
    rid = store.save(rec)
    assert store.list_ids() == [rid] and rec.run_id == rid
    back = store.load(rid)
    assert back.spec == rec.spec and back.summary == rec.summary
    pd.testing.assert_frame_equal(back.trades, rec.trades)
    pd.testing.assert_frame_equal(back.equity, rec.equity)
    assert back.meta["engine_version"] == "0.1.0" and back.meta["run_id"] == rid
    assert {"commit", "dirty"} <= set(back.meta["git"])
    assert back.warnings == rec.warnings
    for name in ("spec.json", "meta.json", "summary.json", "trades.parquet", "equity.parquet"):
        assert (tmp_path / rid / name).exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")]  # 임시 폴더 안 남음
    with pytest.raises(ValueError):
        store.load("../etc")
    with pytest.raises(FileExistsError):
        store.save(rec, run_id=rid)
