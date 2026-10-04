"""Tests for finalize.sh: HANDOFF.new.md replaces HANDOFF.md, the previous one is archived."""
import re
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "finalize.sh"
STAMP = "%Y%m%dT%H%M%SZ"


def finalize(d):
    return subprocess.run(["bash", str(SCRIPT), str(d)], capture_output=True, text=True)


def archive_names(d):
    arc = d / ".handoff-archive"
    return sorted(p.name for p in arc.iterdir()) if arc.exists() else []


@pytest.mark.parametrize("new_content", [None, ""], ids=["missing", "empty"])
def test_without_new_file_exits_1_and_leaves_handoff(tmp_path, new_content):
    (tmp_path / "HANDOFF.md").write_text("old")
    if new_content is not None:
        (tmp_path / "HANDOFF.new.md").write_text(new_content)
    proc = finalize(tmp_path)
    assert proc.returncode == 1
    assert (tmp_path / "HANDOFF.md").read_text() == "old"
    assert archive_names(tmp_path) == []


def test_first_handoff_is_renamed_and_path_printed(tmp_path):
    (tmp_path / "HANDOFF.new.md").write_text("new")
    proc = finalize(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str((tmp_path / "HANDOFF.md").resolve())
    assert (tmp_path / "HANDOFF.md").read_text() == "new"
    assert not (tmp_path / "HANDOFF.new.md").exists()
    assert archive_names(tmp_path) == []


def test_relative_dir_still_prints_absolute_path(tmp_path):
    (tmp_path / "HANDOFF.new.md").write_text("new")
    proc = subprocess.run(["bash", str(SCRIPT), "."], cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert Path(proc.stdout.strip()).is_absolute()
    assert Path(proc.stdout.strip()).resolve() == (tmp_path / "HANDOFF.md").resolve()


@pytest.mark.parametrize("taken,suffix", [(0, ""), (1, "-2"), (2, "-3")],
                         ids=["no-collision", "one-taken", "two-taken"])
def test_previous_handoff_archived_with_utc_stamp_and_collision_suffix(tmp_path, taken, suffix):
    arc = tmp_path / ".handoff-archive"
    arc.mkdir()
    now = time.time()
    # Occupy the archive names for every second the script might stamp, so the suffix is deterministic.
    for s in range(-1, 6):
        stamp = time.strftime(STAMP, time.gmtime(now + s))
        for k in range(taken):
            (arc / f"HANDOFF.{stamp}{'' if k == 0 else f'-{k + 1}'}.md").write_text("occupied")
    before = set(archive_names(tmp_path))
    (tmp_path / "HANDOFF.md").write_text("old")
    (tmp_path / "HANDOFF.new.md").write_text("new")
    proc = finalize(tmp_path)
    assert proc.returncode == 0, proc.stderr
    added = set(archive_names(tmp_path)) - before
    assert len(added) == 1
    name, = added
    assert re.fullmatch(rf"HANDOFF\.\d{{8}}T\d{{6}}Z{re.escape(suffix)}\.md", name)
    assert (arc / name).read_text() == "old"
    assert (tmp_path / "HANDOFF.md").read_text() == "new"
    assert not (tmp_path / "HANDOFF.new.md").exists()
