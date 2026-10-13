"""Reject production memory paths before experimental reads or writes."""
import os
from pathlib import Path


def reject_live_memory_path(path: Path) -> None:
    resolved = Path(path).expanduser().resolve()
    roots = [(Path.home() / "memories").resolve()]
    if os.environ.get("MEMORY_ROOT"):
        roots.append(Path(os.environ["MEMORY_ROOT"]).expanduser().resolve())
    for root in roots:
        if resolved == root or root in resolved.parents:
            raise ValueError("Research harness cannot use the live memory root or its contents.")
