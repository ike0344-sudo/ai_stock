"""터널 주소 통보 — 주소가 바뀔 때만, 이번에 띄운 것만.

    python -m pytest tests/backtesting/test_tunnel_job.py -q

무료 quick tunnel 은 띄울 때마다 주소가 바뀐다. 사람이 로그에서 주소를 찾아 읽어야
한다면 자동화한 의미가 없어서, 이 두 가지가 계약이다.
  · 바뀐 주소만 알린다 (매번 울면 알림을 무시하게 된다)
  · 지난 실행의 로그에 남은 주소를 새 주소로 착각하지 않는다
"""
import time

import pytest

import tunnel_job


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(tunnel_job, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(tunnel_job, "URL_FILE", tmp_path / "state" / "url.txt")
    monkeypatch.setattr(tunnel_job, "LOG_PATH", tmp_path / "cloudflared.log")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    return tmp_path


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(tunnel_job, "send_telegram",
                        lambda msg, token, chat, level=None: box.append(msg) or True)
    return box


def _log(sandbox, text):
    tunnel_job.LOG_PATH.write_text(text, encoding="utf-8")


def test_로그에서_주소를_찾는다(sandbox):
    _log(sandbox, "INF 어쩌고\n|  https://abc-def-ghi.trycloudflare.com  |\nINF 저쩌고\n")
    assert tunnel_job.read_url(0) == "https://abc-def-ghi.trycloudflare.com"


def test_지난_실행의_주소를_새것으로_착각하지_않는다(sandbox):
    """로그 파일이 남아 있으면 어제 주소를 오늘 주소로 읽는다."""
    _log(sandbox, "https://old-tunnel.trycloudflare.com")
    future = time.time() + 60          # 이 시각 이후에 쓰인 것만 인정한다
    assert tunnel_job.read_url(future) is None


def test_마지막_주소를_쓴다(sandbox):
    """cloudflared 가 재연결하면 로그에 주소가 여러 번 찍힌다."""
    _log(sandbox, "https://first.trycloudflare.com\n...\nhttps://second.trycloudflare.com\n")
    assert tunnel_job.read_url(0) == "https://second.trycloudflare.com"


def test_주소가_바뀔_때만_알린다(sent):
    tunnel_job.announce("https://one.trycloudflare.com")
    tunnel_job.announce("https://one.trycloudflare.com")
    tunnel_job.announce("https://one.trycloudflare.com")
    assert len(sent) == 1, "같은 주소로 매번 울면 알림을 무시하게 된다"

    tunnel_job.announce("https://two.trycloudflare.com")
    assert len(sent) == 2 and "two" in sent[1]


def test_알림에_접속에_필요한_것이_다_들어간다(sent):
    tunnel_job.announce("https://x.trycloudflare.com")
    body = sent[0]
    assert "https://x.trycloudflare.com" in body
    assert "sophie" in body, "아이디가 없으면 폰에서 못 들어간다"
    assert "SOPHIE_WEB_PASSWORD" in body


def test_비밀번호_자체는_안_보낸다(sent, monkeypatch):
    """텔레그램은 평문으로 남는다 — 어디를 보라고만 알려준다."""
    monkeypatch.setenv("SOPHIE_WEB_PASSWORD", "s3cr3t-do-not-send")
    tunnel_job.announce("https://x.trycloudflare.com")
    assert "s3cr3t-do-not-send" not in sent[0]


def test_텔레그램이_없어도_주소는_남긴다(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    tunnel_job.announce("https://y.trycloudflare.com")
    assert tunnel_job.URL_FILE.read_text(encoding="utf-8") == "https://y.trycloudflare.com"
    assert "y.trycloudflare.com" in capsys.readouterr().out


def test_cloudflared_를_못_찾으면_알려준다(monkeypatch):
    monkeypatch.setattr(tunnel_job.shutil, "which", lambda _: None)
    monkeypatch.setattr(tunnel_job, "CLOUDFLARED_CANDIDATES", ())
    assert tunnel_job.cloudflared_path() is None
    with pytest.raises(SystemExit):
        tunnel_job.main()
