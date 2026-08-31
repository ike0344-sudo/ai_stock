# 편지 처리: 장시작60분 테마순위 가설 주제 지정 — 검증 결과 + 내 앞선 리포트 정정

편지: `state/agent_mail/strategy-agent/20260831-1905_theme_rank_hypothesis.md` (lead) → 처리 후 read/ 로 이동.

## 1. data-agent 감사(`data-agent_20260831-2015_theme_rank_source_audit.md`) 독립 검증

편지 지시대로 결론을 그대로 받아쓰지 않고 코드/파일을 직접 열어 재확인했다.

| 감사 주장 | 검증 방법 | 결과 |
|---|---|---|
| (a) flow_speed 기준선이 "그 날짜 이전 20일"이 아니라 "지금 시점 최근 20일" 고정값 | `app/reference/baseline.py:97` `days = sorted(daily)[-lookback:]` 직접 열람 | **일치** |
| (b) themes.csv가 날짜 구분 없는 단일 스냅샷 | `app/reference/store.py:28,126` `THEMES_FILE = "themes.csv"` | **일치** |
| (c) `highs` 필드가 원본 아카이브에 아예 없음 | `rank_timeline_20260803.json`에서 `"highs"` grep → 0건. `rank_timeline.py:196-204` frame 작성부 열람 → 키가 정확히 `t/chgtop/rows`뿐, `rows[i]`는 `theme/score/rise/speed/leader/lead_pct/top` 7개뿐 | **일치, 원본 코드로 재확인 완료** |

세 항목 다 감사 결론과 일치 — gate (1) "look-ahead 실패"는 아니므로 주제는 유효, 편지 지시대로 진행한다.

## 2. 검증 중 발견 — 내 앞선 리포트(17:15)가 틀렸다

`strategy-agent_20260831-171500_kospi-theme-score-review.md`에서 가중치 표를
`app/config.py`의 `DEFAULTS`(value_rank 22 / share_ratio 11 / relative_volume 9 / rise_strength 20 / ...)로
적었는데, **이건 코드 기본값일 뿐 실제 적용값이 아니다.** `config.yaml`이 이를 override하고,
2026-08-22 재구성(커밋 `fcdb756`)이 지금도 유효하다:

| 항목 | 내가 17:15에 쓴 값 | 실제(config.yaml, 지금도 유효) |
|---|---|---|
| value_rank | 22 | **30** |
| rise_strength | 20 | **27** |
| value_share | 13 | **18** |
| flow_speed | 12 | **14** |
| rising_ratio | 7 | **8** |
| new_high | 6 | **3** |
| share_ratio | 11 | **0 (완전 제외)** |
| relative_volume | 9 | **0 (완전 제외)** |

`value_rank_cap`도 2.0(자리가중합)이 아니라 3.0(개수기준, `value_rank_weights: [1]*20`로 평탄화)이 적용 중.
41일 아카이브는 08-29 20:11~20:22 배치 재계산본이라 **이 새 가중치로 만들어졌다** — data-agent
감사 결론(2번, "레짐 분할 없음")과 부합하고, 원본은 옳다. 틀린 건 내 리포트의 가중치 표뿐이다.
config.yaml/config.py 어느 쪽도 손대지 않았다(읽기만 함).

### 가설 설계에 미치는 영향
- "지금 돈이 어디에"(value_rank 30 + value_share 18 = 48점)가 "오르고 있나"(rise_strength 27 +
  rising_ratio 8 + new_high 3 = 38점)보다 여전히, 그리고 더 크게 앞선다 — 17:15 리포트의 방향성
  결론(value_rank 최대비중)은 안 틀렸고 오히려 강화됨.
- 다만 "baseline 대비 배수 두 축(share_ratio+relative_volume)이 20점 기여"라던 서술은 **지금은
  틀렸다(0점, 완전 제외)** — 이 둘은 지금 스코어에 어떤 영향도 안 준다. 가설 축 1("레벨 대신
  09:01→10:00 변화가 신호인가")을 설계할 때 이 두 항목을 근거로 끌어오면 안 된다.
- `highs` 축(가설 후보 4번)은 원본에 데이터 자체가 없다(위 1-c). 별도 추출 스크립트 없이는
  사전등록도 측정 의뢰도 불가능 — 이 축은 이번 라운드에서 제외하거나, 추출 스크립트를
  data-agent에 별도 의뢰해야 한다(이건 내 소관 밖).

## 3. 처리 결과
- 편지 이동 완료(read/).
- gate (1) 실패 아님 → 편지 지시대로 큐 항목 #12("가설 3개 제안") 진행 가능. 다음 라운드에서
  후보 3축 중 `highs` 제외한 3개(09:01→10:00 변화, chgtop 고정성, 대장주 vs 2등주)로 사전등록
  초안 작성 예정.
- 17:15 리포트는 **삭제하지 않고** 이 파일을 정정 근거로 남긴다 — 원본 상단에 [정정] 배너
  추가 완료(이 리포트 작성과 같은 turn에 처리).
