import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class RunLogger:
    """Thread-safe append-only JSONL event logger for one analyzer run."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, event: str, **fields) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)

