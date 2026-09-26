"""git_info — 한글 경로가 있는 저장소에서도 commit·dirty 가 채워진다(cp949 디코딩 실패 회귀)."""
import subprocess

from studio.infrastructure import git_info


def _git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True,
                   capture_output=True)


def test_dirty_with_korean_filename(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "core.quotepath", "false")  # 한글 경로를 이스케이프 없이 UTF-8 그대로 내보낸다(실제 환경)
    f = tmp_path / "한글파일.txt"
    f.write_text("a", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "첫 커밋")
    clean = git_info.get(tmp_path)
    assert clean["commit"] and clean["dirty"] is False
    f.write_text("b", encoding="utf-8")  # 수정된 추적 파일이 한글 이름 → status 출력에 한글이 나온다
    dirty = git_info.get(tmp_path)
    assert dirty["commit"] == clean["commit"] and dirty["dirty"] is True


def test_not_a_repo_gives_none(tmp_path):
    assert git_info.get(tmp_path) == {"commit": None, "dirty": None}
