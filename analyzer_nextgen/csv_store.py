import csv
from datetime import datetime, timezone
from pathlib import Path


class CsvStore:
    def __init__(self, input_path: Path, output_path: Path):
        self.input_path = input_path
        self.output_path = output_path
        self.rows: list[dict] = []
        self.fieldnames: list[str] = []

    def load(self) -> list[dict]:
        with self.input_path.open(newline="", encoding="utf-8-sig") as handle:
            self.rows = list(csv.DictReader(handle))
        self.fieldnames = list(self.rows[0].keys()) if self.rows else []
        if "updatedAt" not in self.fieldnames:
            self.fieldnames.append("updatedAt")
        return self.rows

    def save(self) -> None:
        with self.output_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(self.rows)

    @staticmethod
    def mark_updated(row: dict) -> None:
        row["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
