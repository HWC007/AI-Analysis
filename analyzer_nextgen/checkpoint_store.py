import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class CheckpointStore:
    """Atomically stores the latest resumable state for one analyzer run."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def load(self) -> dict:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict) -> None:
        payload = dict(state)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with self._lock:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)

