"""S3 라우터 HTTP 통합테스트 — FastAPI TestClient + 가짜 supabase.

llm-backend 무의존: get_supabase 의존성을 override 하므로 app.* 지연 import 안 탐.
테넌트 스코프(visibility) + IDOR(404 은닉) + 체크섬 헤더 + auth guard 를 HTTP 레벨로 검증.
"""
from __future__ import annotations

import json

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from factor_plugin.backend_router import get_supabase, router  # noqa: E402

SEOHAN = "133d7286-33ab-4056-aca4-0287b7e22d05"
OTHER = "00000000-0000-0000-0000-000000000999"
UID = "123e4567-e89b-12d3-a456-426614174000"


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": self._data})()


class FakeSupabase:
    """profiles.company_id 만 흉내."""

    def __init__(self, company_id):
        self.company_id = company_id

    def table(self, _name):
        return _Query([{"company_id": self.company_id}] if self.company_id else [])


def make_client(company_id):
    app = FastAPI()
    app.include_router(router, prefix="/api/ontology")
    app.dependency_overrides[get_supabase] = lambda: FakeSupabase(company_id)
    return TestClient(app)


# ── visibility: 소유 회사 ──────────────────────────────────────
def test_owner_sees_seohan():
    c = make_client(SEOHAN)
    r = c.get("/api/ontology/plugins", params={"user_id": UID})
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()["plugins"]]
    assert "seohan" in ids


def test_other_company_cannot_see_seohan():
    c = make_client(OTHER)
    r = c.get("/api/ontology/plugins", params={"user_id": UID})
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()["plugins"]]
    assert "seohan" not in ids  # company-private → 타사 미노출


# ── download + 무결성 헤더 ─────────────────────────────────────
def test_owner_downloads_pack_with_checksum():
    c = make_client(SEOHAN)
    r = c.get("/api/ontology/plugins/seohan/pack", params={"user_id": UID})
    assert r.status_code == 200
    assert r.headers["X-Pack-Checksum"].startswith("sha256:")
    assert r.headers["X-Plugin-Id"] == "seohan"
    pack = json.loads(r.content)
    assert pack["adapter_type"] == "seohan"
    # 응답 헤더 체크섬 == 매니페스트 선언 체크섬
    mf = json.loads(
        (__import__("pathlib").Path(__file__).resolve().parent.parent
         / "plugins" / "seohan" / "manifest.json").read_text(encoding="utf-8")
    )
    assert r.headers["X-Pack-Checksum"] == mf["checksum"]


# ── IDOR: 미소유 다운로드 차단 ─────────────────────────────────
def test_other_company_pack_404():
    c = make_client(OTHER)
    r = c.get("/api/ontology/plugins/seohan/pack", params={"user_id": UID})
    assert r.status_code == 404  # 존재 은닉


def test_get_plugin_other_company_404():
    c = make_client(OTHER)
    r = c.get("/api/ontology/plugins/seohan", params={"user_id": UID})
    assert r.status_code == 404


# ── auth guard ────────────────────────────────────────────────
def test_no_user_id_401():
    c = make_client(SEOHAN)
    assert c.get("/api/ontology/plugins").status_code == 401


def test_bad_user_id_400():
    c = make_client(SEOHAN)
    assert c.get("/api/ontology/plugins", params={"user_id": "nope"}).status_code == 400


# ── available-adapters (S4 호환) ──────────────────────────────
def test_available_adapters_owner():
    c = make_client(SEOHAN)
    r = c.get("/api/ontology/available-adapters", params={"user_id": UID})
    assert r.status_code == 200
    adapters = [a["adapter_type"] for a in r.json()["adapters"]]
    assert "seohan" in adapters


def test_available_adapters_other_empty():
    c = make_client(OTHER)
    r = c.get("/api/ontology/available-adapters", params={"user_id": UID})
    assert "seohan" not in [a["adapter_type"] for a in r.json()["adapters"]]


