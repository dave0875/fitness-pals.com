"""Pytest bootstrap to ensure the repo root is on sys.path for imports."""

import sys
from pathlib import Path

# Add repo root to sys.path so `services.training_agent` imports resolve in CI.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
