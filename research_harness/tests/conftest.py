"""Research tests use the product only as a system under test."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MEMORY_ROOT", tempfile.mkdtemp(prefix="gms_research_tests_"))
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
