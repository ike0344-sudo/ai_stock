"""틱 CSV(8컬럼, ka10079 원본)를 4컬럼(time, cur_prc, trde_qty, ref_price)으로 압축·복원.

사용자가 "5개 버릴 수 있다"고 짐작한 것 중 3개(open/high/low)만 진짜 항상
cur_prc와 같았다(전수 검증함, 175개 파일 0건 위반). pred_pre/pred_pre_sig는
파일마다 안 바뀔 거라는 짐작이 틀렸다(175개 중 132개가 파일 내에서 값이
바뀜 — 하루 중 전일종가를 여러 번 넘나드는 종목이 대부분이라 당연함).

대신 부호를 제대로 살려서(pred_pre_sig: 2=+,3=0,5=-) `cur_prc - signed_pred_pre`를
계산하면 파일 전체에서 상수였다(175개 전부, 0건 위반) — 이게 그 틱이 비교하는
기준가(실측: 로컬 일봉의 직전 거래일 종가와 정확히 일치, 009150 2026-08-03에서
확인함). 그래서 pred_pre/pred_pre_sig 둘 다 버리고 그 자리에 파일당 상수 ref_price
하나만 남긴다 — open/high/low(3개) 대신 pred_pre/pred_pre_sig(2개)까지 총 5개를
없애고 cntr_tm/cur_prc/trde_qty/ref_price 4개만 남는다.

cntr_tm의 앞 8자리(날짜)는 파일명(2026-08-03.csv)과 항상 같다(전수 확인) — 압축본엔
시각(HHMMSS)만 남기고 날짜는 파일명에서 복원한다.

복원 시 원본과 완전히 같은지(컬럼명·순서·값·타입) 별도로 round-trip 검증해야 한다
— 이 모듈은 압축/복원만 하고, 검증은 tick_compress_backfill.py가 한다.

2026-08-31 사고: SIGN_MAP에 상한가(1)/하한가(4)가 빠져 있어서 가격제한폭(±30%)에
걸린 종목·날짜가 전부 "알 수 없는 pred_pre_sig 값"으로 압축 스킵됐다(119850
2026-08-04 등). 원본 CSV는 안 지워지니 유실은 아니지만, parquet 코퍼스에서
통째로 빠져 그걸 읽는 쪽(DuckDB 등)에서 조용히 결측이 된다. 1(상한가)은 방향상
상승(2)과, 4(하한가)는 하락(5)과 같은 쪽으로 취급해 기준가 계산에 넣도록 고쳤다.
다만 기준가 계산에만 넣으면 압축본에서 "상한가였다"는 사실 자체가 사라져
복원값이 원본과 달라진다(1이 아니라 2로 복원됨) — 그래서 pred_pre_sig를 버리지
않고 파일당 상수가 아니라 **행마다** 그대로 남긴다(값이 5종류뿐이라 parquet
사전인코딩으로 거의 공짜로 압축됨). 기존에 이미 압축된 파일(3컬럼, pred_pre_sig
없음)과 컬럼 수가 달라지지만, 읽는 쪽이 이미 `union_by_name=true`로 스키마가
달라도 되게 짜여 있어(`tick_holdout_verification.py` 확인) 안전하다.
"""
from __future__ import annotations

import pandas as pd

# 1(상한가)·4(하한가)도 기준가 계산에서는 각각 상승(2)·하락(5)과 같은 방향이다.
SIGN_MAP = {1: 1, 2: 1, 3: 0, 4: -1, 5: -1}

RAW_COLUMNS = [
    "cur_prc", "trde_qty", "cntr_tm", "open_pric", "high_pric", "low_pric",
    "pred_pre", "pred_pre_sig",
]


def verify_losslessness(df: pd.DataFrame) -> str | None:
    """압축 가능 조건을 검사한다. 어긋나면 그 이유를 문자열로 반환(None이면 통과)."""
    if not ((df["open_pric"] == df["cur_prc"]).all()
            and (df["high_pric"] == df["cur_prc"]).all()
            and (df["low_pric"] == df["cur_prc"]).all()):
        return "open/high/low != cur_prc"
    if df["cntr_tm"].astype(str).str[:8].nunique() != 1:
        return "cntr_tm 날짜 접두 불일치"
    signed = df["pred_pre"] * df["pred_pre_sig"].map(SIGN_MAP)
    if signed.isna().any():
        return f"알 수 없는 pred_pre_sig 값: {sorted(df.loc[signed.isna(), 'pred_pre_sig'].unique())}"
    ref = df["cur_prc"] - signed
    if ref.nunique() != 1:
        return f"기준가(cur_prc-signed pred_pre)가 파일 내 상수 아님, 고유값 {ref.nunique()}개"
    return None


