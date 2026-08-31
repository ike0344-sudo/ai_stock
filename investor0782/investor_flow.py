"""시간대별 투자자 — 영웅문 0782 를 스스로 갱신하는 판으로.

0782 는 조회를 눌러야 갱신된다. 이쪽은 1분마다 알아서 받는다.

    python investor_flow.py

ka10051(업종별투자자순매수)은 한 번 부르면 그 시장의 **업종을 전부** 준다. 첫 행이
종합(001 KOSPI / 101 KOSDAQ)이라 그게 시장 전체다. 그래서 업종 선택은 추가 조회가
아니라 이미 받아 둔 응답에서 고르는 일이고, 모든 업종의 기록을 같이 쌓아 둘 수 있다.

0782 를 따라 **본문은 시각별 누적 순매수**고, 구간 변화(증감)는 위 고정 블록에만
한 줄 둔다. 응답이 누적이라 본문은 받은 값 그대로고, 증감이 직전 누적과의 차다.

지나간 시간대는 못 받아온다(REST 에 시장·업종 단위 시간대별 TR 이 없다). 켠 뒤부터
줄이 쌓이고, 그 전 몫은 첫 줄 누적이 통째로 들고 있다.

매도·매수 두 줄은 KRX 에서 따로 받는다(krx.py) — 키움은 순매수만 준다. KRX 는 시장
전체만 주므로 업종을 고르면 그 두 줄은 '-' 가 된다.
"""
import json
import os
import sys
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

# QtCharts 는 ai_stock.spec 이 EXE 에서 빼는 모듈이다. 이 창은 소스로만 도는 별도
# 프로그램이라 상관없지만, 나중에 EXE 로 굽는다면 excludes 에서 빼야 한다.
from PySide6.QtCharts import (QCategoryAxis, QChart, QChartView, QLineSeries,
                              QValueAxis)
from PySide6.QtCore import QMargins, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout,
                               QButtonGroup, QHeaderView, QLabel, QMainWindow, QPushButton,
                               QRadioButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from kiwoom import Kiwoom
from krx import Krx

# 색은 영웅문 0782 화면을 픽셀로 떠서 옮겼다. 소피증권의 검정 판을 쓰다가 0782 와
# 나란히 놓고 견주기로 해서 밝은 쪽으로 돌렸다.
BG = "#F5F5F5"          # 창·조회줄 바탕
PANEL = "#FFFFFF"
CELL_BG = "#FFFFFF"     # 본문 셀
SUM_BG = "#FCFDFF"      # 고정 블록 셀 — 본문보다 아주 살짝 푸르다
TEXT = "#000000"
MUTED = "#1A1A1A"       # 0782 는 라벨도 그냥 검정이다
UP = "#E72410"          # 한국 증시 관례 — 상승 적, 하락 청
DOWN = "#1A4EC4"
MONO = "Gulim,'굴림',Dotum,'돋움',sans-serif"   # HTS 기본 글꼴
GRID = "#C0C0C0"
BORDER = "#A0A0A0"
HEAD_BG = "#DBE3ED"
# 0782 는 앞 세 열 머리글에만 색을 깐다. 키는 열 번호(0 은 '시간', 1 부터 COLS).
HEAD_TINT = {1: "#F5D1CC", 2: "#EBDCBF", 3: "#DBE4C4"}
ZEBRA = "#E6E6E6"       # 0782 는 10 분 묶음으로 바탕을 간다
SEL_BG = "#C9E7F3"   # 0782 는 맨 윗줄(최신)을 하늘색으로 깐다
IDX_KEY = "_idx"     # 지수 — ka10051 이 cur_prc 로 같이 준다
ZERO = "#363637"

SEOUL = ZoneInfo("Asia/Seoul")
POLL_MS = 60_000
MARKETS = (("0", "KOSPI"), ("1", "KOSDAQ"))
# 0782 헤더 순서 그대로다. 기타금융이 은행보다 앞이고, 국가·내국인대우외국인은
# 0782 에 없으므로 세우지 않는다(응답에는 있다).
COLS = [("ind_netprps", "개인"), ("frgnr_netprps", "외국인"), ("orgn_netprps", "기관계"),
        ("sc_netprps", "금융투자"), ("insrnc_netprps", "보험"), ("invtrt_netprps", "투신"),
        ("jnsinkm_netprps", "기타금융"), ("bank_netprps", "은행"),
        ("endw_netprps", "연기금등"), ("samo_fund_netprps", "사모펀드"),
        ("etc_corp_netprps", "기타법인")]
