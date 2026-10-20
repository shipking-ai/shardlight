"""Housekeeping: every TODO/FIXME marker carries an issue number, and every referenced issue appears in TODO.md."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import todos  # noqa: E402


def test_every_todo_marker_names_an_issue():
    items = todos.scan()
    assert items, "the repository is expected to carry TODO(#n) markers"
    bad = [f"{f}:{i}" for f, i, n, _ in items if n is None]
    assert not bad, bad


def test_todo_md_lists_every_referenced_issue():
    text = (ROOT / "TODO.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"issues/(\d+)\)", text))
    used = {n for _, _, n, _ in todos.scan() if n}
    assert used <= listed, sorted(used - listed)
