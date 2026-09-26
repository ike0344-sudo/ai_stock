"""API 테스트 공용 — 임시 루트 + 인라인 러너(워커 프로세스 대신 같은 프로세스에서 작업을 돌린다) + TestClient.

TestClient 의 Host 를 127.0.0.1:8780 으로 고정한다(서버가 실제로 받는 Host — guard 의 루프백 검사를 통과해야 하므로).
"""
import os

import pytest
from fastapi.testclient import TestClient

from jobrunner.dispatcher import Dispatcher
from jobrunner.store import JobStore
from jobrunner.worker import run_job
from studio.api.app import create_app
from studio.application import jobs as app_jobs
from studio.application.services import Services
from studio.infrastructure.legacy_adapter import LegacyAdapter
from studio.infrastructure.preset_store import FilePresetStore
from studio.infrastructure.run_files import FileRunFiles
from studio.infrastructure.run_store import FileRunStore
from studio.infrastructure.services_factory import legacy_catalog
from tests.studio.application.fakes import FakeMarketData

BASE = "http://127.0.0.1:8780"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DATAHUB_ROOT", str(tmp_path))
    monkeypatch.delenv("STUDIO_DEV_ORIGIN", raising=False)
    (tmp_path / ".env").write_text("KIWOOM_SECRETKEY=sk-test-SECRET-VALUE-123456\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def store(root):
    return JobStore(root)


@pytest.fixture
def disp(store):
    def inline(job_id):
        run_job(store, job_id)  # 워커가 하는 일을 그 자리에서 — 끝난 뒤 디스패처의 pid 기록은 running 일 때만이라 무해
        return os.getpid(), 0.0

    return Dispatcher(store, spawner=inline)


@pytest.fixture
def fake_deps(root, monkeypatch):
    run_store = FileRunStore(root / "results" / "studio")
    monkeypatch.setattr(app_jobs, "deps_factory",
                        lambda: app_jobs.Deps(market_data=FakeMarketData(), run_store=run_store))
    return run_store


THEMES = {"000010": "지주사", "000020": "반도체", "000030": "지주사"}


@pytest.fixture
def services(root, fake_deps):
    """모듈 4 API 의 의존 — 가짜 시장 데이터(요청마다 새로), 임시 폴더의 실행 저장소·프리셋(저장소 기본 프리셋 사본)."""
    import shutil
    from pathlib import Path
    presets = root / "presets" / "studio"
    shutil.copytree(Path(__file__).resolve().parents[3] / "presets" / "studio", presets)
    runs = root / "results" / "studio"
    return Services(market_data=FakeMarketData, run_store=fake_deps, run_files=FileRunFiles(runs), presets=FilePresetStore(presets),
                    legacy=LegacyAdapter(), legacy_catalog=legacy_catalog, theme_groups=lambda: THEMES)


@pytest.fixture
def client(root, disp, fake_deps, services):
    return TestClient(create_app(root, dispatcher=disp, static_dir=root / "no-static", services=services), base_url=BASE)


def make_run(client, disp, **spec_over) -> str:
    """백테스트를 하나 돌려 run_id 를 돌려준다(인라인 러너)."""
    from tests.studio.application.fakes import spec_dict
    body = spec_dict(universe={"type": "top_value", "n": 4, "exclude": []}, **spec_over)
    res = client.post("/api/jobs/backtest", json=body)
    assert res.status_code == 202, res.text
    disp.tick()
    job = client.get(f"/api/jobs/{res.json()['data']['job_id']}").json()["data"]
    assert job["status"] == "succeeded", job
    return res.json()["data"]["run_id"]
