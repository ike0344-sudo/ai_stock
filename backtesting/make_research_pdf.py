"""체결데이터 급등주 연구 요약 PDF 생성 (2026-09-20~21, 11건).

state/agent_reports/의 개별 리포트를 사람이 한 번에 읽을 수 있게 한 장으로 묶는다.
내용은 각 리포트의 확정 수치를 그대로 옮긴 것이고, 새로 계산하지 않는다
(재계산하면 리포트와 어긋날 수 있으므로 의도적으로 하드코딩 — 수치의 출처는 각 절에 명시).

실행: python -m backtesting.make_research_pdf
출력: results/체결데이터_급등주연구_요약.pdf
"""
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                 Spacer, Table, TableStyle)

FONT_DIR = r"C:\Windows\Fonts"
OUT = "results/체결데이터_급등주연구_요약.pdf"


def _register_fonts() -> tuple[str, str]:
    """맑은 고딕 등록. 없으면 굴림으로 대체(한글이 깨지면 표가 무의미해지므로 폰트는 필수)."""
    for base, bold, name in (("malgun.ttf", "malgunbd.ttf", "Malgun"),
                              ("gulim.ttc", "gulim.ttc", "Gulim")):
        p1, p2 = os.path.join(FONT_DIR, base), os.path.join(FONT_DIR, bold)
        if os.path.exists(p1):
            pdfmetrics.registerFont(TTFont(name, p1))
            pdfmetrics.registerFont(TTFont(name + "B", p2 if os.path.exists(p2) else p1))
            return name, name + "B"
    raise RuntimeError("한글 폰트를 찾지 못했다 — 폰트 없이 만들면 표가 전부 깨진다")


F, FB = _register_fonts()
ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName=FB, fontSize=15, spaceAfter=6, textColor=colors.HexColor("#1a3a5c"))
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName=FB, fontSize=11.5, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#2a5a8c"))
BODY = ParagraphStyle("B", parent=ss["BodyText"], fontName=F, fontSize=9, leading=13.5, spaceAfter=3)
SMALL = ParagraphStyle("S", parent=BODY, fontSize=7.8, leading=11, textColor=colors.HexColor("#555555"))
TITLE = ParagraphStyle("T", parent=ss["Title"], fontName=FB, fontSize=20, alignment=TA_CENTER, spaceAfter=4)
SUB = ParagraphStyle("Sub", parent=BODY, alignment=TA_CENTER, fontSize=10, textColor=colors.HexColor("#555555"))


