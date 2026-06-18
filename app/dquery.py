import csv
import tempfile
from pathlib import Path


def write_csv_to(rows, path):
    """Write list[dict] to path as UTF-8 BOM CSV. Overwrites if exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("(no data)\n", encoding="utf-8-sig")
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_csv(rows):
    """Write to a temp file, return file path string. Used by reports."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig", newline=""
    ) as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return f.name
