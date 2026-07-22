"""거래대금 상위 종목 스크리너.

Kiwoom ka10032(거래대금상위요청)로 코스피+코스닥 통합 거래대금 순위를 조회한다.
stock-auto-trading의 자동 종목 선정에서도 재사용 가능하도록 일반적으로 설계.
"""
import pandas as pd

from kiwoom_client import KiwoomClient

RANKING_PATH = "/api/dostk/rkinfo"

# 한국 ETF/ETN은 규제상 운용사 브랜드가 종목명 앞에 붙는 관행이 있어, 정확한 상품유형
# 조회 API 대신 이름 접두어 휴리스틱으로 개별 종목과 구분한다 (완벽하지 않을 수 있음 —
# 새 브랜드가 생기면 걸러지지 않을 수 있음).
ETF_ETN_NAME_PREFIXES = (
    "KODEX", "TIGER", "KBSTAR", "SOL", "ACE", "RISE", "KINDEX", "HANARO",
    "ARIRANG", "TIMEFOLIO", "WOORI", "KOSEF", "SMART", "PLUS", "FOCUS",
    "MASTER", "HK", "KIWOOM", "K-", "UNICORN", "히어로즈",
    "마이다스", "파워", "신한", "마이티", "코세프",
)

# 스팩(기업인수목적회사)은 브랜드 접두어 관행이 없어 이름에 그대로 "스팩" 또는 정식
# 명칭 "기업인수목적"이 들어간다 — 이것도 같은 이름 휴리스틱으로 걸러낸다.
SPAC_NAME_MARKERS = ("스팩", "기업인수목적")

# ka10032 응답의 trde_prica(거래대금)는 백만원 단위로 내려온다 (universe.py의
# TRADE_VALUE_UNIT_TO_EOK=100 확산 계산과 동일 컨벤션). 원 단위로 환산해서 저장한다 —
# 그렇지 않으면 프론트엔드가 그대로 "원"으로 표시할 때 실제 거래대금보다 100만분의
# 1로 작게 보인다.
TRADE_VALUE_UNIT_WON = 1_000_000

# stex_tp(거래소구분): 1=KRX, 2=NXT, 3=통합(KRX+NXT). 넥스트레이드(NXT) 출범 이후
# KRX 단독(1)으로는 실제 총거래대금보다 낮게 집계된다(실측: SK하이닉스 KRX 단독
# 5.15조 vs 통합 8.94조) — 반드시 3(통합)을 써야 한다.
STEX_TP_COMBINED = "3"


def _is_excluded_instrument(name: str) -> bool:
    """ETF/ETN/스팩처럼 개별 상장기업이 아닌 상품·명목회사를 이름 휴리스틱으로 판별."""
    upper = name.upper()
    if "ETN" in upper:
        return True
    if any(marker in name for marker in SPAC_NAME_MARKERS):
        return True
    return any(upper.startswith(prefix.upper()) for prefix in ETF_ETN_NAME_PREFIXES)


def top_by_trading_value(
    client: KiwoomClient,
    top_n: int = 35,
    market: str = "000",
    exclude_managed: bool = True,
    exclude_etf: bool = True,
    max_pages: int = 5,
) -> pd.DataFrame:
    """거래대금 상위 종목을 top_n개 반환.

    market: "000"=코스피+코스닥 통합, "001"=코스피, "101"=코스닥.
    ETF/ETN/스팩·관리종목을 걸러내며 페이지를 이어받아(cont-yn/next-key) top_n개를 채운다.
    """
    body = {
        "mrkt_tp": market,
        "mang_stk_incls": "0" if exclude_managed else "1",
        "stex_tp": STEX_TP_COMBINED,
    }

    rows = []
    cont_yn, next_key = "N", ""
    for _ in range(max_pages):
        payload = client.request_tr("ka10032", body, path=RANKING_PATH, cont_yn=cont_yn, next_key=next_key)
        for item in payload.get("trde_prica_upper", []):
            name = item["stk_nm"]
            if exclude_etf and _is_excluded_instrument(name):
                continue
            # stex_tp=3(통합) 응답은 종목코드에 "_AL" 접미사가 붙는다(예: "000660_AL")
            # — 다운스트림(캔들 조회/주문/워치리스트 매칭)은 순수 6자리 코드를 기대하므로
            # 여기서 한 번에 제거한다.
            stock_code = item["stk_cd"].split("_")[0]
            rows.append(
                {
                    "stock_code": stock_code,
                    "name": name,
                    "rank": int(item["now_rank"]),
                    "trading_value": int(item["trde_prica"]) * TRADE_VALUE_UNIT_WON,
                    "change_rate": float(item["flu_rt"]),
                }
            )
        if len(rows) >= top_n or client.last_cont_yn != "Y" or not client.last_next_key:
            break
        cont_yn, next_key = "Y", client.last_next_key

    return pd.DataFrame(rows[:top_n])
