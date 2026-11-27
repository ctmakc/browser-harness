"""Аренда Chrome владельца на уровне задачи (26.11.2026).

Владелец 26.11 23:16: «один агент в фейсбуке посты делает, другой дёргает ads manager… это трэш,
раздублитесь, договоритесь друг с другом». Замок flock /tmp/bu-default.lock держит только один вызов,
между вызовами агенты вклинивались друг другу, и их вкладки и окна перемешивались.

Правило: Chrome владельца (BU_NAME=default, CDP :9222) в каждый момент у одной задачи.
  * Первый вызов browser-harness берёт аренду: кто (держатель), зачем (BH_OWNER_WHY), с какого времени.
  * Каждый вызов держателя продлевает аренду; без вызовов она живёт LEASE_IDLE (10 мин) и снимается сама.
    Пока вызов держателя идёт (его PID жив), аренда не стареет.
  * finish_task() снимает аренду сразу.
  * Держит крон/таймер, а в очереди ждут: через TIMER_GRACE (60 с) без его вызова аренда уходит очереди
    (иначе таймер с проходом каждые 5 мин держит Chrome вечно).
  * Остальные встают в очередь: агенты ждут до BH_LEASE_WAIT сек (90), кроны и таймеры не ждут;
    не дождались — код 75 и строка «занято: кем, зачем, до скольки, ваше место в очереди».
    Очередь — те, кто ждёт прямо сейчас (живой PID), по порядку прихода; ушедший теряет место.
  * Человек в терминале и живой коннектор владельца (его ChatGPT) аренду не берут и не ждут.
Журнал: ~/.local/state/browser-harness/lease.log (взятие, продление не пишется, снятие и отказы).

Держатель задачи: BH_LEASE_HOLDER → TERM_HUB_NAME → сессия агента (CLAUDE_CODE_SESSION_ID / CODEX_THREAD_ID)
→ BU_AGENT → юнит systemd → ppid. Субагенты одной сессии — одна задача.

CLI: python3 lease.py status | acquire --pid N | done --pid N | release [--force] [--why …]
"""
import datetime as _dt
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HOME", "/home/llm"))
STATE = HOME / ".local/state/browser-harness"
LOG = STATE / "lease.log"
LEASE_IDLE = int(os.environ.get("BH_LEASE_IDLE", "600"))      # 10 мин простоя — аренда снимается
TIMER_GRACE = 60                                               # крон/таймер уступает ждущим после 60 с без вызова
AGENT_WAIT = 90                                                # агенты по умолчанию ждут 90 с
EXIT_BUSY = 75                                                 # EX_TEMPFAIL, как у nightgate и flock
POLL = 2.0
TZ = "America/Toronto"

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _now_local(ts=None):
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.fromtimestamp(ts if ts is not None else time.time(), ZoneInfo(TZ))
    except Exception:
        return _dt.datetime.fromtimestamp(ts if ts is not None else time.time())


def _hm(ts):
    return _now_local(ts).strftime("%H:%M")


def _paths(env=os.environ):
    name = env.get("BU_NAME", "default")
    return STATE / f"lease-{name}.json", STATE / f"lease-{name}.lock"


def applies(env=os.environ):
    """Аренда только для Chrome владельца: профиль default и CDP на :9222 (или без BU_CDP_WS)."""
    if env.get("BU_NAME", "default") != "default":
        return False
    ws = env.get("BU_CDP_WS", "")
    return not ws or ":9222" in ws


def _unit():
    try:
        for ln in open("/proc/self/cgroup"):
            m = re.search(r"/([^/]+\.(service|scope))\s*$", ln.strip())
            if m:
                return m.group(1)
    except OSError:
        pass
    return ""


def _in_agent(env):
    return any(env.get(k) for k in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "GEMINI_CLI", "CODEX_THREAD_ID")) \
        or any(k.startswith("CODEX_") for k in env)


def _has_tty():
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
        os.close(fd)
        return True
    except OSError:
        return False


def exempt(env=os.environ):
    """Владелец сам: человек в терминале без агента, его живой ChatGPT-коннектор."""
    try:
        import nightgate
        if (_unit(), env.get("BU_AGENT", "")) in getattr(nightgate, "OWNER_LIVE", set()):
            return "живой коннектор владельца"
    except Exception:
        pass
    if not _in_agent(env) and not env.get("BU_AGENT") and _has_tty():
        return "человек в терминале"
    return ""


def holder(env=os.environ):
    """(id, имя для людей). id одинаков у всех вызовов одной задачи."""
    if env.get("BH_LEASE_HOLDER"):
        return "h:" + env["BH_LEASE_HOLDER"], env["BH_LEASE_HOLDER"]
    if env.get("TERM_HUB_NAME"):
        return "t:" + env["TERM_HUB_NAME"], env["TERM_HUB_NAME"]
    for k, tag in (("CLAUDE_CODE_SESSION_ID", "claude"), ("CODEX_THREAD_ID", "codex")):
        if env.get(k):
            name = env.get("BU_AGENT") or f"{tag} {env[k][:8]}"
            return f"s:{env[k]}", name
    if env.get("BU_AGENT"):
        return "a:" + env["BU_AGENT"], env["BU_AGENT"]
    u = _unit()
    if u and not u.startswith("session-"):
        return "u:" + u, u
    return f"p:{os.getppid()}", f"ppid {os.getppid()}"


