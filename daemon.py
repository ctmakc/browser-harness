"""CDP WS holder + Unix socket relay. One daemon per BU_NAME."""
import asyncio, json, os, re, signal, socket, sys, time, urllib.request
from collections import deque
from pathlib import Path

from cdp_use.client import CDPClient


def _load_env():
    p = Path(__file__).parent / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

NAME = os.environ.get("BU_NAME", "default")
SOCK = f"/tmp/bu-{NAME}.sock"
LOG = f"/tmp/bu-{NAME}.log"
PID = f"/tmp/bu-{NAME}.pid"
BUF = 500
# Своя вкладка на агента (BU_AGENT): параллельные агенты не уводят друг у друга текущую
# вкладку между скриптами. BU_AGENT_WINDOW=1 — каждому агенту отдельное окно (невидимый
# Chrome Тани: активная вкладка в каждом окне, рендер не замораживается). Иначе — фоновая
# вкладка, окно владельца не дёргается. Вкладки простоявших агентов закрываются через AGENT_IDLE.
AGENT_WINDOW = os.environ.get("BU_AGENT_WINDOW") == "1"
AGENT_IDLE = int(os.environ.get("BU_AGENT_IDLE", "1800"))
# Потолок на один CDP-вызов. Без него вкладка с зависшим рендерером (FB messenger на 5 ГБ,
# 28.09) вешала клиента навсегда, а тот держал flock очереди tanya-harness.
CALL_TIMEOUT = float(os.environ.get("BU_CALL_TIMEOUT", "60"))
# Страж вкладок (не для Chrome владельца): страниц больше BU_TAB_LIMIT → закрыть пустые about:blank,
# к которым никто не подключён (сироты умерших демонов). Chrome робота NetworkHub :9241, 24.10.2026:
# 175 пустых вкладок, 188 рендереров, ~33 ГБ RAM. 0 — выключить.
TAB_LIMIT = int(os.environ.get("BU_TAB_LIMIT", "10"))
PROFILES = [
    Path.home() / "Library/Application Support/Google/Chrome",
    Path.home() / "Library/Application Support/Microsoft Edge",
    Path.home() / "Library/Application Support/Microsoft Edge Beta",
    Path.home() / "Library/Application Support/Microsoft Edge Dev",
    Path.home() / "Library/Application Support/Microsoft Edge Canary",
    Path.home() / ".config/google-chrome",
    Path.home() / ".config/chromium",
    Path.home() / ".config/chromium-browser",
    Path.home() / ".config/microsoft-edge",
    Path.home() / ".config/microsoft-edge-beta",
    Path.home() / ".config/microsoft-edge-dev",
    Path.home() / "AppData/Local/Google/Chrome/User Data",
    Path.home() / "AppData/Local/Chromium/User Data",
    Path.home() / "AppData/Local/Microsoft/Edge/User Data",
    Path.home() / "AppData/Local/Microsoft/Edge Beta/User Data",
    Path.home() / "AppData/Local/Microsoft/Edge Dev/User Data",
    Path.home() / "AppData/Local/Microsoft/Edge SxS/User Data",
]
INTERNAL = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://", "about:")
BU_API = "https://api.browser-use.com/api/v3"
REMOTE_ID = os.environ.get("BU_BROWSER_ID")
API_KEY = os.environ.get("BROWSER_USE_API_KEY")

# Любой Browser/Page.setDownloadBehavior (даже behavior=default) навсегда, до перезапуска Chrome,
# подменяет менеджер загрузок профиля на DevToolsDownloadManagerDelegate. Тот не переопределяет
# OpenDownload/ShowDownloadInShell — «Открыть» и «Показать в папке» в Chrome молча перестают работать
# (content/browser/devtools/protocol/devtools_download_manager_delegate.h; проверено 02.10.2026).
# На личном Chrome владельца (локальный профиль, BU_NAME=default) вызов запрещён.
DL_METHODS = ("Browser.setDownloadBehavior", "Page.setDownloadBehavior")
OWNER_CHROME = NAME == "default" and not os.environ.get("BU_CDP_WS") and not REMOTE_ID
DL_BLOCKED = ("setDownloadBehavior запрещён на Chrome владельца: ломает «Открыть»/«Показать в папке» до перезапуска Chrome. "
              "Качай helpers.fetch_file(url) или download(trigger) — они берут байты через fetch страницы.")

