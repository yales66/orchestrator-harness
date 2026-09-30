"""Unit tests for the workspace location. Run: python3 -m pytest eval/effort-sweep/test_common.py -q"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import WORK_ROOT  # noqa: E402


def test_work_root_is_the_resolved_system_temp_dir():
    # On macOS the system temp directory sits behind a symlink; the root is resolved so
    # the workspace path is one string however it is reached.
    assert WORK_ROOT == Path(os.path.realpath(tempfile.gettempdir()))