def compress(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """(압축된 df, ref_price)를 반환한다. 호출 전 verify_losslessness로 통과 확인 필수.

    pred_pre_sig는 파일당 상수가 아니라(값 자체가 상한가/하한가처럼 방향과 별개인
    "제한폭 도달" 정보를 담고 있어 파일당 하나로 못 줄인다) 행마다 그대로 남긴다 —
    값이 1~5 다섯 종류뿐이라 parquet 사전인코딩으로 사실상 공짜다."""
    signed = df["pred_pre"] * df["pred_pre_sig"].map(SIGN_MAP)
    ref_price = int((df["cur_prc"] - signed).iloc[0])
    out = pd.DataFrame({
        "time": df["cntr_tm"].astype(str).str[8:],  # HHMMSS만
        "cur_prc": df["cur_prc"].astype("int64"),
        "trde_qty": df["trde_qty"].astype("int64"),
        "pred_pre_sig": df["pred_pre_sig"].astype("int64"),
    })
    return out, ref_price


def decompress(compact: pd.DataFrame, date_str: str, ref_price: int) -> pd.DataFrame:
    """압축본 + 파일명의 날짜(YYYY-MM-DD) + ref_price로 원본 8컬럼을 그대로 복원한다.
    pred_pre_sig는 저장된 값을 그대로 쓴다(역산 안 함) — 상한가(1)/하한가(4)가
    상승(2)/하락(5)으로 잘못 복원되는 걸 막는다."""
    date_compact = date_str.replace("-", "")
    cntr_tm = date_compact + compact["time"].astype(str).str.zfill(6)
    signed = compact["cur_prc"] - ref_price
    pred_pre = signed.abs()
    out = pd.DataFrame({
        "cur_prc": compact["cur_prc"],
        "trde_qty": compact["trde_qty"],
        "cntr_tm": cntr_tm.astype("int64"),
        "open_pric": compact["cur_prc"],
        "high_pric": compact["cur_prc"],
        "low_pric": compact["cur_prc"],
        "pred_pre": pred_pre,
        "pred_pre_sig": compact["pred_pre_sig"],
    })
    return out


def _demo() -> None:
    """자가 점검: 압축 -> 복원이 원본과 완전히 같은지."""
    raw = pd.DataFrame({
        "cur_prc": [100, 105, 95, 100],
        "trde_qty": [10, 5, 3, 1],
        "cntr_tm": [20260803090000, 20260803090001, 20260803090002, 20260803090003],
        "open_pric": [100, 105, 95, 100],
        "high_pric": [100, 105, 95, 100],
        "low_pric": [100, 105, 95, 100],
        "pred_pre": [0, 5, 5, 0],
        "pred_pre_sig": [3, 2, 5, 3],
    })
    assert verify_losslessness(raw) is None
    compact, ref = compress(raw)
    assert ref == 100
    restored = decompress(compact, "2026-08-03", ref)
    for col in RAW_COLUMNS:
        assert (restored[col].astype(raw[col].dtype) == raw[col]).all(), f"{col} 불일치"

    # 손실 조건도 검사되는지
    bad = raw.copy()
    bad.loc[0, "high_pric"] = 999
    assert verify_losslessness(bad) is not None

    # 2026-08-31 회귀: 상한가(1)/하한가(4)도 스킵 없이 정확히 복원되는지
    limit = pd.DataFrame({
        "cur_prc": [130, 130, 70, 100],
        "trde_qty": [10, 5, 3, 1],
        "cntr_tm": [20260804090000, 20260804090001, 20260804090002, 20260804090003],
        "open_pric": [130, 130, 70, 100],
        "high_pric": [130, 130, 70, 100],
        "low_pric": [130, 130, 70, 100],
        "pred_pre": [30, 30, 30, 0],
        "pred_pre_sig": [1, 1, 4, 3],  # 상한가, 상한가, 하한가, 보합
    })
    assert verify_losslessness(limit) is None, "상한가/하한가가 있으면 스킵되면 안 된다"
    compact_l, ref_l = compress(limit)
    assert ref_l == 100
    restored_l = decompress(compact_l, "2026-08-04", ref_l)
    for col in RAW_COLUMNS:
        assert (restored_l[col].astype(limit[col].dtype) == limit[col]).all(), f"상한가 회귀 {col} 불일치"
    assert list(restored_l["pred_pre_sig"]) == [1, 1, 4, 3], "상한가(1)가 상승(2)으로 뭉개지면 안 된다"

    print("OK: tick_compress 자가 점검 통과(상한가/하한가 회귀 포함)")


if __name__ == "__main__":
    _demo()
