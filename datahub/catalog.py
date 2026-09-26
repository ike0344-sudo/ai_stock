"""공유 데이터 카탈로그 로더 + 검증 (설계 §2.4.2, 테스트 H1).

    from datahub import catalog
    catalog.path("daily", code="005930")     # -> <저장소>/data/stocks/daily/005930.csv

경로는 전부 저장소 루트 기준 상대경로다. 테스트만 `DATAHUB_ROOT` 환경변수로 루트를 바꾼다.
"""
import os
import string
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

CATALOG_YAML = Path(__file__).resolve().with_name("catalog.yaml")


def root() -> Path:
    """저장소 루트. 호출마다 읽는다 — 테스트가 환경변수로 바꿀 수 있게."""
    return Path(os.environ.get("DATAHUB_ROOT") or Path(__file__).resolve().parent.parent)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")   # 오타 난 키가 조용히 무시되지 않게


class Lock(_Model):
    path: str
    covers: list[str]


class Writer(_Model):
    id: str
    cmd: str
    triggers: list[str] = []


class Dataset(_Model):
    id: str
    label: str
    basis: str
    path: str
    also: list[str] = []
    lock: str | None = None
    writers: list[Writer] = []
    readers: list[str] = []
    freshness: dict = {}
    retention: str
    notes: str = ""

    @model_validator(mode="after")
    def _paths_relative(self) -> "Dataset":
        for p in [self.path, *self.also]:
            if Path(p).is_absolute() or ".." in Path(p).parts:
                raise ValueError(f"{self.id}: 경로는 저장소 루트 기준 상대경로여야 한다: {p}")
        return self


class Schedule(_Model):
    id: str
    label: str = ""
    owner: str
    when: str
    does: str
    default: str


class Alert(_Model):
    id: str
    title: str = ""
    when: str
    default: str


class Calendar(_Model):
    source: str
    holidays: list[str] = []


class Catalog(_Model):
    version: int
    calendar: Calendar
    locks: dict[str, Lock]
    datasets: list[Dataset]
    schedules: list[Schedule] = []
    alerts: list[Alert] = []

    @model_validator(mode="after")
    def _consistent(self) -> "Catalog":
        ids = [d.id for d in self.datasets]
        if len(ids) != len(set(ids)):
            raise ValueError(f"데이터셋 id 중복: {sorted({i for i in ids if ids.count(i) > 1})}")
        by_id = {d.id: d for d in self.datasets}
        for d in self.datasets:
            if d.lock is not None and d.lock not in self.locks:
                raise ValueError(f"{d.id}: 없는 잠금 '{d.lock}'")
        for name, lk in self.locks.items():          # 잠금 <-> 데이터셋 양방향 일치
            for c in lk.covers:
                if c not in by_id:
                    raise ValueError(f"잠금 {name} 이 없는 데이터셋 '{c}' 를 덮는다")
                if by_id[c].lock != name:
                    raise ValueError(f"잠금 {name} 이 {c} 를 덮는다고 했지만 {c}.lock={by_id[c].lock}")
        for d in self.datasets:
            if d.lock is not None and d.id not in self.locks[d.lock].covers:
                raise ValueError(f"{d.id}: 잠금 {d.lock} 의 covers 에 빠져 있다")
        return self


@lru_cache(maxsize=1)
def load() -> Catalog:
    return Catalog.model_validate(yaml.safe_load(CATALOG_YAML.read_text(encoding="utf-8")))


def dataset(dataset_id: str) -> Dataset:
    for d in load().datasets:
        if d.id == dataset_id:
            return d
    raise KeyError(f"카탈로그에 없는 데이터셋: {dataset_id}")


def placeholders(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def path(dataset_id: str, **fmt: str) -> Path:
    """데이터셋의 저장소 기준 절대경로. `{code}` 같은 자리는 fmt 로 채운다(빠지면 KeyError)."""
    tmpl = dataset(dataset_id).path
    missing = placeholders(tmpl) - fmt.keys()
    if missing:
        raise KeyError(f"{dataset_id}: 경로 인자 부족 {sorted(missing)}")
    return root() / tmpl.format(**fmt)


def lock_base(resource: str) -> Path:
    """잠금 경로(확장자 전). risk_state_lock 이 뒤에 `.lock` 을 붙인다."""
    try:
        return root() / load().locks[resource].path
    except KeyError:
        raise KeyError(f"카탈로그에 없는 잠금: {resource}") from None
