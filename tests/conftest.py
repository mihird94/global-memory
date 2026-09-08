import os
import tempfile
import pytest

# Global pytest configuration for GMS test suites.
# Ensures MEMORY_ROOT is set to an isolated temporary directory
# before any test module imports memory_mcp_server or memoryctl.
if not os.environ.get("MEMORY_ROOT"):
    _test_mem_root = tempfile.mkdtemp()
    os.environ["MEMORY_ROOT"] = _test_mem_root
