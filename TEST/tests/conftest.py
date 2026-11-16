"""Expose canonical application and test packages from their current locations."""
import sys
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'apps/agentOS/src').is_dir())
for path in (ROOT, ROOT / 'apps/agentOS', ROOT / 'apps/agentOS/src', ROOT / 'apps/agent'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
