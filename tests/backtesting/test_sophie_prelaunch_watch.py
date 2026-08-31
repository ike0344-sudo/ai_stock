import os

from backtesting.sophie_prelaunch_watch import _STATUS_RE, _TICK_RE, new_lines_since


def _write(tmp_path, name, text):
    # newline="" — Windows 텍스트 모드가 \n을 \r\n으로 바꿔써서 바이트 오프셋 계산이
    # 어긋나는 걸 막는다(실측: 이 픽스처 없이 처음 돌렸을 때 두 테스트가 그 이유로 깨졌다).
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline="")
    return str(path)


# ---- new_lines_since ----

def test_new_lines_since_returns_only_appended_lines(tmp_path):
    path = _write(tmp_path, "log.txt", "line1\nline2\n")
    offset = os.path.getsize(path)

    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write("line3\nline4\n")

    lines, new_offset = new_lines_since(path, offset)

    assert lines == ["line3", "line4"]
    assert new_offset == os.path.getsize(path)


def test_new_lines_since_missing_file_returns_empty(tmp_path):
    lines, offset = new_lines_since(str(tmp_path / "nope.txt"), 0)
    assert lines == []
    assert offset == 0


def test_new_lines_since_holds_back_incomplete_last_line(tmp_path):
    path = _write(tmp_path, "log.txt", "")
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write("complete\npartial")  # 마지막 줄이 개행으로 안 끝남

    lines, offset = new_lines_since(path, 0)

    assert lines == ["complete"]
    # "partial"은 다음 번에 다시 읽히도록 offset이 그 앞에서 멈춰야 한다
    assert offset == len("complete\n".encode("utf-8"))


def test_new_lines_since_resets_offset_when_file_rotated_smaller(tmp_path):
    path = _write(tmp_path, "log.txt", "a" * 100 + "\n")
    big_offset = os.path.getsize(path)

    path2 = _write(tmp_path, "log.txt", "새로시작\n")  # 로그 회전으로 파일이 작아짐

    lines, offset = new_lines_since(path2, big_offset)

    assert lines == ["새로시작"]


# ---- 정규식 ----

def test_tick_re_extracts_timestamp_and_count():
    line = "2026-08-31 08:05:12,345 INFO    [engine] app.engine.runner: 가동 중 · 틱 42 · 종목 200 · 테마 23"
    m = _TICK_RE.search(line)
    assert m is not None
    assert m.group(1) == "2026-08-31 08:05:12"
    assert m.group(2) == "42"


def test_tick_re_no_match_on_unrelated_line():
    assert _TICK_RE.search("2026-08-31 08:05:12,345 INFO 아무 상관없는 줄") is None


def test_status_re_extracts_status_text():
    line = "2026-08-31 08:00:05,000 INFO    [feed] ws: 상태: 구독 200종목 (연결됨)"
    m = _STATUS_RE.search(line)
    assert m is not None
    assert m.group(2) == "구독 200종목 (연결됨)"