# Менеджер паролей Chrome закрыт для скриптов (ночной аудит безопасности 05.11.2026). Через CDP скрипт мог открыть
# chrome://password-manager и вызвать chrome.passwordsPrivate.requestPlaintextPassword — это все сохранённые
# пароли открытым текстом. API есть и на chrome://settings (проверено 05.11), поэтому отказ трёх видов:
#   1) адрес менеджера паролей (chrome://…passw…) или строка passwordsPrivate в любых параметрах любого вызова;
#   2) attach к вкладке, которая уже на менеджере паролей; любой вызов в сессии такой вкладки
#      (адрес chrome://-вкладок перечитывается на каждом вызове — внутренняя навигация тоже ловится);
#   3) выполнение кода (Runtime/Debugger/…) во вкладке chrome://settings*, кроме PW_SETTINGS_OK.
# Target.sendMessageToTarget и Target.exposeDevToolsProtocol обходят сессии — запрещены целиком.
# Секреты для автоматики — файлы ~/.config/local-secrets/*.env (600).
PW_PARAM_RE = re.compile(r"chrome:/*[^\s\"']*passw|passwordsprivate", re.I)
PW_PAGE_RE = re.compile(r"^chrome://(password-manager|settings/passwords)", re.I)
PW_CODE_METHODS = ("Runtime.evaluate", "Runtime.callFunctionOn", "Runtime.compileScript", "Runtime.runScript",
                   "Runtime.addBinding", "Debugger.", "Page.addScriptToEvaluateOnNewDocument", "Page.createIsolatedWorld",
                   "DOM.", "DOMDebugger.", "Input.", "Overlay.")
PW_SETTINGS_OK = {"chrome.send('resetAutoOpenFileTypes')"}   # interaction-skills/downloads.md
PW_RAW_METHODS = ("Target.sendMessageToTarget", "Target.exposeDevToolsProtocol")
PW_BLOCKED = ("менеджер паролей Chrome закрыт для скриптов (аудит 05.11.2026): chrome://password-manager, "
              "chrome://settings/passwords, passwordsPrivate и выполнение кода на chrome://settings запрещены. "
              "Пароль для автоматики — отдельный файл ~/.config/local-secrets/<имя>.env с правами 600.")


def log(msg):
    open(LOG, "a").write(f"{msg}\n")


def get_ws_url():
    if url := os.environ.get("BU_CDP_WS"):
        return url
    for base in PROFILES:
        try:
            port, path = (base / "DevToolsActivePort").read_text().strip().split("\n", 1)
        except (FileNotFoundError, NotADirectoryError):
            continue
        deadline = time.time() + 30
        while True:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(1)
            try:
                probe.connect(("127.0.0.1", int(port.strip())))
                break
            except OSError:
                if time.time() >= deadline:
                    raise RuntimeError(
                        f"Chrome's remote-debugging page is open, but DevTools is not live yet on 127.0.0.1:{port.strip()} — if Chrome opened a profile picker, choose your normal profile first, then tick the checkbox and click Allow if shown"
                    )
                time.sleep(1)
            finally:
                probe.close()
        return f"ws://127.0.0.1:{port.strip()}{path.strip()}"
    raise RuntimeError(f"DevToolsActivePort not found in {[str(p) for p in PROFILES]} — enable chrome://inspect/#remote-debugging, or set BU_CDP_WS for a remote browser")


