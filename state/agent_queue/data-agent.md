# data-agent 큐

- [x] 체결(ka10079) 수집 8/03~8/28, 115종목 (사용자 지시로 117종목으로 확장, 117/117 완료)
- [x] 수집 완료 후 전수 검증 — 종목별 19일치 존재, 체결가 범위가 그 종목 주가대와 일치 (완전성 0건 이상, 가격범위 이상 2건 발견·원인규명, tick_verify_full.py)
- [x] 자동 등록은 보류(사용자 결정, 명확한 필요 사례 아직 없음) — 상시화 필요시 대비 요구사항 문서 작성 완료(state/agent_reports/data-agent_tick_daily_requirements.md), 등록은 안 함
- [x] 162종목(ratio 0.05~0.5) 분봉 결손 재수집 여부 판단 — 영향 미미하면 보류 유지 (판단: 보류 유지, 근거는 기존 분석 그대로 — state/agent_reports/data-agent_20260830-162800.md)

- [x] NXT 체결 포함 여부 — 위 stex_tp 결론은 **뒤집힘(2026-08-30 저녁)**. stex_tp
      파라미터가 아니라 종목코드 접미사(`_AL`=통합, `_NX`=NXT전용, 접미사없음=KRX전용)로
      실제로 갈렸다(사용자 발견, 코드로 재확인 완료). ka10079/ka10080 둘 다 접미사
      기준으로 동일하게 동작함을 스모크 테스트로 확인. 지금 통합(`_AL`) 재수집 진행
      중 — state/agent_reports/data-agent_20260830-174500_NXT측정.md

- [x] ka10032(거래대금상위, screener 가 쓰는 TR)가 NXT 를 포함하는지 확인
      결론: **통합(KRX+NXT) 기준 확정.** 48종목 표본, ka10032 정규장순증가분 vs
      `_AL`(통합) 분봉누적 오차 중앙값 -5.4%(거의 일치) vs KRX전용 대비는 +58.9%
      (완전히 어긋남). 실거래 screener는 이미 NXT를 보고 있었고 어긋난 건 백테스트
      (KRX전용 틱)뿐이었음 — state/agent_reports/data-agent_20260830-174500_NXT측정.md

- [x] 실시간체결(0B) 푸시의 27/28 필드(매도/매수 최우선호가)가 실제로 오는지 실측
      확인 — **둘 다 온다** (7틱 전수, 27≥10≥28 정상 스프레드). 최소 변경 설계 작성
      완료(parse_tick/get_latest_ask 대칭 추가), merge 여부는 lead 판단 대기 —
      state/agent_reports/data-agent_20260831-163700_0B_2728_실측.md. 배경: 새
      웹소켓 연결·새 앱키 없이 지금 도는 소피증권 0B 구독에서 이미 받고 있을 가능성
      — REG 메시지의 type/data가 배열이라 프로토콜상 여러 타입 구독을 이미 전제함.
      스캘핑 가설C(누적 주문흐름 불균형)가 틱룰 근사 대신 진짜 Lee-Ready를 쓸 수
      있게 됨. monitoring-agent가 병행 확인하는 웹소켓 충돌 여부와도 연결됨(새
      연결 아니면 충돌 자체가 없음, 다만 소피증권 웹소켓이 실제로 도는지는 별도
      확인 필요). **우선순위 낮음 — 통합(_AL) 재수집 완료 후 착수.** 켜는 것은
      사용자 승인 후.

- [x] (backtest-agent 요청, 사용자 직접지시 2026-09-24) **통합(_AL) 틱 09-21~09-23 3거래일 추가 수집** — 완료 2026-09-24 21:05. **519/519 (173종목 x 3일), 결측 0, 실패 0.** 유니버스는 168+신규리더5=173 상위집합(9월 홀드아웃은 126이라 필요하면 걸러 쓸 것). 스키마·역시간순·08:00~20:00 전구간 기존과 동일 확인 — state/agent_reports/data-agent_20260924-2105_tick_0921_0923.md

      **왜 필요한가**: `leader_20pct` 규칙(+10% 도달 시 누적대금 ≤82.4억 매수 → +20% 익절)이
      3라운드 스트레스 테스트를 대부분 통과했는데, **홀드아웃 증거가 9월 63건 하나뿐**이라
      확정을 못 하고 있다. 8월 OOS(+0.20%)는 상위 2건을 빼면 -0.73%로 뒤집혀 증거에서 제외했다
      (state/agent_reports/backtest-agent_20260924-105404_leader_20pct_round3.md §2-(3)).
      **3거래일이 더 오면 독립 홀드아웃을 하나 더 만들 수 있다.** 지금 표본으론 더 짜낼 게 없다.

      **정확히 무엇을**:
      - 대상 날짜: **2026-09-21(월), 09-22(화), 09-23(수) — 3거래일뿐**.
        (사용자 지시는 "09-19~09-23"이었으나 09-19는 토·09-20은 일요일로 장이 없다.
        일봉 캐시로 확인함. 09-24는 오늘이라 장 마감 후 별도 판단.)
      - 대상 종목: `data/stocks/tick_al/` 기존 **168종목 전부**(기존 수집과 같은 유니버스여야
        비교가 성립한다. 유니버스를 바꾸면 9월 결과와 직접 비교가 깨진다).
      - 저장 위치·형식: 기존과 동일 `data/stocks/tick_al/<code>/<YYYY-MM-DD>.parquet`,
        컬럼 `time`(HHMMSS 문자열)/`cur_prc`/`trde_qty`/`pred_pre_sig`, **원본 역시간순 유지**.
      - 참고 스크립트: 루트 `tick_collect_804_828_al.py`(START_DATE/END_DATE 상수만 바꾸면
        되는 구조). 레이트리밋 대기·장중 일시정지 로직이 이미 들어 있다.

      **주의(수집 방식은 data-agent 판단, 아래는 내가 아는 제약만 전달)**:
      - ka10079 조회창이 **20거래일**이라고 `data/stocks/tick_al/README.md`에 적혀 있다.
        09-21~23은 3거래일 전이라 창 안이지만, **늦어질수록 위험하므로 우선순위 높게** 부탁한다.
      - README 경고대로 원본은 08:00~20:00 전체가 담긴다. **정규장 필터는 소비하는 쪽
        (백테스트)에서 하므로 수집 단계에서 자르지 말 것** — 기존 8·9월 데이터와 형식을
        맞춰야 한다.
      - 키움 REST 429는 계정 단위라 앱키를 나눠도 총량이 안 나뉜다(기존 메모).

      **완료 판정(내가 확인할 것)**: 3일 × 168종목 중 실제로 받아진 파일 수, 종목별 결측,
      그리고 기존 날짜와 같은 스키마인지. 결측이 있으면 몇 종목인지만 알려주면 된다
      (전량 아니어도 분석은 가능하다 — 다만 몇 개가 빠졌는지는 리포트에 적어야 한다).

      급하지 않으면 다른 지시가 우선이다. 다만 **조회창 20거래일 제약 때문에 무한정
      미룰 수는 없다**는 점만 감안해달라.

