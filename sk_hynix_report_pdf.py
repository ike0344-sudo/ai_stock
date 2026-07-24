"""sk_hynix_envelope_integrated.py 분석 결과를 PDF 리포트로 정리한다.

matplotlib은 이 환경에서 어떤 백엔드를 쓰든(Agg/svg/pdf 전부 확인) _backend_agg 컴파일
확장을 임포트하려다 Windows 애플리케이션 제어 정책에 막혀 전혀 쓸 수 없다 — 그래서
차트도 순수 파이썬인 reportlab(컴파일 확장 없음, 이 환경에서 정상 동작 확인됨)으로
직접 벡터 드로잉해서 PDF에 얹는다. 분석 로직(fetch/envelope/zones/backtest) 자체는
sk_hynix_envelope_integrated.py / sk_hynix_envelope_correlation.py 함수를 그대로 재사용
— 이 스크립트는 "결과를 PDF로 어떻게 그리느냐"만 새로 담당한다.

실행: python sk_hynix_report_pdf.py
출력: sk_hynix_envelope_report.pdf
"""
import os

import pandas as pd
from dotenv import load_dotenv
from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# reportlab 기본 내장 폰트(Helvetica 등)는 한글 글리프가 없다 — CID 폰트("HYGothic-Medium"
# 등)는 실제 글리프를 PDF에 임베드하지 않고 뷰어의 시스템 폰트에 기대는 방식이라, CJK
# 폰트가 없는 렌더러에서는 한글이 아예 안 보이는 걸 실측으로 확인했다. Windows 기본
# 한글 폰트(맑은 고딕) TTF를 직접 임베드해야 어떤 뷰어에서도 확실히 보인다.
FONT_REGULAR, FONT_BOLD = "Malgun", "MalgunBold"
pdfmetrics.registerFont(TTFont(FONT_REGULAR, "C:/Windows/Fonts/malgun.ttf"))
pdfmetrics.registerFont(TTFont(FONT_BOLD, "C:/Windows/Fonts/malgunbd.ttf"))

from kiwoom_client import KiwoomClient
from sk_hynix_envelope_correlation import (
    MA_WINDOW,
    SPLIT_TRANCHE_PCTS,
    TIER_PCTS,
    backtest_split_entry_strategy,
    backtest_tier_entries,
    compute_envelope,
    extract_zones,
    load_regular_session_15min,
    tier_label,
)
from sk_hynix_envelope_integrated import DATA_DIR, STOCK_CODE, fetch_combined_15min

OUTPUT_PATH = "sk_hynix_envelope_report.pdf"


def _zone_table_data(zones: pd.DataFrame, top_n: int = 5) -> list:
    header = ["시작", "종료", "봉수", "단계", "최대 괴리율"]
    if not len(zones):
        return [header, ["해당 구간 없음", "", "", "", ""]]
    rows = [header]
    top = zones.sort_values("max_deviation_pct", ascending=False).head(top_n)
    for _, row in top.iterrows():
        rows.append([
            row["start"].strftime("%Y-%m-%d %H:%M"), row["end"].strftime("%Y-%m-%d %H:%M"),
            str(row["bars"]), tier_label(int(row["max_tier"]), TIER_PCTS), f"{row['max_deviation_pct']:.1f}%",
        ])
    return rows


def _backtest_table_data(rows: list[tuple[str, pd.DataFrame]]) -> list:
    header = ["구간", "거래 수", "승률", "평균 수익률", "최고/최저", "단순합산"]
    out = [header]
    for label, trades in rows:
        if trades.empty:
            out.append([label, "0", "-", "-", "-", "-"])
            continue
        win_rate = (trades["return_pct"] > 0).mean() * 100
        out.append([
            label, str(len(trades)), f"{win_rate:.1f}%", f"{trades['return_pct'].mean():+.2f}%",
            f"{trades['return_pct'].max():+.2f}% / {trades['return_pct'].min():+.2f}%",
            f"{trades['return_pct'].sum():+.2f}%",
        ])
    return out


TABLE_STYLE = TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
    ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b2f38")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f5f7")]),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
])


