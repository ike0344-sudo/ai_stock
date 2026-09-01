"""통합(KRX+NXT) 분봉 캐시 경로 — kospi-theme-engine 소유, 여기선 경로만 가리킨다.

1.7GB(1,265종목)를 ai_stock 쪽으로 복사하지 않는다. `kospi-theme-engine/data/cache/
minute_al/`을 그대로 가리키기만 한다. 없으면 **조용히 KRX 전용으로 떨어지지 않고
에러를 낸다** — "무조건 통합(AL)" 규칙(state/agent_mail/data-agent/standing.md,
2026-09-01)을 지키기 위해서다. 실제로 KRX전용 근사를 쓰다 신호 크기와 같은 자릿수의
오차를 만든 사고가 있었다(backtest-agent_20260901-153000).

    from backtesting.minute_store import minute_al_dir
    path = minute_al_dir()   # "kospi-theme-engine/data/cache/minute_al"

이 함수를 어디서 호출해 기존 `os.path.join(data_dir, "stocks", "minute")` 계열
경로를 대체할지는 아직 안 정했다 — `backtesting/*.py` 수정은 lead 승인 후
(data-agent_<날짜시각>_minute_al_bridge.md 의 호출부 목록 참고).

data-agent 실측(2026-09-01, state/agent_reports/data-agent_20260901-1645_minute_al_bridge.md):
- **기간**: KRX전용(data/stocks/minute)보다 짧다. AL·KRX 공통종목 979개 기준
  2026-06-29부터는 거의 전종목이 있다(9개만 결측, 07-01부터는 8개). 그 전으로 갈수록
  결측 종목이 급격히 늘어난다(AL 중앙값 시작일 2026-04-30, KRX 중앙값 2025-08-01) —
  **과거로 갈수록 못 쓴다.**
- **종목**: AL 1,265 vs KRX 1,046, 공통 979. AL전용 286 / KRX전용 67.
- **가격**: 같은 분의 종가는 KRX와 사실상 동일하다(표본 928쌍 중 95%가 완전 일치,
  평균 절대오차 0.008%, 최대 0.7%) — 수익률/가격 기반 신호는 KRX 근사로 큰 문제 없다.
- **거래대금/거래량**: 크게 다르다(120종목 표본, 09:00~10:00 누적거래대금 기준
  중앙값 절대오차 17.5%, 평균 29%, 최대 298%) — NXT 거래가 실제로 더해져서다.
  종목 크기(직전 5일 평균 거래대금)와 깔끔한 상관은 없었다(4분위 중앙값이
  18.6/37.5/9.6/0.0%로 들쭉날쭉 — NXT 참여도가 종목별 특성이지 시가총액 함수가 아님).
  **거래대금 순위·VWAP류 신호는 KRX 근사를 쓰면 안 된다.**
- **결측**: 샘플 80종목 중 4개(5%)가 자기 시작일 이후 구간에 거래일 결측 있음
  (전부 시작일이 이른 종목 — 저유동 종목의 실제 무거래일로 추정, 추가 확인 안 함).
"""
import functools
import os

MINUTE_AL_DIR = os.path.join("kospi-theme-engine", "data", "cache", "minute_al")


def minute_al_dir(path: str = MINUTE_AL_DIR) -> str:
    """통합 분봉 디렉터리 경로. 없으면 FileNotFoundError — 호출부가 조용히 KRX
    전용으로 대체하지 못하게 막는 게 목적이다(그게 실제로 사고 원인이었다)."""
    if not os.path.isdir(path):
        raise FileNotFoundError(
            f"통합(AL) 분봉 캐시가 없다: {path} — KRX 전용 경로로 조용히 대체하지 마라. "
            "kospi-theme-engine/data/cache/minute_al 이 있는지, cwd가 ai_stock 루트인지 확인해라."
        )
    return path


