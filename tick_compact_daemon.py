"""완료된(더 이상 안 바뀌는) 틱 종목을 뒤에서 압축한다 — 수집기(tick_collect_803_828.py
또는 tick_collect_804_828_al.py)와 병행 실행. 8컬럼 CSV -> 압축 parquet, 파일당 원자적 교체.

    python tick_compact_daemon.py                                  # KRX전용(data/stocks/tick)
    python tick_compact_daemon.py --tick-dir data/stocks/tick_al --main-progress state/tick_collection/progress_al.json --compact-progress state/tick_collection/compress_progress_al.json --log state/tick_collection/compress_log_al.txt --report state/agent_reports/data-agent_tick_al_compress_progress.md

경로를 인자로 받는다 — KRX전용/통합(_AL) 둘 다 이 파일 하나로 돌린다(2026-08-31,
파일을 두 벌 만들지 않는다). 인자를 안 주면 기존 KRX전용 기본값 그대로 동작해
하위호환된다.

진행기록: <compact-progress> (종목단위, 재개 가능)
tick_compress.py의 verify_losslessness를 파일 단위로 통과한 것만 압축한다 — 어긋나는
파일이 나오면 그 날짜만 원본 CSV로 남기고 계속 진행한다(그 종목 전체를 포기하지 않음).
압축 직후 디스크에 실제로 쓰인 parquet을 다시 읽어 원본과 완전히 같은지 재확인하고 나서만
원본을 지운다 — "성공 처리됐는데 실제로는 아닌" 사고를 반복하지 않기 위함.
"""
import argparse
import glob
import json
import os
import time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from tick_compress import RAW_COLUMNS, compress, decompress, verify_losslessness

# 통합(AL) 기본. KRX 전용(data/stocks/tick)은 2026-08-31 삭제됐다 — 되살리지 마라.
TICK_DIR = "data/stocks/tick_al"
MAIN_PROGRESS_PATH = "state/tick_collection/progress.json"
COMPACT_PROGRESS_PATH = "state/tick_collection/compress_progress.json"
LOG_PATH = "state/tick_collection/compress_log.txt"
REPORT_PATH = "state/agent_reports/data-agent_tick_compress_progress.md"
SLEEP_BETWEEN_FILES = 0.1  # 로컬 디스크 압축 — 네트워크 아니라 짧아도 됨, 그래도 겸손하게
POLL_INTERVAL_SEC = 300


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(path: str, default: dict) -> dict:
    if os.path.isfile(path):
        return json.loads(open(path, encoding="utf-8").read())
    return default


def save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def compact_one_file(csv_path: str) -> str:
    """반환: "compacted" / "skipped(사유 로그)" / "already_compacted" """
    pq_path = csv_path[:-4] + ".parquet"
    if os.path.isfile(pq_path) and not os.path.isfile(csv_path):
        return "already_compacted"

    date_str = os.path.basename(csv_path)[:-4]
    raw = pd.read_csv(csv_path)

    reason = verify_losslessness(raw)
    if reason:
        log(f"{csv_path}: 압축 건너뜀(원본 CSV 유지) - {reason}")
        return f"skipped: {reason}"

    compact, ref_price = compress(raw)
    table = pa.Table.from_pandas(compact, preserve_index=False)
    table = table.replace_schema_metadata({b"ref_price": str(ref_price).encode()})

    tmp_pq = pq_path + ".tmp"
    pq.write_table(table, tmp_pq)

    # 디스크에 실제로 쓰인 것을 다시 읽어서 원본과 완전히 같은지 재확인 —
    # "성공 처리됐는데 실제로는 아닌" 사고 재발 방지(오늘 ka10079 사고와 같은 계열).
    reread_table = pq.read_table(tmp_pq)
    ref_from_meta = int(reread_table.schema.metadata[b"ref_price"])
    restored = decompress(reread_table.to_pandas(), date_str, ref_from_meta)
    for col in RAW_COLUMNS:
        if not (raw[col].astype("int64").values == restored[col].astype("int64").values).all():
            os.remove(tmp_pq)
            log(f"{csv_path}: round-trip 불일치({col}) - 원본 CSV 유지, parquet 안 씀")
            return f"roundtrip_mismatch: {col}"

    os.replace(tmp_pq, pq_path)
    os.remove(csv_path)  # round-trip 확인 뒤에만 원본 삭제
    return "compacted"


