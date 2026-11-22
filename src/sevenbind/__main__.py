"""Entry point: `7Bind.exe`, or `python -m sevenbind`.

  --headless           run without a window, print status to the console
  --backup             back up every installed channel once and exit
  --autostart          (Windows Run entry) start hidden in the tray
  --updated <version>  (updater) started by the previous version after an update
  --install-to <exe> --wait <pids> --from-version <v>   (updater) put this exe in place of <exe>
  --version
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from . import __version__

    if "--version" in argv:
        print(__version__)
        return 0

    if "--install-to" in argv:
        from . import updater

        def arg(flag, default=""):
            i = argv.index(flag) if flag in argv else -1
            return argv[i + 1] if 0 <= i < len(argv) - 1 else default
        pids = [int(p) for p in arg("--wait").split(",") if p.strip().isdigit()]
        return updater.install_to(Path(arg("--install-to")), pids, arg("--from-version", "?"))

    if "--backup" in argv:
        import json
        from .core import Core
        core = Core()
        core.scan()
        for r in core.backup_all():
            print(json.dumps({"channel": r["channel"], "result": r["result"]}))
        return 0

    if "--headless" in argv:
        import json
        import threading
        import time
        from .core import Core
        core = Core()
        threading.Thread(target=core.run, daemon=True).start()
        try:
            while True:
                time.sleep(10)
                s = core.status()
                print(json.dumps({k: s[k] for k in ("running", "linked", "cloud", "backup_count", "events")}), flush=True)
        except KeyboardInterrupt:
            core.stop()
        return 0

    updated_from = None
    if "--updated" in argv:
        i = argv.index("--updated")
        updated_from = argv[i + 1] if i + 1 < len(argv) else "?"
        from . import updater
        updater.mark_ready()

    from .app import run_window
    return run_window(updated_from, autostart="--autostart" in argv)


if __name__ == "__main__":
    sys.exit(main())
