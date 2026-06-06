"""factor_plugin — Factor MES 플러그인 플랫폼 코어 (T1 선언적).

host 비의존 순수 모듈(registry/validate) + host 에 mount 되는 FastAPI 라우터(backend_router).
backend_router 는 app.* 를 지연 import 하므로 이 패키지는 단독 import/테스트 가능.
"""
from .registry import (
    DEFAULT_PLUGINS_DIR,
    PluginRecord,
    discover_plugins,
    load_pack,
    pack_checksum,
)
from .validate import validate_bundle, validate_manifest, validate_pack, verify_checksum

__all__ = [
    "DEFAULT_PLUGINS_DIR",
    "PluginRecord",
    "discover_plugins",
    "load_pack",
    "pack_checksum",
    "validate_bundle",
    "validate_manifest",
    "validate_pack",
    "verify_checksum",
]
