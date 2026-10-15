"""ka10059 응답 → 저장 행 변환 (부호·배율·기간·오늘 줄 제외)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("cid", Path(__file__).resolve().parents[1] / "scripts" / "collect_investor_daily.py")


def test_to_frame():
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    row = lambda dt, px: {"dt": dt, "cur_prc": px, "flu_rt": "-1362", "acc_trde_qty": "979842", "acc_trde_prica": "121637",
                          "ind_invsr": "+6048", "frgnr_invsr": "8698", "orgn": "-14519", "etc_corp": "-279", "natfor": "52"}
    df = m.to_frame([row("20261015", "-1"), row("20261014", "-121800"), row("20190531", "+5"), row("20261014", "1")], "20261015")
    assert df["date"].tolist() == ["20261014"]                    # 오늘(잠정)·2019-06 전·중복 날짜 제거
    r = df.iloc[0]
    assert r.close == 121800 and r.chg_pct == -13.62 and r.ind == 6048 and r.orgn == -14519 and r.value_mw == 121637
    assert r.isna()["samo"]                                       # 응답에 없는 칸은 빈 값(0 으로 꾸미지 않는다)
