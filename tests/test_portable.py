"""amemo/portable.py: замок файла между процессами, сброс на диск, домашняя папка."""
import subprocess
import sys
import time

from amemo import portable

HOLDER = """
import sys, time
from amemo import portable
with portable.file_lock(sys.argv[1]):
    print("locked", flush=True)
    time.sleep(float(sys.argv[2]))
"""


def test_file_lock_waits_for_another_process(tmp_path):
    lock = tmp_path / "x.lock"
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(lock), "0.6"], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        started = time.monotonic()
        with portable.file_lock(lock):                  # держатель спит 0,6 с под замком — ждём его
            waited = time.monotonic() - started
        assert waited > 0.3
    finally:
        holder.wait(timeout=10)
    with portable.file_lock(lock):                      # снят — берётся снова сразу
        pass


def test_fsync_path_accepts_files_and_folders(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"x")
    portable.fsync_path(path)
    portable.fsync_path(tmp_path)
    portable.fsync_dir(tmp_path)


def test_home_prefers_userprofile_only_on_windows(monkeypatch, tmp_path):
    env = {"USERPROFILE": str(tmp_path / "profile"), "HOME": str(tmp_path / "home")}
    monkeypatch.setattr(portable, "WINDOWS", False)
    assert portable.home(env) == tmp_path / "home"
    monkeypatch.setattr(portable, "WINDOWS", True)
    assert portable.home(env) == tmp_path / "profile"
    assert portable.home({"HOME": str(tmp_path / "home")}) == tmp_path / "home"