# 0782 가 기본으로 켜 두는 넷. 나머지는 체크해서 켠다.
CHART_ON = ("ind_netprps", "frgnr_netprps", "orgn_netprps", "sc_netprps")
# 앞 넷은 0782 범례에서 뜬 색 그대로다. 나머지는 0782 가 기본으로 안 켜므로 흰
# 바탕에서 서로 구분되게 고른 값이다.
LINE_COLOR = {"ind_netprps": "#FF8534", "frgnr_netprps": "#3568FF",
              "orgn_netprps": "#5CAE85", "sc_netprps": "#993300",
              "insrnc_netprps": "#B22222", "invtrt_netprps": "#8A2BE2",
              "jnsinkm_netprps": "#2E8B57", "bank_netprps": "#8B7355",
              "endw_netprps": "#008B8B", "samo_fund_netprps": "#708090",
              "etc_corp_netprps": "#444444"}
ROWS_SHOWN = 200
# 요약 블록과 본문은 **서로 다른 표**다(하나는 고정, 하나는 스크롤). 표마다 제 내용에
# 맞춰 열을 잡으면 위아래가 어긋나므로 두 표에 같은 너비를 셀마다 박는다.
TIME_W = 68          # 0782 실측 — '14:56:00' 이 12px 굴림에서 딱 들어간다
COL_W = 80
ROW_H = 21           # 0782 실측
CELL_FONT = 12        # 0782 표 글자 크기(굴림 9pt)
UI_FONT = 11          # 체크박스·라디오는 작게 — 키우면 줄이 창 밖으로 밀린다


def hero_window_size() -> tuple[int, int] | None:
    """떠 있는 영웅문 0782 창의 실제 크기. 없으면 None.

    창 크기를 숫자로 박아 두면 배율(1.25)에 걸려 매번 어긋난다 — 원본을 재는 편이
    확실하다. 제목에 [0782] 가 있으면서 내 프로세스가 아닌 창을 찾는다.
    """
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    me = ctypes.windll.kernel32.GetCurrentProcessId()
    found = []

    def visit(hwnd, _lparam):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        if "[0782]" not in buf.value:
            return True
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me:
            return True                     # 내 창은 건너뛴다
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        found.append((r.right - r.left, r.bottom - r.top))
        return False

    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    u.EnumWindows(proto(visit), 0)
    return found[0] if found else None


class TintedHeader(QHeaderView):
    """열마다 다른 바탕색을 가진 표 머리글.

    QHeaderView::section 에는 열을 고르는 선택자가 없어서 스타일시트로는 '개인'만
    분홍으로 깔 수 없다. 그려 버리는 편이 짧다.
    """

    def __init__(self, parent) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(False)
        self.setHighlightSections(False)

    def paintSection(self, painter, rect, index: int) -> None:
        painter.fillRect(rect, QColor(HEAD_TINT.get(index, HEAD_BG)))
        painter.setPen(QColor(GRID))
        painter.drawLine(rect.right(), rect.top(), rect.right(), rect.bottom())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        painter.setPen(QColor(TEXT))
        painter.setFont(self.font())
        model = self.model()
        text = model.headerData(index, Qt.Orientation.Horizontal) if model else ""
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(text or ""))


def _num(v: str) -> int:
    """API 는 '--264' 처럼 부호를 겹쳐 주고, 0782 CSV 는 '-24,744' 처럼 쉼표를 넣는다.
    앞 부호만 살리고 나머지 장식은 다 버린다."""
    s = str(v).strip().replace(",", "")
    neg = s.startswith("-")
    return -int(s.lstrip("+-") or 0) if neg else int(s.lstrip("+-") or 0)


