from backtesting import telegram_news_source
from backtesting.telegram_news_source import fetch_telegram_channel_posts


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _widget_page(posts_oldest_first: list[str]) -> str:
    """실측(t.me/s/firstsquaw)에서 확인한 구조를 그대로 재현 — 메시지 텍스트 div
    바로 뒤에 footer div가 이어지고, 끝에는 항상 (<a>@채널명</a>) 서명이 붙는다."""
    blocks = []
    for text in posts_oldest_first:
        blocks.append(
            f'<div class="tgme_widget_message_text js-message_text" dir="auto">{text}'
            f'<br/>(<a href="https://t.me/firstsquaw" target="_blank">@firstsquaw</a>)</div>\n'
            f'<div class="tgme_widget_message_footer compact js-message_footer">...</div>'
        )
    return "<html><body>" + "\n".join(blocks) + "</body></html>"


def test_fetch_telegram_channel_posts_returns_newest_first(monkeypatch):
    page = _widget_page(["OLDEST HEADLINE", "MIDDLE HEADLINE", "NEWEST HEADLINE"])
    monkeypatch.setattr(
        telegram_news_source.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(page),
    )

    posts = fetch_telegram_channel_posts("firstsquaw")

    assert posts == ["NEWEST HEADLINE", "MIDDLE HEADLINE", "OLDEST HEADLINE"]


def test_fetch_telegram_channel_posts_strips_signature_and_html_tags(monkeypatch):
    page = _widget_page(["SK HYNIX SETS 2.5% CAP<br/>ON SHARE CONVERSIONS: <b>KSD</b>"])
    monkeypatch.setattr(
        telegram_news_source.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(page),
    )

    posts = fetch_telegram_channel_posts("firstsquaw")

    assert posts == ["SK HYNIX SETS 2.5% CAP ON SHARE CONVERSIONS: KSD"]
    assert "@firstsquaw" not in posts[0]
    assert "<" not in posts[0]


def test_fetch_telegram_channel_posts_unescapes_html_entities(monkeypatch):
    page = _widget_page(["EU&#39;S VON DER LEYEN: BAN LIST &amp; MORE"])
    monkeypatch.setattr(
        telegram_news_source.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(page),
    )

    posts = fetch_telegram_channel_posts("firstsquaw")

    assert posts == ["EU'S VON DER LEYEN: BAN LIST & MORE"]


def test_fetch_telegram_channel_posts_respects_limit(monkeypatch):
    page = _widget_page([f"HEADLINE {i}" for i in range(10)])
    monkeypatch.setattr(
        telegram_news_source.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse(page),
    )

    posts = fetch_telegram_channel_posts("firstsquaw", limit=3)

    assert posts == ["HEADLINE 9", "HEADLINE 8", "HEADLINE 7"]


def test_fetch_telegram_channel_posts_returns_empty_list_on_request_failure(monkeypatch):
    def raise_error(url, headers=None, timeout=10):
        raise RuntimeError("network down")

    monkeypatch.setattr(telegram_news_source.requests, "get", raise_error)

    assert fetch_telegram_channel_posts("firstsquaw") == []


def test_fetch_telegram_channel_posts_returns_empty_list_when_no_messages_found(monkeypatch):
    monkeypatch.setattr(
        telegram_news_source.requests, "get",
        lambda url, headers=None, timeout=10: _FakeResponse("<html><body>no messages here</body></html>"),
    )

    assert fetch_telegram_channel_posts("firstsquaw") == []
