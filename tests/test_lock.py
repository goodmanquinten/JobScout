import os
import time

import pytest

from jobscout.lock import LockBusy, file_lock


def test_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / "x.lock"
    with file_lock(path):
        assert path.exists()
        with pytest.raises(LockBusy), file_lock(path):
            pass
    assert not path.exists()


def test_stale_lock_is_taken_over(tmp_path):
    path = tmp_path / "x.lock"
    path.write_text("123")
    old = time.time() - 3 * 3600
    os.utime(path, (old, old))
    with file_lock(path):
        assert path.read_text() == str(os.getpid())
