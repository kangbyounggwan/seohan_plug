"""pytest 부트스트랩 — repo_root 를 path 에 추가해 factor_plugin import 가능하게."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
