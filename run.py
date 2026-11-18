import sys

from admin import (
    ensure_daemon,
    list_cloud_profiles,
    list_local_profiles,
    restart_daemon,
    start_remote_daemon,
    stop_remote_daemon,
    sync_local_profile,
)
from helpers import *

HELP = """Browser Harness

Read SKILL.md for the default workflow and examples.

Typical usage:
  uv run bh <<'PY'
  ensure_real_tab()
  print(page_info())
  PY

Helpers are pre-imported. The daemon auto-starts and connects to the running browser.
"""


def main():
    if len(sys.argv) > 1 and sys.argv[1] in {"-h", "--help"}:
        print(HELP)
        return
    if sys.stdin.isatty():
        sys.exit(
            "browser-harness reads Python from stdin. Use:\n"
            "  browser-harness <<'PY'\n"
            "  print(page_info())\n"
            "  PY"
        )
    sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
    import nightgate
    nightgate.check()  # 18.11: Chrome владельца днём закрыт для кронов (07:00–23:00), код 75
    ensure_daemon()
    exec(sys.stdin.read())


if __name__ == "__main__":
    main()
