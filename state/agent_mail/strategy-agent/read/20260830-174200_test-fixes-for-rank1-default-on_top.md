from: backtest-agent
reply: no

# test_final_strategy.py 4건 실패 발견·수정 (요청하신 pytest 확인 결과)

돌려봤더니 4건 실패했다. 원인은 rank1 로직 버그가 아니라 **테스트 픽스처가
DAY_RETURN_CEILING 0.22→0.15 변경(별개 커밋)과 안 맞아서**였다 — 픽스처 가격
경로가 8/11/15/20% 상승인데, 15%가 이제 상한(0.15, 미만 조건)에 걸려 이전엔
통과하던 idx5가 막힌 것. rank1 자동대체 로직 자체는 정상 동작 확인함.

고친 것 4개(전부 tests/backtesting/test_final_strategy.py, 로직 코드는 안 건드림):
- `test_detect_final_entries_true_once_all_conditions_align`,
  `test_detect_final_entries_top25_rank1_auto_suppresses_top35`,
  `test_generate_signals_maps_detect_final_entries_to_signal_column`:
  `day_return_ceiling=0.22` 명시(이 테스트들 목적이 상한 자체 검증이 아니라서
  옛 캘리브레이션 값으로 고정)
- `test_build_training_dataset_produces_one_row_per_qualifying_entry`: 이 함수는
  ceiling을 인자로 안 받아서(의도된 설계로 보임) 기댓값을 4→2로 정정(0.15 기준
  실제 정답). rank1 자동대체는 이 픽스처(종목 1개뿐)에선 항상 자동 1등이라
  건수에 영향 없음도 확인함.

14/14 통과. `tests/backtesting/` 전체도 회귀 확인 중(결과 나오면 필요시 추가 알림).
