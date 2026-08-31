"""삼성전기(009150) 1분봉 "통합"(KRX+NXT, 08:00~20:00) 차트를 받아 로컬 캐시로 저장한다.

sk_hynix_envelope_integrated.py의 fetch_combined_15min() 패턴을 그대로 재사용 — 다만
tic_scope="1"(1분봉)로 받는다. 기존 정규장 전용 캐시(data/stocks/minute/009150.csv)가
1분봉으로 저장돼 있고 backtesting/data_loader.py의 _resample_minute가 1분봉을 임의
분봉으로 리샘플할 수 있으므로, 통합 데이터도 1분봉으로 받아둬야 나중에 60분봉이든
15분봉이든 유연하게 다시 쓸 수 있다.

⚠️ 모의투자 계좌로 조회하면 KRX/NXT/SOR을 구분하지 않는 것으로 보인다(앞선 대화 및
sk_hynix_envelope_integrated.py에서 실측) — 08:00~09:00, 15:31~20:00 구간 가격이 실제
NXT 체결가가 아니라 모의서버가 만들어낸 값일 수 있다. 실전 계좌로 재확인 전까지는
참고용으로만 볼 것.

기존 data/stocks/minute/009150.csv(정규장/KRX 전용, 여러 실거래 전략·대시보드가 이
파일의 스키마를 신뢰함)는 절대 건드리지 않는다 — 새 경로
data/stocks/minute_combined/009150.csv에 별도 저장한다.

실행: python fetch_009150_combined_minute.py
"""
import os

import pandas as pd
from dotenv import load_dotenv

from backtesting.data_loader import FULL_HISTORY_MAX_PAGES, _atomic_to_csv
from fetch_chart import MINUTE_COLUMN_MAP, find_records, to_dataframe
from kiwoom_client import KiwoomClient

STOCK_CODE = "009150"
COMBINED_CODE = f"{STOCK_CODE}_AL"  # 통합(KRX+NXT) — screener.py/sk_hynix_envelope_integrated.py의 접미사 관례
# sk_hynix_envelope_integrated.py는 15분봉이라 MAX_PAGES=20으로도 전체 이력(2025-07-01)에
# 닿았지만, 1분봉은 하루당 봉 수가 ~13배 많아 같은 20페이지로는 최근 한 달치(cont-yn="Y"인
# 채로 페이지 상한에 먼저 도달)만 받힌다(실측). data_loader.py가 "전체 이력 받기"용으로
# 이미 쓰는 안전 상한을 그대로 재사용 — cont-yn이 먼저 끊기면 이 값 전에 자동으로 멈춘다.
MAX_PAGES = FULL_HISTORY_MAX_PAGES
OUTPUT_PATH = os.path.join("data", "stocks", "minute_combined", f"{STOCK_CODE}.csv")


def fetch_combined_1min(client: KiwoomClient) -> pd.DataFrame:
    """ka10080을 "_AL" 접미사로 호출해 08:00~20:00 통합 1분봉을 페이지네이션으로
    끝까지(가용 이력 한계까지) 받는다. sk_hynix_envelope_integrated.fetch_combined_15min과
    동일 패턴이고 tic_scope만 1분으로 바꿨다."""
    pages = client.get_minute_chart_pages(COMBINED_CODE, tic_scope="1", max_pages=MAX_PAGES)
    records = [r for page in pages for r in find_records(page)]
    df = to_dataframe(records, MINUTE_COLUMN_MAP, "%Y%m%d%H%M%S")
    return df[~df.index.duplicated(keep="last")].sort_index()


def main():
    load_dotenv()
    appkey = os.environ["KIWOOM_APPKEY"]
    secretkey = os.environ["KIWOOM_SECRETKEY"]
    is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"
    print(f"키움 {'모의투자' if is_mock else '실전투자'} 계좌로 {STOCK_CODE} 통합(KRX+NXT) 1분봉 조회 중...")
    if is_mock:
        print("경고: 모의투자 계좌 — NXT 시간대 가격이 실제 체결가가 아닐 수 있습니다(스크립트 상단 docstring 참고).")

    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    df = fetch_combined_1min(client)
    # get_minute_chart_pages 마지막 호출의 cont-yn을 그대로 들고 있음 — "Y"면 MAX_PAGES
    # 상한에 걸려 멈춘 것(더 받을 이력이 남음), "N"이면 API가 더 줄 데이터가 없어 자연히
    # 멈춘 것(진짜 가용 이력 한계).
    hit_page_cap = client.last_cont_yn == "Y"

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    _atomic_to_csv(df, OUTPUT_PATH)

    trading_days = df.index.normalize().unique()
    print(f"\n저장 완료: {OUTPUT_PATH}")
    print(f"기간: {trading_days.min().date()} ~ {trading_days.max().date()} (거래일 {len(trading_days)}일)")
    print(f"총 {len(df)}행, 하루 평균 {len(df) / len(trading_days):.1f}봉")
    if hit_page_cap:
        print(f"경고: MAX_PAGES({MAX_PAGES})에 도달해 멈췄습니다 — API에 더 과거 이력이 남아있을 수 있습니다(가용 이력 한계 아님).")
    else:
        print("cont-yn이 자연히 끊겨 멈췄습니다 — 위 시작일이 API가 주는 가용 이력의 실제 한계입니다.")


if __name__ == "__main__":
    main()