- [>] (**보류 2026-09-26 — 사용자: "호가수집은 새로운 서버 만들고 그때 하자". 설계안은 `state/agent_reports/data-agent_20260926-0900_orderbook_plan.md` 에 보존. 새 서버 전엔 켜지도 시험하지도 마라**) (backtest-agent 요청, **사용자 승인 2026-09-24**) **호가(ka10004) 상시 수집 시작 + 틱 자동수집 상시화 확인**

      사용자가 "데이터 늘리기 → 호가 수집 → NautilusTrader 검토" 3단계를 승인했다.
      그중 수집 부분만 여기 넘긴다(분석/이식은 내 쪽).

      **(A) 호가 수집 시작 — 우선순위 높음**
      이미 `backtesting/orderbook_collector.py`가 있고, 그 docstring에 핵심이 적혀 있다:
      **"호가는 과거 이력을 조회하는 API가 없다 — 지금부터 직접 쌓아야 나중에 쓸 수 있다."**
      즉 **오늘 안 켜면 오늘 데이터는 영영 없다.** 틱과 달리 20거래일 소급도 불가능하다.
      - 파서 스켈레톤도 이미 있다(`backtesting/orderbook_parser.py`, 2026-08-30 작성).
        확정된 필드는 `stock_code`/`received_at`/`buy_fpr_bid`/`sel_fpr_bid`뿐이고
        2~10단은 미확인이라 NULL로 둔 상태 — **실제 수신 데이터가 쌓이면 그때 맵만 채우면 된다.**
      - 대상 종목·폴링 주기·저장 경로는 data-agent 판단. 다만 **분석에 쓰려면 최소한
        "언제·어느 종목·1~10단 호가와 잔량"이 시각과 함께 남아야** 한다.
      - 실시간 구독을 밀어내지 않도록 앱키 분리는 기존 관례(배치/수집용 별도 앱키) 따라달라.

      **왜 필요한가**: 지금 체결(틱)만 있어서 "사려는 사람이 얼마나 쌓여 있는지"를 못 본다.
      12번의 측정에서 반복해 걸린 벽이 **비용 0.52% > 신호 크기**인데, 호가가 있으면
      (1) 실제 체결 가능 가격을 정확히 알아 비용 추정이 정밀해지고
      (2) 매물벽 소화 같은 가설을 직접 검증할 수 있다(지금은 체결로 간접 추정만 했다).

      **(B) 틱 자동수집 상시화 확인**
      `data/stocks/tick_al/`에 9월치가 09-18까지 매일 들어와 있는 걸로 보아 자동수집이
      돌고 있는 듯한데, **09-19 이후가 비어 있다.** 멈춘 건지, 주기가 긴 건지 확인해달라.
      앞서 요청한 09-21~23 3거래일 수집과 같이 처리하면 된다.
      **틱은 조회창 20거래일이라 놓치면 복구 불가**다 — 상시화가 안 돼 있으면 그게 가장 시급하다.

      **완료 판정(내가 확인할 것)**: 호가는 하루치라도 쌓이면 스키마를 확인해 파서 맵을
      채우고, 그때부터 분석 설계를 시작하겠다. 틱은 09-21~23 파일 존재 여부.

