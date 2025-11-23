"""Pytest bootstrap for backend tests to make the app package importable."""

import sys
from pathlib import Path

# Ensure project packages are importable in tests without relying on external PYTHONPATH.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
