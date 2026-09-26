"""테스트용 handler — 워커의 허용 접두사에 이 모듈을 monkeypatch 로 더해서 쓴다(실제 허용 목록은 그대로)."""
import time

from jobrunner.worker import CancelledError

SECRET = "sk-test-SECRET-VALUE-123456"


def ok(ctx):
    ctx.progress(50, "중간", "절반")
    ctx.log(f"토큰은 {SECRET} 입니다")
    ctx.log("Authorization: Bearer abcdefghijklmnop1234")
    return {"run_id": ctx.payload.get("run_id"), "message": "끝"}


def boom(ctx):
    raise ValueError("터졌다")


def cancelled(ctx):
    raise CancelledError()


def wait_for_cancel(ctx):
    for _ in range(200):
        if ctx.is_cancelled():
            raise CancelledError()
        time.sleep(0.05)


def child_echo(ctx):
    import sys
    lines = []
    code = ctx.run_child([sys.executable, "-c", f"print('a'); print('{SECRET}'); print('b')"], on_line=lines.append)
    if code != 0 or lines != ["a", "****", "b"]:
        raise RuntimeError(f"code={code} lines={lines}")