def diff(prev: dict | None, cur: dict) -> dict | None:
    """직전 누적과의 차 = 0782 의 '증감'. 첫 응답은 견줄 곳이 없어 아무것도 못 낸다."""
    if prev is None:
        return None
    return {k: cur.get(k, 0) - prev.get(k, 0) for k, _ in COLS}


def load_csv(path: Path) -> list:
    """0782 가 내보낸 CSV 를 화면이 쓰는 모양으로 — [(시각, 누적, 증감)] 최신 앞.

    파일은 이미 최신이 위고 값은 누적이다. 증감만 바로 아랫줄(더 이전)과의 차로 만든다.
    영웅문이 cp949 로 쓴다.
    """
    import csv

    with path.open(encoding="cp949", newline="") as fh:
        raw = [r for r in csv.DictReader(fh) if r.get("시간")]
    ko_to_key = {ko: key for key, ko in COLS}
    cums = [(r["시간"], {ko_to_key[ko]: _num(r[ko]) for ko in ko_to_key if ko in r})
            for r in raw]
    out = []
    for i, (t, cum) in enumerate(cums):
        prev = cums[i + 1][1] if i + 1 < len(cums) else None
        out.append((t, cum, diff(prev, cum)))
    return out


def _fmt(v: int) -> str:
    return f"{v:+,}" if v else "0"


def _color(v: int) -> str:
    return UP if v > 0 else (DOWN if v < 0 else ZERO)