def is_waiter_patient(env=os.environ):
    """Агент ждёт в очереди, крон/таймер — нет (пропускает проход)."""
    if "BH_LEASE_WAIT" in env:
        try:
            return float(env["BH_LEASE_WAIT"])
        except ValueError:
            pass
    return float(AGENT_WAIT) if _in_agent(env) else 0.0


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, TypeError):
        return True


def _log(event, st, extra=""):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write("\t".join([_now_local().strftime("%F %T"), event, st.get("name", "-"),
                               (st.get("why") or "-")[:160].replace("\t", " ").replace("\n", " "),
                               extra or "-"]) + "\n")
    except OSError:
        pass


class _Locked:
    def __init__(self, env=os.environ):
        self.path, self.lock = _paths(env)

    def __enter__(self):
        STATE.mkdir(parents=True, exist_ok=True)
        self.fd = open(self.lock, "a+")
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        try:
            self.st = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.st = {}
        self.st.setdefault("queue", [])
        return self

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.st, ensure_ascii=False, indent=1))
        os.replace(tmp, self.path)

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        self.fd.close()
        return False


def _expire(st, now):
    """Снять просроченную аренду и выкинуть ушедших из очереди. True — что-то поменялось."""
    changed = False
    lease = st.get("lease")
    if lease:
        lease["active"] = [p for p in lease.get("active", []) if _alive(p)]
        waiting = any(w.get("pid") and _alive(w["pid"]) and w["id"] != lease["id"] for w in st["queue"])
        kind = lease.get("kind") or ("agent" if lease["id"][:2] in ("s:", "t:", "h:") else "timer")
        if not lease["active"] and kind == "timer" and waiting \
                and now - lease.get("last", 0) >= TIMER_GRACE:
            # 27.11 00:10: таймер academl-comment-dm продлевал аренду каждым проходом и держал Chrome час,
            # агенты в очереди не дожидались. Проход таймера закончен — уступает очереди.
            _log("RELEASE", lease, f"таймер уступил очереди: {TIMER_GRACE} с без вызова, держал с "
                                   f"{_hm(lease.get('since', now))}, вызовов {lease.get('calls', 0)}")
            st["lease"] = None
            changed = True
        elif not lease["active"] and now - lease.get("last", 0) >= LEASE_IDLE:
            _log("RELEASE", lease, f"простой {LEASE_IDLE // 60} мин, последний вызов {_hm(lease.get('last', now))}"
                                   f", держал с {_hm(lease.get('since', now))}")
            st["lease"] = None
            changed = True
    q = [w for w in st["queue"] if w.get("pid") and _alive(w["pid"])]
    if len(q) != len(st["queue"]):
        st["queue"], changed = q, True
    return changed


def busy_text(st, me_id, now):
    lease = st["lease"]
    if lease.get("active"):
        free = f"сейчас идёт его вызов, после него аренда снимется сама через {LEASE_IDLE // 60} мин простоя"
    else:
        free = f"снимется сама в {_hm(lease.get('last', now) + LEASE_IDLE)}, если он не продолжит"
    waiting = [w["name"] for w in st["queue"] if w["id"] != me_id]
    s = (f"browser-harness: Chrome владельца занят задачей «{lease['name']}» ({lease.get('why') or 'без причины'}), "
         f"держит с {_hm(lease['since'])}, последний вызов {_hm(lease['last'])}; {free}, или раньше по finish_task(). "
         f"Код {EXIT_BUSY}.\n")
    if waiting:
        s += f"  Ещё ждут: {', '.join(waiting)}.\n"
    s += ("  Кроны и таймеры: этот проход пропустить. Агентам: доделать другое и повторить вызов "
          "(дольше ждать: BH_LEASE_WAIT=<сек>); статус: python3 /home/llm/Developer/browser-harness/lease.py status\n")
    return s


