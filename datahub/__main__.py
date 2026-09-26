"""CLI:  python -m datahub status | wait-quiet | ledger | archive-minute-al

wait-quiet 는 stdout 에만 쓴다(설계 §2.4.9-10, H9) — 무거운 모듈(pandas)도 부르지 않는다.
"""
import argparse
import sys


def _cmd_status(a) -> int:
    from . import status
    V = {"good": "좋음", "warn": "주의", "bad": "나쁨"}
    for r in status.overview():
        ref = r.get("reference_date") or r.get("last_date_mode") or r.get("updated") or "-"
        n = r.get("n_codes") or r.get("codes_archive") or ""
        print(f"{r['id']:<20} {V[r['verdict']]:<4} 기준 {str(ref):<16} {str(n):>5}  {r['reason']}")
    return 0


def _cmd_check(a) -> int:
    """알림 규칙 점검. --send 면 텔레그램 발송(같은 알림은 하루 1회), 아니면 위반만 출력."""
    from datetime import datetime
    from . import alerts
    now = datetime.now()
    found = alerts.evaluate(alerts.build_context(now), now, alerts.enabled_rules())
    if a.send:
        sent = alerts.dispatch(found, now)
        print(f"위반 {len(found)}건 · 발송 {len(sent)}건")
    else:
        for x in found:
            print(f"[{x.id}] {x.message}")
        print(f"위반 {len(found)}건")
    return 0


def _cmd_wait_quiet(a) -> int:
    from .locks import wait_quiet
    return wait_quiet(until=a.until, max_minutes=a.max_minutes)


def _cmd_ledger(a) -> int:
    from . import ledger
    for r in ledger.runs(ledger.read(a.days))[-a.n:]:
        prog = f" {r['done']}/{r['total']}" if r["total"] else ""
        err = f"  ! {r['error']}" if r["error"] else ""
        print(f"{r['ts']}  {r['state']:<5} {r['writer']} [{r['lock']}] {r['trigger']}{prog}{err}")
    return 0


def _cmd_archive(a) -> int:
    import time
    from . import gate, minute_al_archive as arch
    if not a.all and not a.codes:
        print("--all 또는 --codes 가 필요하다", file=sys.stderr)
        return 2
    codes = [c for chunk in (a.codes or []) for c in chunk.split(",") if c] or None
    t0 = time.time()
    with gate.write("minute_al", writer="datahub.archive-minute-al",
                    detail={"mode": "all" if a.all else "codes", "codes": len(codes) if codes else None}) as w:
        s = arch.archive_all(codes, only_stale=not a.force,
                             progress=lambda i, n: (w.progress(i, n),
                                                    print(f"  [{i}/{n}]", flush=True) if i % 200 == 0 else None))
        w.result(**{k: v for k, v in s.items() if k != "failed"}, failed=len(s["failed"]))
    print(f"완료 {time.time() - t0:.0f}초 · 종목 {s['codes']} (병합 {s['merged']}, 건너뜀 {s['skipped']}, 실패 {len(s['failed'])}) "
          f"· 행 {s['rows_before']:,} -> {s['rows_after']:,}")
    for f in s["failed"][:20]:
        print("  실패", f)
    return 1 if s["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="datahub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="데이터셋별 신선도 판정").set_defaults(fn=_cmd_status)
    ck = sub.add_parser("check", help="알림 규칙 점검(--send 면 텔레그램 발송)")
    ck.add_argument("--send", action="store_true")
    ck.set_defaults(fn=_cmd_check)
    q = sub.add_parser("wait-quiet", help="공유 데이터 쓰기가 없을 때까지 대기(0=조용함, 3=기한 초과)")
    q.add_argument("--until", metavar="HH:MM", help="지금 이후 처음 오는 이 시각까지")
    q.add_argument("--max-minutes", type=float, help="최대 대기 분(둘 다 없으면 30)")
    q.set_defaults(fn=_cmd_wait_quiet)
    lg = sub.add_parser("ledger", help="최근 쓰기 작업")
    lg.add_argument("--days", type=int, default=7)
    lg.add_argument("-n", type=int, default=30)
    lg.set_defaults(fn=_cmd_ledger)
    ar = sub.add_parser("archive-minute-al", help="통합 분봉 캐시 -> 보관소 병합")
    ar.add_argument("--all", action="store_true")
    ar.add_argument("--codes", nargs="+", metavar="CODE")
    ar.add_argument("--force", action="store_true", help="이미 병합된 파일도 다시")
    ar.set_defaults(fn=_cmd_archive)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
