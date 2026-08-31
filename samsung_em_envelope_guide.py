"""삼성전기(009150) 15분봉 60이평 엔벨로프 전략을 사람이 직접 매매할 수 있도록
쉬운 말로 정리한 실행 가이드 PDF. results/samsung_em_envelope.csv의 그리드서치
결과(backtesting.cli rule --strategy envelope) 중 OOS 성과가 가장 안정적이었던
envelope_pct=0.03/exit_mode=opposite_band 조합을 그대로 설명한다 — 새 백테스트를
다시 돌리지 않고 이미 저장된 결과 숫자만 표로 옮긴다.

matplotlib이 이 환경에서 막혀 있어(sk_hynix_report_pdf.py 참고) reportlab으로
직접 그린다. 실행: python samsung_em_envelope_guide.py
출력: samsung_em_envelope_guide.pdf
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_REGULAR, FONT_BOLD = "Malgun", "MalgunBold"
pdfmetrics.registerFont(TTFont(FONT_REGULAR, "C:/Windows/Fonts/malgun.ttf"))
pdfmetrics.registerFont(TTFont(FONT_BOLD, "C:/Windows/Fonts/malgunbd.ttf"))

OUTPUT_PATH = "samsung_em_envelope_guide.pdf"
STOCK_NAME, STOCK_CODE = "삼성전기", "009150"
MA_WINDOW = 60
ENVELOPE_PCT = 3  # %
# results/samsung_em_envelope.csv (2025-08-01~2026-08-06, IS/OOS 70/30, 수수료+슬리피지+세금 반영)
OOS_RETURN_PCT, OOS_MDD_PCT, OOS_WIN_RATE_PCT, OOS_TRADES = 33.3, 16.9, 61.5, 13
BENCHMARK_RETURN_PCT = 81.3

TABLE_STYLE = TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
    ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b2f38")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTSIZE", (0, 0), (-1, -1), 9.5),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f5f7")]),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
])


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("KoTitle", parent=styles["Title"], fontName=FONT_BOLD, fontSize=19))
    styles.add(ParagraphStyle("KoH2", parent=styles["Heading2"], fontName=FONT_BOLD, fontSize=13.5, spaceBefore=16, textColor=colors.HexColor("#1f4e8c")))
    styles.add(ParagraphStyle("KoBody", parent=styles["BodyText"], fontName=FONT_REGULAR, fontSize=10.5, leading=15))
    styles.add(ParagraphStyle("KoBig", parent=styles["BodyText"], fontName=FONT_BOLD, fontSize=12, leading=17, textColor=colors.HexColor("#1f4e8c")))
    styles.add(ParagraphStyle("KoCaveat", parent=styles["BodyText"], fontName=FONT_REGULAR, fontSize=9, leading=13, textColor=colors.HexColor("#8a5a00"), backColor=colors.HexColor("#fff6e0")))
    return styles


def build_story(styles) -> list:
    story = []
    story.append(Paragraph(f"{STOCK_NAME}({STOCK_CODE}) 15분봉 엔벨로프 매매 가이드", styles["KoTitle"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"이동평균({MA_WINDOW}봉)에서 너무 멀어진 가격이 다시 돌아오는 것에 베팅하는 전략입니다. "
        "차트 프로그램에 조건 두 개만 걸어두면 사람이 직접 봉마다 계산할 필요 없이 그대로 따라할 수 있습니다.",
        styles["KoBody"],
    ))

    story.append(Paragraph("1. 준비: 차트 설정", styles["KoH2"]))
    story.append(ListFlowable([
        ListItem(Paragraph(f"종목: {STOCK_NAME}({STOCK_CODE})", styles["KoBody"])),
        ListItem(Paragraph("봉 종류: 15분봉", styles["KoBody"])),
        ListItem(Paragraph(f"이동평균선: {MA_WINDOW}선 (15분봉 {MA_WINDOW}개 = 약 2.3거래일치, 종가 기준)", styles["KoBody"])),
        ListItem(Paragraph(f"밴드: 이동평균선의 ±{ENVELOPE_PCT}% — 차트 프로그램에 엔벨로프 지표가 있으면 이동평균 {MA_WINDOW}, 상하 {ENVELOPE_PCT}%로 설정", styles["KoBody"])),
    ], bulletType="bullet"))

    story.append(Paragraph("2. 매수 — 이렇게만 확인하세요", styles["KoH2"]))
    story.append(Paragraph(f"15분봉이 방금 끝났을 때, 그 종가가 60이평선 × (1 − {ENVELOPE_PCT}%) 즉 하단 밴드 아래에 있으면 매수.", styles["KoBig"]))
    story.append(Paragraph(
        "예: 60이평선이 150,000원이면 하단 밴드는 150,000 × 0.97 = 145,500원. "
        "15분봉 종가가 145,500원 이하로 마감하면 그 다음 매수 기회에 진입합니다.",
        styles["KoBody"],
    ))

    story.append(Paragraph("3. 매도 — 이렇게만 확인하세요", styles["KoH2"]))
    story.append(Paragraph(f"매수한 뒤, 15분봉 종가가 60이평선 × (1 + {ENVELOPE_PCT}%) 즉 상단 밴드 위로 올라오면 전량 매도.", styles["KoBig"]))
    story.append(Paragraph(
        "같은 예시로 60이평선이 150,000원이면 상단 밴드는 150,000 × 1.03 = 154,500원. "
        "매수 이후 종가가 154,500원을 넘어서면 그 다음 매도 기회에 전량 청산합니다. "
        "하단 터치 후 이평선까지만 오면 파는 게 아니라, 반대편(상단 밴드)까지 와야 파는 방식이라 "
        "구간을 더 길게 들고 갑니다.",
        styles["KoBody"],
    ))

    story.append(Paragraph("4. 한 장 요약 체크리스트", styles["KoH2"]))
    story.append(ListFlowable([
        ListItem(Paragraph("보유 중인 물량이 없다 → 15분봉 종가가 60이평선의 -3% 아래인지 확인 → 맞으면 매수", styles["KoBody"])),
        ListItem(Paragraph("보유 중인 물량이 있다 → 15분봉 종가가 60이평선의 +3% 위인지 확인 → 맞으면 전량 매도", styles["KoBody"])),
        ListItem(Paragraph("둘 다 아니면 아무것도 안 하고 다음 15분봉을 기다린다", styles["KoBody"])),
    ], bulletType="1"))

    story.append(Paragraph("5. 과거 데이터로 확인된 성과 (참고용)", styles["KoH2"]))
    story.append(Paragraph(
        "2025-08-01~2026-08-06 기간, 실제로 검증하지 않은 최근 구간(OOS)만 기준. 수수료·슬리피지·매도세 이미 반영.",
        styles["KoBody"],
    ))
    rows = [
        ["항목", "값"],
        ["기간 수익률", f"+{OOS_RETURN_PCT:.1f}%"],
        ["최대 낙폭(MDD)", f"{OOS_MDD_PCT:.1f}%"],
        ["승률", f"{OOS_WIN_RATE_PCT:.1f}%"],
        ["거래 횟수", f"{OOS_TRADES}건"],
        ["같은 기간 그냥 사서 들고만 있었을 때", f"+{BENCHMARK_RETURN_PCT:.1f}%"],
    ]
    t = Table(rows, hAlign="LEFT", colWidths=[70 * mm, 70 * mm])
    t.setStyle(TABLE_STYLE)
    story.append(t)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "⚠️ 주의: 이 기간은 주가가 계속 오른 구간이라 그냥 사서 들고만 있는 것보다 이 전략의 수익이 낮습니다 "
        "(밴드 되돌림을 노리는 전략 특성상 상승분을 다 못 먹는 게 정상). 검증에 쓰인 거래가 13건뿐이라 표본이 "
        "작고, 이 규칙 자체에는 손절 라인이 없어 하단 밴드보다 더 크게 빠지면 계속 손실을 안고 갈 수 있습니다. "
        "실제 돈을 넣기 전에 본인 판단으로 손절 기준(예: 매수가 대비 -X%)을 추가하는 것을 권합니다. "
        "투자 조언이 아니라 과거 재현 결과입니다.",
        styles["KoCaveat"],
    ))

    return story


def main() -> None:
    doc = SimpleDocTemplate(
        OUTPUT_PATH, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"{STOCK_NAME} 엔벨로프 매매 가이드",
    )
    doc.build(build_story(_styles()))
    print(f"PDF 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