- [x] (backtest-agent 제안, **사용자 직접지시 2026-09-24 "변환 시켜"**) **분봉 CSV → parquet 전환** — 완료 2026-09-24. 1,055/1,055 변환, 전수검증 불일치 0건, 3.23GB→0.96GB(70%↓), 원본 CSV 보존. `data_loader._read_local` 에 mtime 가드 추가(낡은 parquet이 조용히 읽히는 문제 발견·차단) — state/agent_reports/data-agent_20260924-1955_minute_parquet_migration.md

      **순서 안내**: 위 호가 항목(66행)이 먼저다 — 호가는 과거 조회 API가 없어
      지금 안 켜면 그 시간대가 영원히 비지만, 이 변환은 언제 해도 결과가 같다.
      다만 호가는 "켜두고 쌓이길 기다리는" 일이라 **이 변환과 병행해도 된다.**

      **요청 범위: `data/stocks/minute/` 1,055개 CSV만.** 나머지는 건드리지 말 것.

      **왜 이 범위인가 — 전부 바꾸면 오히려 느려진다(실측):**

      | 대상 | 파일당 크기 | 용량 절감 | 읽기 속도 | 판정 |
      |---|---|---|---|---|
      | **분봉 minute/** | 3.1 MB | **81% ↓** (3.25GB → 0.60GB) | **2.8배 빠름** | **전환 권장** |
      | 일봉 daily/ | 55 KB | 54% ↓ | **5배 느림** | 전환 금지 |
      | 월봉 monthly/ | 13 KB | 13% ↓ | **10배 느림** | 전환 금지 |

      작은 파일은 parquet 메타데이터 오버헤드가 본문보다 커서 손해다. pandas
      `read_csv`/`read_parquet` 60~12개 표본 실측(zstd 압축, 2026-09-24).
      **"parquet이 무조건 좋다"가 아니라 파일이 클 때만 좋다.**

      **기대 효과**: 디스크 **2.65GB 절감**(전체 data 4.1GB의 65%), 분봉 읽기 2.8배.
      분봉은 백테스트에서 가장 자주·가장 많이 읽는 데이터다(292거래일×1,055종목 스캔).

      **코드 영향은 거의 없다**: 읽는 쪽이 `pd.read_csv` → `pd.read_parquet` 한 줄.
      pandas를 polars로 바꾸자는 얘기가 아니다(그건 220개 파일이라 반대했다).

      **주의사항 (내가 겪은 사고 기준)**:
      - **원본 CSV를 지우지 말고 남겨달라.** 소피증권 데이터 보존 원칙과 같은 이유이고,
        전환 후 값이 같은지 대조할 기준이 필요하다.
      - **dtype 고정**: CSV는 매번 타입을 추측하지만 parquet은 저장 시점 타입이 박힌다.
        지금 분봉 CSV에 종목코드 컬럼은 없어 앞자리 0 문제는 없음을 확인했다(코드는 파일명에 있음).
        날짜/시각 컬럼 타입만 확정해서 넣어달라.
      - **전환 후 전수 대조**: 무작위 표본이 아니라 전체 1,055개에 대해 행수·컬럼·
        합계가 같은지 확인. 조용히 틀리는 종류라 눈으로는 안 보인다.
      - 압축은 zstd로 쟀다. 다른 걸 쓰면 절감률이 달라진다.

      **이건 내 영역이 아니라서 올린다** — 저장 구조를 바꾸면 수집·백필에 영향이 가고,
      그건 data-agent 판단이다. 하지 않기로 해도 된다. 다만 그 경우
      "분봉 3.1GB를 CSV로 계속 둔다"가 의식적 선택이라는 것만 기록해달라.

      **같이 검토할 것(소피증권, 우선순위 낮음)**: `kospi-theme-engine/` CSV 2,072개 중
      **1MB 이상 79개만** 같은 이유로 후보다(`results/score_audit.csv` 20.6MB →
      5.7MB, 73% 절감·2.7배 실측). 나머지 1,993개는 작아서 전환하면 손해다.
      소피 데이터는 삭제 금지·압축 보관 원칙이 걸려 있으니 원본 유지 필수.

      **완료 판정(내가 확인할 것)**: `data/stocks/minute/`에 parquet이 생기고 원본 CSV가
      남아 있을 것, 무작위 20종목에서 CSV와 parquet의 행수·종가 합계 일치.

      **[추가 2026-09-24 · 읽는 쪽 준비 완료 + 필수 조건 1건]**

      **읽는 쪽은 내가 이미 고쳐놨다.** `backtesting/data_loader._read_local`이
      **parquet이 있으면 parquet을, 없으면 CSV를** 읽는다(전환 중 공존해도 동작).
      그러니 **파일만 만들면 즉시 효과가 난다 — 읽는 코드를 기다릴 필요 없다.**
      회귀 테스트 4건 추가(parquet 읽기 / CSV와 값 동일 / 전환 중 parquet 우선 /
      기존 CSV 경로 유지), `tests/backtesting/` **1,051건 전부 통과** 확인.

      **★ 필수 조건: 날짜를 인덱스로 저장해달라.**
      `_resample_minute`이 `df.index.normalize()`로 날짜별로 잘라 리샘플한다
      (하루 경계를 안 지키면 전날 15:29와 다음날 09:00이 한 봉에 섞인다 — 이걸 막는
      회귀 테스트가 이미 있다). 그래서 parquet이 **인덱스를 잃으면 조용히 깨진다.**
      - 권장: `df.to_parquet(path)` — pandas는 인덱스를 보존한다(내가 테스트로 확인).
      - 인덱스를 컬럼으로 풀어 저장하면 안 된다. 굳이 그래야 하면 미리 알려달라,
        읽는 쪽에서 `set_index`를 하도록 내가 맞추겠다.
      - 검증 한 줄: `pd.read_parquet(p).index.dtype` 이 `datetime64[ns]` 여야 한다.

      **[검증기 제공 2026-09-24] 완료 판정을 직접 돌려볼 수 있게 만들어 뒀다.**

      ```
      python tools/verify_parquet_migration.py data/stocks/minute
      ```

      **표본이 아니라 전수로** CSV↔parquet을 대조하고, 종료코드 0이면 통과다.
      잡아내는 사고 4종(전부 실제로 동작 확인함):
      - **인덱스가 날짜가 아님** ← 위 필수조건 위반. `reset_index()` 후 저장하면 걸린다
      - 행 수 불일치 / 컬럼 불일치 / 값 불일치

      원본 CSV가 있어야 대조가 되니 **변환 후 이 스크립트를 통과시킨 다음에**
      CSV 정리 여부를 판단해달라(지우라는 뜻은 아니다 — 판단은 data-agent 몫).
      불일치가 나오면 파일명과 이유가 같이 찍히니 그대로 알려주면 된다.

- [x] (lead 지시, **사용자 승인 2026-09-25**) **데이터 허브 module-1 — 허브 핵심 + 쓰는 곳 6곳 관문 + 통합 분봉 보관소**

      설계서: `docs/02-design/features/backtest-studio.design.md` — **§2.4 전체를 먼저 읽을 것**
      (§2.4.2 카탈로그 · §2.4.3 관문 · §2.4.4 잠금 · §2.4.5 장부 · §2.4.9 소피증권 계약 ·
      §2.4.10 보관소 · §2.4.11 수집기 플래그), 테스트 §8.2 H1~H9, 파일 변경 목록 §11.4, 운영 §11.5.
      Plan: `docs/01-plan/features/backtest-studio.plan.md` (v0.4).

      **왜**: 공유 데이터(일봉·분봉·지수·통합 분봉 캐시·체결)를 쓰는 곳이 7군데로 흩어져 있고 동시 쓰기를
      막는 장치가 없다 — 사용자 지시 "데이터 관리는 중앙에서 통제". 그리고 `fetch_minute.py` 가 통합 분봉
      캐시를 갱신마다 최근 20거래일로 통째로 덮어써 이력이 사라진다(2,041종목 중 1,685종목이 09-04 정체).

      **기한**: 아래 2(보관소 최초 전체 병합)와 fetch_minute 병합 훅은 **2026-10-02 까지** — 워치독 분봉
      갱신이 10-03(토) 09:00 이후 돌 예정(09-19 완료 + 13일). 가능하면 오늘 끝내라(오늘은 추석 휴장으로 보임 —
      소피증권 마지막 기록 09-23 20:10).

      **할 일 (순서대로)**
      1. `datahub/` 패키지 새로 만들기
         - `catalog.yaml` — §2.4.2 표의 11종 + locks 3종 + calendar(holidays 는 KRX 휴장일 공지로 채우되
           확인 못 한 날짜는 넣지 말고 보고) + schedules·alerts 항목(값만 적는다, 실행은 module-2)
         - `catalog.py` — pydantic 검증(H1), `path(dataset_id, **fmt)`
         - `calendar.py` — 지난 거래일 = `data/index/daily/001.csv` 날짜, 앞날 = 평일 − holidays
         - `locks.py` — 잠금 경로, `owner(resource)` (토큰 pid → psutil 생존 + create_time ≤ 잠금 mtime)
         - `ledger.py` — `state/datahub/ledger-YYYY-MM.jsonl`, 한 줄 추가는 작은 잠금 안에서
         - `gate.py` — `write(lock, writer, detail)`: `backtesting.risk_manager.risk_state_lock` 재사용(블로킹,
           60초마다 "잠금 대기: <소유자 명령줄>" 을 stdout 으로) + 장부 start/progress(최대 60초 간격)/end.
           소피증권 정규장 시간(설정 `kospi-theme-engine/config.yaml` market.open/close)이면 경고만 출력하고
           막지 않는다. 본문 예외면 end(ok=false) 기록 후 다시 던진다. `DATAHUB_TRIGGER`·`DATAHUB_JOB_ID`
           환경변수가 있으면 장부에 기록, 없으면 trigger=external.
         - `minute_al_archive.py` — `data/stocks/minute_al_archive/{code}.parquet`. 병합 = 보관소 ∪ 기존 캐시 ∪ 새 봉,
           같은 분은 나중 것 우선, 날짜 인덱스 보존, tmp + 교체. **행이 줄면 안 된다(H7).**
           `merge(code, *frames)`, `archive_all()`, `read(code, start, end)`
         - wait-quiet — 잠금 `daily_minute` 에 살아 있는 소유자 없음 AND 표식 `state/daily_report`·
           `state/minute_refresh` 가 "실행 중"(시작 > 끝, 6시간 이내 — 워치독과 같은 규칙, BOM JSON 은 utf-8-sig)
           아님. `--until HH:MM` / `--max-minutes N`, **stdout 에만 출력(stderr 0바이트 — H9)**, 종료코드 0=조용함 3=기한 초과
         - `__main__.py` CLI: `status`(데이터셋별 최신일·종목 수) · `wait-quiet` · `ledger` · `archive-minute-al [--all | --codes …]`
         - datahub 핵심은 fastapi·studio 를 import 하지 않는다(§9.3).
      2. **보관소 최초 전체 병합 실행**: `python -m datahub archive-minute-al --all` — 소요 시간·종목 수·총 행 수 보고.
         1.3GB 라 종목 단위로 처리(한꺼번에 메모리에 올리지 말 것).
      3. 쓰는 곳 6곳에 관문 적용 (§11.4 표 그대로)
         - `backfill_universe.py` — 관문 `daily_minute` + 진행 기록 + `--codes=A,B` 또는 `--codes @파일` + `--stop-at HH:MM`
           (종목 시작 전 확인, 지나면 남은 수를 기록하고 정상 종료)
         - `backtesting/updater.py` `update_top35` — 관문 (**lead 승인: 이 파일 수정 허락**)
         - `daily_report_job.py` `update_indexes` — 관문
         - `tick_collect_804_828_al.py` — 관문 `tick_al` + `--codes`(목록/@파일) + `--stop-at`(워커가 새 종목 시작 전 확인 →
           지났으면 "deferred" 로 done 에 안 넣고 정상 종료)
         - `kospi-theme-engine/scripts/fetch_minute.py` — 관문 `minute_al` + **캐시 교체 직전 보관소 병합** + `--archive-only`
           (보관소에만 병합, 캐시는 안 씀)
         - `kospi-theme-engine/scripts/fill_daily.py` — 관문 `daily_minute` + 클라이언트 키를 `batch_keys()` 로
      4. `backtesting/daily_cache.py` — 캐시 tmp 파일 이름에 PID (**lead 승인**)
      5. 소피증권 재기동 스크립트 2개 — **BOM 유지**(수정 후 첫 3바이트 EF BB BF 확인), 관리자 권한으로 도는 스크립트
         - `kospi-theme-engine/restart_after_midnight.ps1`: 엔진 종료 **전**, 저장소 루트에서
           `python -X utf8 -m datahub wait-quiet --until 08:00` → 결과 한 줄을 그 스크립트 로그에
         - `kospi-theme-engine/rebuild_after_close.ps1`: 엔진 교체·재기동 **전** `wait-quiet --max-minutes 30`,
           그 호출만 `$ErrorActionPreference='Continue'` 로 감쌈(스크립트 안 PyInstaller 주석과 같은 이유)
      6. 테스트 `tests/datahub/` H1~H9 (§8.2) + datahub 핵심 import 규칙 검사. 기존 `tests/backtesting/` 무회귀.
      7. 실제 동작 1회씩 확인(오늘 휴장이라 가벼운 API 호출 허용 — 배치 앱키):
         `python backfill_universe.py --codes=005930` /
         `cd kospi-theme-engine && python -X utf8 -m scripts.fetch_minute --codes 005930 --archive-only`
         → 장부 기록, 보관소 행 수 불감소 확인. `python -m datahub wait-quiet --max-minutes 1` 은 즉시 0.
      8. `state/agent_mail/data-agent/standing.md` 에 상시 규칙 **추가**(덮어쓰기 금지 — git 복구 불가):
         "공유 데이터 쓰기는 `datahub.write()` 안에서만, 새 코드의 경로는 `datahub.catalog` 에서"

      **하지 말 것**: 소피증권 엔진(EXE·`app/`) 수정 · 거래일 장중(09:00~15:30) 소피증권 스크립트 수정 · 데이터 삭제 ·
      git commit(사람이 한다) · 워치독 수정과 서버·화면(module-2 몫).
      위 `[>]` 항목의 **(B) 틱 자동수집 상시화는 허브 `tick_nightly`(module-2, 설계 §2.4.11)로 흡수됐다 — 따로 만들지 마라.**
      (A) 호가 수집은 그 항목 그대로 둔다.

      **보고**: 시작 · 25/50/75% · 끝에 STATUS.md 자기 행. 자세한 건
      `state/agent_reports/data-agent_<날짜시각>_datahub_module1.md`. 설계 전제가 틀렸거나 설계와 다르게 해야 할
      이유가 생기면 **멈추고 바로 보고** — 지난번 120일 장부 때 지시 전제 3건을 짚어준 것처럼.

- [x] (lead 지시 2026-09-25, module-3 점검 G3-3·D3-6 — 사용자 "지금 모두 수정") **카탈로그 index 경로 수정 + 멈춘 일봉 원인 확인**
      1. 편지 `state/agent_mail/data-agent/20260925_backtest-agent_catalog-index-path.md` 처리 — `catalog.path("index")` 가
         `{daily,minute}/{001,101}` 집합 표기 때문에 KeyError. 경로 표기를 고치거나(예: `data/index/{kind}/{code}.csv`) path() 를 고쳐라.
         테스트 추가. 끝나면 backtest-agent 에 편지로 알려라(그쪽이 우회를 지운다).
      2. **일봉 328종목이 2026-08-31 에서 멈춤**, **시장 정보(universe.csv) 없는 종목 419개**(backtest-agent 보고
         `state/agent_reports/backtest-agent_20260925-2000_studio_service.md` §8), **소피증권 유니버스 8종목 일봉이 09-23 보다 오래됨**
         (014160·033340·046070·051980·057540·082660·131400·254120 — 소피증권 기동 경고, lead 확인). 각각 **거래정지·상장폐지인지,
         수집에서 빠진 것인지** 구분해라. 백필 대상 선정(`stale_codes` = 분봉 폴더 ∪ 소피증권 유니버스)이 이 종목들을 영영 안 고르는
         구조인지도 확인. 수집 누락이면 `backfill_universe.py --codes @파일` 로 보충(관문 안 · 오늘·내일 휴장이라 API 괜찮다).
         상장폐지·정지는 보충하지 말고 목록으로 보고(허브 카탈로그에 "거래 중단 종목" 표시가 필요한지 의견).
      보고: STATUS.md 자기 행 + `state/agent_reports/data-agent_<날짜시각>_catalog_index_stale_daily.md`. git commit 금지.

- [x] (lead 지시 2026-09-25, **사용자 승인 "module-2 시작"**) **데이터 허브 module-2 — 허브 쪽 1단계(서버 없이 도는 것)**
      설계서 §2.4.6 정책 · §2.4.7 일정 · §2.4.8 상태·감시·알림 · §2.4.9 소피증권 계약 · §2.4.11 야간 자동 수집과 따라잡기 ·
      §4.2(`/api/data/*` 응답 모양) · §8.2 H5·H10~H21 을 먼저 읽어라. **작업 실행기(`jobrunner`)와 서버는 monitoring-agent 가 동시에 만든다** —
      그래서 이번 항목은 jobrunner·FastAPI 없이 도는 것만 한다(수집 작업 처리기·일정 실행·API 라우터는 jobrunner 가 나온 뒤 lead 가 따로 넣는다).
      1. `datahub/policy.py` — 소피증권 `config.yaml` 운영 시간 기준 판정(allow_now / needs_confirm / schedule_only + 제안 시각),
         대량/소량 기준, 허브 수집 동시 1개, 배치키 경고, CPU 우선순위 권고 — **H5**(시계 주입 행렬)
      2. `datahub/status.py`·`quality.py` — 데이터셋별 신선도 판정(§2.4.8 표 규칙 6종), 밀린 종목(소피증권 유니버스 표시),
         결측 거래일(최근 120거래일 보유 비율), 품질 검사 5종, **체결 조회창**(최근 20거래일, 날짜별 기대 종목 = D-1 거래대금 상위 35
         합집합 − 초대형주 + 보충 2종목 — **P7**: 기존 `daily_top_n_from_local` 과 집합 동일), 보관소 커버리지, 장부 밖 쓰기 감지 — **H10·H11**
      3. `datahub/sophie.py` — 운영 시간(설정 출처 표기), 엔진 상태(`/healthz` 200·401 = 가동, psutil `ai_stock.exe` 시작 시각 → 거래일인데
         오늘 00:00 전 시작이면 "어제 상태"), 분봉 기준선 갱신 표식·로그 끝줄·다음 예정(워치독 13일 규칙), 기준 데이터 data↔dist 동기,
         자정 재기동·재빌드 로그 — **H12**. `datahub status` 의 sophie_reference 날짜가 08-16 로 보이던 것(module-1 G6)도 여기서 바로잡아라
      4. **휴장일** — KRX 공지가 302 였으니 다른 출처(예: 거래소 휴장일 안내 공개 페이지, 증권사·언론 공지)를 찾아 2026 남은 휴장일을
         `catalog.yaml` 에 채워라. 확실하지 않은 날짜는 넣지 말고 출처와 함께 보고
      5. `datahub/collectors.py` — 수집 명령 조립(일봉 3모드·체결 catch_up/range·통합 분봉 4모드, §2.4.10 표·§4.2 그대로, `--codes @파일`)과
         "빠진 체결 쌍" 계획 함수(§2.4.11 단계 2~3: start/end/종목 순서 = 먼저 사라질 날짜 순, 포기 목록 제외, 시도 횟수 파일) — **H15**
      6. `datahub/alerts.py` — 규칙 판정(§2.4.8 알림 표 9종)과 하루 1회 중복 방지, 발송은 `backtesting.notifier.send_telegram` — **H14**
      7. 테스트 `tests/datahub/` 에 위 H 번호 + P7. 기존 무회귀.
      **하지 말 것**: jobrunner·FastAPI·화면·워치독 수정(monitoring-agent 몫), 데이터 삭제, 장중 소피증권 스크립트 수정, git commit.
      보고: 시작·50%·끝에 STATUS.md, 자세한 건 `state/agent_reports/data-agent_<날짜시각>_datahub_module2_core.md`.

- [x] (lead 판정 2026-09-25 — 네 결정요청 답) **백필 대상 = 일봉 폴더 전체(거래 중단 제외) + 기준일을 거래일 달력으로**
      판정: **넣는다.** `backfill_universe.py` 머리말부터 "로컬에 이미 있는 전 종목의 일봉/1분봉을 증분 갱신한다"가 목적인데,
      대상 풀(분봉 폴더 ∪ 소피 유니버스)이 일봉만 있는 367종목을 영영 빼먹는 건 목적에서 벗어난 결함이다. 늘어나는 시간(~17%)은
      아래 2번이 휴장·주말 헛돌기를 없애 상쇄한다(오늘 09-25 휴장인데 16:04 야간 갱신이 2,210종목을 전부 "밀림"으로 보고 다시 받는 중 —
      새 데이터 0, API 3시간+).
      1. 풀 = 분봉 폴더 ∪ 소피 유니버스 ∪ **일봉 폴더** − `state/datahub/inactive_codes.json`(거래 중단)
      2. 기준일 = `datahub.calendar` 로 "마감이 확정된 가장 최근 거래일"(거래일 16:00 이후면 오늘, 아니면 직전 거래일 — 휴장·주말이면 직전 거래일).
         달력일 `date.today()-1` 을 쓰지 않는다 — 월요일 아침·휴장일에 전 종목을 밀림으로 보는 원인
      3. 테스트: 휴장일(09-25) 기준 → 이미 최신인 종목은 대상에서 빠짐 / 일봉만 있는 종목이 풀에 들어감 / 거래 중단 종목 제외
      4. 효과 실측: 오늘 기준 대상 종목 수(바꾸기 전 2,210 → 후 ?)
      git commit 금지. 보고: STATUS.md 한 줄 + 모듈2 보고서에 덧붙임.

- [x] (lead 지시 2026-09-25, module-2 2단계 데이터 쪽 — 사용자 승인 범위) **허브 수집 작업 처리기 + 일정 실행기**
      설계서 §2.4.7 일정 · §2.4.10 통합 분봉 갱신 모드 · §2.4.11 야간 자동 수집과 따라잡기 · §8.2 H13·H15~H21 과
      `jobrunner/worker.py` 머리말(처리기 계약)·`state/agent_reports/monitoring-agent_20260925-1710_module2_server.md` "data-agent 가 지킬 계약"을 먼저 읽어라.
      1. `datahub/jobs.py` — 처리기 `collect_daily`·`collect_ticks`(range/catch_up)·`collect_minute_al`(4모드)·`archive_minute_al`.
         시그니처 `def handler(ctx)`, **실행 파일 허용 목록 검사는 여기서**(§7: sys.executable + 고정 스크립트 3종·`-m scripts.fetch_minute`·
         run_minute_refresh.ps1 만), `run_child(env=)` 로 `DATAHUB_TRIGGER=hub`·`DATAHUB_JOB_ID` 전달, 진행률은 장부 progress 기록에서,
         잠금 대기면 `ctx.progress(waiting_lock=...)`. 체결 catch_up 은 수집 → `tick_compact_daemon.py --once` → 상태 재계산 → 시도 횟수 갱신까지 한 잡에서
      2. `datahub/scheduler.py` — 허브 소유 일정(`tick_nightly` 켜짐·`daily_catchup`·`minute_archive`·`freshness_check`) 실행, 같은 밤 재시도(60분, 최대 3회),
         3일 밤 실패 → 포기 목록, `--stop-at` 야간 구간 끝, 선행(야간 갱신·분봉 기준선 갱신 표식) 대기, 서버가 켜질 때 따라잡기(H20), 외부 일정 관측,
         `state/datahub/overrides.json`. 스케줄러 **시작 함수만** 제공(예: `start(root, store) -> Thread`) — 서버 연결은 monitoring-agent 몫
      3. 테스트 H13·H15~H21(가짜 시계·가짜 수집기 `STUDIO_FAKE_COLLECTORS=1`)
      git commit 금지. 보고: STATUS.md + `state/agent_reports/data-agent_<날짜시각>_datahub_jobs_scheduler.md`.

- [x] (lead 지시 2026-09-25, module-2 2단계 — 위 항목 다음) **허브 API 라우터 `datahub/api.py`**
      monitoring-agent 가 화면과 맞출 **API 계약**을 편지 + `docs/02-design/api/datahub-api.md` + `frontend/src/types/data.ts` 로 보낸다 —
      **그 모양 그대로** `/api/data/*` 를 구현하라(FastAPI 는 이 파일만 import). 계약 편지가 아직 없으면 이 항목은 `[>]` 로 두고 편지를 기다려라.
      라우터 객체만 제공(`router`) — `studio/api/app.py` 연결은 monitoring-agent 몫이니 끝나면 편지로 알려라.
      테스트: 설계서 §8.3 L1 1~12(허브 쪽). git commit 금지.

- [x] (lead 지시 2026-09-25 22:40, module-2 마무리 — 사용자 승인 범위) **실제 수집 경로 1회 검증 + overview 캐시 60초 + P7 확인**
      허브 API·처리기·일정 수용(lead 재실행 datahub 107 passed, monitoring-agent 가 8780 에 연결·실데이터 6탭 확인). 남은 건 **진짜 수집기로 한 번도 안 돌았다**는 것 —
      첫 실전이 월요일(09-28) 밤 20:15 회차가 되기 전에, 주말(소피증권 꺼짐·REST 비어 있음)에 작게 한 번 태운다. 화면 버튼과 같은 길 = **라이브 8780 API**.
      1. SC-1: `POST http://127.0.0.1:8780/api/data/jobs/collect-daily` 종목 지정 2~3개(`Origin: http://127.0.0.1:8780`) → job 상태 흐름(queued→running→succeeded)·진행률·
         `ledger_run`·장부 출처 "허브"·파일 갱신 확인
      2. SC-2: `POST /api/data/jobs/collect-ticks` `range` 1종목×1거래일(조회창 안, **아직 파일이 없는 쌍**으로 — 새 파일 생성과 조회창 반영을 보려고) → 파일 생성·`tick-window` 반영·장부
      3. 둘 다 실패·잠금 대기·진행률 0 고정 같은 게 나오면 고치고 다시. 걸린 시간 기록
      4. **설계 §8.9 는 overview 캐시 60초**인데 지금 10초다 — 상태 바가 10초마다 부르니 화면이 열려 있으면 4초짜리 계산이 쉬지 않고 돈다(워치독 프로브 지연의 원인 중 하나). 60초로
      5. §8.7 **P7**(조회창 기대 종목 vs `daily_top_n_from_local(35)` − 초대형주 + 보충, 최근 20거래일 집합 동일) 테스트가 있는지 확인, 없으면 추가
      8780 서버는 monitoring-agent 가 하트비트 전환으로 곧 재기동한다 — 워커는 분리 실행이라 살아남지만, 제출 직전에 `/api/meta/status` 200 인지 보고 보내라.
      git commit 금지. 보고: STATUS.md + `state/agent_reports/data-agent_<날짜시각>_module2_real_run.md`.

- [x] (lead 지시 2026-09-25 22:40, **module-6 데이터 — 사용자 승인 "module-2 끝나면 4~6 바로"**) **분봉(보관소)·체결 로더 — 스튜디오가 읽는 입구**
      설계서 §3.7 끝 "시점 규칙·데이터 출처", §3.2 `intraday`·`tick` 칸, §8.6·§8.7(P8)·§8.9(분봉 2단계 ≤60초) 를 먼저 읽어라. 위 항목 다음에.
      1. 새 파일 `studio/infrastructure/intraday_data.py`(market_data.py 는 backtest-agent 소유라 건드리지 마라) —
         ① 분봉: `minute_al_archive`(카탈로그 경로)에서 종목·기간을 읽어 `bar_minutes`(1·3·5·10·15·30·60)로 리샘플, **P8: 기존 `_resample_minute` 와 동일**. 정규장만/전구간 선택(통합 분봉은 NXT 시간 포함 — 기본은 정규장 09:00~15:30, 근거를 머리말에)
         ② 체결: `tick_al` 파일 → 오름차순(원본은 역시간순), 같은 초 다중 체결 순서 보존, 열 이름·자료형 고정
         ③ 날짜별 "그날 거래대금 상위 N" 사전 필터 재료(D−1 기준) — 분봉 2단계(일봉 D−1 순위 → 분봉)가 쓸 것
      2. 계층 규칙(§9.3): infrastructure 는 domain·application.ports·datahub 읽기 API 만. `tests/studio/test_import_rules.py` 통과
      3. 테스트: P8 · 역시간순 → 오름차순 · 같은 초 · 보관소 기간 밖 요청은 조용히 비지 말고 범위를 돌려줌 · 성능(60거래일×상위 30 로드 시간 실측)
      4. 끝나면 **backtest-agent·strategy-agent 에 편지**: 함수 서명·반환 모양·열 이름(엔진·틱 조건식이 이걸 쓴다)
      git commit 금지. 보고: STATUS.md + `state/agent_reports/data-agent_<날짜시각>_module6_loaders.md`.

- [x] (lead 지시 2026-09-25 23:20 — module-6 로더 수용 후속, 급하지 않음) **체결 파일 시각 어긋남(4,423개 중 1,762개) 원인 확인 — 데이터 무결성**
      로더 수용(lead 재실행: tests/studio+jobrunner 507 passed, 네 로더 32건 포함 · 통합 테스트 4 passed). 네가 찾은 어긋남이 **페이지 이어붙이기 경계**에서 생기는지 확인해라 —
      경계라면 **중복 행·빠진 행**이 같이 있을 수 있고, 그건 같은 초 순서 문제가 아니라 거래량 합(대금 속도 조건)이 틀리는 문제다.
      1. 어긋난 자리 표본 20곳: 수집기(`tick_collect_804_828_al.py`)의 페이지 경계(연속조회 키)와 위치 비교 — 수집 로그·페이지 크기로
      2. 같은 (시각, 가격, 수량) 연속 중복 행 수 · 그날 합계 거래량 vs 일봉 거래량(통합 기준) 대조로 누락·중복 규모
      3. 결과 표: 원인 / 영향(순서만 vs 합계까지) / 고칠 곳(수집기 vs 로더) — **데이터 파일은 고치지 마라**(판단은 lead·사용자). 재수집이 필요해 보이면 대상 수·시간 견적만
      git commit 금지. 보고: STATUS.md + `state/agent_reports/data-agent_<날짜시각>_tick_order_audit.md`.

- [x] (lead 지시 2026-09-25 23:20 — 급하지 않음, **실행 금지·견적만**) **분봉 과거 깊게 받기(deep_archive) 견적 — 사용자 결정용**
      분봉 단타 백테스트는 보관소 기간(종목별 1~2개월)이 짧아 결과가 얇다. 늘리려면 `collect_minute_al` `deep_archive` 로 받아야 하는데, REST 를 몇 시간 쓰는 일이라 사용자가 정한다.
      표로: 대상 종목 집합(최근 60·120·250거래일 각각 "전일 거래대금 상위 30" 합집합 종목 수) · 종목당 페이지 수·총 요청 수 · 예상 시간(계정 단위 한도 기준 실측치) ·
      보관소 증가 용량 · 가장 이른 시각(주말·야간만) · 소피증권 기준선 캐시 무영향 확인. git commit 금지. 보고: STATUS 한 줄 + `state/agent_reports/data-agent_<날짜시각>_deep_archive_estimate.md`.

- [x] (lead 지시 2026-09-25 23:35 — 네 견적 권장 1번, module-6 "과거 깊게 받기" 실경로 확인) **deep_archive 시험 1종목 × 250일**
      감사·견적 둘 다 수용(체결 어긋남 = 원천 성질·합계 정확·재수집 불필요, 설계서 L-7 에 기록). 큰 수집(60/120/250일안)은 **사용자 결정 대기** — 이 항목은 그 판단 재료이자
      deep_archive 경로가 진짜 수집기로 한 번도 안 돈 것을 확인하는 시험이다.
      1. 라이브 8780 API `POST /api/data/jobs/collect-minute-al` `mode=deep_archive`, 1종목(보관 시작일이 늦은 대형주 하나), `days=250` → job 흐름·진행률·장부·걸린 시간
      2. 실제로 닿은 가장 이른 날짜(250거래일 깊이가 나오는지), 보관소 행 수 증가(불감소), **소피증권 캐시 md5 불변**
      3. 끝나면 결과를 견적 보고서에 덧붙이고 STATUS 한 줄. 더 큰 수집은 하지 마라. git commit 금지.

- [x] (**취소 23:50 — 사용자 "과거 분봉 다 받았는데 또 받아?" 맞음: `data/stocks/minute`(KRX) 1,055종목·6,674만 행·2025-07~ 이 이미 있다. 아무것도 안 돌았음 확인**) (lead 결정 2026-09-25 23:40 — **사용자 위임 "너가 알아서 해"**) **분봉 과거 깊게 받기 = 250거래일안(종목별 필요 깊이, "권장" 방식) — 지금 시작, 월 08:10 전 완료**
      시험(005380×250일, 237거래일·1.12초/페이지) 수용. 판단 근거: 60일로는 홀드아웃 20% 가 12일이라 분봉 검증이 안 되고, 250일(약 20시간·+632MB)도 이번 주말 창 안에 끝난다.
      1. 대상 = 네 견적의 250일 집합(445종목 − 이미 보관 중인 25). 작업은 깊이 구간별로 나누되(작업당 종목 ≤300, `days` 하나) **60일 집합에 드는 종목이 먼저 끝나게** 순서를 잡아라 —
         중간에 멈춰도 가장 많이 쓰일 종목부터 채워지게
      2. 라이브 8780 API 로 제출(허브 수집 한 번에 하나라 줄 선다). 제출 뒤 각 작업의 시작·진행률·걸린 시간을 STATUS 에 짧게 갱신(한 작업 끝날 때마다)
      3. 끝나면: 종목별 보관 시작일 분포 · 실패 종목(429 등) **다시 받기** · 보관소 행 수 불감소 · **소피증권 캐시 md5 불변** · 걸린 총시간 vs 견적 · 분봉 단타 백테스트에서 쓸 수 있는 (날짜,종목) 쌍이 몇 배 늘었는지
      4. 안전: **월요일 08:10 전에 반드시 끝** — 토요일 20:00 까지 안 끝날 기미면 남은 작업을 취소하고 보고(다음 주말 이어받기). 소피증권이 켜져 있으면 제출하지 마라.
         다른 통합 분봉 쓰기(기준선 갱신)는 잠금으로 기다리게 되니 10-03 전에 끝나는지 확인. 메모리 여유(커밋)가 3GB 밑이면 보고
      git commit 금지. 보고: STATUS.md + `state/agent_reports/data-agent_<날짜시각>_deep_archive_250.md`.

- [x] (lead 지시 2026-09-25 23:50 — 위 취소의 대안, module-6 데이터 보완) **분봉 로더에 기존 KRX 분봉 출처 추가 — 다시 받지 않고 있는 1년치를 쓴다**
      lead 가 스튜디오 분봉 출처를 통합 보관소(종목별 1~2개월)로만 잡아 놓고, 이미 있는 `data/stocks/minute`(KRX, 1,055종목, 시작일 중앙값 2025-08-14·520종목 2025-07~)를 안 봤다.
      1. `intraday_data` 분봉 함수에 `source="krx"|"al"` — **기본 `krx`**(긴 과거), `al` 은 통합 보관소(최근·NXT 포함). 카탈로그 경로로. 반환 모양(Panel·열·라벨 규칙)은 두 출처가 같게
      2. 출처별 사용 가능 기간 함수(종목별 시작·끝) — 엔진·화면이 "이 기간은 어느 출처로 몇 종목" 을 보여줄 것
      3. 차이를 머리말에: KRX 분봉은 **NXT 체결 제외**(2025-03 이후 거래량·거래대금이 통합보다 낮게 잡힘), 정규장만. 가격은 같은 종목이라 거의 같음 — 실제로 한 종목·한 달을 두 출처로 비교해 거래량 비율·종가 차이를 숫자로
      4. 테스트: 두 출처 같은 모양 · krx 가 P8(`_resample_minute`)과 동일 · 기간 밖 `DataRangeError`
      5. 끝나면 backtest-agent·strategy-agent 에 편지(서명·기본값·차이 숫자). git commit 금지. 보고: STATUS + 로더 보고서에 덧붙임.

- [x] (lead 지시 2026-09-26 00:15 — **사용자 결정 "통합 기본 + KRX 선택"**, 작게) **분봉 로더 기본 출처를 `al` 로 되돌리기**
      23:50 지시의 "기본 krx" 는 lead 실수였다 — 9월 1일 사용자 규칙 "통합(AL)만, 예외 없음"을 안 보고 정했다. 사용자가 방금 정함: **기본 통합, KRX 는 사용자가 고를 때만.**
      `intraday_data` 의 `source` 기본값을 `"al"` 로, `krx` 는 그대로 선택 가능. 두 출처 차이 숫자(거래량 0.62~0.94배)는 머리말에 유지. 테스트의 기본값 기대 갱신. git commit 금지. 보고: STATUS 한 줄.

- [x] (lead 지시 2026-09-26 08:50 — 66행 [>] "호가 상시 수집"(사용자 승인 09-24)의 준비, **설계안만 · 켜지 마라**) **호가 수집 설계안 — 허브 편입 · 소피증권 무충돌 · 월요일 켤 수 있게**
      호가는 과거 조회가 안 돼 하루 놓치면 그날치가 영영 없다. 허브가 생겼으니 이제 허브 규칙 안에서 설계할 수 있다. 다만 장중에 도는 수집이라 소피증권(실거래 중 실시간·REST 한도 공유)과
      충돌하면 안 되므로 **사용자 승인 후에만 켠다.** 일요일 저녁까지 표로:
      1. 방식: WebSocket 실시간 호가(배치 앱키 — 같은 앱키로 WS 를 열면 소피증권 실시간이 끊기는 규칙) vs REST `ka10004` 폴링(계정 단위 REST 한도를 장중 소피증권과 나눠 씀) — 각각 한도·끊김 위험을 근거와 함께
      2. 대상 종목(예: 소피증권 유니버스·top35 합집합 — 몇 종목), 간격, 하루 용량(압축), 저장 위치 = **카탈로그 새 데이터셋 + 쓰기 관문·잠금**(허브 규칙), 보관 규칙
      3. 일정: 허브 일정으로(장 시작 전 켜고 장 끝나면 끔), 실패·끊김 알림, 소피증권 가동 확인과의 관계
      4. `backtesting/orderbook_collector.py`·`orderbook_parser.py`(2~10단 미확인)를 쓸지, 월요일 첫날은 몇 종목·몇 분으로 시험할지
      5. 위험 표: 소피증권·8765·나스닥 감시에 주는 영향과 막는 방법
      **아무것도 켜지 말고 수집도 하지 마라**(WS 연결 시험도 사용자 승인 뒤). git commit 금지. 보고: `state/agent_reports/data-agent_<날짜시각>_orderbook_plan.md` + STATUS 한 줄.

- [x] (lead 지시 2026-09-26 10:00, **studio-conditions c4 — 사용자 승인 "C안, 5명 병렬"**) **거래량·순위·테마·업종·분봉/틱 전용 조건**
      설계 §3.3 의 `ind_volume.py`·`ind_group.py`·분봉 전용(`intraday.py` 확장)·틱 전용(`tick.py` 확장) 표 + `infrastructure/reference_data.py`(테마 그룹·업종 구성 — 카탈로그 경로, domain 엔 dict 로 주입).
      top_value_count(최근 n일 대금 상위 m 진입 횟수)는 사용자 테마 점수 기준과 같은 계산인지 확인해 적어라. 테마·업종은 현재 구성 — 결과 경고 문구 제공. 테스트: 손계산 + 카나리아.
      공통: 설계서 `docs/02-design/features/studio-conditions.design.md` 를 먼저 읽어라(§3 전부·§8·§11.3). **미래참조 없음이 최우선** — 새 조건마다 카나리아. 기존 명세·프리셋·실행 결과·패리티(P1~P8) 무회귀.
      파일 규칙: 새 지표는 **자기 분류 모듈**(`ind_*.py`)에 정의 + `catalog.py`·`indicators.py` 에는 등록 한 줄만(고치기 직전 다시 읽고 Edit, 전체 덮어쓰기 금지). `ast.py`·`evaluator.py`·엔진은 backtest-agent 만.
      분봉 기본 출처 통합(AL), 실주문·KIWOOM_IS_MOCK 무접촉, git commit 금지. 그대로 믿지 말고 검증 — 설계가 틀렸으면 틀렸다고 써라.
      보고: STATUS + `state/agent_reports/data-agent_<날짜시각>_conditions_c4.md`.

- [x] (**취소 10:05 — 사용자: "수급 공매도는 없어도 될 거 같아". 하지 마라**) (lead 지시 2026-09-26 10:00, studio-conditions c7) **외국인·기관·개인 순매수, 공매도 과거 자료 견적**
      어떤 키움 TR/KRX 경로로 종목별 **일별 과거**를 받을 수 있는지(기간 한계), 전 종목·N년 받는 요청 수·시간(계정 단위 한도 실측 기준), 용량, 허브 데이터셋 안(카탈로그·잠금·일정), 매일 증분 방법.
      REST 는 스키마 확인용 몇 건만(주말). 결과는 표로 → 사용자 결정. 보고: `state/agent_reports/data-agent_<날짜시각>_flows_short_estimate.md`.

- [x] (lead 지시 2026-09-26 13:15, 작게) **`test_handler_reports_waiting_lock` 가끔 실패 고치기** — module-2 점검 G2-4("원인 불명 1회")가 오늘 전체 스위트(1,725건, 3분)에서 다시 실패, 단독 6회는 전부 통과 → **부하 때 시간에 기대는 테스트**로 보인다.
      전체 스위트나 CPU 부하를 걸고 재현 → 붙여 둔 진단 메시지로 원인 확인 → 고정 대기(sleep) 대신 "조건이 될 때까지 기다리되 상한" 식으로 결정적으로. 고친 뒤 단독 10회 + 부하 5회 + 전체 스위트 1회 통과. 제품 코드 문제면 그쪽을 고치고 보고. git commit 금지. 보고: STATUS 한 줄.

- [ ] (lead 지시 2026-09-26 15:00 — 13:50 수정 후속) **`test_handler_reports_waiting_lock` 이 아직 가끔 실패 — 이번엔 증상이 다르다**
      lead 실측: `pytest tests/studio tests/jobrunner tests/datahub` **한 번에** 돌리면 4회 중 2회 실패, `tests/datahub` 만은 통과.
      실패 내용: `assert 'failed' == 'succeeded'` — 대기 표시는 나왔는데 **작업이 failed 로 끝남**(13:50 고친 건 대기 시간 문제였다).
      의심: 앞선 studio·jobrunner 테스트가 남긴 프로세스·잠금 파일·작업 폴더·환경변수와 부딪힘(격리 부족), 또는 부하 때 자식 수집기 실패.
      1. 세 폴더를 한 번에 돌려 재현 → 네가 붙인 타임라인 메시지·작업 log.txt 로 **실패 원인**부터
      2. 테스트 격리 문제면 테스트(임시 루트·잠금 경로·정리)를, 제품 문제(잠금 대기 중 자식이 죽는 등)면 제품을 고쳐라 — 어느 쪽인지 보고
      3. 고친 뒤 세 폴더 한 번에 5회 연속 통과. git commit 금지. 보고: STATUS 한 줄.
