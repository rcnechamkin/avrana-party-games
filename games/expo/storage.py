"""Optional private persistence boundary; never imported by the domain engine."""
import json
import os
from pathlib import Path
import tempfile


class SnapshotStore:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return None
        if self.path.stat().st_size > 4_000_000:
            raise ValueError('Snapshot is too large')
        return json.loads(self.path.read_text(encoding='utf-8'))

    def write(self, snapshot):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.crew-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def clear(self):
        self.path.unlink(missing_ok=True)
