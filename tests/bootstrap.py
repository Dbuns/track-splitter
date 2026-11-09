"""Locate the app when running checks directly or with unittest discovery."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
(ROOT / ".tmp").mkdir(parents=True, exist_ok=True)
(ROOT / ".tmp" / "test-results").mkdir(parents=True, exist_ok=True)
