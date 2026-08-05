import pytest

from fetch_chart import find_records


def test_find_records_raises_clear_error_on_api_return_code_failure():
    # 실측 회귀 테스트 — API가 200 OK로 응답하면서 return_code!=0(토큰 만료 등 자체
    # 오류)를 실어 보내면, 이전에는 이 체크가 없어 "레코드 리스트를 찾지 못했습니다"만
    # 보여서 진짜 원인(토큰/레이트리밋 등)을 알 수 없었다(strategy_1 실계좌 로그에서
    # "확인 중 오류 - 응답에서 차트 레코드 리스트를 찾지 못했습니다"가 종목당 수백 번
    # 반복된 원인으로 실측 확인).
    payload = {"return_code": 3, "return_msg": "유효하지 않은 토큰입니다"}

    with pytest.raises(RuntimeError, match="유효하지 않은 토큰입니다"):
        find_records(payload)


def test_find_records_still_works_when_return_code_absent():
    # 테스트 픽스처처럼 return_code를 안 실은 페이로드는 그대로 키 탐색으로 넘어간다.
    payload = {"stk_min_pole_chart_qry": [{"cur_prc": "+100"}]}

    assert find_records(payload) == [{"cur_prc": "+100"}]


def test_find_records_allows_return_code_zero_with_empty_list():
    # 정상 응답인데 그 구간에 실제로 봉이 없는 경우(신규상장 등)는 에러가 아니다.
    payload = {"return_code": 0, "return_msg": "정상적으로 처리되었습니다", "stk_min_pole_chart_qry": []}

    assert find_records(payload) == []
