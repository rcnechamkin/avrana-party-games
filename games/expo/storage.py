"""Optional private persistence boundary; never imported by the domain engine."""
import json
import os
from pathlib import Path
import tempfile

# The largest snapshot file, in bytes, for reading and for writing alike (AVR-273): a file the
# server would refuse to read after a restart is never written.
MAX_SNAPSHOT_BYTES = 4_000_000


class SnapshotStore:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return None
        if self.path.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError('Snapshot is too large')
        return json.loads(self.path.read_text(encoding='utf-8'))

    def write(self, snapshot):
        # The bytes of the file are made first, so their number is known before anything
        # touches the disk. Either refusal below is a failed write like any other: the caller
        # rolls back, and the file on disk is untouched.
        try:
            data = json.dumps(snapshot, ensure_ascii=False).encode('utf-8')
        except (TypeError, ValueError, RecursionError) as e:
            raise OSError('Snapshot cannot be serialised') from e          # AVR-268
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise OSError('Snapshot is too large to be read back')         # AVR-273
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.crew-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def clear(self):
        self.path.unlink(missing_ok=True)
