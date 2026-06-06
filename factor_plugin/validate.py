"""Plugin validation — 매니페스트/pack 계약 검사 (T1 선언적).

spec/manifest.schema.json + spec/pack.schema.json 의 핵심 제약을 코드로 미러.
jsonschema 가 설치돼 있으면 추가 정식 검증, 없으면 manual 검사만(의존성 경량).
SDK(fpkg)와 서버(backend_router/install)가 공유.
"""
from __future__ import annotations

import re

from .registry import pack_checksum

_ID_RE = re.compile(r"^[a-z0-9_]+$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_CHECKSUM_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_PACKFILE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

ALLOWED_TYPES = {"ontology"}  # T1
ALLOWED_VISIBILITY = {"public", "company-private"}

_REQUIRED_MANIFEST = (
    "schema_version", "id", "name", "version", "type",
    "visibility", "author", "kernel_api", "data", "checksum",
)


def validate_manifest(m: dict) -> list[str]:
    """매니페스트 오류 목록(빈 리스트 = 유효)."""
    errs: list[str] = []
    for k in _REQUIRED_MANIFEST:
        if k not in m or m[k] in (None, ""):
            errs.append(f"필수 필드 누락: {k}")

    if isinstance(m.get("id"), str) and not _ID_RE.match(m["id"]):
        errs.append("id 는 ^[a-z0-9_]+$ 형식이어야 함")
    if isinstance(m.get("version"), str) and not _SEMVER_RE.match(m["version"]):
        errs.append("version 은 semver(x.y.z) 이어야 함")
    if m.get("type") not in ALLOWED_TYPES:
        errs.append(f"type 은 {sorted(ALLOWED_TYPES)} (T1) 중 하나여야 함")
    if m.get("visibility") not in ALLOWED_VISIBILITY:
        errs.append(f"visibility 는 {sorted(ALLOWED_VISIBILITY)} 중 하나여야 함")
    if m.get("visibility") == "company-private" and not m.get("company_id"):
        errs.append("company-private 는 company_id 필수")
    if isinstance(m.get("checksum"), str) and not _CHECKSUM_RE.match(m["checksum"]):
        errs.append("checksum 은 'sha256:<64 hex>' 형식이어야 함")
    if m.get("permissions"):
        errs.append("T1 선언적 플러그인은 permissions 가 비어 있어야 함(코드/권한 금지)")

    d = m.get("data")
    if not isinstance(d, dict) or not isinstance(d.get("pack"), str):
        errs.append("data.pack (pack 파일명) 필수")
    elif not _PACKFILE_RE.match(d["pack"]):
        errs.append("data.pack 파일명은 ^[A-Za-z0-9_.-]+$ (traversal 금지)")

    author = m.get("author")
    if not isinstance(author, dict) or not author.get("name"):
        errs.append("author.name 필수")
    return errs


def validate_pack(p: dict) -> list[str]:
    """pack 데이터 오류 목록."""
    errs: list[str] = []
    if not isinstance(p.get("adapter_type"), str):
        errs.append("pack.adapter_type (문자열) 필수")
    if not isinstance(p.get("entities"), dict):
        errs.append("pack.entities (객체) 필수")
    if not isinstance(p.get("edges"), list):
        errs.append("pack.edges (배열) 필수")
    return errs


def verify_checksum(manifest: dict, pack: dict) -> bool:
    """매니페스트 checksum 이 pack 의 canonical sha256 과 일치?"""
    return manifest.get("checksum") == pack_checksum(pack)


def validate_bundle(manifest: dict, pack: dict) -> list[str]:
    """매니페스트+pack 통합 검증 (cross-check 포함). 빈 리스트 = 게시 가능."""
    errs = validate_manifest(manifest) + validate_pack(pack)
    if manifest.get("type") == "ontology":
        ma, pa = manifest.get("adapter_type"), pack.get("adapter_type")
        if ma and pa and ma != pa:
            errs.append(f"adapter_type 불일치: manifest={ma} pack={pa}")
    if isinstance(manifest.get("checksum"), str) and _CHECKSUM_RE.match(manifest["checksum"]):
        if not verify_checksum(manifest, pack):
            errs.append("checksum 불일치 (pack 변조 또는 매니페스트 미갱신 — `fpkg checksum` 재실행)")
    return errs
