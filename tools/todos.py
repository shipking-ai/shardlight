"""List every TODO marker in the repository and check the convention ``TODO(#<issue>): text``.

    python tools/todos.py            # grouped by issue
    python tools/todos.py --check    # exit 1 if a TODO/FIXME has no issue number (used by tests)

Every open item lives in a GitHub issue; the code marker points at the place to start.  See TODO.md.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "shots", "assets", "userdata"}
EXTS = {".py", ".yml", ".yaml", ".bat", ".toml"}
MARK = re.compile(r"\b(TODO|FIXME)\b(\(#(\d+)\))?")


def scan() -> list[tuple[str, int, str | None, str]]:
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.suffix not in EXTS or any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        if p.name in ("todos.py", "TODO.md", "test_todos.py"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = MARK.search(line)
            if m and "#" in line.split(m.group(1))[0] + "#":
                out.append((str(p.relative_to(ROOT)).replace("\\", "/"), i, m.group(3), line.strip()))
    return out


def main() -> int:
    items = scan()
    bad = [t for t in items if t[2] is None]
    if "--check" in sys.argv:
        for f, i, _, line in bad:
            print(f"{f}:{i}: TODO without an issue number: {line}")
        return 1 if bad else 0
    by = defaultdict(list)
    for f, i, n, line in items:
        by[n or "?"].append((f, i, line))
    for n in sorted(by, key=lambda x: (x == "?", int(x) if x.isdigit() else 0)):
        print(f"#{n}" if n != "?" else "NO ISSUE")
        for f, i, line in by[n]:
            print(f"    {f}:{i}  {line[:110]}")
    print(f"{len(items)} markers, {len(bad)} without an issue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
