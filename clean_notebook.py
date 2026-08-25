"""Reset workshop.ipynb for commit: strip outputs and blank the paste-in fields.

Run before committing the notebook, after any live run:

    python3 clean_notebook.py
"""

import json
import re
import sys
from pathlib import Path

NOTEBOOK = Path(__file__).parent / "workshop.ipynb"

# Variables a participant fills in by hand. The trailing comment is kept.
PASTE_FIELDS = ("NAME", "THREAD_ID")
FIELD_LINE = re.compile(rf'^({"|".join(PASTE_FIELDS)}) = ".*?"(\s*#.*)?$')


def _as_lines(text: str) -> list[str]:
    """Jupyter's on-disk form for source: one list entry per line, newline kept."""
    parts = text.split("\n")
    return [line + "\n" for line in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def clean(nb: dict) -> int:
    """Blank paste-in fields, clear outputs, and normalize source layout in place.
    Returns the number of cells changed."""
    changed = 0
    for cell in nb["cells"]:
        before = json.dumps(cell, sort_keys=True)
        lines = "".join(cell["source"]).split("\n")
        if cell["cell_type"] == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
            for i, line in enumerate(lines):
                match = FIELD_LINE.match(line)
                if match:
                    lines[i] = f'{match.group(1)} = ""{match.group(2) or ""}'
        cell["source"] = _as_lines("\n".join(lines))
        changed += json.dumps(cell, sort_keys=True) != before
    return changed


def main() -> int:
    nb = json.loads(NOTEBOOK.read_text())
    changed = clean(nb)
    NOTEBOOK.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
    print(f"{NOTEBOOK.name}: {changed} cell(s) cleaned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