# ── S4 install: 다운로드 → 백단 이관(plugin_installs 기록) ────────────────────
class _InstallQuery:
    """plugin_installs 테이블 흉내 — upsert/select/update/eq/order 지원."""

    def __init__(self, store):
        self.store = store
        self._filters = {}
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def upsert(self, row, on_conflict=None, **k):
        self._op, self._payload = "upsert", row
        return self

    def update(self, patch, **k):
        self._op, self._payload = "update", patch
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._op == "upsert":
            row = dict(self._payload)
            key = (row["company_id"], row["plugin_id"])
            existing = self.store.get(key)
            if existing:              # 멱등 — installed_at 불변, 나머지 갱신
                existing.update(row)
                row = existing
            else:
                row.setdefault("installed_at", "t0")
                self.store[key] = row
            return type("R", (), {"data": [row]})()
        if self._op == "update":
            hit = [v for v in self.store.values()
                   if all(v.get(c) == val for c, val in self._filters.items())]
            for v in hit:
                v.update(self._payload)
            return type("R", (), {"data": hit})()
        rows = [v for v in self.store.values()
                if all(v.get(c) == val for c, val in self._filters.items())]
        return type("R", (), {"data": rows})()


class FakeSupabaseInstall:
    """profiles.company_id + plugin_installs 저장소를 흉내."""

    def __init__(self, company_id):
        self.company_id = company_id
        self.installs: dict = {}

    def table(self, name):
        if name == "plugin_installs":
            return _InstallQuery(self.installs)
        return _Query([{"company_id": self.company_id}] if self.company_id else [])


def make_install_client(company_id):
    app = FastAPI()
    app.include_router(router, prefix="/api/ontology")
    fake = FakeSupabaseInstall(company_id)
    app.dependency_overrides[get_supabase] = lambda: fake
    return TestClient(app), fake


def test_install_owner_records():
    c, fake = make_install_client(SEOHAN)
    r = c.post("/api/ontology/plugins/seohan/install", params={"user_id": UID})
    assert r.status_code == 200
    inst = r.json()["install"]
    assert inst["plugin_id"] == "seohan"
    assert inst["company_id"] == SEOHAN
    assert inst["status"] == "active"
    assert inst["checksum"].startswith("sha256:")
    assert (SEOHAN, "seohan") in fake.installs  # DB 기록됨


def test_install_shows_in_list():
    c, _ = make_install_client(SEOHAN)
    c.post("/api/ontology/plugins/seohan/install", params={"user_id": UID})
    r = c.get("/api/ontology/installs", params={"user_id": UID})
    assert r.status_code == 200
    ids = [i["plugin_id"] for i in r.json()["installs"]]
    assert "seohan" in ids


def test_install_idempotent_single_row():
    c, fake = make_install_client(SEOHAN)
    c.post("/api/ontology/plugins/seohan/install", params={"user_id": UID})
    c.post("/api/ontology/plugins/seohan/install", params={"user_id": UID})
    assert len(fake.installs) == 1  # UNIQUE(company_id, plugin_id) — 재설치 = 갱신


def test_install_other_company_404():
    c, fake = make_install_client(OTHER)
    r = c.post("/api/ontology/plugins/seohan/install", params={"user_id": UID})
    assert r.status_code == 404          # 미소유 = 존재 은닉
    assert fake.installs == {}           # 기록 안 됨


def test_uninstall_sets_removed():
    c, _ = make_install_client(SEOHAN)
    c.post("/api/ontology/plugins/seohan/install", params={"user_id": UID})
    r = c.delete("/api/ontology/plugins/seohan/install", params={"user_id": UID})
    assert r.status_code == 200 and r.json()["status"] == "removed"
    lst = c.get("/api/ontology/installs", params={"user_id": UID}).json()["installs"]
    assert [i for i in lst if i["plugin_id"] == "seohan"][0]["status"] == "removed"


def test_install_no_user_id_401():
    c, _ = make_install_client(SEOHAN)
    assert c.post("/api/ontology/plugins/seohan/install").status_code == 401
