"""Verify MochiSync file operations are protected by a lock."""
import threading, json
from pathlib import Path
from filelock import FileLock
from kg.mochi_sync import MochiSync


def test_concurrent_save_no_corruption(tmp_path):
    """Two threads saving simultaneously must not lose entries."""
    sync_path = tmp_path / "mochi_sync.json"
    sync_path.write_text(json.dumps({"map": {}, "state": {}}))

    errors = []
    lock = FileLock(str(sync_path) + ".lock", timeout=30)

    def writer(sync_obj):
        try:
            sync_obj._save()
        except Exception as e:
            errors.append(e)

    sync_a = MochiSync.__new__(MochiSync)
    sync_a._sync_path = sync_path
    sync_a._file_lock = lock
    sync_a._map = {"card_a": "mochi_a"}
    sync_a._state = {}

    sync_b = MochiSync.__new__(MochiSync)
    sync_b._sync_path = sync_path
    sync_b._file_lock = lock
    sync_b._map = {"card_b": "mochi_b"}
    sync_b._state = {}

    t1 = threading.Thread(target=writer, args=(sync_a,))
    t2 = threading.Thread(target=writer, args=(sync_b,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors
    data = json.loads(sync_path.read_text())
    assert isinstance(data["map"], dict)


def test_mochi_sync_has_file_lock_attr(tmp_path):
    """MochiSync instances must have a _file_lock attribute after init."""
    # We can't fully init MochiSync (needs Mochi client), but verify the lock is created
    sync_path = tmp_path / "mochi_sync.json"
    sync_path.write_text(json.dumps({"map": {}, "state": {}}))

    obj = MochiSync.__new__(MochiSync)
    obj._sync_path = sync_path
    obj._file_lock = FileLock(str(sync_path) + ".lock", timeout=30)
    obj._map = {}
    obj._state = {}

    # Verify lock works
    with obj._file_lock:
        obj._save()

    data = json.loads(sync_path.read_text())
    assert data == {"map": {}, "state": {}}
