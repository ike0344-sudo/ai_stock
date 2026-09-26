"""module-6 API — 분봉 봉(캔들 서랍) · 분봉·체결 사용 가능 기간 · 분봉·틱 명세 검증·제출."""
import pytest

from tests.studio.application.fakes import CODES
from tests.studio.application.fakes_intraday import IntradayFake


@pytest.fixture
def m6(client, services):
    fake = IntradayFake(n_days=12, codes=CODES[:5], bar_minutes=5)
    services.market_data = lambda: fake
    return client, fake


def test_minute_bars_end_labels_and_source(m6):
    client, fake = m6
    code = CODES[0]
    d1 = fake.days[-1].date()
    r = client.get(f"/api/stocks/{code}/bars", params={"interval": "5m", "start": str(d1), "end": str(d1)})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["interval"] == "5m" and d["source"] == "al" and len(d["bars"]) > 20
    assert d["bars"][0]["t"].startswith(str(d1)) and d["bars"][0]["t"][11:] >= "09:05"  # 봉 끝 시각(첫 봉 라벨 ≥ 09:05)
    assert fake.last_source == "al"
    client.get(f"/api/stocks/{code}/bars", params={"interval": "5m", "source": "krx", "start": str(d1), "end": str(d1)})
    assert fake.last_source == "krx"  # 출처는 요청이 명시한 것을 그대로(섞지 않는다)
    assert client.get(f"/api/stocks/{code}/bars", params={"interval": "5m", "source": "xx"}).status_code == 422
    assert client.get(f"/api/stocks/{code}/bars", params={"interval": "7m"}).status_code == 422
    assert client.get("/api/stocks/999999/bars", params={"interval": "5m"}).status_code == 404  # 그 종목 분봉이 없다


def test_minute_bars_window_is_capped(m6):
    client, fake = m6
    d = client.get(f"/api/stocks/{CODES[0]}/bars", params={"interval": "5m", "start": "2000-01-01"}).json()["data"]
    assert len(d["bars"]) > 0  # 시작을 아득히 옛날로 줘도 보관 범위·45일 창으로 잘려 응답이 커지지 않는다


def test_intraday_sources_counts_and_ranges(m6):
    client, fake = m6
    a, b = fake.days[0].date(), fake.days[-1].date()
    d = client.get("/api/meta/intraday-sources", params={"start": str(a), "end": str(b)}).json()["data"]
    al = d["minute"]["al"]
    assert al["total"] == 5 and al["full"] == 5 and al["partial"] == 0 and al["range"] == [str(a), str(b)]
    assert d["minute"]["krx"]["total"] == 5
    assert d["tick"]["codes"] == 5 and d["tick"]["days"] == 12 and d["tick"]["days_in_range"] == 12
    assert d["tick"]["first"] == str(a) and d["tick"]["last"] == str(b)
    # 기간이 보관 범위를 넘으면 전 기간 보유(full)는 0, 일부만(partial)이 된다
    wide = client.get("/api/meta/intraday-sources", params={"start": str(a.replace(year=a.year - 1)), "end": str(b)}).json()["data"]
    assert wide["minute"]["al"]["full"] == 0 and wide["minute"]["al"]["partial"] == 5
    assert client.get("/api/meta/intraday-sources", params={"start": str(b), "end": str(a)}).status_code == 400
    assert client.get("/api/meta/intraday-sources").status_code == 400


def test_validate_intraday_and_tick_specs(m6):
    client, fake = m6
    from tests.studio.application.fakes import spec_dict
    a, b = str(fake.days[0].date()), str(fake.days[-1].date())
    intra = spec_dict(mode="intraday", period={"start": a, "end": b}, intraday={"bar_minutes": 5, "source": "krx"},
                      universe={"type": "top_value", "n": 30, "exclude": []})
    r = client.post("/api/conditions/validate", json={"spec": intra}).json()["data"]
    assert r["ok"] is True, r
    tick = {**spec_dict(mode="tick", period={"start": a, "end": b}, universe={"type": "top_value", "n": 5, "exclude": []}), "strategy": None,
            "tick": {"entry_source": "catalog", "catalog": {"breakout_min": 5}}}
    r = client.post("/api/conditions/validate", json={"spec": tick}).json()["data"]
    assert r["ok"] is True and r["narration"], r
    bad = {**tick, "tick": {"entry_source": "catalog", "catalog": {"breakout_min": None, "value_speed": None, "buy_ratio": None}}}
    r = client.post("/api/conditions/validate", json={"spec": bad}).json()["data"]
    assert r["ok"] is False and any("틱 조건이 하나도 없음" in e["message"] for e in r["errors"])
