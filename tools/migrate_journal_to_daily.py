#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_mem_root() -> Path:
    memory_root = os.environ.get("MEMORY_ROOT")
    if memory_root:
        return Path(memory_root).expanduser()
    return Path.home() / "memories"


MEM_ROOT = _default_mem_root()


def migrate_journal(mem_root: Path = MEM_ROOT, backup: bool = True) -> dict:
    journal_path = mem_root / "episodic" / "journal.md"
    history_dir = mem_root / "episodic" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    if not journal_path.exists():
        print(f"No journal found at {journal_path}")
        return {"migrated_days": 0, "entries_count": 0}

    content = journal_path.read_text()
    if not content.strip():
        print(f"Journal at {journal_path} is empty.")
        return {"migrated_days": 0, "entries_count": 0}

    if backup:
        backup_path = journal_path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(journal_path, backup_path)
        print(f"Backed up original journal to {backup_path}")

    # Regex to split on entry headers: ### YYYY-MM-DD ...
    header_regex = re.compile(r"^(###\s+(\d{4}-\d{2}-\d{2}).*)$", re.MULTILINE)

    matches = list(header_regex.finditer(content))
    if not matches:
        print("No date headers (### YYYY-MM-DD) found in journal.")
        return {"migrated_days": 0, "entries_count": 0}

    entries_by_date: dict[str, list[str]] = {}

    for i, match in enumerate(matches):
        date_str = match.group(2)
        start_idx = match.start()
        end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        entry_text = content[start_idx:end_idx].strip()

        if date_str not in entries_by_date:
            entries_by_date[date_str] = []
        entries_by_date[date_str].append(entry_text)

    total_entries = 0
    written_files = 0

    for date_str, entries in sorted(entries_by_date.items()):
        daily_file = history_dir / f"{date_str}.md"
        
        # Read existing file content if present to avoid duplicating identical blocks
        existing_text = daily_file.read_text() if daily_file.exists() else ""
        
        new_blocks = []
        for entry in entries:
            # Check if this exact entry is already present in daily file
            if entry not in existing_text:
                new_blocks.append(entry)
                total_entries += 1

        if new_blocks:
            with open(daily_file, "a") as f:
                if existing_text and not existing_text.endswith("\n\n"):
                    f.write("\n\n")
                f.write("\n\n".join(new_blocks) + "\n")
            written_files += 1

    # Replace original journal.md with a lightweight pointer note
    pointer_text = (
        "# Episodic Journal Index\n"
        "**Note:** Daily logs are stored in `episodic/history/YYYY-MM-DD.md`.\n"
        "This file is retained as an archive pointer.\n"
    )
    journal_path.write_text(pointer_text)
    print(f"Updated {journal_path} with archive pointer.")

    print(
        f"Migration complete: {total_entries} entries written across {len(entries_by_date)} days "
        f"in {history_dir}."
    )
    return {"migrated_days": len(entries_by_date), "entries_count": total_entries}


if __name__ == "__main__":
    migrate_journal()
