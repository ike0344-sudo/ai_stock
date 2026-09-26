"""공용 작업 실행기 — 분리 프로세스로 긴 작업(수집·백테스트)을 돌린다.

    store       state/jobs/<id>/ 저장 (job.json · progress.json · log.txt · cancel.flag)
    spawn       워커 분리 실행·생존 확인·트리 종료
    dispatcher  서버 스레드: 예약 시각·그룹 한도·죽은 워커 정리·취소
    worker      `python -m jobrunner.worker <id>` — handler("모듈:함수") 실행 (계약은 worker.py 머리말)
    child       자식 명령 실행 + 출력 → log.txt (비밀값 가림)
    mask        .env 값·Bearer 토큰 가림

설계: docs/02-design/features/backtest-studio.design.md §2.1, §3.3, §9.3
jobrunner 는 datahub·studio·backtesting·fastapi 를 import 하지 않는다(handler 는 문자열로만 연결).
"""
