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
