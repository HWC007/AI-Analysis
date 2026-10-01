import csv
import os
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def save_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise RuntimeError("Account CSV is empty")
    fields = list(rows[0])
    for field in ("AI_customer_type", "AI_maintenance_status"):
        if field not in fields:
            fields.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)
