import sys
from pathlib import Path

# Ensure `app` package is importable in tests without relying on PYTHONPATH mutation externally.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
