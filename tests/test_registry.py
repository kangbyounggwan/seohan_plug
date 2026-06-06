"""factor_plugin 코어 단위테스트 (host 비의존). 실행: repo_root 에서 `pytest`.

DB 의존 엔드포인트(라우터의 list/get/download)는 llm-backend 통합테스트에서.
여기서는 디스커버리/검증/체크섬/visibility/auth-guard 순수 로직을 친다.
"""
from __future__ import annotations

import copy

import pytest

from factor_plugin import (
    discover_plugins,
    load_pack,
    pack_checksum,
    validate_bundle,
    validate_manifest,
    validate_pack,
    verify_checksum,
)


@pytest.fixture
def seohan():
    recs = discover_plugins()
    assert "seohan" in recs, "seohan 플러그인이 발견돼야 함"
    rec = recs["seohan"]
    return rec, load_pack(rec)


# ── 디스커버리 ────────────────────────────────────────────────
def test_discover_finds_seohan(seohan):
    rec, _ = seohan
    assert rec.id == "seohan"
    assert rec.manifest["type"] == "ontology"
    assert rec.manifest["adapter_type"] == "seohan"


# ── 매니페스트/pack 계약 ──────────────────────────────────────
def test_seohan_manifest_valid(seohan):
    rec, _ = seohan
    assert validate_manifest(rec.manifest) == []


def test_seohan_pack_valid(seohan):
    _, pack = seohan
    assert validate_pack(pack) == []


def test_seohan_bundle_valid(seohan):
    rec, pack = seohan
    assert validate_bundle(rec.manifest, pack) == []


# ── 체크섬 무결성 ─────────────────────────────────────────────
def test_checksum_matches_manifest(seohan):
    rec, pack = seohan
    assert verify_checksum(rec.manifest, pack)
    assert rec.manifest["checksum"] == pack_checksum(pack)


def test_tampered_pack_fails_checksum(seohan):
    rec, pack = seohan
    tampered = copy.deepcopy(pack)
    tampered["entities"]["__INJECTED__"] = {"vars": {}}
    assert not verify_checksum(rec.manifest, tampered)
    errs = validate_bundle(rec.manifest, tampered)
    assert any("checksum" in e for e in errs)


# ── 매니페스트 검증 규칙 ──────────────────────────────────────
def test_missing_required_field():
    errs = validate_manifest({"id": "x"})
    assert any("schema_version" in e for e in errs)


def test_company_private_requires_company_id():
    m = {
        "schema_version": "1.0", "id": "x", "name": "X", "version": "1.0.0",
        "type": "ontology", "visibility": "company-private",
        "author": {"name": "a"}, "kernel_api": "^1.0",
        "data": {"pack": "pack.json"},
        "checksum": "sha256:" + "0" * 64,
    }
    assert any("company_id" in e for e in validate_manifest(m))
    m["company_id"] = "c1"
    assert validate_manifest(m) == []


def test_t1_rejects_permissions():
    m = {
        "schema_version": "1.0", "id": "x", "name": "X", "version": "1.0.0",
        "type": "ontology", "visibility": "public",
        "author": {"name": "a"}, "kernel_api": "^1.0",
        "data": {"pack": "pack.json"}, "checksum": "sha256:" + "0" * 64,
        "permissions": ["fs:write"],
    }
    assert any("permissions" in e for e in validate_manifest(m))


def test_invalid_id_pattern():
    m = {
        "schema_version": "1.0", "id": "Bad ID!", "name": "X", "version": "1.0.0",
        "type": "ontology", "visibility": "public",
        "author": {"name": "a"}, "kernel_api": "^1.0",
        "data": {"pack": "pack.json"}, "checksum": "sha256:" + "0" * 64,
    }
    assert any("id 는" in e for e in validate_manifest(m))


def test_bad_semver():
    m = {
        "schema_version": "1.0", "id": "x", "name": "X", "version": "1.0",
        "type": "ontology", "visibility": "public",
        "author": {"name": "a"}, "kernel_api": "^1.0",
        "data": {"pack": "pack.json"}, "checksum": "sha256:" + "0" * 64,
    }
    assert any("semver" in e for e in validate_manifest(m))


# ── visibility 스코프 (라우터 순수 함수) ──────────────────────
def test_visibility_scope():
    from factor_plugin.backend_router import _visible

    pub = {"visibility": "public"}
    priv = {"visibility": "company-private", "company_id": "C-OWN"}
    assert _visible(pub, None) is True
    assert _visible(pub, "anyone") is True
    assert _visible(priv, "C-OWN") is True
    assert _visible(priv, "C-OTHER") is False  # IDOR 차단
    assert _visible(priv, None) is False
    assert _visible({"visibility": "weird"}, "C-OWN") is False  # fail-closed


# ── auth guard ────────────────────────────────────────────────
def test_require_user_id_guard():
    from fastapi import HTTPException

    from factor_plugin.backend_router import require_user_id

    assert require_user_id("123e4567-e89b-12d3-a456-426614174000")
    with pytest.raises(HTTPException) as e1:
        require_user_id(None)
    assert e1.value.status_code == 401
    with pytest.raises(HTTPException) as e2:
        require_user_id("not-a-uuid")
    assert e2.value.status_code == 400
