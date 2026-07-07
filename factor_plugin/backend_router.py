"""S3 — Ontology Plugin Registry API (테넌트 스코프). llm-backend 에 mount.

⚠️ 보안: registry(discover_plugins/load_pack)는 스코프 0 — 누구 것이든 다 보인다.
   이 라우터가 require_user_id + company_id 기반 visibility 스코프를 강제한다:
     - public          → 모든 인증 사용자
     - company-private → 요청자 profiles.company_id == manifest.company_id 일 때만
   company-private 의 미소유 요청 = **404(존재 은닉, IDOR 차단)**.
   ⚠️ company_id 를 클라가 query 로 보내지 못한다(우회 차단). 신원은 user_id → profiles 로만.

   app.* 는 함수 안에서 지연 import → factor_plugin 패키지는 단독 import/테스트 가능.

mount (llm-backend/app/main.py):
   from factor_plugin.backend_router import router as ontology_router
   app.include_router(ontology_router, prefix="/api/ontology", tags=["Ontology"])

서빙 소스 = 이 repo 의 plugins/ (또는 env FACTOR_PLUGINS_DIR). PipelineV3 overlay 의
factor-MES/packs/ 와는 별개 디렉터리(혼동 금지).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .registry import DEFAULT_PLUGINS_DIR, discover_plugins, load_pack, pack_checksum

logger = logging.getLogger(__name__)
router = APIRouter()

# 카탈로그 노출용 경량 매니페스트 키 (내부 경로/data 포인터 제외)
_PUBLIC_KEYS = (
    "id", "name", "version", "type", "adapter_type",
    "visibility", "description", "author", "kernel_api", "checksum",
)


def _plugins_dir() -> Path:
    env = os.environ.get("FACTOR_PLUGINS_DIR")
    return Path(env) if env else DEFAULT_PLUGINS_DIR


def get_supabase():
    """service-role supabase. llm-backend 런타임에서만 결합(지연 import)."""
    from app.main import get_supabase_client  # noqa: PLC0415

    return get_supabase_client()


def require_user_id(user_id: str | None = Query(None)) -> str:
    """user_id 없으면 401, 비-UUID 면 400. (api_catalog.require_user_id 패턴.)"""
    if not user_id:
        raise HTTPException(401, "user_id required (Supabase auth.uid())")
    try:
        uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(400, f"user_id must be a valid UUID (got {user_id!r})")
    return user_id


def _company_id_for_user(sb, user_id: str) -> str | None:
    """profiles.company_id (service-role bypass)."""
    rows = (
        sb.table("profiles").select("company_id").eq("id", user_id)
        .limit(1).execute().data
    )
    return rows[0]["company_id"] if rows else None


def _visible(manifest: dict, company_id: str | None) -> bool:
    """visibility 스코프. unknown visibility = 숨김(fail-closed)."""
    vis = manifest.get("visibility")
    if vis == "public":
        return True
    if vis == "company-private":
        return company_id is not None and manifest.get("company_id") == company_id
    return False


def _public_manifest(manifest: dict) -> dict:
    return {k: manifest[k] for k in _PUBLIC_KEYS if k in manifest}


@router.get("/plugins")
def list_plugins(
    user_id: str = Depends(require_user_id),
    sb=Depends(get_supabase),
) -> dict:
    """요청자에게 보이는 플러그인 매니페스트 목록(public + 소유 company-private)."""
    company_id = _company_id_for_user(sb, user_id)
    recs = discover_plugins(_plugins_dir())
    items = [
        _public_manifest(r.manifest)
        for r in recs.values()
        if _visible(r.manifest, company_id)
    ]
    return {"plugins": items}


@router.get("/available-adapters")
def available_adapters(
    user_id: str = Depends(require_user_id),
    sb=Depends(get_supabase),
) -> dict:
    """S4 호환 — 보이는 ontology 플러그인을 adapter 목록으로(데스크탑 install UI)."""
    company_id = _company_id_for_user(sb, user_id)
    recs = discover_plugins(_plugins_dir())
    adapters = [
        {
            "adapter_type": r.manifest.get("adapter_type", r.id),
            "plugin_id": r.id,
            "name": r.manifest.get("name"),
            "version": r.manifest.get("version"),
        }
        for r in recs.values()
        if r.manifest.get("type") == "ontology" and _visible(r.manifest, company_id)
    ]
    return {"adapters": adapters}


@router.get("/plugins/{plugin_id}")
def get_plugin(
    plugin_id: str,
    user_id: str = Depends(require_user_id),
    sb=Depends(get_supabase),
) -> dict:
    """단일 플러그인 매니페스트. 미소유 company-private/미존재 → 404."""
    company_id = _company_id_for_user(sb, user_id)
    rec = discover_plugins(_plugins_dir()).get(plugin_id)
    if not rec or not _visible(rec.manifest, company_id):
        raise HTTPException(404, "plugin not found")
    return _public_manifest(rec.manifest)


@router.get("/plugins/{plugin_id}/pack")
def download_pack(
    plugin_id: str,
    user_id: str = Depends(require_user_id),
    sb=Depends(get_supabase),
) -> Response:
    """pack 데이터 다운로드(설치용). 미소유/미존재 → 404(존재 은닉). 무결성 헤더 첨부."""
    company_id = _company_id_for_user(sb, user_id)
    rec = discover_plugins(_plugins_dir()).get(plugin_id)
    if not rec or not _visible(rec.manifest, company_id):
        raise HTTPException(404, "plugin not found")
    pack = load_pack(rec)
    body = json.dumps(pack, ensure_ascii=False, separators=(",", ":"))
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "X-Pack-Checksum": pack_checksum(pack),
            "X-Plugin-Id": rec.id,
            "X-Plugin-Version": str(rec.manifest.get("version", "")),
        },
    )


# ── S4 install: 다운로드 → 백단 이관(테넌트 설치 기록) ──────────────────────
# "지금 열기(webview)" 와 구분되는 "다운로드" 액션이 이 엔드포인트를 부른다.
# 데이터형(T1 ontology) 플러그인만 설치 대상 — 코드 실행 0, 선언형 pack.
# 기록 테이블 plugin_installs (마이그 078): UNIQUE(company_id, plugin_id) upsert.
# 쓰기는 service_role 로만 — visibility 검증을 통과한 요청만 기록된다(IDOR 차단 동일).
_INSTALLABLE_TYPES = ("ontology",)


@router.post("/plugins/{plugin_id}/install")
def install_plugin(
    plugin_id: str,
    user_id: str = Depends(require_user_id),
    sb=Depends(get_supabase),
) -> dict:
    """플러그인을 요청자 회사에 설치 기록(백단 이관). 미소유/미존재 → 404(존재 은닉).

    멱등: 같은 (company_id, plugin_id) 재호출은 버전/체크섬/status 만 갱신(installed_at 불변).
    """
    company_id = _company_id_for_user(sb, user_id)
    if company_id is None:
        raise HTTPException(403, "no company for user (profiles.company_id null)")
    rec = discover_plugins(_plugins_dir()).get(plugin_id)
    if not rec or not _visible(rec.manifest, company_id):
        raise HTTPException(404, "plugin not found")
    m = rec.manifest
    if m.get("type") not in _INSTALLABLE_TYPES:
        # 서비스형(report 등)은 클릭 설치 불가 — 데이터형만 백단 이관 대상.
        raise HTTPException(
            400, f"plugin type {m.get('type')!r} is not installable (data plugins only)"
        )
    pack = load_pack(rec)  # 설치 시점 pack 실체화 → 체크섬 스냅샷(드리프트 감지 기준)
    row = {
        "company_id": company_id,
        "user_id": user_id,
        "plugin_id": rec.id,
        "plugin_type": m.get("type", "ontology"),
        "adapter_type": m.get("adapter_type"),
        "version": str(m.get("version", "")),
        "checksum": pack_checksum(pack),
        "status": "active",
        "manifest": _public_manifest(m),
        "error": None,
    }
    res = (
        sb.table("plugin_installs")
        .upsert(row, on_conflict="company_id,plugin_id")
        .execute()
    )
    installed = res.data[0] if getattr(res, "data", None) else row
    logger.info(
        "plugin installed: company=%s plugin=%s v%s by user=%s",
        company_id, rec.id, row["version"], user_id,
    )
    return {"install": installed}


@router.get("/installs")
def list_installs(
    user_id: str = Depends(require_user_id),
    sb=Depends(get_supabase),
) -> dict:
    """요청자 회사의 설치 이력(추적 UI/설치상태). status 무관 전체 — FE 가 필터."""
    company_id = _company_id_for_user(sb, user_id)
    if company_id is None:
        return {"installs": []}
    rows = (
        sb.table("plugin_installs")
        .select("*")
        .eq("company_id", company_id)
        .order("installed_at", desc=True)
        .execute()
        .data
    )
    return {"installs": rows or []}


@router.delete("/plugins/{plugin_id}/install")
def uninstall_plugin(
    plugin_id: str,
    user_id: str = Depends(require_user_id),
    sb=Depends(get_supabase),
) -> dict:
    """설치 제거(soft) — status=removed. 이력 보존(감사 추적). 미소유여도 회사 스코프로 no-op."""
    company_id = _company_id_for_user(sb, user_id)
    if company_id is None:
        raise HTTPException(403, "no company for user (profiles.company_id null)")
    (
        sb.table("plugin_installs")
        .update({"status": "removed"})
        .eq("company_id", company_id)
        .eq("plugin_id", plugin_id)
        .execute()
    )
    logger.info("plugin uninstalled: company=%s plugin=%s by user=%s",
                company_id, plugin_id, user_id)
    return {"ok": True, "plugin_id": plugin_id, "status": "removed"}
