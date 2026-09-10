"""SK하이닉스·삼성전자 공매도/수급 점검. 실행할 때마다 캐시를 갱신하고 두 표를 찍는다.

    python short_check.py            # 000660, 005930
    python short_check.py 000660     # 한 종목만
    python short_check.py --demo     # 자체 점검

데이터: 키움 ka10014(공매도추이) / ka20068(대차) / ka10059(투자자별)
        KRX MDCSTAT30502_OUT(순보유잔고) — krx_short_balance.py, 로그인 불필요
"""
import os, sys, pandas as pd
from dotenv import load_dotenv
from kiwoom_client import KiwoomClient
from krx_short_balance import fetch_balance

CODES = ["000660", "005930"]
NAMES = {"000660": "SK하이닉스", "005930": "삼성전자"}
CACHE = ".cache/shorts"
NUM = lambda s: pd.to_numeric(s.astype(str).str.replace("+", "", regex=False), errors="coerce")


def balance(d: pd.DataFrame) -> pd.DataFrame:
    """매도압력 = 그날 최대 순매도 주체 규모, 흡수율 = 기타법인(자사주 프록시) / 매도압력."""
    d = d.copy()
    inv = ["개인", "외국인", "기관"]
    ok = d[inv].notna().any(axis=1)          # 투자자별은 100일치뿐이라 과거 구간은 전부 NaN
    d["매도압력"] = pd.NA
    d["최대매도주체"] = pd.NA
    d.loc[ok, "매도압력"] = d.loc[ok, inv].min(axis=1).abs()
    d.loc[ok, "최대매도주체"] = d.loc[ok, inv].idxmin(axis=1)
    d["매도압력"] = pd.to_numeric(d.매도압력)
    # ponytail: 매도압력이 작은 날은 흡수율이 폭주하므로 20만주 미만은 미표시.
    d["흡수율"] = (d.기타법인 / d.매도압력.where(d.매도압력 >= 200_000) * 100).round(0)
    d["공매도비중"] = (d.공매도량 / d.거래량 * 100).round(2)
    return d


def _refresh(client, api, path, key, body, out):
    """페이지를 따라가며 받아 기존 캐시에 합친다."""
    rows, cont, nk = [], "N", ""
    for _ in range(20):
        r = client.request_tr(api, body, path=path, cont_yn=cont, next_key=nk)
        rows += r.get(key, [])
        if client.last_cont_yn != "Y":
            break
        cont, nk = "Y", client.last_next_key
    new = pd.DataFrame(rows)
    if os.path.exists(out):
        new = pd.concat([pd.read_csv(out, dtype=str), new.astype(str)])
    new = new.drop_duplicates("dt").sort_values("dt")
    new.to_csv(out, index=False)
    return new


def collect(client, code, today):
    sh = _refresh(client, "ka10014", "/api/dostk/shsa", "shrts_trnsn",
                  {"stk_cd": code, "tm_tp": "1", "strt_dt": "20240101", "end_dt": today},
                  f"{CACHE}/{code}.csv")
    sl = _refresh(client, "ka20068", "/api/dostk/slb", "dbrt_trde_trnsn",
                  {"strt_dt": "20240101", "end_dt": today, "all_tp": "0", "stk_cd": code},
                  f"{CACHE}/{code}_slb.csv")
    inv = pd.DataFrame(client.request_tr("ka10059", {"dt": today, "stk_cd": code, "amt_qty_tp": "1",
                                                     "trde_tp": "0", "unit_tp": "1"},
                                         path="/api/dostk/stkinfo").get("stk_invsr_orgn", []))
    d = pd.DataFrame({"dt": sh.dt, "종가": NUM(sh.close_pric).abs(), "거래량": NUM(sh.trde_qty),
                      "공매도량": NUM(sh.shrts_qty), "비중%": NUM(sh.trde_wght)})
    d = d.merge(pd.DataFrame({"dt": sl.dt, "대차상환": NUM(sl.dbrt_trde_rpy),
                              "대차잔고": NUM(sl.rmnd)}), on="dt", how="left")
    d = d.merge(pd.DataFrame({"dt": inv.dt, "개인": NUM(inv.ind_invsr), "외국인": NUM(inv.frgnr_invsr),
                              "기관": NUM(inv.orgn), "기타법인": NUM(inv.etc_corp)}), on="dt", how="left")

    bal = f"{CACHE}/{code}_balance.csv"
    balance_note = None  # "데이터 없음"과 "수집이 깨져서 없음"을 구분해 산출물(attrs)에 남긴다.
    try:
        fetched = fetch_balance(code, 2025)
        fetched.to_csv(bal, index=False)
        if fetched.attrs.get("failed_years"):
            balance_note = f"KRX 순보유잔고 {fetched.attrs['failed_years']}년 수집 실패 — 해당 연도 결측"
            print(f"[!] {balance_note}")
    except Exception as e:
        if os.path.exists(bal):
            stale_last = pd.read_csv(bal, dtype={"dt": str}).dt.max()
            balance_note = f"KRX 순보유잔고 갱신 실패({type(e).__name__}) — 캐시 사용 중, 최신 {stale_last}까지(오늘 {today})"
        else:
            balance_note = f"KRX 순보유잔고 갱신 실패({type(e).__name__}) — 캐시도 없어 전체 결측"
        print(f"[!] {balance_note}")
    if os.path.exists(bal):
        b = pd.read_csv(bal, dtype={"dt": str})
        b["순보유잔고"] = b.bal_qty
        b["잔고증감"] = b.bal_qty.diff()
        d = d.merge(b[["dt", "순보유잔고", "잔고증감"]], on="dt", how="left")
    result = d.sort_values("dt").reset_index(drop=True)
    # pandas .attrs는 merge/sort_values를 거치면 사라지므로 마지막 객체에 붙인다 —
    # show()가 이 사실을 표에 붙여 출력한다(콘솔 스크롤로 위 print를 놓쳐도 보이게).
    if balance_note:
        result.attrs["순보유잔고_note"] = balance_note
    return result


