"""backtest-dashboard의 결과 조회 계층 — results/ 폴더에 표준 규칙
({전략명}_{YYYYMMDD_HHMMSS}.csv)으로 저장된 백테스트 결과를 읽기 전용으로 파싱한다.
dashboard_data.py와 동일하게 HTTP를 전혀 모르는 순수 함수만 둔다(Design §9.2).
"""
import csv
import os
from datetime import datetime


def list_results(results_dir: str) -> list[dict]:
    """results_dir의 .csv 파일 목록을 생성시각(mtime) 내림차순으로 반환한다.

    results/ 폴더가 아직 없으면(첫 백테스트 실행 전) 빈 목록을 반환한다."""
    if not os.path.isdir(results_dir):
        return []

    entries = []
    for filename in os.listdir(results_dir):
        if not filename.endswith(".csv"):
            continue
        path = os.path.join(results_dir, filename)
        mtime = os.path.getmtime(path)
        entries.append({"filename": filename, "mtime": mtime})

    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return [
        {"filename": e["filename"], "created_at": datetime.fromtimestamp(e["mtime"]).isoformat()}
        for e in entries
    ]


def read_result(results_dir: str, filename: str) -> dict | None:
    """지정한 결과 파일 하나를 표 형태(columns/rows)로 파싱한다.

    filename은 반드시 list_results()가 반환한 이름 중 하나여야 한다 — 호출자
    (dashboard_server.py)가 화이트리스트 검증을 하고, 여기서는 안전을 위해
    한 번 더 상위 디렉터리 이동이 섞인 이름을 거부한다(경로 순회 방지)."""
    if os.path.sep in filename or "/" in filename or ".." in filename:
        return None

    path = os.path.join(results_dir, filename)
    if not os.path.exists(path):
        return None

    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        columns = reader.fieldnames or []

    return {"filename": filename, "columns": columns, "rows": rows}