class Window(QMainWindow):
    def __init__(self, client: Kiwoom | None) -> None:
        super().__init__()
        self._client = client               # None 이면 예제 모드 — 조회를 안 한다
        self._prev: dict[tuple[str, str], dict] = {}     # (시장, 업종) -> 직전 누적
        self._rows: dict[tuple[str, str], list] = {}     # (시장, 업종) -> [(시각, 누적, 증감)]
        self._names: dict[str, list[tuple[str, str]]] = {m: [] for m, _ in MARKETS}
        self._krx = Krx()
        self._sellbuy: dict[str, dict] = {}      # 시장 -> {열키: (매도, 매수)}
        self._path = Path(__file__).with_name("logs") / "investor.jsonl"
        self._path.parent.mkdir(exist_ok=True)
        self.setWindowTitle("[0782] 투자자별 매매동향 — 시간대별투자자")
        # 창 바탕은 스타일시트가 아니라 팔레트로 준다. QWidget 에 background 를 걸면
        # Qt 가 체크박스·라디오까지 스타일시트로 그려서 네모·동그라미가 사라진다.
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(BG))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
        pal.setColor(QPalette.ColorRole.Base, QColor(PANEL))
        pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
        self.setPalette(pal)
        self.setStyleSheet(
            f"QWidget{{color:{TEXT};font-family:{MONO};font-size:12px;}}"
            f"QComboBox{{background:{PANEL};color:{TEXT};border:1px solid {BORDER};"
            f"padding:1px 6px;}}"
            f"QComboBox QAbstractItemView{{background:{PANEL};color:{TEXT};"
            f"selection-background-color:#316AC5;selection-color:#FFFFFF;}}"
            f"QPushButton{{background:#ECECEC;color:{TEXT};border:1px solid {BORDER};"
            f"padding:2px 10px;}}"
            f"QPushButton:hover{{background:#DCE6F5;}}"
            # 지시자에는 아무 규칙도 두지 않는다 — 크기 하나만 줘도 Qt 가 네이티브
            # 그림을 걷어내고 체크 표시만 남긴다.
            f"QCheckBox,QRadioButton{{color:{MUTED};padding:0 2px;font-size:{UI_FONT}px;}}")

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(3)

        # ── 조회 조건 줄 (0782 의 맨 윗줄)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.cb_sector = QComboBox()
        self.cb_sector.setMinimumWidth(150)
        self.cb_sector.currentIndexChanged.connect(lambda _: self._draw())
        bar.addWidget(self.cb_sector)
        # QRadioButton 은 **부모가 같으면 자동으로 한 그룹**이다. 그대로 두면 '금액'을
        # 누르는 순간 KOSPI 가 꺼지고, 그 여파로 _unit_changed 가 쌓인 값을 지웠다.
        self.grp_market = QButtonGroup(self)
        self.grp_unit = QButtonGroup(self)
        self.market_btns = {}
        for code, name in MARKETS:          # 0782 는 콤보가 아니라 라디오다
            rb = QRadioButton(name)
            rb.setChecked(code == "0")
            rb.toggled.connect(lambda on, c=code: on and self._market_changed())
            self.market_btns[code] = rb
            self.grp_market.addButton(rb)
            bar.addWidget(rb)
        bar.addSpacing(10)
        self.rb_amt = QRadioButton("금액")
        self.rb_qty = QRadioButton("수량")
        self.rb_amt.setChecked(True)
        self.rb_qty.toggled.connect(lambda _o: self._unit_changed())
        for rb in (self.rb_amt, self.rb_qty):
            self.grp_unit.addButton(rb)
            bar.addWidget(rb)
        bar.addStretch(1)
        self.status = QLabel("첫 조회 대기")
        self.status.setStyleSheet(f"color:{MUTED};padding:0 8px;background:transparent")
        bar.addWidget(self.status)
        self.btn_chart = QPushButton("숨기기")      # 0782 의 [숨기기]
        self.btn_chart.clicked.connect(self._toggle_chart)
        bar.addWidget(self.btn_chart)
        outer.addLayout(bar)

        # ── 고정 블록: 순매수 / 증감 (0782 는 위에 매도·매수까지 넷이다)
        # QLabel + HTML 로는 열이 안 맞았다 — Qt 리치텍스트는 width 를 힌트로만 써서
        # 내용이 길면 늘려 버린다. 표 위젯은 열 너비가 픽셀로 확정된다.
        self.summary = self._make_table(rows=4, header=True)
        # 높이는 showEvent 에서 잡는다 — 배치 전에는 머리글 실제 높이를 모르고,
        # sizeHint 로 어림잡으면 '증감' 줄이 반쯤 잘린다.
        outer.addWidget(self.summary)

        # ── 본문: 시각별 누적 순매수. 머리글은 위 블록 것을 쓰므로 감춘다.
        self.body = self._make_table(rows=0, header=False)
        outer.addWidget(self.body, 3)

        # ── 차트 항목 토글 (0782 의 체크박스 줄)
        picks = QHBoxLayout()
        picks.setSpacing(1)
        self.checks = {}
        for key, ko in COLS:
            cb = QCheckBox(ko)
            cb.setChecked(key in CHART_ON)
            cb.stateChanged.connect(lambda _s: self._draw())
            self.checks[key] = cb
            picks.addWidget(cb)
        self.cb_index = QCheckBox("지수보이기")     # 0782 의 오른쪽 끝 체크
        self.cb_index.setChecked(True)
        self.cb_index.stateChanged.connect(lambda _s: self._draw())
        picks.addStretch(1)
        picks.addWidget(self.cb_index)
        outer.addLayout(picks)

        self.chart = QChart()
        self.chart.legend().setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chart.legend().setLabelColor(QColor(TEXT))
        self.chart.setBackgroundVisible(False)
        self.chart.setMargins(QMargins(2, 2, 2, 2))
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setStyleSheet(f"border:1px solid {BORDER};background:{PANEL};")
        outer.addWidget(self.chart_view, 2)

        self.setCentralWidget(body)
        # 0782 창 크기에 맞춘 기본값. 한 번 끌어서 맞추면 그 크기를 기억한다.
        self._settings = QSettings("sophie", "investor_flow")
        # 예제 모드는 0782 와 크기를 견주는 자리다 — 저장된 크기가 이기면 기본값을
        # 고쳐도 화면이 안 바뀐다(실제로 그래서 한참 헤맸다).
        geo = None if self._client is None else self._settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            # 0782 가 떠 있으면 그 크기를 따라가고, 없으면 실측 기본값을 쓴다.
            self.resize(804, 536)
            self._target = hero_window_size()
        if self._settings.value("chart_hidden", "0") == "1":
            self._toggle_chart()

        if self._client is None:
            self._load_demo()
        else:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.poll)
            self._timer.start(POLL_MS)
            self.poll()

    def _load_demo(self) -> None:
        """0782 CSV 로 화면을 채운다 — 하루치가 다 들어와 나란히 견줄 수 있다."""
        here = Path(__file__).parent
        found = []
        for csv_path in sorted(here.glob("[0-9][0-9][0-9].csv")):
            code = csv_path.stem
            self._rows[("0", code)] = load_csv(csv_path)
            found.append((code, "종합(KOSPI)" if code == "001" else f"업종 {code}"))
        self._names["0"] = found
        # 예제도 매도·매수는 오늘치 KRX 를 쓴다 — CSV 에는 그 두 줄이 없다.
        from datetime import date
        try:
            self._sellbuy["0"] = self._krx.sell_buy("0", date.today().strftime("%Y%m%d"))
        except Exception:                    # noqa: BLE001
            pass
        self._fill_sectors()
        self._draw()
        self.status.setText(f"예제 — CSV {len(found)}개 · 조회 안 함")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 배치가 한 번 끝난 뒤라야 머리글 실제 높이를 안다. 여기서 바로 읽으면
        # 아직 이전 값이라 '증감' 줄이 잘린다.
        QTimer.singleShot(0, self._fit_summary)
        if getattr(self, "_target", None):
            # 요약 블록 높이가 정해진 **뒤에** 창을 맞춰야 한다 — 먼저 하면 그 사이
            # 높이가 바뀌어 세로가 덜 맞는다(실측 530 대 566).
            QTimer.singleShot(60, self._fit_window)

    def _fit_window(self) -> None:
        """실제 창 크기를 재서 0782 에 맞춘다. resize 값과 실제 픽셀이 배율만큼
        어긋나므로 비율로 두어 번 되민다 — 숫자를 박는 것보다 이 편이 안 깨진다."""
        import ctypes
        from ctypes import wintypes

        tw, th = self._target
        u = ctypes.windll.user32
        for _ in range(6):
            r = wintypes.RECT()
            u.GetWindowRect(int(self.winId()), ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            if not w or not h or (abs(tw - w) <= 1 and abs(th - h) <= 1):
                break
            self.resize(round(self.width() * tw / w), round(self.height() * th / h))
            QApplication.processEvents()

    def _fit_summary(self) -> None:
        t = self.summary
        h = (t.horizontalHeader().height() + sum(t.rowHeight(r) for r in range(4))
             + 2 * t.frameWidth())
        t.setFixedHeight(h)

    def closeEvent(self, event) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("chart_hidden", "0" if self.chart_view.isVisible() else "1")
        super().closeEvent(event)

    def _market(self) -> str:
        return next((c for c, rb in self.market_btns.items() if rb.isChecked()), "0")

    def _unit(self) -> str:
        """ka10051 의 amt_qty_tp — 0 금액, 1 수량."""
        return "1" if self.rb_qty.isChecked() else "0"

    def _unit_changed(self) -> None:
        """단위가 바뀌면 쌓아 둔 값은 못 쓴다 — 금액과 수량을 섞으면 안 된다."""
        self._rows.clear()
        self._prev.clear()
        self._draw()

    def _sector(self) -> str:
        return self.cb_sector.currentData() or ""

    def _market_changed(self) -> None:
        self._fill_sectors()
        self._draw()

    def _toggle_chart(self) -> None:
        shown = not self.chart_view.isVisible()
        self.chart_view.setVisible(shown)
        self.btn_chart.setText("숨기기" if shown else "차트")

    def _fill_sectors(self) -> None:
        """업종 목록은 응답이 준 것을 그대로 쓴다 — 코드를 박아 두면 거래소가 바꿀 때 어긋난다."""
        keep = self._sector()
        self.cb_sector.blockSignals(True)
        self.cb_sector.clear()
        for code, name in self._names.get(self._market(), []):
            self.cb_sector.addItem(f"{code} {name}", code)
        if keep:
            i = self.cb_sector.findData(keep)
            if i >= 0:
                self.cb_sector.setCurrentIndex(i)
        self.cb_sector.blockSignals(False)

    def poll(self) -> None:
        now = datetime.now(SEOUL)
        # 장 밖에서는 누적이 안 움직여 같은 값만 쌓인다. 화면은 두고 조회만 쉰다.
        if not (dtime(9, 0) <= now.time() <= dtime(15, 40)):
            self.status.setText(f"장외 {now:%H:%M:%S}")
            return
        for mkt, name in MARKETS:
            try:
                res = self._client.tr(
                    "ka10051", {"mrkt_tp": mkt, "amt_qty_tp": self._unit(),
                                "base_dt": "", "stex_tp": "3"}, "/api/dostk/sect")
                rows = res.get("inds_netprps") or []
            except Exception as exc:                       # noqa: BLE001
                self.status.setText(f"조회 실패 {name} — {exc}")
                continue
            if not rows:
                continue
            self._names[mkt] = [(r.get("inds_cd", ""), r.get("inds_nm", "")) for r in rows]
            for r in rows:
                key = (mkt, r.get("inds_cd", ""))
                cur = {k: _num(r.get(k, 0)) for k, _ in COLS}
                cur[IDX_KEY] = _num(r.get("cur_prc", 0))   # 0782 '지수보이기' 용
                d = diff(self._prev.get(key), cur)
                self._prev[key] = cur
                hist = self._rows.setdefault(key, [])
                hist.insert(0, (now.strftime("%H:%M:%S"), cur, d))
                del hist[ROWS_SHOWN:]
                # ponytail: 파일에는 종합만 남긴다. 업종까지 전부 적으면 하루 7MB 다.
                # 업종 기록이 재시작 뒤에도 필요해지면 그때 업종별 파일로 쪼갤 것.
                if r.get("inds_cd") in ("001", "101"):
                    self._append(now, r.get("inds_nm", name), cur, d)
        for mkt, _name in MARKETS:
            try:
                got = self._krx.sell_buy(mkt, now.strftime("%Y%m%d"))
            except Exception:                # noqa: BLE001 - 곁다리가 화면을 막으면 안 된다
                got = {}
            if got:
                self._sellbuy[mkt] = got
        if self.cb_sector.count() == 0:
            self._fill_sectors()
        self._draw()
        self.status.setText(f"자동 갱신 {now:%H:%M:%S} · 1분")

    def _append(self, now, name, cum, d) -> None:
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": now.strftime("%H:%M:%S"), "inds": name,
                                     "cum": cum, "delta": d}, ensure_ascii=False) + "\n")
        except OSError:
            pass          # 기록이 화면을 죽이면 안 된다

    # ── 그리기 ────────────────────────────────────────────────────────────
    def _make_table(self, rows: int, header: bool) -> QTableWidget:
        """두 표가 **같은 열 너비**를 픽셀로 갖게 한다 — 이게 정렬의 전부다."""
        t = QTableWidget(rows, len(COLS) + 1)
        t.setHorizontalHeader(TintedHeader(t))
        t.setHorizontalHeaderLabels(["시간"] + [ko for _, ko in COLS])
        t.horizontalHeader().setVisible(header)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(True)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 두 표 다 세로 스크롤바 자리를 잡아 둔다. 한쪽만 생기면 그만큼 밀려 어긋난다.
        t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        h = t.horizontalHeader()
        # 머리글 글자 폭이 곧 열의 최소 너비다 — 기본값이면 "기타금융" 때문에 열이
        # 밀려 뒤쪽 세 개가 화면 밖으로 잘렸다. 최소를 낮춰 11 열이 다 들어오게 한다.
        h.setMinimumSectionSize(44)
        # 시간은 고정, 값 열은 남는 폭을 고르게 나눠 갖는다 — 0782 처럼 표가 창을
        # 꽉 채운다. 두 표의 폭·스크롤바 자리가 같으므로 나눈 결과도 같다.
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        t.setColumnWidth(0, TIME_W)
        for i in range(len(COLS)):
            h.setSectionResizeMode(i + 1, QHeaderView.ResizeMode.Stretch)
        v = t.verticalHeader()
        # 최소가 기본 폰트 높이(24)라 defaultSectionSize 만으로는 21 이 안 된다.
        v.setMinimumSectionSize(ROW_H)
        v.setDefaultSectionSize(ROW_H)
        # Fixed 가 아니면 셀 내용 높이에 맞춰 늘어난다 — 실측 30px 로 0782 의 1.7 배였다.
        v.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        # QHeaderView::section 규칙은 두지 않는다 — 두면 TintedHeader 가 칠한 색을
        # 스타일시트가 덮어 '개인' 분홍이 사라진다.
        t.setStyleSheet(
            f"QTableWidget{{background:{CELL_BG};color:{TEXT};gridline-color:{GRID};"
            f"border:1px solid {BORDER};font-size:{CELL_FONT}px;}}"
            f"QTableWidget::item{{padding:0 4px;}}"
            f"QScrollBar:vertical{{background:#F0F0F0;width:17px;"
            f"border-left:1px solid {GRID};}}"
            f"QScrollBar::handle:vertical{{background:#CDCDCD;"
            f"border:1px solid #A6A6A6;min-height:20px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}")
        hf = t.horizontalHeader().font()
        hf.setPixelSize(CELL_FONT)
        t.horizontalHeader().setFont(hf)
        return t

    @staticmethod
    def _cell(text: str, color: str, bg: str | None = None) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setForeground(QColor(color))
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if bg:
            it.setBackground(QColor(bg))
        return it

    def _draw(self) -> None:
        hist = self._rows.get((self._market(), self._sector()), [])
        self._draw_summary(hist)
        self._draw_table(hist)
        self._draw_chart(hist)

    def _draw_summary(self, hist: list) -> None:
        """0782 위쪽 고정 블록 — 매도 / 매수 / 순매수 / 증감.

        매도·매수는 KRX 라 **시장 전체만** 있다. 업종을 고르면 그 두 줄은 '-' 다.
        """
        cum, d = (hist[0][1], hist[0][2]) if hist else ({}, None)
        whole = self._sector() in ("001", "101")
        sb = self._sellbuy.get(self._market(), {}) if whole else {}
        rows = [("매 도", {k: sb[k][0] for k in sb} if sb else None, False),
                ("매 수", {k: sb[k][1] for k in sb} if sb else None, False),
                ("순매수", cum or None, True),
                ("증감", d, True)]
        for row, (label, vals, signed) in enumerate(rows):
            # 0782 는 라벨 칸만 머리글 색으로 깔고 가운데로 세운다.
            lab = self._cell(label, TEXT, HEAD_BG)
            lab.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.summary.setItem(row, 0, lab)
            for i, (k, _ko) in enumerate(COLS):
                if not vals or k not in vals:
                    it = self._cell("-", ZERO, SUM_BG)
                elif signed:
                    it = self._cell(_fmt(vals[k]), _color(vals[k]), SUM_BG)
                else:
                    # 매도·매수는 방향이 없는 절대금액이다 — 적청으로 칠하면 거짓말이 된다.
                    it = self._cell(f"{vals[k]:,}", TEXT, SUM_BG)
                self.summary.setItem(row, i + 1, it)

    def _draw_table(self, hist: list) -> None:
        self.body.setRowCount(len(hist))
        for r, (t, cum, _d) in enumerate(hist):
            # 0782 는 한 줄 걸러가 아니라 10 분 묶음으로 바탕을 간다 — 14:4x 가 회색
            # 이면 14:3x 는 흰색이다. 분 십의 자리가 홀수인 묶음에 회색을 깐다.
            band = ZEBRA if (t[3:4].isdigit() and int(t[3]) % 2) else CELL_BG
            bg = SEL_BG if r == 0 else band
            tm = self._cell(t, TEXT, bg)
            tm.setTextAlignment(Qt.AlignmentFlag.AlignCenter)   # 0782 는 시각만 가운데
            self.body.setItem(r, 0, tm)
            for i, (k, _ko) in enumerate(COLS):
                self.body.setItem(r, i + 1, self._cell(_fmt(cum[k]), _color(cum[k]), bg))

    def _draw_chart(self, hist: list) -> None:
        """누적 순매수 추이 — 0782 하단 차트와 같은 값이다."""
        self.chart.removeAllSeries()
        for ax in list(self.chart.axes()):
            self.chart.removeAxis(ax)
        old = list(reversed(hist))              # hist 는 최신이 앞이다
        if len(old) < 2:
            return
        lo, hi = 0, 0
        for key, ko in COLS:
            if not self.checks[key].isChecked():
                continue
            s = QLineSeries()
            s.setName(ko)
            s.setPen(QPen(QColor(LINE_COLOR[key]), 1.6))
            for x, (_t, cum, _d) in enumerate(old):
                v = cum[key]
                lo, hi = min(lo, v), max(hi, v)
                s.append(x, v)
            self.chart.addSeries(s)
        if not self.chart.series():
            return
        # 지수는 단위가 순매수와 달라 같은 축에 얹으면 선이 눌린다 — 축을 따로 둔다.
        idx_series = None
        if self.cb_index.isChecked() and old[0][1].get(IDX_KEY):
            idx_series = QLineSeries()
            idx_series.setName("지수")
            idx_series.setPen(QPen(QColor("#000000"), 1.2))
            for x, (_t, cum, _d) in enumerate(old):
                idx_series.append(x, cum.get(IDX_KEY, 0))
            self.chart.addSeries(idx_series)
        ax_x = QCategoryAxis()
        ax_x.setRange(0, len(old) - 1)
        # 눈금을 다 세우면 글자가 겹친다 — 정각만 세운다(0782 도 시(時) 단위다).
        seen_hour = set()
        for i, (t, _c, _d) in enumerate(old):
            hour = t[:2]
            if hour not in seen_hour:
                seen_hour.add(hour)
                ax_x.append(hour, i)
        ax_x.setLabelsPosition(
            QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue)
        ax_y = QValueAxis()
        pad = max(1, int((hi - lo) * 0.08))
        ax_y.setRange(lo - pad, hi + pad)
        ax_y.setLabelFormat("%d")
        small = QFont()
        small.setPixelSize(10)      # 큰 글씨면 '-20,000' 이 '...' 로 잘린다
        for ax, side in ((ax_x, Qt.AlignmentFlag.AlignBottom),
                         (ax_y, Qt.AlignmentFlag.AlignRight)):   # 0782 는 눈금이 오른쪽
            ax.setLabelsFont(small)
            ax.setLabelsColor(QColor(TEXT))
            ax.setTitleBrush(QColor(TEXT))
            ax.setLinePenColor(QColor(GRID))
            ax.setGridLineColor(QColor(GRID))
            self.chart.addAxis(ax, side)
        for s in self.chart.series():
            if s is idx_series:
                continue
            s.attachAxis(ax_x)
            s.attachAxis(ax_y)
        if idx_series is not None:
            ax_i = QValueAxis()
            vals = [p.y() for p in idx_series.points()]
            lo_i, hi_i = min(vals), max(vals)
            pad_i = max(1, (hi_i - lo_i) * 0.15)
            ax_i.setRange(lo_i - pad_i, hi_i + pad_i)
            ax_i.setLabelsVisible(False)
            ax_i.setGridLineVisible(False)
            ax_i.setLinePenColor(QColor(GRID))
            self.chart.addAxis(ax_i, Qt.AlignmentFlag.AlignLeft)
            idx_series.attachAxis(ax_x)
            idx_series.attachAxis(ax_i)


def _font():
    """0782 와 같은 글꼴. 굴림이 없으면 Qt 가 알아서 고른다."""
    f = QFont("Gulim", 9)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def main() -> int:
    # 배율 스케일링을 끈다. 켜 두면 같은 코드가 실행마다 1.0/1.25 로 갈려 행 높이와
    # 창 폭이 25% 씩 달라졌다(실측 21px 이 30px 로). 0782 와 픽셀을 맞추려면 논리=실제여야 한다.
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    demo = "--demo" in sys.argv
    client = None
    if not demo:
        client = Kiwoom()
        if not client.ok:
            print(".env 에 KIWOOM_APPKEY / KIWOOM_SECRETKEY 가 없다", file=sys.stderr)
            return 1
    app = QApplication(sys.argv)
    app.setFont(_font())
    win = Window(client)
    win.show()
    # --shot <경로>: 자기 자신을 찍고 끝낸다. 바깥에서 찍으면 배율 때문에 잘려서
    # 실제 화면을 못 본다(개발용).
    if "--shot" in sys.argv:
        path = sys.argv[sys.argv.index("--shot") + 1]
        for _ in range(8):
            app.processEvents()
        win.grab().save(path)
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