def build_envelope_chart(df: pd.DataFrame, oversold: pd.DataFrame, overheated: pd.DataFrame, width=460, height=220) -> Drawing:
    """일별 마지막 봉 기준으로 다운샘플한 종가/이평/밴드 + 구간 음영을 reportlab
    벡터 드로잉으로 그린다(matplotlib 없이). 15분봉 원본(1만2천+개)을 그대로 그리면
    포인트가 페이지 폭보다 훨씬 많아 다운샘플이나 마찬가지 해상도로 뭉개지므로,
    가독성을 위해 일봉 단위로 미리 줄인다 — 구간/tier 판정 자체는 이미 15분봉
    해상도로 끝난 뒤 계산된 결과를 그대로 쓴다(이 함수는 시각화만 담당)."""
    daily = df.resample("1D").last().dropna(subset=["close"])
    n = len(daily)
    margin_l, margin_r, margin_t, margin_b = 55, 15, 30, 25
    plot_w, plot_h = width - margin_l - margin_r, height - margin_t - margin_b

    all_vals = pd.concat([
        daily["close"], daily["ma"],
        *[daily["ma"] * (1 + t / 100) for t in TIER_PCTS],
        *[daily["ma"] * (1 - t / 100) for t in TIER_PCTS],
    ]).dropna()
    y_min, y_max = all_vals.min(), all_vals.max()
    y_pad = (y_max - y_min) * 0.05

    def x_of(i):
        return margin_l + (i / max(n - 1, 1)) * plot_w

    def y_of(v):
        return margin_b + (v - (y_min - y_pad)) / ((y_max + y_pad) - (y_min - y_pad)) * plot_h

    day_pos = {d: i for i, d in enumerate(daily.index)}

    def nearest_day_idx(ts):
        d = ts.normalize()
        if d in day_pos:
            return day_pos[d]
        after = [dd for dd in daily.index if dd >= d]
        return day_pos[after[0]] if after else n - 1

    dr = Drawing(width, height)
    dr.add(Rect(margin_l, margin_b, plot_w, plot_h, strokeColor=colors.HexColor("#999999"), fillColor=None))

    tier_alpha = {1: 0.15, 2: 0.25, 3: 0.4}
    for _, row in oversold.iterrows():
        x0, x1 = x_of(nearest_day_idx(row["start"])), x_of(nearest_day_idx(row["end"]))
        r = Rect(x0, margin_b, max(x1 - x0, 1.5), plot_h, fillColor=colors.blue, strokeColor=None)
        r.fillOpacity = tier_alpha[int(row["max_tier"])]
        dr.add(r)
    for _, row in overheated.iterrows():
        x0, x1 = x_of(nearest_day_idx(row["start"])), x_of(nearest_day_idx(row["end"]))
        r = Rect(x0, margin_b, max(x1 - x0, 1.5), plot_h, fillColor=colors.red, strokeColor=None)
        r.fillOpacity = tier_alpha[int(row["max_tier"])]
        dr.add(r)

    def poly(series, color, width_=1.0, dash=None):
        pts = []
        for i, v in enumerate(series.values):
            if pd.isna(v):
                continue
            pts.extend([x_of(i), y_of(v)])
        if len(pts) >= 4:
            line = PolyLine(pts, strokeColor=color, strokeWidth=width_)
            if dash:
                line.strokeDashArray = dash
            dr.add(line)

    for t in TIER_PCTS:
        poly(daily["ma"] * (1 + t / 100), colors.HexColor("#aaaaaa"), 0.6, dash=[2, 2])
        poly(daily["ma"] * (1 - t / 100), colors.HexColor("#aaaaaa"), 0.6, dash=[2, 2])
    poly(daily["close"], colors.HexColor("#1f4e8c"), 1.1)
    poly(daily["ma"], colors.HexColor("#e08a1e"), 1.1)

    dr.add(String(margin_l, height - 10, f"SK하이닉스 통합(KRX+NXT) 일별 종가 · {MA_WINDOW}봉 이평 · 괴리율 밴드", fontSize=8, fillColor=colors.black, fontName=FONT_REGULAR))
    dr.add(String(margin_l, margin_b - 15, str(daily.index.min().date()), fontSize=7, fillColor=colors.grey, fontName=FONT_REGULAR))
    dr.add(String(width - margin_r - 55, margin_b - 15, str(daily.index.max().date()), fontSize=7, fillColor=colors.grey, fontName=FONT_REGULAR))
    legend_y = height - 22  # 제목 텍스트와 겹치지 않도록 한 줄 아래에 별도 배치
    for label, color, lx in (
        (f"종가", colors.HexColor("#1f4e8c"), margin_l), (f"{MA_WINDOW}이평", colors.HexColor("#e08a1e"), margin_l + 55),
        ("과대낙폭", colors.blue, margin_l + 110), ("과열", colors.red, margin_l + 170),
    ):
        dr.add(Line(lx, legend_y + 3, lx + 10, legend_y + 3, strokeColor=color, strokeWidth=2))
        dr.add(String(lx + 13, legend_y, label, fontSize=6.5, fillColor=colors.black, fontName=FONT_REGULAR))
    return dr