def show(code, d, days=10):
    print(f"\n{'='*96}\n{NAMES.get(code, code)}({code})\n{'='*96}")
    if d.attrs.get("순보유잔고_note"):
        print(f"[!] {d.attrs['순보유잔고_note']}")
    t = d.tail(days)
    money = lambda v: f"{v:,.0f}" if pd.notna(v) else "-"
    signed = lambda v: f"{v:+,.0f}" if pd.notna(v) else "-"
    pct = lambda v: f"{v:.2f}" if pd.notna(v) else "-"

    c1 = [c for c in ["dt", "종가", "공매도량", "비중%", "대차상환", "대차잔고", "순보유잔고", "잔고증감"] if c in t]
    print("[공매도]")
    print(t[c1].to_string(index=False, formatters={**{c: money for c in c1 if c != "dt"},
                                                   "비중%": pct, "잔고증감": signed}))
    c2 = [c for c in ["dt", "거래량", "개인", "외국인", "기관", "기타법인", "매도압력", "흡수율"] if c in t]
    print("\n[수급]")
    print(t[c2].to_string(index=False, formatters={**{c: money for c in c2 if c != "dt"},
                          **{c: signed for c in ["개인", "외국인", "기관", "기타법인"] if c in c2},
                          "흡수율": lambda v: f"{v:.0f}" if pd.notna(v) else "-"}))

    s = d.dropna(subset=["순보유잔고"]) if "순보유잔고" in d else pd.DataFrame()
    if len(s) > 5:
        print(f"\n순보유잔고 {s.dt.iloc[-1]}: {s.순보유잔고.iloc[-1]:,.0f}주 "
              f"(전일 {s.잔고증감.iloc[-1]:+,.0f}, 5일 {s.순보유잔고.iloc[-1]-s.순보유잔고.iloc[-6]:+,.0f}) "
              f"| 대차잔고 대비 {s.순보유잔고.iloc[-1]/d.대차잔고.dropna().iloc[-1]*100:.1f}%")
    print(f"공매도 {days}일 평균 {t.공매도량.mean():,.0f}주(비중 {t['비중%'].mean():.2f}%) "
          f"| 매도압력 평균 {t.매도압력.mean():,.0f}주 | 기타법인 흡수 {t.기타법인.mean():,.0f}주")
    print("매도 주도: " + ", ".join(f"{k} {v}일" for k, v in t.최대매도주체.value_counts().items()))


def main():
    codes = [a for a in sys.argv[1:] if a.isdigit()] or CODES
    load_dotenv(".env")
    client = KiwoomClient(os.environ["KIWOOM_APPKEY"], os.environ["KIWOOM_SECRETKEY"],
                          is_mock=os.environ.get("KIWOOM_IS_MOCK", "false").lower() == "true")
    os.makedirs(CACHE, exist_ok=True)
    today = pd.Timestamp.today().strftime("%Y%m%d")
    for code in codes:
        show(code, balance(collect(client, code, today)))


def demo():
    nan = float("nan")
    d = pd.DataFrame({"개인": [-1_000_000, 500_000, -100_000, nan], "외국인": [300_000, -2_000_000, 50_000, nan],
                      "기관": [100_000, 500_000, 50_000, nan], "기타법인": [600_000, 1_000_000, -90_000, nan],
                      "공매도량": [200_000, 300_000, 10_000, 50_000], "거래량": [5_000_000, 6_000_000, 1_000_000, 2_000_000]})
    r = balance(d)   # 마지막 행: 투자자별 없는 과거 구간
    assert list(r.매도압력)[:3] == [1_000_000, 2_000_000, 100_000], r.매도압력.tolist()
    assert pd.isna(r.매도압력.iloc[3]), "투자자별 없는 행은 매도압력 NaN"
    assert list(r.최대매도주체)[:3] == ["개인", "외국인", "개인"], r.최대매도주체.tolist()
    assert list(r.흡수율)[:2] == [60.0, 50.0], r.흡수율.tolist()
    assert pd.isna(r.흡수율.iloc[2]), "매도압력 20만주 미만이면 흡수율 미표시"
    assert list(r.공매도비중) == [4.0, 5.0, 1.0, 2.5], r.공매도비중.tolist()
    print("demo ok")


if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main()
