#!/usr/bin/env bash
set -euo pipefail

export HOME="${BROWSER_HARNESS_HOME:-/home/llm}"
# Копия обёртки ~/.local/bin/browser-harness в репозитории (26.11). Выкатка: cp owner-wrapper.sh ~/.local/bin/browser-harness.
# BH_DIR — папка кода (по умолчанию живая), для пробы ветки: BH_DIR=/fast/wt/<ветка>.
BH_DIR="${BH_DIR:-/home/llm/Developer/browser-harness}"
BH_VENV=/home/llm/Developer/browser-harness/.venv

# Заслонка 22.09.2026: Chrome владельца (:9222) — его рабочий браузер, агенты постоянно
# перехватывали его под анкеты и формы. Из агентской сессии (Claude/Codex/Gemini) пускаем
# только с явной причиной BH_OWNER_WHY="…" — когда нужен именно логин владельца.
# Всё остальное (анкеты, формы, регистрации, заявки) → tanya-harness (Chrome Тани на claw).
# Скрипты по крону/таймерам агентских переменных не имеют и проходят как раньше.
# Чужой Chrome через BU_CDP_WS (не :9222) заслонку не трогает.
# Ночной предохранитель 18.11.2026 (владелец: «их вобще надо на ночь переносить»): профиль default
# днём 07:00–23:00 Toronto отбивает кроны и агентов без прямой команды владельца кодом 75,
# до очереди flock и до записи в owner-chrome.log. Логика и списки — Developer/browser-harness/nightgate.py.
/usr/bin/python3 -I "$BH_DIR/nightgate.py" || exit $?

in_agent=0
if [[ -n "${CLAUDECODE:-}" || -n "${GEMINI_CLI:-}" ]] || env | grep -q '^CODEX_'; then in_agent=1; fi
other_chrome=0
if [[ -n "${BU_CDP_WS:-}" && "${BU_CDP_WS}" != *":9222"* ]]; then other_chrome=1; fi

if [[ "$in_agent" == 1 && "$other_chrome" == 0 ]]; then
  if [[ -z "${BH_OWNER_WHY:-}" ]]; then
    cat >&2 <<'MSG'
browser-harness: Chrome владельца закрыт для агентов.
  Анкеты, формы, регистрации, заявки, любые сайты без его личного логина →
      tanya-harness <<'PY' ... PY      (тот же API helpers, Chrome Тани на claw)
  Публичное чтение → WebFetch / WebSearch / mcp__playwright__*.
  Нужен именно залогиненный аккаунт владельца (его почта, его кабинет, его банк)?
      BH_OWNER_WHY="какой кабинет и зачем" browser-harness <<'PY' ... PY
  Только одноразово: без циклов, new_tab не делать (background_tab + close_tab).
MSG
    exit 64
  fi
  export BU_ACTIVATE=0   # вкладку агента на передний план не выдёргивать
  mkdir -p "$HOME/.local/state/browser-harness"
  printf '%s\t%s\t%s\n' "$(date '+%F %T')" "${CLAUDE_CODE_SESSION_ID:-${PPID}}" "$BH_OWNER_WHY" \
    >> "$HOME/.local/state/browser-harness/owner-chrome.log"
fi

# Аренда Chrome владельца на задачу (26.11, владелец: «раздублитесь, договоритесь друг с другом»): lease.py.
# Первый вызов задачи берёт аренду, каждый следующий её продлевает; finish_task() и 10 мин простоя снимают.
# Чужая задача держит → агент ждёт до BH_LEASE_WAIT сек (90), крон/таймер не ждёт; не дождались — код 75
# с именем держателя и временем. Журнал ~/.local/state/browser-harness/lease.log. Статус: python3 lease.py status.
/usr/bin/python3 -I "$BH_DIR/lease.py" acquire --pid $$ || exit $?
export BH_LEASE_HELD=1
trap '/usr/bin/python3 -I "$BH_DIR/lease.py" done --pid $$ || true' EXIT

# Очередь на браузер внутри задачи: один скрипт за раз на профиль (BU_NAME) — субагенты одной задачи
# не дерутся за вкладки и курсор. Ожидание BU_LOCK_WAIT сек (900), при таймауте код 75.
if [[ -x "$BH_DIR/.venv/bin/browser-harness" ]]; then
  run=("$BH_DIR/.venv/bin/browser-harness" "$@")
else
  run=("$BH_VENV/bin/python" -c "import sys; sys.path.insert(0, '$BH_DIR'); sys.argv[0]='browser-harness'; import run; run.main()" "$@")
fi
rc=0
flock -w "${BU_LOCK_WAIT:-900}" -E 75 "/tmp/bu-${BU_NAME:-default}.lock" "${run[@]}" || rc=$?
exit $rc
