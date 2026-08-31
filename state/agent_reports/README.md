# 에이전트 → lead 보고함

orca pane 은 별도 claude 세션이라 SendMessage 가 안 붙는다(2026-08-30 확인).
그래서 파일로 보고한다. pane 은 여기에 쓰고, lead 는 이 폴더만 보면 된다.

파일명: `<agent>_<YYYYMMDD-HHMMSS>.md`  (예: `backtest-agent_20260830-0412.md`)
lead 가 읽은 것은 `read/` 로 옮긴다. 남아 있는 = 아직 안 읽은 보고.
