"""KRX 공매도 순보유잔고 수집 (로그인 불필요).

네이버 금융 '공매도현황' 탭이 임베드하는 KRX 외부공개 로더(srtLoader)를 경유하면
dbms/MDC_OUT/STAT/srt/*_OUT 네임스페이스가 익명으로 열린다. 로그인이 필요한
dbms/MDC/STAT/srt/* 와 같은 데이터다.

    python krx_short_balance.py 000660 [시작연도]
"""
import sys, requests, pandas as pd

URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
LOADER = "https://data.krx.co.kr/comm/srt/srtLoader/index.cmd?screenId=MDCSTAT300"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Referer": LOADER, "X-Requested-With": "XMLHttpRequest"}


def _isu(session, code):
    r = session.post(URL, headers=HDR, data={"bld": "dbms/comm/finder/finder_srtisu",
                                             "locale": "ko_KR", "mktsel": "ALL", "searchText": code})
    for row in r.json().get("block1", []):
        if row.get("short_code") == code:
            return row["full_code"]
    raise SystemExit(f"종목코드 {code} 를 찾지 못했습니다")


def fetch_balance(code: str, start_year: int = 2025) -> pd.DataFrame:
    """일별 공매도 순보유잔고. 조회기간 1년 초과 시 INVALIDPERIOD2라 연 단위로 쪼갠다."""
    s = requests.Session()
    s.headers.update({"User-Agent": HDR["User-Agent"]})
    s.get(LOADER, timeout=15)
    isu = _isu(s, code)
    end_year = pd.Timestamp.today().year
    rows = []
    failed_years = []  # 3회 다 실패한 연도 — 반환값에 실려야 호출자가 "그 해가 빠졌다"를 알 수 있다.
    for y in range(start_year, end_year + 1):
        body = {"bld": "dbms/MDC_OUT/STAT/srt/MDCSTAT30502_OUT", "locale": "ko_KR", "searchType": "2",
                "mktTpCd": "1", "isuCd": isu, "isuCd2": isu, "trdDd": f"{y}1231",
                "strtDd": f"{y}0101", "endDd": f"{y}1231", "share": "1", "money": "1", "csvxls_isNo": "false"}
        for attempt in range(3):          # KRX가 간헐적으로 응답을 늦게 준다
            try:
                r = s.post(URL, headers=HDR, data=body, timeout=40)
                rows += r.json().get("OutBlock_1", [])
                break
            except (requests.RequestException, ValueError) as e:
                if attempt == 2:
                    print(f"[!] {y}년 수집 실패: {type(e).__name__}")
                    failed_years.append(y)
    if not rows:
        raise SystemExit("데이터 없음")
    df = pd.DataFrame(rows)
    num = lambda s_: pd.to_numeric(s_.str.replace(",", "", regex=False), errors="coerce")
    out = pd.DataFrame({"dt": df.RPT_DUTY_OCCR_DD.str.replace("/", "", regex=False),
                        "bal_qty": num(df.BAL_QTY), "bal_amt": num(df.BAL_AMT),
                        "list_shrs": num(df.LIST_SHRS), "bal_rto": pd.to_numeric(df.BAL_RTO, errors="coerce")})
    out = out.drop_duplicates("dt").sort_values("dt").reset_index(drop=True)
    # pandas .attrs는 merge/sort_values/reset_index를 거치면 사라지므로 마지막
    # 객체에 붙인다 — 호출자(short_check.py 등)가 "일부 연도가 통째로 빠졌다"를
    # 반환값만 보고 알 수 있게 한다(그전엔 print뿐이라 파이프/백그라운드 실행 시 안 보였다).
    out.attrs["failed_years"] = failed_years
    return out


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "000660"
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
    df = fetch_balance(code, year)
    path = f".cache/shorts/{code}_balance.csv"
    df.to_csv(path, index=False)
    print(f"{path}: {len(df)}행 {df.dt.iloc[0]}~{df.dt.iloc[-1]}")
    if df.attrs.get("failed_years"):
        print(f"[!] 수집 실패한 연도(결측): {df.attrs['failed_years']}")
    d = df.tail(10).copy()
    d["증감"] = d.bal_qty.diff()
    print(d[["dt", "bal_qty", "bal_rto", "증감"]].to_string(index=False, formatters={
        "bal_qty": "{:,.0f}".format, "증감": lambda v: f"{v:+,.0f}" if pd.notna(v) else "-"}))
