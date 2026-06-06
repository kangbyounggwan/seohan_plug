"""Plugin registry — host 비의존 디스커버리/로딩/체크섬 (T1 선언적 플러그인).

app.* / FastAPI 의존 0 → 이 repo 안에서 단독 단위테스트. FastAPI 라우터(backend_router)가
이걸 import 해 테넌트 스코프 + HTTP 를 얹는다.

플러그인 레이아웃 (드롭인):
  plugins/<id>/manifest.json   — 매니페스트(계약, spec/manifest.schema.json)
  plugins/<id>/pack.json       — 데이터 본문(spec/pack.schema.json)

새 플러그인 = plugins/<id>/ 디렉터리만 떨구면 등록(코드 수정 0). 향후 레지스트리 DB 로
이관해도 이 인터페이스(discover_plugins/load_pack)는 유지.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# repo_root/plugins  (이 파일: factor_plugin/registry.py → parent.parent = repo_root)
DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"


@dataclass(frozen=True)
class PluginRecord:
    """발견된 플러그인 한 개 (매니페스트 + 번들 디렉터리)."""

    id: str
    manifest: dict
    dir: Path

    @property
    def pack_path(self) -> Path:
        pack_name = (self.manifest.get("data") or {}).get("pack", "pack.json")
        return self.dir / pack_name


def canonical_bytes(pack: dict) -> bytes:
    """체크섬/전송용 canonical 직렬화 (compact, ensure_ascii=False). 서버·SDK 동일 규칙."""
    return json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def pack_checksum(pack: dict) -> str:
    """pack 데이터의 canonical sha256 ('sha256:<hex>')."""
    return "sha256:" + hashlib.sha256(canonical_bytes(pack)).hexdigest()


def discover_plugins(plugins_dir: Path | None = None) -> dict[str, PluginRecord]:
    """plugins/*/manifest.json 스캔 → {id: PluginRecord}. 손상/누락은 skip."""
    base = plugins_dir or DEFAULT_PLUGINS_DIR
    out: dict[str, PluginRecord] = {}
    if not base.exists():
        logger.info("plugins dir 없음: %s", base)
        return out
    for mf in sorted(base.glob("*/manifest.json")):
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception("manifest 파싱 실패 (skip): %s", mf)
            continue
        pid = manifest.get("id")
        if not pid:
            logger.warning("manifest id 없음 (skip): %s", mf)
            continue
        if pid in out:
            logger.warning("plugin id 중복 (%s): %s 가 덮어씀", pid, mf)
        out[pid] = PluginRecord(id=pid, manifest=manifest, dir=mf.parent)
        logger.info("plugin 발견: id=%s type=%s ver=%s dir=%s",
                    pid, manifest.get("type"), manifest.get("version"), mf.parent.name)
    return out


def load_pack(record: PluginRecord) -> dict:
    """플러그인의 pack 데이터 본문 로드."""
    return json.loads(record.pack_path.read_text(encoding="utf-8"))
