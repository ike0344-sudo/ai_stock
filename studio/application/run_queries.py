"""실행 기록 조회 — 목록·상세·거래·평가금·CSV·수정·비교 (설계서 §4.1 `/api/runs*`, §5.4 결과·실행 기록·비교).

읽기 전용 + 이름·메모·별표 수정 + 결과 삭제뿐이다. **spec.json 은 실행 뒤에 바꿀 수 없다**(사전 판정 기준을 사후에 못 고치게 —
backtest-agent 계약): PATCH 는 name·memo·starred 만 받는다. 삭제는 results/studio/<run_id> 만(데이터 아님).
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd

from studio.domain.narration import narrate
from studio.domain.spec import Spec

from .run_analysis import analyze, downsample
from .services import Services
from .spec_diff import diff_specs

EDITABLE = ("name", "memo", "starred")
COMPARE_MIN, COMPARE_MAX = 2, 5
MAX_MEMO = 2000
MAX_NAME = 100


class RunNotFound(Exception):
    pass


class RunInputError(ValueError):
    """수정·비교 요청 값 오류(API 400/422 로 바뀐다)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field, self.message = field, message


def clean(o: Any) -> Any:
    """JSON 안전화: NaN·±inf → None, numpy → 파이썬, Timestamp → ISO 문자열."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def frame_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame → JSON 안전한 dict 목록(시각은 ISO)."""
    if df.empty:
        return []
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%dT%H:%M:%S").where(out[col].notna(), None)
    out = out.astype(object).where(out.notna(), None)
    return clean(out.to_dict(orient="records"))


def list_runs(svc: Services, *, q: str | None = None, mode: str | None = None, starred: bool | None = None,
              kind: str | None = None) -> list[dict[str, Any]]:
    rows = svc.run_files.list_rows()
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in (r["name"] or "").lower() or needle in (r["memo"] or "").lower()
                or needle in r["run_id"]]
    if mode:
        rows = [r for r in rows if r["mode"] == mode]
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    if starred is not None:
        rows = [r for r in rows if bool(r["starred"]) == starred]
    return rows  # 최신 먼저(run_id 가 시각순)


def _require(svc: Services, run_id: str) -> None:
    if not svc.run_files.exists(run_id):
        raise RunNotFound(run_id)


def run_detail(svc: Services, run_id: str) -> dict[str, Any]:
    """§4.2 GET /api/runs/{id}: meta·spec·summary·warnings + 읽을 때 계산한 분해(analysis)와 풀이 문장."""
    _require(svc, run_id)
    f = svc.run_files
    meta, spec_d, summary = f.read_json(run_id, "meta.json"), f.read_json(run_id, "spec.json"), f.read_json(run_id, "summary.json")
    initial = float((spec_d.get("portfolio") or {}).get("initial_capital") or 10_000_000)
    try:
        analysis = analyze(f.read_trades(run_id), f.read_equity(run_id), initial, svc.theme_groups())
    except Exception as exc:  # 분해 실패가 결과 화면 전체를 막지 않게 — 원인을 화면에 보여준다
        analysis = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        narration = narrate(Spec.model_validate(spec_d))
    except Exception:
        narration = None
    return clean({"run_id": run_id, "meta": meta, "spec": spec_d, "summary": summary, "warnings": meta.get("warnings", []),
                  "analysis": analysis, "narration": narration,
                  "has_grid": svc.run_files.has(run_id, "grid.parquet"), "has_folds": svc.run_files.has(run_id, "folds.json")})


def run_trades(svc: Services, run_id: str) -> list[dict[str, Any]]:
    _require(svc, run_id)
    return frame_records(svc.run_files.read_trades(run_id))


def run_equity(svc: Services, run_id: str) -> list[dict[str, Any]]:
    _require(svc, run_id)
    return frame_records(svc.run_files.read_equity(run_id))


class NoSuchPart(Exception):
    """그 실행엔 그 파일이 없다(예: 일반 백테스트에 grid.parquet) — API 404."""


