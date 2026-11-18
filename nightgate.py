"""Ночной предохранитель Chrome владельца (18.11.2026).

Владелец 18.11: «их вобще надо на ночь переносить, нахера они мне в рабочее время за моим компом».
Профиль default (его Chrome, CDP :9222) днём, с 07:00 до 23:00 America/Toronto, отдан ему.
Днём отбиваем кодом 75 (EX_TEMPFAIL):
  * BU_AGENT из списка кронов (CRON_AGENT_RX) — всегда, даже из сессии агента;
  * скрипт без агентской сессии и без терминала — крон/таймер/сервис;
  * агентскую сессию, разосланную оркестратором (tmux-spawn, osmozg-front), без явной ручной причины
    в BH_OWNER_WHY («по его команде», «по его просьбе», вход в кабинет, 3DS, SMS-код, 2FA).
Проходят: ночь; чужой Chrome (BU_NAME≠default или BU_CDP_WS не на :9222); человек в терминале;
интерактивный агент (окно на экране владельца, его Telegram-канал); агент по прямой команде владельца; пассивное чтение уже открытой вкладки (PASSIVE_WHY_RX).
Отбитые попытки пишутся в ~/.local/state/browser-harness/night-gate.log.

Вызовы: `python3 nightgate.py` (обёртка ~/.local/bin/browser-harness, код 0/75),
run.py main() до ensure_daemon(), helpers._send() для скриптов, импортирующих helpers напрямую.
"""
import datetime as _dt
import os
import re
import sys
from pathlib import Path

TZ = "America/Toronto"
NIGHT_FROM, NIGHT_TO = 23, 7          # окно автоматики: 23:00–07:00
EXIT_CODE = 75
LOG = Path(os.environ.get("HOME", "/home/llm")) / ".local/state/browser-harness/night-gate.log"

# BU_AGENT кронов и фоновых прогонов, которые ходили в Chrome владельца (/tmp/bu-default.log, 18.11)
CRON_AGENT_RX = re.compile(
    r"^(test-cron|cron[-_].*|night[-_].*|mmix-fb-.*|omni-.*|threads-.*|li-.*|linkedin-.*|gsc-.*|ohc-fb-.*"
    r"|meta-monitor.*|messenger-crm.*|mmix-comment.*|lead-social.*|ck-fb-.*|irs-mail.*|x-daily.*|owner-social.*)$",
    re.I)
# ручная задача по прямой команде владельца
MANUAL_WHY_RX = re.compile(
    r"по\s+(его\s+)?(прямой\s+)?(команд|просьб)\w*|по\s+(команде|просьбе)\s+владельца|владел\w*\s+(сам\s+)?(попросил|велел|сказал)"
    r"|\bвход(а|ом|е)?\b|\bвойти\b|\b3-?d\s*s(ecure)?\b|\b3ds\b|\bsms\b|\bсмс\b|\b2fa\b",
    re.I)
# пассивно: читает уже открытую вкладку, вкладок не открывает и не навигирует (каждые 5 мин, работает только днём)
PASSIVE_WHY_RX = re.compile(r"^rbc-statements-pull:")
# интерактивный агент: окно терминала на экране владельца (logind session-*.scope), его Telegram-канал,
# удалённое управление — с ним говорит сам владелец. Разосланные оркестратором (tmux-spawn-*, osmozg-front-*) — нет.
INTERACTIVE_RX = re.compile(r"^(session-\w+\.scope|telegram-channel\.service|claude-rc\.service|claude-term-ttyd\.service)$")
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "GEMINI_CLI", "CODEX_THREAD_ID")


def now_local():
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo(TZ))
    except Exception:
        return _dt.datetime.now()


def is_night(t=None):
    h = (t or now_local()).hour
    return h >= NIGHT_FROM or h < NIGHT_TO


def owner_profile(env=os.environ):
    if env.get("BU_NAME", "default") != "default":
        return False
    ws = env.get("BU_CDP_WS", "")
    return not ws or ":9222" in ws


def _in_agent(env):
    return any(env.get(k) for k in AGENT_ENV) or any(k.startswith("CODEX_") for k in env)


def _has_tty():
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
        os.close(fd)
        return True
    except OSError:
        return False


def _unit():
    try:
        for ln in open("/proc/self/cgroup"):
            m = re.search(r"/([^/]+\.(service|scope))\s*$", ln.strip())
            if m:
                return m.group(1)
    except OSError:
        pass
    return ""


def decide(env=os.environ, t=None, tty=None, unit=None):
    """(пускать?, причина)."""
    if not owner_profile(env):
        return True, "не Chrome владельца"
    if is_night(t):
        return True, "ночь"
    agent = env.get("BU_AGENT", "")
    why = env.get("BH_OWNER_WHY", "")
    if agent and CRON_AGENT_RX.match(agent):
        return False, f"BU_AGENT={agent} в списке кронов"
    if why and PASSIVE_WHY_RX.match(why) and not agent:
        return True, "пассивное чтение открытой вкладки"
    if _in_agent(env):
        if why and MANUAL_WHY_RX.search(why):
            return True, "ручная задача по команде владельца"
        if INTERACTIVE_RX.match(unit if unit is not None else _unit()):
            return True, "интерактивный агент владельца (окно на экране / Telegram)"
        return False, "агент без прямой команды владельца в BH_OWNER_WHY"
    if tty if tty is not None else _has_tty():
        return True, "человек в терминале"
    return False, "крон/таймер без ручной задачи"


def check(exit_on_block=True):
    ok, reason = decide()
    if ok:
        return True
    env = os.environ
    who = env.get("BU_AGENT") or env.get("CLAUDE_CODE_SESSION_ID") or _unit() or f"ppid {os.getppid()}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write("\t".join([now_local().strftime("%F %T"), "BLOCK75", who, _unit() or "-", reason,
                               (env.get("BH_OWNER_WHY") or "-")[:160].replace("\t", " ")]) + "\n")
    except OSError:
        pass
    sys.stderr.write(
        f"browser-harness: Chrome владельца днём закрыт для автоматики (07:00–23:00 {TZ}), код {EXIT_CODE}.\n"
        f"  Причина: {reason}.\n"
        "  Кроны и таймеры — только в окне 23:00–07:00 (osmozg-control timer-every <таймер> '<OnCalendar>').\n"
        "  Ручная задача по прямой команде владельца: BH_OWNER_WHY=\"<кабинет и зачем> — по его команде\".\n"
        "  Без его логина → tanya-harness (Chrome Тани) или агентский Chrome :9333.\n")
    if exit_on_block:
        raise SystemExit(EXIT_CODE)
    return False


if __name__ == "__main__":
    check()
