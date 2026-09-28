"""CDP WS holder + Unix socket relay. One daemon per BU_NAME."""
import asyncio, json, os, socket, sys, time, urllib.request
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

    async def attach_first_page(self):
        """Attach to a real page (or any page). Sets self.session. Returns attached target or None."""
        targets = (await self.cdp.send_raw("Target.getTargets"))["targetInfos"]
        pages = [t for t in targets if is_real_page(t)]
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
        try:
            await self.cdp.start()
        except Exception as e:
            raise RuntimeError(f"CDP WS handshake failed: {e} -- click Allow in Chrome if prompted, then retry")
        await self.attach_first_page()
        orig = self.cdp._event_registry.handle_event
        mark_js = "if(!document.title.startsWith('\U0001F7E2'))document.title='\U0001F7E2 '+document.title"
        async def tap(method, params, session_id=None):
            self.events.append({"method": method, "params": params, "session_id": session_id})
            if method == "Page.javascriptDialogOpening":
                self.dialog = params
            elif method == "Page.javascriptDialogClosed":
                self.dialog = None
            elif method in ("Page.loadEventFired", "Page.domContentEventFired"):
                try: await asyncio.wait_for(self.cdp.send_raw("Runtime.evaluate", {"expression": mark_js}, session_id=self.session), timeout=2)
                except Exception: pass
            return await orig(method, params, session_id)
        self.cdp._event_registry.handle_event = tap

    async def _enable(self, sid):
        for d in ("Page", "DOM", "Runtime", "Network"):
            try: await asyncio.wait_for(self.cdp.send_raw(f"{d}.enable", session_id=sid), timeout=5)
            except Exception as e: log(f"enable {d}: {e}")

    async def _agent_tab(self, agent):
        """Своя вкладка агента: создаётся при первом обращении, дальше переиспользуется."""
        a = self.agents.get(agent)
        if a: return a
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
        # Browser-level Target.* calls must not use a session (stale or otherwise).
        # For everything else, explicit session in req wins; else default.
        browser_level = method.startswith(("Target.", "Browser."))
        if agent and not a and not browser_level and not req.get("session_id"):
            a = await self._agent_tab(agent)
        default = a["sid"] if a else self.session
        sid = None if browser_level else (req.get("session_id") or default)
        try:
            return {"result": await asyncio.wait_for(self.cdp.send_raw(method, params, session_id=sid), timeout=CALL_TIMEOUT)}
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
    await serve(d)


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
