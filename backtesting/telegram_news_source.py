"""텔레그램 공개 채널(예: First Squawk, @FirstSquaw)의 최신 글을 가져온다.

t.me/s/<channel> 페이지는 텔레그램이 웹사이트 임베드용으로 제공하는 로그인 불필요
공개 미리보기라 API 키나 봇 등록 없이 그대로 GET으로 읽을 수 있다(실측 확인:
https://t.me/s/firstsquaw 가 200 응답, 실제 최근 헤드라인이 그대로 HTML에 들어있음
— 예: "SK HYNIX SETS 2.5% CAP ON SHARE CONVERSIONS TO US ADR: KSD"). 공식 Bot API는
그 채널의 관리자가 우리 봇을 직접 추가해줘야만 메시지를 받을 수 있어(남의 채널이라
불가능) 이 공개 미리보기 페이지가 유일한 무료 경로다. X(트위터)와 달리 텔레그램은
공개 채널에 한해 이런 무인증 웹 미리보기를 제공한다.

페이지 마크업이 바뀌면(텔레그램이 위젯 HTML 구조를 변경하는 경우) 이 파서가 깨질
수 있다 — market_snapshot.py/nasdaq_drop_monitor.py의 다른 소스들과 같은 원칙으로,
실패하면 예외를 올리지 않고 빈 리스트를 반환한다."""
import html
import re

import requests

TELEGRAM_PREVIEW_URL_TEMPLATE = "https://t.me/s/{channel}"
TELEGRAM_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}
DEFAULT_CHANNEL = "firstsquaw"
DEFAULT_POST_LIMIT = 5

# 각 글은 <div class="tgme_widget_message_text js-message_text" ...>내용</div> 바로
# 다음에 <div class="tgme_widget_message_footer ...">가 이어지는 구조가 페이지 전체에
# 일관돼 있어(실측 확인), 이 경계를 기준으로 메시지 하나씩 잘라낸다.
_MESSAGE_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text js-message_text"[^>]*>(.*?)</div>\s*<div class="tgme_widget_message_footer',
    re.S,
)
# 모든 글 끝에 채널 자기소개 서명("(<a href=...>@채널명</a>)")이 붙어 있어 헤드라인
# 텍스트에서 잘라낸다.
_SIGNATURE_RE = re.compile(r'(<br/?>\s*)?\(<a[^>]*>@\w+</a>\)\s*$', re.S)
_LINE_BREAK_RE = re.compile(r"<br\s*/?>")
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_message_text(raw_html: str) -> str:
    text = _SIGNATURE_RE.sub("", raw_html)
    text = _LINE_BREAK_RE.sub(" ", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return " ".join(text.split())


def fetch_telegram_channel_posts(channel: str = DEFAULT_CHANNEL, limit: int = DEFAULT_POST_LIMIT) -> list[str]:
    """channel의 최근 글 텍스트를 최신순으로 최대 limit개 반환. 페이지에는 오래된
    글이 먼저 나오므로 뒤집어서 반환한다. 조회/파싱 실패 시 빈 리스트(다른 헤드라인
    소스 실패 시 알림 자체를 막지 않는 것과 같은 원칙)."""
    url = TELEGRAM_PREVIEW_URL_TEMPLATE.format(channel=channel)
    try:
        res = requests.get(url, headers=TELEGRAM_REQUEST_HEADERS, timeout=10)
        res.raise_for_status()
        posts = [_clean_message_text(m) for m in _MESSAGE_TEXT_RE.findall(res.text)]
        posts = [p for p in posts if p]
        return list(reversed(posts))[:limit]
    except Exception:
        return []
