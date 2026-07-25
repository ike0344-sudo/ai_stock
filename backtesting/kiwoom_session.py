"""대시보드 프로세스 전체가 공유하는 단일 KiwoomClient.

market_snapshot.py/account_status.py처럼 각자 폴링하는 패널이 저마다 별도
KiwoomClient를 쓰면, 각 클라이언트는 "자기 자신의 이전 호출"과만 1.1초 간격을
지키고 다른 클라이언트가 언제 호출했는지는 전혀 모른다 — 그래서 두 패널의 요청이
우연히 겹치면 계정 단위로 걸리는 것으로 보이는 키움 rate limit을 넘겨 429가 난다
(실측: market_snapshot 폴링을 1~2초로 당긴 뒤 두 클라이언트를 동시에 돌리면 토큰
발급(oauth2/token) 요청 자체가 429 — TR 호출이 아니라 인증 단계에서부터 걸림).

대시보드 안의 모든 Kiwoom 호출이 이 모듈의 get_client()로 같은 인스턴스를
공유하면, 프로세스 내에서는 KiwoomClient 자체의 페이싱(_throttle)이 전역적으로
적용돼 겹침이 원천 차단된다. run-trading(별도 프로세스로 실행되는 실전매매 봇)과의
겹침까지는 막지 못한다 — 그건 프로세스 간 조율이 필요해 범위 밖.
"""
import threading

from kiwoom_client import KiwoomClient

_lock = threading.Lock()
_client: KiwoomClient | None = None
_client_key: tuple[str, str, bool] | None = None


def get_client(appkey: str, secretkey: str, is_mock: bool) -> KiwoomClient:
    """appkey/secretkey/is_mock이 이전 호출과 다르면 새 클라이언트로 교체한다 —
    그렇지 않으면 목/실전 전환이나 키 교체 후에도 첫 호출 때의 예전 자격증명을
    가진 클라이언트를 계속 돌려주게 된다."""
    global _client, _client_key
    key = (appkey, secretkey, is_mock)
    with _lock:
        if _client is None or _client_key != key:
            _client = KiwoomClient(appkey, secretkey, is_mock=is_mock)
            _client_key = key
        return _client
