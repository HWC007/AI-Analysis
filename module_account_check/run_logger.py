import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class RunLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.lock = threading.Lock()

    def log(self, event: str, **data) -> None:
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **data}
        with self.lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
