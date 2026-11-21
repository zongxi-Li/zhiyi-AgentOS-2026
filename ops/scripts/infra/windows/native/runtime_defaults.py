"""Read the same non-secret defaults in source checkouts and portable builds."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
BACKEND = ROOT / "apps/backend"
SOURCE = BACKEND / "src/shared/runtime-defaults.json"
BUILT = BACKEND / "dist/shared/runtime-defaults.json"
DEFAULTS = json.loads((SOURCE if SOURCE.is_file() else BUILT).read_text(encoding="utf-8"))