def stop_remote():
    if not REMOTE_ID or not API_KEY: return
    try:
        req = urllib.request.Request(
            f"{BU_API}/browsers/{REMOTE_ID}",
            data=json.dumps({"action": "stop"}).encode(),
            method="PATCH",
            headers={"X-Browser-Use-API-Key": API_KEY, "Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15).read()
        log(f"stopped remote browser {REMOTE_ID}")
    except Exception as e:
        log(f"stop_remote failed ({REMOTE_ID}): {e}")


def is_real_page(t):
    return t["type"] == "page" and not t.get("url", "").startswith(INTERNAL)


class Daemon:
    def __init__(self):
        self.cdp = None
        self.session = None
        self.agents = {}  # agent -> {"sid", "tid", "own", "last"}
        self.events = deque(maxlen=BUF)
        self.dialog = None
        self.stop = None  # asyncio.Event, set inside start()
        self.sess = {}    # sessionId -> [targetId, url] — для запрета менеджера паролей

    async def attach_first_page(self):
        """Attach to a real page (or any page). Sets self.session. Returns attached target or None."""
        targets = (await self.cdp.send_raw("Target.getTargets"))["targetInfos"]
        pages = [t for t in targets if is_real_page(t)]
        if not pages:
            # Пустая вкладка уже есть — берём её: новая about:blank на каждый старт демона копилась
            # (Chrome робота :9241, 17.10.2026: 25 пустых вкладок за двое суток).
            pages = [t for t in targets if t["type"] == "page" and t.get("url") == "about:blank"][:1]
        if not pages:
            # No real pages — create one instead of attaching to omnibox popup
            tid = (await self.cdp.send_raw("Target.createTarget", {"url": "about:blank"}))["targetId"]
            log(f"no real pages found, created about:blank ({tid})")
            pages = [{"targetId": tid, "url": "about:blank", "type": "page"}]
        self.session = (await self.cdp.send_raw(
            "Target.attachToTarget", {"targetId": pages[0]["targetId"], "flatten": True}
        ))["sessionId"]
        log(f"attached {pages[0]['targetId']} ({pages[0].get('url','')[:80]}) session={self.session}")
        for d in ("Page", "DOM", "Runtime", "Network"):
            try:
                await asyncio.wait_for(
                    self.cdp.send_raw(f"{d}.enable", session_id=self.session),
                    timeout=5
                )
            except Exception as e:
                log(f"enable {d}: {e}")
        return pages[0]

    async def start(self):
        self.stop = asyncio.Event()
        url = get_ws_url()
        log(f"connecting to {url}")
        self.cdp = CDPClient(url)
        # Одно «Разрешить» владельца = соединение навсегда (08.10.2026).
        # 1) Клиентский keepalive выключен: websockets по умолчанию рвёт WS, если Chrome не ответил на пинг
        #    за 20 с (долгий скриншот, подвисшая вкладка), а каждое новое подключение снова зовёт окно Allow.
        #    Сокет локальный: настоящий обрыв (Chrome закрыт) всё равно виден сразу.
        # 2) Рукопожатие с Chrome владельца ждёт клика до BU_ALLOW_WAIT с (6 ч), а не 10 с: окно висит одно,
        #    admin.ensure_daemon пока не плодит новых демонов (смотрит pid-файл).
        import functools, cdp_use.client as _cc
        _orig_connect = getattr(_cc.websockets, "_bh_orig_connect", _cc.websockets.connect)
        _cc.websockets._bh_orig_connect = _orig_connect
        _cc.websockets.connect = functools.partial(
            _orig_connect, ping_interval=None,
            **({"open_timeout": float(os.environ.get("BU_ALLOW_WAIT", "21600"))} if OWNER_CHROME else {}))
        nag = None
        if OWNER_CHROME:
            log("waiting for owner to click «Разрешить» in Chrome (if the prompt is shown)")
            # 3) Рукопожатие висит дольше 6 с → окно «Разрешить» ждёт владельца: кнопка ему в Telegram
            #    (chrome-allow notify, сам не чаще раза в 10 мин; нажатие жмёт окно через бот ОСМОЗГ).
            async def _nag():
                await asyncio.sleep(6)
                while True:
                    log("handshake still pending -> chrome-allow notify")
                    try:
                        await asyncio.create_subprocess_exec(
                            os.path.expanduser("~/.local/bin/chrome-allow"), "notify",
                            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    except Exception as e:
                        log(f"chrome-allow notify: {e}")
                    await asyncio.sleep(600)
            nag = asyncio.create_task(_nag())
        try:
            await self.cdp.start()
        except Exception as e:
            raise RuntimeError(f"CDP WS handshake failed: {e} -- click Allow in Chrome if prompted, then retry")
        finally:
            if nag:
                nag.cancel()
        await self.attach_first_page()
        await self.tab_guard()
        # Chrome перезапустили / WS оборвался → демон выходит, следующий вызов ensure_daemon поднимет
        # свежий на актуальный адрес. Иначе демон живёт с мёртвым соединением и каждый вызов
        # получает «no close frame received or sent» (lisw-robot, 15–17.10.2026: Chrome :9241
        # перезапущен 15.10 18:51, демон с 14.10 отвечал этим двое суток).
        async def _watch_ws(task):
            try: await task
            except BaseException: pass
            log("CDP connection closed -> daemon exits")
            self.stop.set()
        self._ws_watch = asyncio.create_task(_watch_ws(self.cdp._message_handler_task))
        orig = self.cdp._event_registry.handle_event
        mark_js = "if(!document.title.startsWith('\U0001F7E2'))document.title='\U0001F7E2 '+document.title"
        async def tap(method, params, session_id=None):
            self.events.append({"method": method, "params": params, "session_id": session_id})
            if method == "Target.attachedToTarget":
                ti = params.get("targetInfo") or {}
                self.sess[params.get("sessionId")] = [ti.get("targetId"), ti.get("url", "")]
            elif method == "Target.detachedFromTarget":
                self.sess.pop(params.get("sessionId"), None)
            if method in ("Target.detachedFromTarget", "Target.targetDestroyed", "Target.targetCrashed"):
                # Вкладку агента закрыли (владелец или сам агент через Target.closeTarget): забыть её,
                # следующий вызов агента получит свежую. Иначе «No target with given id found» навсегда.
                gone_t, gone_s = params.get("targetId"), params.get("sessionId")
                for ag, a in list(self.agents.items()):
                    if (gone_t and gone_t in (a.get("tid"), a.get("own"))) or (gone_s and gone_s == a.get("sid")):
                        self.agents.pop(ag, None); log(f"agent {ag[:12]}: tab gone ({method}), forgotten")
            if method == "Page.javascriptDialogOpening":
                self.dialog = params
            elif method == "Page.javascriptDialogClosed":
                self.dialog = None
            elif method in ("Page.loadEventFired", "Page.domContentEventFired"):
                try: await asyncio.wait_for(self.cdp.send_raw("Runtime.evaluate", {"expression": mark_js}, session_id=self.session), timeout=2)
                except Exception: pass
            return await orig(method, params, session_id)
        self.cdp._event_registry.handle_event = tap

    async def tab_guard(self):
        """Страниц больше TAB_LIMIT → закрыть пустые about:blank без подключённого клиента.
        attached=false = вкладку держал умерший демон (systemd убил его вместе с oneshot-юнитом),
        живые вкладки агентов и сессия этого демона подключены и не трогаются. Последнюю
        страницу не закрываем никогда: без окон Chrome выходит."""
        if OWNER_CHROME or TAB_LIMIT <= 0: return 0
        try:
            targets = (await asyncio.wait_for(self.cdp.send_raw("Target.getTargets"), timeout=10))["targetInfos"]
        except Exception as e:
            log(f"tab_guard: {e}"); return 0
        pages = [t for t in targets if t["type"] == "page"]
        if len(pages) <= TAB_LIMIT: return 0
        mine = {a.get(k) for a in self.agents.values() for k in ("tid", "own")}
        idle = [t for t in pages if t.get("url") in ("about:blank", "") and not t.get("attached")
                and t["targetId"] not in mine]
        idle = idle[:max(0, len(pages) - 1)]
        closed = 0
        for t in idle:
            try:
                await asyncio.wait_for(self.cdp.send_raw("Target.closeTarget", {"targetId": t["targetId"]}), timeout=5)
                closed += 1
            except Exception:
                pass
        log(f"tab_guard: {len(pages)} pages > {TAB_LIMIT}, closed {closed} orphan about:blank")
        return closed

    async def close_agent_tabs(self):
        """Выход демона (SIGTERM от systemd, shutdown): закрыть свои вкладки агентов. Иначе их id
        умирают вместе с демоном, новый демон заводит новую вкладку, а старая висит до перезапуска
        Chrome (linkedin-services-watch каждые 20 мин → ~72 пустые вкладки в сутки)."""
        for agent, a in list(self.agents.items()):
            if a.get("own"):
                try: await asyncio.wait_for(self.cdp.send_raw("Target.closeTarget", {"targetId": a["own"]}), timeout=3)
                except Exception: pass
                log(f"agent {agent[:12]}: daemon exit, tab closed")
        self.agents.clear()

    async def _target_url(self, tid):
        try:
            r = await asyncio.wait_for(self.cdp.send_raw("Target.getTargetInfo", {"targetId": tid}), timeout=5)
            return (r.get("targetInfo") or {}).get("url", "")
        except Exception:
            return ""

    async def _pw_guard(self, method, params, sid):
        """Причина отказа (строка) или None. См. PW_BLOCKED."""
        if method in PW_RAW_METHODS:
            return "raw"
        try: blob = json.dumps(params, ensure_ascii=False)
        except Exception: blob = str(params)
        if PW_PARAM_RE.search(blob):
            return "param"
        if method == "Target.attachToTarget" and PW_PAGE_RE.search(await self._target_url(params.get("targetId"))):
            return "attach"
        if method.startswith(("Target.", "Browser.")) or not sid:
            return None
        s = self.sess.get(sid)
        if not s or not s[0]:
            return None
        # Адрес перечитывается перед каждым выполнением кода и на любой chrome://-вкладке: вкладка могла
        # уйти на chrome:// через history.back()/внутреннюю навигацию, кэш об этом не знает.
        if method.startswith(PW_CODE_METHODS) or s[1].startswith("chrome") or not s[1]:
            s[1] = await self._target_url(s[0]) or s[1]
        if PW_PAGE_RE.search(s[1]):
            return "page"
        if s[1].lower().startswith("chrome://settings") and method.startswith(PW_CODE_METHODS) \
                and (params.get("expression") or "").strip() not in PW_SETTINGS_OK:
            return "settings-code"
        return None

    async def _enable(self, sid):
        for d in ("Page", "DOM", "Runtime", "Network"):
            try: await asyncio.wait_for(self.cdp.send_raw(f"{d}.enable", session_id=sid), timeout=5)
            except Exception as e: log(f"enable {d}: {e}")

    async def _agent_tab(self, agent):
        """Своя вкладка агента: создаётся при первом обращении, дальше переиспользуется."""
        a = self.agents.get(agent)
        if a: return a
        await self.tab_guard()
        params = {"url": "about:blank", "background": True}
        if AGENT_WINDOW: params["newWindow"] = True
        tid = (await asyncio.wait_for(self.cdp.send_raw("Target.createTarget", params), timeout=20))["targetId"]
        sid = (await asyncio.wait_for(self.cdp.send_raw("Target.attachToTarget", {"targetId": tid, "flatten": True}), timeout=20))["sessionId"]
        await self._enable(sid)
        a = self.agents[agent] = {"sid": sid, "tid": tid, "own": tid, "last": time.time()}
        log(f"agent {agent[:12]}: own tab {tid} window={AGENT_WINDOW}")
        return a

    async def _gc_agents(self):
        now = time.time()
        for agent, a in list(self.agents.items()):
            if now - a["last"] < AGENT_IDLE: continue
            del self.agents[agent]
            if a.get("own"):
                try: await self.cdp.send_raw("Target.closeTarget", {"targetId": a["own"]})
                except Exception: pass
            log(f"agent {agent[:12]}: idle, tab closed")

    async def handle(self, req):
        meta = req.get("meta")
        agent = req.get("agent")
        if meta == "drain_events":
            out = list(self.events); self.events.clear()
            return {"events": out}
        if meta == "pending_dialog": return {"dialog": self.dialog}
        if meta == "shutdown":    self.stop.set(); return {"ok": True}
        await self._gc_agents()
        a = self.agents.get(agent) if agent else None
        if a: a["last"] = time.time()
        if meta in ("session", "target") and agent and not a: a = await self._agent_tab(agent)
        if meta == "session":     return {"session_id": a["sid"] if a else self.session}
        if meta == "target":      return {"target_id": a["tid"] if a else None}
        if meta == "set_session":
            sid = req.get("session_id")
            if agent:
                a = self.agents.setdefault(agent, {"own": None})
                a.update(sid=sid, tid=req.get("target_id"), last=time.time())
            else:
                self.session = sid
            try:
                await asyncio.wait_for(self.cdp.send_raw("Page.enable", session_id=sid), timeout=3)
                await asyncio.wait_for(self.cdp.send_raw("Runtime.evaluate", {"expression": "if(!document.title.startsWith('\U0001F7E2'))document.title='\U0001F7E2 '+document.title"}, session_id=sid), timeout=2)
            except Exception: pass
            return {"session_id": sid}

        method = req["method"]
        params = req.get("params") or {}
        if OWNER_CHROME and method in DL_METHODS:
            log(f"blocked {method} from agent {str(agent)[:12]}")
            return {"error": DL_BLOCKED}
        pw = await self._pw_guard(method, params, req.get("session_id") or (a["sid"] if a else self.session))
        if pw:
            log(f"blocked password-manager ({pw}) {method} from agent {str(agent)[:12]}")
            return {"error": PW_BLOCKED}
        # Browser-level Target.* calls must not use a session (stale or otherwise).
        # For everything else, explicit session in req wins; else default.
        browser_level = method.startswith(("Target.", "Browser."))
        if agent and not a and not browser_level and not req.get("session_id"):
            a = await self._agent_tab(agent)
        default = a["sid"] if a else self.session
        sid = None if browser_level else (req.get("session_id") or default)
        try:
            res = await asyncio.wait_for(self.cdp.send_raw(method, params, session_id=sid), timeout=CALL_TIMEOUT)
            if method == "Target.attachToTarget" and isinstance(res, dict) and res.get("sessionId"):
                self.sess.setdefault(res["sessionId"], [params.get("targetId"), ""])
            return {"result": res}
        except asyncio.TimeoutError:
            log(f"timeout {CALL_TIMEOUT:.0f}s: {method} session={sid}")
            if a and sid == a.get("sid"):
                # Вкладка не отвечает: закрываем её, следующий вызов агента получит свежую.
                self.agents.pop(agent, None)
                for t in {a.get("tid"), a.get("own")} - {None}:
                    try: await asyncio.wait_for(self.cdp.send_raw("Target.closeTarget", {"targetId": t}), timeout=5)
                    except Exception: pass
            return {"error": f"CDP {method} timed out after {CALL_TIMEOUT:.0f}s (tab hung?)"}
        except Exception as e:
            msg = str(e)
            if "Session with given id not found" in msg and a and sid == a["sid"]:
                # Закрыл вспомогательную вкладку → назад в свою основную; её тоже нет → новая.
                own = a.get("own")
                try:
                    if not own or own == a.get("tid"): raise RuntimeError("no own tab")
                    a["sid"] = (await self.cdp.send_raw("Target.attachToTarget", {"targetId": own, "flatten": True}))["sessionId"]
                    a["tid"] = own
                    await self._enable(a["sid"])
                    log(f"agent {agent[:12]}: stale session {sid}, back to own tab {own}")
                except Exception:
                    log(f"agent {agent[:12]}: stale session {sid}, new own tab")
                    self.agents.pop(agent, None)
                    a = await self._agent_tab(agent)
                return {"result": await self.cdp.send_raw(method, params, session_id=a["sid"])}
            if "Session with given id not found" in msg and sid == self.session and sid:
                log(f"stale session {sid}, re-attaching")
                if await self.attach_first_page():
                    return {"result": await self.cdp.send_raw(method, params, session_id=self.session)}
            return {"error": msg}


async def serve(d):
    if os.path.exists(SOCK):
        os.unlink(SOCK)

    async def handler(reader, writer):
        try:
            line = await reader.readline()
            if not line: return
            resp = await d.handle(json.loads(line))
            writer.write((json.dumps(resp, default=str) + "\n").encode())
            await writer.drain()
        except Exception as e:
            log(f"conn: {e}")
            try:
                writer.write((json.dumps({"error": str(e)}) + "\n").encode())
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()

    server = await asyncio.start_unix_server(handler, path=SOCK)
    os.chmod(SOCK, 0o600)
    log(f"listening on {SOCK} (name={NAME}, remote={REMOTE_ID or 'local'})")
    async with server:
        await d.stop.wait()


async def main():
    d = Daemon()
    await d.start()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, d.stop.set)
    try:
        await serve(d)
    finally:
        await d.close_agent_tabs()


def already_running():
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(1)
        s.connect(SOCK); s.close(); return True
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout):
        return False


if __name__ == "__main__":
    if already_running():
        print(f"daemon already running on {SOCK}", file=sys.stderr)
        sys.exit(0)
    open(LOG, "w").close()
    open(PID, "w").write(str(os.getpid()))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log(f"fatal: {e}")
        sys.exit(1)
    finally:
        stop_remote()
        try: os.unlink(PID)
        except FileNotFoundError: pass