def compact_one_stock(code: str) -> dict:
    files = sorted(glob.glob(f"{TICK_DIR}/{code}/*.csv"))
    result = {"compacted": 0, "skipped": 0, "errors": []}
    for f in files:
        status = compact_one_file(f)
        if status == "compacted":
            result["compacted"] += 1
        elif status != "already_compacted":
            result["skipped"] += 1
            result["errors"].append(status)
        time.sleep(SLEEP_BETWEEN_FILES)
    return result


def write_progress_report(compact_progress: dict, main_done_count: int) -> None:
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    n = len(compact_progress.get("done", []))
    body = (
        f"# data-agent 틱 압축 진행률 (최신: {time.strftime('%Y-%m-%d %H:%M')})\n\n"
        f"- 압축 완료 {n}종목 (수집 완료 {main_done_count}종목 중)\n"
        f"- 형식: 8컬럼 CSV -> 3컬럼+ref_price 메타데이터 parquet (실측 6.8% 크기)\n"
    )
    tmp = f"{REPORT_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, REPORT_PATH)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--tick-dir", default=TICK_DIR)
    p.add_argument("--main-progress", default=MAIN_PROGRESS_PATH)
    p.add_argument("--compact-progress", default=COMPACT_PROGRESS_PATH)
    p.add_argument("--log", default=LOG_PATH)
    p.add_argument("--report", default=REPORT_PATH)
    p.add_argument("--once", action="store_true",
                    help="한 번만 훑고 종료(상시 데몬 대신 일회성 압축용)")
    p.add_argument("--rescan-all", action="store_true",
                    help="이미 압축완료로 표시된 종목도 다시 훑는다 — tick_compress.py"
                         " 버그 수정(상한가/하한가) 이후 예전에 건너뛴 파일을 다시 잡는 용도")
    return p.parse_args()


def main() -> None:
    global TICK_DIR, MAIN_PROGRESS_PATH, COMPACT_PROGRESS_PATH, LOG_PATH, REPORT_PATH
    args = parse_args()
    TICK_DIR = args.tick_dir
    MAIN_PROGRESS_PATH = args.main_progress
    COMPACT_PROGRESS_PATH = args.compact_progress
    LOG_PATH = args.log
    REPORT_PATH = args.report

    compact_progress = load_json(COMPACT_PROGRESS_PATH, {"done": []})
    done_compact = set(compact_progress["done"])
    log(f"틱 압축 데몬 시작 - tick_dir={TICK_DIR}, once={args.once}, rescan_all={args.rescan_all}")

    while True:
        main_progress = load_json(MAIN_PROGRESS_PATH, {"done": []})
        main_done = set(main_progress.get("done", []))
        to_compact = sorted(main_done) if args.rescan_all else sorted(main_done - done_compact)

        if to_compact:
            log(f"압축 대상 {len(to_compact)}종목 (수집완료 {len(main_done)}, 압축완료 {len(done_compact)})")
        for code in to_compact:
            result = compact_one_stock(code)
            done_compact.add(code)
            compact_progress["done"] = sorted(done_compact)
            save_json(COMPACT_PROGRESS_PATH, compact_progress)
            log(f"{code}: 압축 {result['compacted']}일, 건너뜀 {result['skipped']}일" +
                (f" ({result['errors']})" if result["errors"] else ""))
            write_progress_report(compact_progress, len(main_done))

        if args.once:
            log("--once 지정됨 - 종료")
            break
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