def main():
    load_dotenv()
    appkey = os.environ["KIWOOM_APPKEY"]
    secretkey = os.environ["KIWOOM_SECRETKEY"]
    is_mock = os.environ.get("KIWOOM_IS_MOCK", "true").lower() == "true"

    client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
    combined_raw = fetch_combined_15min(client)
    trading_days = combined_raw.index.normalize().unique()

    combined = compute_envelope(combined_raw, MA_WINDOW, TIER_PCTS)
    oversold = extract_zones(combined["oversold"], combined["oversold_tier"], combined["deviation_pct"].abs(), "과대낙폭")
    overheated = extract_zones(combined["overheated"], combined["overheated_tier"], combined["deviation_pct"].abs(), "과열")

    hynix_path = os.path.join(DATA_DIR, "stocks", "minute", f"{STOCK_CODE}.csv")
    regular_raw = load_regular_session_15min(hynix_path)
    regular_raw = regular_raw.loc[str(trading_days.min().date()):str(trading_days.max().date())]
    regular = compute_envelope(regular_raw, MA_WINDOW, TIER_PCTS)
    regular_oversold = extract_zones(regular["oversold"], regular["oversold_tier"], regular["deviation_pct"].abs(), "과대낙폭(정규장)")
    regular_overheated = extract_zones(regular["overheated"], regular["overheated_tier"], regular["deviation_pct"].abs(), "과열(정규장)")

    tier_backtests = [
        (f"과대낙폭 {tier_label(t, TIER_PCTS)}", backtest_tier_entries(combined, oversold, tier=t, exit_ma_col="ma"))
        for t in range(1, len(TIER_PCTS) + 1)
    ]
    split_trades = backtest_split_entry_strategy(combined, oversold)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("KoTitle", parent=styles["Title"], fontName=FONT_BOLD, fontSize=18))
    styles.add(ParagraphStyle("KoH2", parent=styles["Heading2"], fontName=FONT_BOLD, fontSize=13, spaceBefore=14))
    styles.add(ParagraphStyle("KoBody", parent=styles["BodyText"], fontName=FONT_REGULAR, fontSize=9.5, leading=13))
    styles.add(ParagraphStyle("KoCaveat", parent=styles["BodyText"], fontName=FONT_REGULAR, fontSize=8.5, leading=12, textColor=colors.HexColor("#8a5a00"), backColor=colors.HexColor("#fff6e0")))

    story = []
    story.append(Paragraph("SK하이닉스 통합(KRX+NXT) 15분봉 60이평 엔벨로프 분석", styles["KoTitle"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"분석기간 {trading_days.min().date()} ~ {trading_days.max().date()} "
        f"({len(trading_days)}거래일, 15분봉 {len(combined_raw)}개, 하루 평균 {len(combined_raw) / len(trading_days):.0f}봉) · "
        f"괴리율 임계값 {', '.join(f'{t:.0f}%' for t in TIER_PCTS)}",
        styles["KoBody"],
    ))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"⚠️ {'모의투자' if is_mock else '실전투자'} 계좌로 조회했습니다. 계좌평가/호가 조회에서 이미 확인된 바와 같이 "
        "모의투자는 KRX/NXT/SOR 시세를 구분하지 않는 것으로 보여, 08:00~09:00·15:31~20:00 구간 가격이 "
        "실제 NXT 체결가가 아닐 수 있습니다. 이 리포트는 실전 계좌 재검증 전까지 참고용입니다.",
        styles["KoCaveat"],
    ))

    story.append(Paragraph("구간 요약", styles["KoH2"]))
    summary_rows = [
        ["구분", "구간 수", "총 봉수", f"{TIER_PCTS[0]:.0f}~{TIER_PCTS[1]:.0f}%", f"{TIER_PCTS[1]:.0f}~{TIER_PCTS[2]:.0f}%", f"{TIER_PCTS[2]:.0f}%+"],
        ["과대낙폭", str(len(oversold)), str(int(oversold["bars"].sum()) if len(oversold) else 0)] + [
            str((oversold["max_tier"] == t).sum()) if len(oversold) else "0" for t in (1, 2, 3)
        ],
        ["과열", str(len(overheated)), str(int(overheated["bars"].sum()) if len(overheated) else 0)] + [
            str((overheated["max_tier"] == t).sum()) if len(overheated) else "0" for t in (1, 2, 3)
        ],
    ]
    t = Table(summary_rows, hAlign="LEFT")
    t.setStyle(TABLE_STYLE)
    story.append(t)

    story.append(Spacer(1, 10))
    story.append(Paragraph("차트: 통합 일별 종가 · 60이평 · 괴리율 밴드 · 구간 음영", styles["KoBody"]))
    story.append(build_envelope_chart(combined, oversold, overheated))

    story.append(Paragraph("과대낙폭 최대 괴리율 상위 5개 구간", styles["KoH2"]))
    t = Table(_zone_table_data(oversold), hAlign="LEFT", colWidths=[85, 85, 40, 60, 70])
    t.setStyle(TABLE_STYLE)
    story.append(t)

    story.append(Paragraph("과열 최대 괴리율 상위 5개 구간", styles["KoH2"]))
    t = Table(_zone_table_data(overheated), hAlign="LEFT", colWidths=[85, 85, 40, 60, 70])
    t.setStyle(TABLE_STYLE)
    story.append(t)

    story.append(Paragraph("정규장 전용(09:00~15:30) 대비", styles["KoH2"]))
    story.append(Paragraph(
        f"같은 기간 기준 과대낙폭 {len(oversold)}개(통합) vs {len(regular_oversold)}개(정규장), "
        f"과열 {len(overheated)}개(통합) vs {len(regular_overheated)}개(정규장). "
        f"60봉 이평의 실제 반영 기간이 통합은 약 {60 / (len(combined_raw) / len(trading_days)):.1f}거래일, "
        f"정규장 전용은 약 {60 / 27:.1f}거래일로 서로 달라 이평선 반응 속도 차이가 구간 수 차이에 큰 영향을 줍니다 — "
        "단순 개수 비교보다 이 창 길이 차이를 먼저 감안해야 합니다.",
        styles["KoBody"],
    ))

    story.append(PageBreak())
    story.append(Paragraph("분할매수 tier별 백테스트 (진입=tier 최초 터치, 청산=60이평 회복)", styles["KoH2"]))
    t = Table(_backtest_table_data(tier_backtests), hAlign="LEFT", colWidths=[110, 55, 45, 65, 105, 65])
    t.setStyle(TABLE_STYLE)
    story.append(t)

    story.append(Paragraph(
        f"PDF 전략3 재현: -{SPLIT_TRANCHE_PCTS[0]:.0f}% 터치 시 3분할 매수"
        f"({'/'.join(f'-{p:.0f}%' for p in SPLIT_TRANCHE_PCTS)}) → 60선 터치 전량 익절(하드스톱/시간청산 포함)",
        styles["KoH2"],
    ))
    t = Table(_backtest_table_data([("PDF 전략3 재현(통합)", split_trades)]), hAlign="LEFT", colWidths=[110, 55, 45, 65, 105, 65])
    t.setStyle(TABLE_STYLE)
    story.append(t)
    if not split_trades.empty:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"청산 사유별 건수: {split_trades['exit_reason'].value_counts().to_dict()} · "
            f"평균 체결 분할 수: {split_trades['filled_tranches'].mean():.2f} / {len(SPLIT_TRANCHE_PCTS)}",
            styles["KoBody"],
        ))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "⚠️ 위 백테스트 수치는 이 표본에서의 과거 재현 결과이며 투자 조언이 아닙니다. 과대낙폭 구간 표본이 "
        f"{len(oversold)}개(그중 1단계 {(oversold['max_tier'] == 1).sum() if len(oversold) else 0}건)로 적어 "
        "통계적 신뢰도가 낮고, 모의투자 데이터라 NXT 구간 가격 자체의 신뢰성 caveat도 그대로 적용됩니다. "
        "실전 계좌로 재검증 전까지는 참고 수준으로만 볼 것을 권합니다.",
        styles["KoCaveat"],
    ))

    doc = SimpleDocTemplate(
        OUTPUT_PATH, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="SK하이닉스 통합 15분봉 엔벨로프 분석",
    )
    doc.build(story)
    print(f"PDF 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
