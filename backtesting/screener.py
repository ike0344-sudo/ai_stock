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


def _is_excluded_instrument(name: str, exclude_spac: bool = True) -> bool:
    """ETF/ETN/스팩처럼 개별 상장기업이 아닌 상품·명목회사를 이름 휴리스틱으로 판별.

    브랜드 접두어는 **뒤에 공백이 와야** 인정한다. ETF·ETN은 "KODEX 레버리지",
    "신한 레버리지 WTI원유 ETN"처럼 운용사와 상품명 사이가 띄어져 있고, 개별 종목은
    붙여 쓴다. 이 구분이 없으면 신한지주·HK이노엔·파워로직스·파워넷이 거래대금
    순위에서 통째로 빠진다(실측) — "신한", "HK", "파워"가 위 목록에 있기 때문이다.
    kospi-theme-engine/app/ingest/rest.py 의 is_fund_like 와 같은 규칙이다.
    """
    upper = name.upper()
    if "ETN" in upper:
        return True
    if exclude_spac and any(marker in name for marker in SPAC_NAME_MARKERS):
        return True
    for prefix in ETF_ETN_NAME_PREFIXES:
        p = prefix.upper()
        if not upper.startswith(p):
            continue
        rest = upper[len(p):]
        # "K-" 처럼 구분자를 품은 접두어는 그 자체가 경계다.
        if p.endswith("-") or not rest or rest[0] == " ":
            return True
    return False


def top_by_trading_value(
    client: KiwoomClient,
    top_n: int = 35,
    market: str = "000",
    exclude_managed: bool = True,
    exclude_etf: bool = True,
    max_pages: int = 5,
    exclude_spac: bool = True,
) -> pd.DataFrame:
    """거래대금 상위 종목을 top_n개 반환.

    market: "000"=코스피+코스닥 통합, "001"=코스피, "101"=코스닥.
    ETF/ETN/스팩·관리종목을 걸러내며 페이지를 이어받아(cont-yn/next-key) top_n개를 채운다.
    exclude_spac=False면 스팩은 남긴다 — 스팩 급등도 "돈이 들어오는" 사건이라 순위에서
    보고 싶을 때가 있다. 그 경우 **베이스라인도 같은 설정으로 받아야** 스팩만 장전
    물량이 안 빠져 정규장 순위가 위로 뜨는 일이 없다.

    키움 [0184](당일거래량상위) 화면과 비슷한 정보를 보여주기 위해, ka10032 응답에
    이미 들어있는 필드들을 추가로 파싱해 반환한다 — current_price(현재가), change_amount
    (대비, 부호 있는 증감액), volume(거래량), prev_day_volume(전일 거래량),
    volume_vs_prev_day_pct(전일비 %, 전일 거래량이 0이면 None).
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
        # HTTP 200이어도 API 자체 오류는 return_code!=0으로 응답에 실려 온다(kiwoom_client.py의
        # place_order 등과 동일한 관례) — 이 체크 없이 진행하면 trde_prica_upper가 없어
        # rows=[]가 되고, 호출부에서 결과 DataFrame의 "stock_code" 컬럼이 없다는 KeyError만
        # 보여서 진짜 원인(토큰 만료/레이트리밋 등)이 로그에 안 남는다(실측: 워치리스트
        # 갱신 실패가 'stock_code' KeyError로만 반복 기록돼 원인 추적이 안 됐던 문제).
        if payload.get("return_code") != 0:
            raise RuntimeError(f"ka10032 응답 오류 - return_code={payload.get('return_code')} {payload.get('return_msg', '')}".strip())
        for item in payload.get("trde_prica_upper", []):
            name = item["stk_nm"]
            if exclude_etf and _is_excluded_instrument(name, exclude_spac):
                continue
            # stex_tp=3(통합) 응답은 종목코드에 "_AL" 접미사가 붙는다(예: "000660_AL")
            # — 다운스트림(캔들 조회/주문/워치리스트 매칭)은 순수 6자리 코드를 기대하므로
            # 여기서 한 번에 제거한다.
            stock_code = item["stk_cd"].split("_")[0]
            volume = int(item["now_trde_qty"])
            prev_volume = int(item["pred_trde_qty"])
            rows.append(
                {
                    "stock_code": stock_code,
                    "name": name,
                    "rank": int(item["now_rank"]),
                    "trading_value": int(item["trde_prica"]) * TRADE_VALUE_UNIT_WON,
                    "change_rate": float(item["flu_rt"]),
                    # cur_prc/sel_bid/buy_bid 등 호가·현재가류 필드는 부호가 실제 가격의
                    # 부호가 아니라 전일종가 대비 방향 표시일 뿐이다(kiwoom_client.py의
                    # place_order 문서화와 동일한 키움 API 관례) — 그대로 float()하면
                    # 하락 종목 가격이 음수로 잘못 파싱된다. 반면 pred_pre(대비)는 그
                    # 자체가 부호 있는 증감액이라 그대로 float()해야 방향이 살아있다.
                    "current_price": abs(float(item["cur_prc"])),
                    "change_amount": float(item["pred_pre"]),
                    "volume": volume,
                    "prev_day_volume": prev_volume,
                    "volume_vs_prev_day_pct": (volume / prev_volume * 100) if prev_volume else None,
                }
            )
        if len(rows) >= top_n or client.last_cont_yn != "Y" or not client.last_next_key:
            break
        cont_yn, next_key = "Y", client.last_next_key

    return pd.DataFrame(rows[:top_n])
