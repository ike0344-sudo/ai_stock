import json
import math

from backtesting.orderbook_parser import ASSUMED_SCHEMA, parse_orderbook_jsonl


def test_parse_orderbook_jsonl_maps_confirmed_fields_and_nulls_unconfirmed(tmp_path):
    path = tmp_path / "20260830" / "005930.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({
            "stock_code": "005930",
            "received_at": "2026-08-30T09:05:00",
            "buy_fpr_bid": "-70100",  # 부호는 등락방향, 실제 가격은 절대값
            "sel_fpr_bid": "70200",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    df = parse_orderbook_jsonl(str(tmp_path / "*" / "*.jsonl"))

    assert list(df.columns) == ASSUMED_SCHEMA
    row = df.iloc[0]
    assert row["code"] == "005930"
    assert row["date_str"] == "2026-08-30"
    assert row["bid1_price"] == 70100.0
    assert row["ask1_price"] == 70200.0
    assert math.isnan(row["bid2_price"])
    assert math.isnan(row["rank"])
