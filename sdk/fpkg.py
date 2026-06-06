#!/usr/bin/env python
"""fpkg — Factor MES 플러그인 작성자 CLI (T1 선언적).

플러그인을 개발해 올리는 흐름의 로컬 단계:

  python sdk/fpkg.py validate  plugins/seohan     # 매니페스트+pack 계약 검증
  python sdk/fpkg.py checksum  plugins/seohan     # pack canonical sha256 재계산 → manifest 갱신
  python sdk/fpkg.py build     plugins/seohan      # 배포용 .fpkg(zip) 생성 (dist/)

검증 통과한 번들만 게시(레지스트리 업로드). 게시(publish)는 운영 레지스트리 확정 후 추가.
host(llm-backend) 비의존 — factor_plugin 코어만 사용.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

# repo_root 를 path 에 (sdk/ 에서 실행해도 factor_plugin import 되게)
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from factor_plugin import pack_checksum, validate_bundle  # noqa: E402


def _load(bundle_dir: Path) -> tuple[dict, dict, Path]:
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    pack_name = (manifest.get("data") or {}).get("pack", "pack.json")
    pack_path = bundle_dir / pack_name
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    return manifest, pack, pack_path


def cmd_validate(bundle_dir: Path) -> int:
    manifest, pack, _ = _load(bundle_dir)
    errs = validate_bundle(manifest, pack)
    if errs:
        print(f"[FAIL] {bundle_dir} - {len(errs)} 오류")
        for e in errs:
            print(f"   - {e}")
        return 1
    print(f"[OK] {bundle_dir} - 유효 (id={manifest['id']} v{manifest['version']})")
    return 0


def cmd_checksum(bundle_dir: Path) -> int:
    manifest, pack, _ = _load(bundle_dir)
    new = pack_checksum(pack)
    old = manifest.get("checksum")
    manifest["checksum"] = new
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"checksum 갱신: {old} → {new}")
    return 0


def cmd_build(bundle_dir: Path) -> int:
    manifest, pack, pack_path = _load(bundle_dir)
    errs = validate_bundle(manifest, pack)
    if errs:
        print(f"[FAIL] build 중단 - 검증 실패 ({len(errs)})")
        for e in errs:
            print(f"   - {e}")
        return 1
    dist = _REPO_ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"{manifest['id']}-{manifest['version']}.fpkg"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(bundle_dir / "manifest.json", "manifest.json")
        z.write(pack_path, pack_path.name)
    print(f"[OK] build -> {out} ({out.stat().st_size} bytes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows cp949 콘솔에서도 한글/기호 출력되게 UTF-8 강제
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(prog="fpkg", description="Factor MES 플러그인 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "checksum", "build"):
        sp = sub.add_parser(name)
        sp.add_argument("bundle_dir", type=Path)
    args = p.parse_args(argv)
    fn = {"validate": cmd_validate, "checksum": cmd_checksum, "build": cmd_build}[args.cmd]
    return fn(args.bundle_dir.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
