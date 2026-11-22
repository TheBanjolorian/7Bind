import subprocess
import sys
import threading
import time
from pathlib import Path

from sevenbind import single

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_second_start_is_refused_and_shows_the_first(home):
    assert single.acquire()
    shown = threading.Event()
    single.listen(shown.set)
    code = "import sys; from sevenbind import single; sys.exit(0 if single.acquire() else 3)"
    r = subprocess.run([sys.executable, "-c", code], env={"SEVENBIND_HOME": str(home), "PYTHONPATH": SRC})
    assert r.returncode == 3
    assert single.tell_running("show")
    assert shown.wait(3)


def test_main_exits_when_already_running(home):
    code = ("import sys; from sevenbind.__main__ import main; sys.exit(main(['--backup']))")
    assert single.acquire()
    r = subprocess.run([sys.executable, "-c", code], env={"SEVENBIND_HOME": str(home), "PYTHONPATH": SRC},
                       capture_output=True, text=True)
    assert r.returncode == 1 and "running" in r.stdout