def _first_last_date(path: str) -> tuple[str, str] | None:
    """파일 전체를 읽지 않고 첫 줄·끝 4KB만 봐서 (시작일, 끝일)을 얻는다 —
    kospi-theme-engine/check_minute_refresh.py 와 같은 방식(1,265개 파일을 매번
    통째로 읽으면 느리다)."""
    try:
        with open(path, "rb") as f:
            f.readline()  # header
            first_line = f.readline().decode("utf-8", "replace")
            if not first_line:
                return None
            first_date = first_line.split(",")[0][:10]
            f.seek(0, 2)
            back = min(4096, f.tell())
            f.seek(-back, 2)
            tail = f.read().decode("utf-8", "replace").strip().splitlines()
            if not tail:
                return None
            last_date = tail[-1].split(",")[0][:10]
        return first_date, last_date
    except OSError:
        return None


@functools.lru_cache(maxsize=1)
def coverage(path: str = MINUTE_AL_DIR) -> dict[str, tuple[str, str]]:
    """종목코드 -> (시작일, 끝일). 프로세스당 한 번만 스캔한다(1,265개 파일 head/tail —
    lru_cache 없이 매 호출 스캔하면 `assert_date_covered`를 호출부마다 부르는 게
    부담스러워진다). 캐시를 갱신하려면 `coverage.cache_clear()`."""
    directory = minute_al_dir(path)
    result = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".csv"):
            continue
        dates = _first_last_date(os.path.join(directory, name))
        if dates:
            result[name[:-4]] = dates
    return result


def assert_date_covered(date: str, codes: list[str] | None = None, path: str = MINUTE_AL_DIR) -> None:
    """요청한 날짜(YYYY-MM-DD)가 codes(없으면 전종목)의 통합 분봉 커버리지 안에
    있는지 확인한다. 밖이면 **에러** — "파일은 있는데 그 날짜가 없어서 조용히 빈
    값"이 제일 위험하다는 지시(2026-09-01 lead)에 따라, 무엇이 없어서 못 하는지
    종목·날짜를 메시지에 찍는다."""
    cov = coverage(path)
    targets = codes if codes is not None else list(cov)
    missing = [c for c in targets if c not in cov]
    out_of_range = [c for c in targets if c in cov and not (cov[c][0] <= date <= cov[c][1])]
    if missing or out_of_range:
        detail = []
        if missing:
            detail.append(f"커버리지에 아예 없는 종목 {len(missing)}개(예: {missing[:5]})")
        if out_of_range:
            examples = [(c, cov[c]) for c in out_of_range[:5]]
            detail.append(f"{date}가 범위 밖인 종목 {len(out_of_range)}개(예: {examples})")
        raise ValueError(f"통합(AL) 분봉 커버리지 밖 요청 — {date}: " + "; ".join(detail))


def demo() -> None:
    path = minute_al_dir()
    assert os.path.isdir(path), path
    files = [f for f in os.listdir(path) if f.endswith(".csv")]
    assert len(files) > 1000, f"종목 수가 너무 적다: {len(files)}"

    try:
        minute_al_dir("data/cache/존재하지않는_경로")
        raise AssertionError("없는 경로인데 에러가 안 났다")
    except FileNotFoundError:
        pass

    cov = coverage()
    assert len(cov) == len(files), (len(cov), len(files))
    sample_code, (start, end) = next(iter(cov.items()))
    assert start <= end, (sample_code, start, end)

    assert_date_covered(end, codes=[sample_code])  # 커버리지 안 — 통과해야 함
    try:
        assert_date_covered("1999-01-01", codes=[sample_code])
        raise AssertionError("범위 밖 날짜인데 에러가 안 났다")
    except ValueError:
        pass
    try:
        assert_date_covered(end, codes=["없는코드999999"])
        raise AssertionError("없는 종목인데 에러가 안 났다")
    except ValueError:
        pass

    print(f"minute_store demo ok — {len(files)}종목 확인, 커버리지 {sample_code}={start}~{end}")


if __name__ == "__main__":
    demo()