def table(data, widths, highlight_rows=(), align_right_from=1):
    t = Table(data, colWidths=widths, repeatRows=1)
    st = [
        ("FONTNAME", (0, 0), (-1, -1), F), ("FONTNAME", (0, 0), (-1, 0), FB),
        ("FONTSIZE", (0, 0), (-1, -1), 7.8), ("LEADING", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2a5a8c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b0b0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (align_right_from, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6fa")]),
    ]
    for r in highlight_rows:
        st += [("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fff2cc")),
               ("FONTNAME", (0, r), (-1, r), FB)]
    t.setStyle(TableStyle(st))
    return t


def build():
    os.makedirs("results", exist_ok=True)
    doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title="체결데이터 급등주 연구 요약", author="backtest-agent")
    S = []

    # ── 표지 ─────────────────────────────────────────────
    S += [Spacer(1, 30 * mm), Paragraph("체결데이터 급등주 연구 요약", TITLE),
          Paragraph("당일 +20% 급등주를 +10% 아래에서 살 수 있는가", SUB), Spacer(1, 8 * mm)]
    S.append(table([
        ["항목", "내용"],
        ["데이터", "체결(틱) 통합 KRX+NXT · data/stocks/tick_al"],
        ["기간", "2026-08-04 ~ 09-18 (33거래일)"],
        ["종목", "168종목 / 3,903 종목·일 / 체결 1억 7,727만 건"],
        ["검증 분리", "IS = 8월(18일) · OOS = 9월(15일)"],
        ["비용", "왕복 0.52% (수수료 0.03 + 거래세 0.23 + 슬리피지 0.26)"],
        ["측정 건수", "11건 (전부 사전등록 후 측정)"],
        ["작성", "backtest-agent · 2026-09-21"],
    ], [32 * mm, 128 * mm], align_right_from=0))
    S += [Spacer(1, 10 * mm), Paragraph(
        "※ 모든 측정은 결과를 보기 전에 방법·기각조건을 문서로 못박고(docs/*_PREREGISTRATION.md) 진행했다. "
        "안 되는 것도 전부 표에 남겼으며, 문턱을 바꿔가며 통과선을 찾지 않았다.", SMALL)]
    S.append(PageBreak())

    # ── 1. 한 줄 결론 ────────────────────────────────────
    S.append(Paragraph("1. 결론 — 11건 중 비용을 넘은 것은 하나뿐", H1))
    S.append(Paragraph(
        "<b>+9%에 도달한 순간, 그때까지의 누적 거래대금이 73억 미만이고, 시각이 09:10 이전이면 매수 → 전량 +20% 익절.</b> "
        "이 규칙만 9월 홀드아웃에서 비용을 넘었다(+3.04%). 나머지 10건은 전부 기각되거나 판정보류다.", BODY))
    S.append(Spacer(1, 3 * mm))
    S.append(table([
        ["구간", "거래", "+20% 도달", "순수익", "중앙값", "승률", "95% 신뢰구간", "비용2배"],
        ["IS (8월)", "52", "32.7%", "+2.06%", "+1.80%", "62%", "[+0.23, +3.83]", "+1.51%"],
        ["OOS (9월)", "31", "51.6%", "+3.04%", "+9.10%", "68%", "[+0.12, +5.62]", "+2.51%"],
    ], [24 * mm, 14 * mm, 20 * mm, 18 * mm, 18 * mm, 14 * mm, 30 * mm, 18 * mm], highlight_rows=(2,)))
    S.append(Paragraph(
        "<b>다만 '검증됨'이라 부르지 않는다.</b> OOS 31건·12일뿐이고 신뢰구간 하한이 +0.12로 사실상 0에 붙어 있다. "
        "손절이 없어 최악 -20.8%였고, 호가가 얇은 자리다. 거래일이 더 쌓여야 확정할 수 있다.", BODY))

    # ── 2. 측정 11건 요약 ────────────────────────────────
    S.append(Paragraph("2. 측정 11건 요약", H1))
    S.append(table([
        ["#", "측정", "핵심 결과", "판정"],
        ["1", "+10%에 사서 +20%에 팔기", "기저율 23.8%, 손익비 3.11:1 → 기대값 -0.055% (정확히 본전)", "기각"],
        ["2", "+10% 미만 진입 + 15~20% 분할매도", "25개 조합 전부 손실. 분할매도가 전량 +20%보다 나쁨", "기각"],
        ["3", "가온전선형(대금 폭발) 겨냥", "그 유형 칸은 평균 -0.31%. 정반대(저대금·이른시각)가 정답", "기각"],
        ["4", "삼화콘덴서 +20% 날 공통점", "직전 20일 변동성이 평소 4배(AUC 0.845). 적중률은 6%", "관찰"],
        ["5", "유형B(대금 폭발) 내부 공통점", "체결속도 AUC 0.735로 갈리나 12개 칸 전부 순수익 마이너스", "기각"],
        ["6", "+10%까지 터진 거래대금", "+20% 간 쪽 107억 vs 못 간 쪽 266억 (2.5배)", "기술통계"],
        ["7", "대금순위 20위 안 & +20%", "중앙값 200억. 20위 안이 오히려 불리(25.5% vs 34.5%)", "기술통계"],
        ["8", "체결가속도 지수 (5지표 0~100점)", "80점 이상 0건(구조적). 복합이 단일 최강보다 못함", "기각"],
        ["9", "고점 재탈환 시 체결속도", "빠를수록 지속률 13.9%→38.4%. 그래도 순수익 마이너스", "기각"],
        ["10", "재탈환 비대칭 손익비 / 간격", "손절 좁히면 손절률 폭증(65~75%). 전 조합 마이너스", "기각"],
        ["11", "눌림 → 재돌파 소요시간", "중앙값 7.4분. 깊이 5%가 경계선(97.5% → 36.8%)", "기술통계"],
    ], [7 * mm, 46 * mm, 89 * mm, 16 * mm], highlight_rows=(), align_right_from=3))

    S.append(PageBreak())

    # ── 3. 반복 확인된 발견 ──────────────────────────────
    S.append(Paragraph("3. 여러 번 반복해서 확인된 것", H1))
    S.append(Paragraph("서로 다른 측정에서 같은 방향으로 계속 나온 것들이라 신뢰도가 가장 높다.", BODY))
    S.append(table([
        ["발견", "확인 횟수", "내용"],
        ["돈이 덜 터진 쪽이 간다", "5회",
         "+20% 가는 종목은 살 수 있는 시점에 누적대금이 절반 이하. 대금 폭발은 +10% 이후에 일어난다"],
        ["매수 비중이 높을수록 나쁘다", "6회",
         "성공군의 매수비율이 오히려 낮음(68.8% vs 71.4%). 매도를 흡수하며 오르는 쪽이 더 간다"],
        ["적중률 ≠ 수익성", "4회",
         "적중률을 2.5배 올리고도 순수익이 2배 나빠진 사례. 실패 시 손실이 더 크게 늘어난다"],
        ["이른 시각이 유리", "4회",
         "개장 30분 내 사건이 압도적으로 많고 회복률·지속률도 높다"],
        ["라벨이 바뀌면 지표 부호도 바뀐다", "3회",
         "가격속도는 5분 라벨에선 음(평균회귀), 당일 +20% 라벨에선 양. 같은 지표를 그대로 옮기면 안 된다"],
    ], [38 * mm, 16 * mm, 104 * mm], align_right_from=3))

    # ── 4. 실무 참고표 ───────────────────────────────────
    S.append(Paragraph("4. 실무에 바로 쓸 수 있는 참고표", H1))
    S.append(Paragraph("<b>(가) +10% 시점 누적 거래대금별 +20% 달성률</b>", H2))
    S.append(table([
        ["+10%까지 누적대금", "건수", "달성률", "중앙 도달시각"],
        ["~50억", "73", "42.5%", "4.8분"],
        ["50~100억", "46", "43.5%", "8.3분"],
        ["100~200억", "69", "31.9%", "31.4분"],
        ["200~400억", "63", "27.0%", "22.6분"],
        ["400~800억", "58", "20.7%", "68.8분"],
        ["800억 초과", "68", "8.8%", "119.1분"],
    ], [40 * mm, 20 * mm, 24 * mm, 30 * mm], highlight_rows=(1, 2, 6)))
    S.append(Paragraph("100억 미만 43% vs 800억 초과 8.8% — 약 5배 차이로 깨끗하게 줄어든다.", SMALL))

    S.append(Paragraph("<b>(나) -2% 이상 눌림 → 고점 재돌파 (+20% 달성 종목 859건)</b>", H2))
    S.append(table([
        ["되돌림 깊이", "건수", "재돌파율", "소요 중앙값", "75%", "90%"],
        ["2~3%", "323", "97.5%", "3.7분", "6.6분", "14.1분"],
        ["3~5%", "273", "94.1%", "10.6분", "27.6분", "62.4분"],
        ["5~8%", "147", "79.6%", "29.4분", "69.5분", "163.2분"],
        ["8% 이상", "114", "36.8%", "68.9분", "131.0분", "218.2분"],
    ], [26 * mm, 18 * mm, 22 * mm, 26 * mm, 22 * mm, 22 * mm], highlight_rows=(1, 4)))
    S.append(Paragraph(
        "5%가 경계선. 5% 이내면 94~98%가 회복하고 대부분 10분 안에 끝나지만, 5%를 넘으면 재돌파율이 36.8%까지 무너진다. "
        "시각대별로도 갈린다 — 09:00~09:30 눌림은 94.1%가 4.7분 만에 회복, 13시 이후는 53.8%만 회복.", SMALL))

    S.append(Paragraph("<b>(다) 고점 재탈환 시 체결속도별 지속률</b>", H2))
    S.append(table([
        ["체결속도(10초)", "건수", "익절률(+2% 선착)", "손절률", "순수익"],
        ["~5틱/초", "3,412", "13.9%", "8.2%", "-0.486%"],
        ["5~15틱/초", "2,109", "23.9%", "18.7%", "-0.464%"],
        ["15~30틱/초", "1,122", "28.5%", "25.9%", "-0.509%"],
        ["30~60틱/초", "680", "38.4%", "27.4%", "-0.355%"],
        ["60틱/초 초과", "303", "33.3%", "35.3%", "-0.581%"],
    ], [28 * mm, 20 * mm, 32 * mm, 22 * mm, 24 * mm], highlight_rows=(4, 5)))
    S.append(Paragraph(
        "속도가 빠를수록 지속률이 오르지만 60틱/초를 넘으면 손절률이 익절률을 역전한다. "
        "다만 전 구간 순수익 마이너스 — ±2% 구조에서 본전이려면 익절률-손절률 격차가 26%p 필요한데 최고가 11%p다.", SMALL))

    S.append(PageBreak())

    # ── 5. 기각된 가설 ───────────────────────────────────
    S.append(Paragraph("5. 기각된 가설 (안 되는 것도 남긴다)", H1))
    S.append(table([
        ["가설", "왜 기각됐나"],
        ["분할매도(+15/17.5/20%)가 낫다", "전량 +20%보다 나쁨. 일찍 판 물량이 +20%까지의 상승을 못 먹는다"],
        ["돈이 빨리 몰리는 종목이 간다", "대금속도 AUC 0.436~0.481 — 역방향/무차별"],
        ["체결금액 가속도가 핵심", "AUC 0.487. 세 번째 라벨에서도 무의미"],
        ["매수 비중이 높으면 좋다", "AUC 0.443 — 여섯 번 모두 반대 방향"],
        ["소피증권 테마 대장주를 사면 좋다", "대장주 쪽이 -0.48~-1.27%로 더 나쁨(9월 데이터 없어 8월 한정)"],
        ["5개 지표 복합지수 80점 이상", "상관 낮은 백분위를 평균내면 최대 74.7점 — 80점이 구조적으로 불가능"],
        ["비대칭 손익비면 재탈환이 산다", "손절 -0.5%로 조이면 손절률 65~75%. 익절률이 같이 무너진다"],
        ["대금순위 20위 안이 유리하다", "20위 안 25.5% vs 20위 밖 34.5% — 오히려 불리"],
    ], [52 * mm, 108 * mm], align_right_from=2))

    # ── 6. 스스로 잡은 오류 ──────────────────────────────
    S.append(Paragraph("6. 측정 중에 스스로 잡은 오류 5건", H1))
    S.append(Paragraph("안 잡았으면 반대 결론을 보고할 뻔한 것들이다. 기록으로 남긴다.", BODY))
    S.append(table([
        ["오류", "영향", "조치"],
        ["부동소수 경계", "100.0×1.10 = 110.00000000000001이라 '정확히 +10%'인 체결이 탈락. KRX 전일종가는 10의 배수가 흔해 실제로 A/B 분류가 틀어짐", "허용오차 도입 + 회귀 테스트"],
        ["갭시작 오염", "갭으로 시작한 종목은 누적대금 0이라 저대금 필터에 자동 포함 → OOS +1.51%가 +0.20%로 내려앉음", "전 측정에서 갭시작 제외 규칙화"],
        ["선택편향", "'승부난 것만' 보면 느린 쪽이 성공하는 것처럼 보임(무승부율 77.8% vs 31.4%). 전체 기준으로는 정반대", "무승부를 분모에 포함"],
        ["틱/격자 혼동", "가격 속도 계산에서 틱 배열을 1초 격자처럼 인덱싱", "g['px'] 사용으로 교정"],
        ["표본 누락", "+10% 도달을 380건으로 집계했으나 시가가 +5~10%에서 출발한 51건이 빠져 있었음(정답 431건)", "전수 재스캔"],
    ], [26 * mm, 104 * mm, 30 * mm], align_right_from=3))

    # ── 7. 한계 ──────────────────────────────────────────
    S.append(Paragraph("7. 한계 (결론과 반드시 같이 읽을 것)", H1))
    for t in [
        "<b>33거래일, 국면 하나뿐이다.</b> 9월이 8월보다 훨씬 강했다(+20% 도달률 IS 16.9% vs OOS 32.1%). 다른 국면에서 성립하는지 모른다.",
        "<b>유니버스 168종목은 거래대금 상위권 위주다.</b> 시장 전체(약 2,540종목)로 외삽하면 안 된다. 순위도 '168종목 내 순위'이지 시장 전체 순위가 아니다.",
        "<b>지정가 매도는 '닿으면 체결'로 가정했다.</b> 호가 잔량 데이터가 없어 검증 불가능한 유리한 가정이다.",
        "<b>선별된 자리는 호가가 얇다.</b> 누적대금 73억 미만을 고르는 규칙은 체결이 어려운 쪽을 고르는 것과 같다. 비용 2배 민감도로 눌러도 양수지만 실제 체결 품질은 확인 못 했다.",
        "<b>생존편향.</b> 현재 상장 유지 중인 종목만 데이터에 있다.",
        "<b>백테스트 결과는 실계좌 성과를 보장하지 않는다.</b>",
    ]:
        S.append(Paragraph("· " + t, BODY))

    # ── 8. 부록 ──────────────────────────────────────────
    S.append(Paragraph("8. 원본 리포트 경로", H1))
    S.append(table([
        ["#", "파일 (state/agent_reports/)"],
        ["1", "backtest-agent_20260920-190424_leader_20pct_precursor.md"],
        ["2", "backtest-agent_20260920-231451_ladder_exit.md"],
        ["3", "backtest-agent_20260920-232957_bigmove_entry.md"],
        ["4", "backtest-agent_20260920-234500_samhwa_20pct.md"],
        ["5", "backtest-agent_20260921-000500_bigmoney_type.md"],
        ["6", "backtest-agent_20260921-002500_value_at_10pct.md"],
        ["7", "backtest-agent_20260921-004500_top20_rank_at10.md"],
        ["8", "backtest-agent_20260921-011818_accel_index.md"],
        ["9", "backtest-agent_20260921-012535_retake_high_speed.md"],
        ["10", "backtest-agent_20260921-013500_retake_asym_and_gap.md"],
        ["11", "backtest-agent_20260921-013837_pullback_retake_timing.md"],
    ], [8 * mm, 152 * mm], align_right_from=2))
    S.append(Paragraph(
        "사전등록 문서는 docs/ 아래 *_PREREGISTRATION.md 7건. 데이터 산출물은 results/ 아래 "
        "leader_20pct_events.csv · ladder_exit_events.csv · bigmoney_events.csv · at10_events.csv · "
        "rank10_events.csv · accel_events.csv · retake_events.csv · retake_grid.csv · pullback20_events.csv.", SMALL))

    doc.build(S)
    print(f"생성 완료: {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")
    return OUT


if __name__ == "__main__":
    build()