def acquire(pid=None, env=os.environ, wait=None):
    """0 — аренда наша (взята или продлена), EXIT_BUSY — занято. pid — процесс вызова (жив = аренда не стареет)."""
    if not applies(env) or exempt(env):
        return 0
    me_id, me_name = holder(env)
    why = (env.get("BH_OWNER_WHY") or env.get("BU_AGENT") or "").strip()
    pid = int(os.getppid() if pid is None else pid)   # 0 — процесс не держит аренду живой (только продление)
    wait = is_waiter_patient(env) if wait is None else wait
    first_try = time.time()
    deadline = first_try + wait
    logged = False
    while True:
        now = time.time()
        with _Locked(env) as L:
            st = L.st
            _expire(st, now)
            lease = st.get("lease")
            if lease and lease["id"] == me_id:          # наша — продлеваем
                lease["last"] = now
                lease["active"] = sorted(set(lease.get("active", []) + ([pid] if pid else [])))
                lease["calls"] = lease.get("calls", 0) + 1
                if why and why != lease.get("why"):
                    lease["why"] = why
                st["queue"] = [w for w in st["queue"] if w["id"] != me_id]
                L.save()
                return 0
            # впереди в очереди — только те, кто ждёт прямо сейчас (живой PID); ушедшие место не блокируют
            ahead = []
            for w in st["queue"]:
                if w["id"] == me_id:
                    break
                if w.get("pid") and _alive(w["pid"]):
                    ahead.append(w)
            if not lease and not ahead:                  # свободно и мы первые — берём
                st["lease"] = {"id": me_id, "name": me_name, "why": why, "since": now, "last": now,
                               "active": [pid] if pid else [], "calls": 1, "unit": _unit() or "-",
                               "kind": "agent" if _in_agent(env) else "timer"}
                st["queue"] = [w for w in st["queue"] if w["id"] != me_id]
                L.save()
                _log("TAKE", st["lease"], f"ждал в очереди {now - first_try:.0f} с" if logged else "")
                return 0
            timed_out = now >= deadline
            mine_pos = next((i for i, w in enumerate(st["queue"]) if w["id"] == me_id), None)
            if timed_out:                                # уходим — место в очереди освобождаем
                if mine_pos is not None:
                    st["queue"].pop(mine_pos)
            elif mine_pos is None:                       # ждём — встаём в конец, стоим, пока жив наш PID
                st["queue"].append({"id": me_id, "name": me_name, "why": why, "pid": pid or os.getpid(),
                                    "since": now, "seen": now})
            else:
                st["queue"][mine_pos].update(seen=now, pid=pid or os.getpid())
            L.save()
            who = (lease or (ahead[0] if ahead else {})).get("name", "-")
            if not logged:
                logged = True
                _log("WAIT" if wait > 0 else "BUSY75", {"name": me_name, "why": why},
                     f"держит {who}" + (f", жду до {wait:.0f} с" if wait > 0 else ", проход пропущен"))
            if timed_out:
                if wait > 0:
                    _log("BUSY75", {"name": me_name, "why": why}, f"не дождался за {wait:.0f} с, держит {who}")
                if lease:
                    sys.stderr.write(busy_text(st, me_id, now))
                else:
                    sys.stderr.write(f"browser-harness: Chrome владельца освобождается, первой в очереди ждёт задача "
                                     f"«{who}»; повторите вызов позже. Код {EXIT_BUSY}.\n")
                return EXIT_BUSY
        time.sleep(POLL)


def done(pid=None, env=os.environ):
    """Конец одного вызова: PID из активных убрать, отсчёт простоя — с этого момента."""
    if not applies(env):
        return 0
    me_id, _ = holder(env)
    pid = int(pid or os.getppid())
    with _Locked(env) as L:
        lease = L.st.get("lease")
        if lease and lease["id"] == me_id:
            lease["active"] = [p for p in lease.get("active", []) if p != pid and _alive(p)]
            lease["last"] = time.time()
            L.save()
    return 0


def release(env=os.environ, force=False, why="finish_task"):
    """Снять аренду (свою; force — любую, для фронта). True — сняли."""
    if not applies(env):
        return False
    me_id, me_name = holder(env)
    with _Locked(env) as L:
        lease = L.st.get("lease")
        if not lease or (lease["id"] != me_id and not force):
            return False
        extra = f"{why}, держал с {_hm(lease['since'])}, вызовов {lease.get('calls', 0)}"
        if force and lease["id"] != me_id:
            extra += f", снял {me_name}"
        _log("RELEASE", lease, extra)
        L.st["lease"] = None
        L.save()
    return True


def status(env=os.environ):
    now = time.time()
    with _Locked(env) as L:
        if _expire(L.st, now):
            L.save()
        st = json.loads(json.dumps(L.st))
    out = []
    try:
        import nightgate
        hold = nightgate.desk_hold() if hasattr(nightgate, "desk_hold") else ""
        if hold:
            out.append(f"Владелец за компьютером: Chrome закрыт для агентов до {hold}.")
    except Exception:
        pass
    lease = st.get("lease")
    if lease:
        until = ("идёт его вызов" if lease.get("active")
                 else f"снимется сама в {_hm(lease['last'] + LEASE_IDLE)}")
        out.append(f"Занят: «{lease['name']}» — {lease.get('why') or '-'}; с {_hm(lease['since'])}, "
                   f"вызовов {lease.get('calls', 0)}, последний {_hm(lease['last'])}; {until}.")
    else:
        out.append("Свободен.")
    for i, w in enumerate(st["queue"], 1):
        out.append(f"  очередь №{i}: «{w['name']}» — {w.get('why') or '-'} (ждёт с {_hm(w.get('since', now))})")
    return "\n".join(out)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="lease.py")
    ap.add_argument("cmd", choices=["status", "acquire", "done", "release"])
    ap.add_argument("--pid", type=int)
    ap.add_argument("--wait", type=float)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--why", default="снято вручную")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(status())
        return 0
    if a.cmd == "acquire":
        return acquire(a.pid, wait=a.wait)
    if a.cmd == "done":
        return done(a.pid)
    ok = release(force=a.force, why=a.why)
    print("снята" if ok else "аренды у этой задачи нет")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