def run_grid(svc: Services, run_id: str) -> list[dict[str, Any]]:
    """최적화·워크포워드의 조합 표 전체(무효·거래 부족 조합 포함 — 되는 것만 보이지 않게)."""
    _require(svc, run_id)
    if not svc.run_files.has(run_id, "grid.parquet"):
        raise NoSuchPart("grid")
    return frame_records(svc.run_files.read_grid(run_id))


def run_folds(svc: Services, run_id: str) -> dict[str, Any]:
    _require(svc, run_id)
    if not svc.run_files.has(run_id, "folds.json"):
        raise NoSuchPart("folds")
    return clean(svc.run_files.read_json(run_id, "folds.json"))


def trades_csv(svc: Services, run_id: str) -> bytes:
    """Excel 이 한글을 바로 읽도록 UTF-8 BOM."""
    _require(svc, run_id)
    buf = io.StringIO()
    svc.run_files.read_trades(run_id).to_csv(buf, index=False)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def patch_run(svc: Services, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _require(svc, run_id)
    unknown = set(body) - set(EDITABLE)
    if unknown:
        raise RunInputError(sorted(unknown)[0], f"수정할 수 없는 칸: {sorted(unknown)} (이름·메모·별표만 — 명세는 실행 뒤 못 고친다)")
    patch: dict[str, Any] = {}
    if "name" in body:
        name = body["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
            raise RunInputError("name", f"이름은 1~{MAX_NAME}자 문자열")
        patch["name"] = name.strip()
    if "memo" in body:
        memo = body["memo"]
        if memo is not None and (not isinstance(memo, str) or len(memo) > MAX_MEMO):
            raise RunInputError("memo", f"메모는 {MAX_MEMO}자 이하 문자열")
        patch["memo"] = memo or None
    if "starred" in body:
        if not isinstance(body["starred"], bool):
            raise RunInputError("starred", "starred 는 true/false")
        patch["starred"] = body["starred"]
    svc.run_files.patch_meta(run_id, patch)
    return next(r for r in svc.run_files.list_rows() if r["run_id"] == run_id)


def delete_run(svc: Services, run_id: str) -> None:
    _require(svc, run_id)
    svc.run_files.delete(run_id)


def compare_runs(svc: Services, ids: list[str]) -> dict[str, Any]:
    """2~5 개 실행: 곡선(같은 기준으로 100 시작), 지표, 첫 실행 대비 조건 차이 문장."""
    if not isinstance(ids, list) or not (COMPARE_MIN <= len(ids) <= COMPARE_MAX) or len(set(ids)) != len(ids):
        raise RunInputError("ids", f"서로 다른 실행 {COMPARE_MIN}~{COMPARE_MAX}개를 골라야 한다")
    rows = {r["run_id"]: r for r in svc.run_files.list_rows()}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise RunNotFound(missing[0])
    specs: dict[str, Spec] = {i: Spec.model_validate(svc.run_files.read_json(i, "spec.json")) for i in ids}
    runs = []
    for i in ids:
        eq = svc.run_files.read_equity(i)
        base = float(eq["equity"].iloc[0]) if len(eq) else 1.0
        cols = ["ts", "equity", "drawdown_pct"] + [c for c in eq.columns if c.startswith("benchmark_")]
        small = downsample(eq[[c for c in cols if c in eq.columns]])
        curve = frame_records(small.assign(rel=small["equity"] / base * 100)) if len(eq) else []
        summary = svc.run_files.read_json(i, "summary.json")
        runs.append({**rows[i], "metrics_all": summary.get("metrics") or {}, "equity": curve,
                     "initial_capital": float(specs[i].portfolio.initial_capital)})
    diffs = [{"run_id": i, "vs": ids[0], "items": diff_specs(specs[ids[0]], specs[i])} for i in ids[1:]]
    return clean({"runs": runs, "diffs": diffs})
