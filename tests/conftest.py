import os
import sys
import tempfile
from pathlib import Path
import pytest

# Global pytest configuration for GMS test suites.
# Ensures MEMORY_ROOT is set to an isolated temporary directory
# before any test module imports memory_mcp_server or memoryctl.
if not os.environ.get("MEMORY_ROOT"):
    _test_mem_root = tempfile.mkdtemp()
    os.environ["MEMORY_ROOT"] = _test_mem_root

repo_root = str(Path(__file__).parent.parent)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

