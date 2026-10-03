"""Browser control via CDP. Read, edit, extend -- this file is yours."""
import base64, json, os, socket, time, urllib.request
from pathlib import Path
from urllib.parse import urlparse


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
# Кто шлёт скрипт: у каждого агента своя вкладка в демоне (daemon.py, _agent_tab).
# Без id (кроны, ручной запуск) — старая общая вкладка.
AGENT = next((os.environ[k] for k in ("BU_AGENT", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "TMUX_PANE") if os.environ.get(k)), None)
ACTIVATE = os.environ.get("BU_ACTIVATE", "1") != "0"
INTERNAL = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://", "about:")


def _send(req):
    if AGENT: req = {**req, "agent": AGENT}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(float(os.environ.get("BU_CALL_TIMEOUT", "60")) + 30)  # демон сам режет вызов на BU_CALL_TIMEOUT
    s.connect(SOCK)
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk: break
        data += chunk
    s.close()
    r = json.loads(data)
    if "error" in r: raise RuntimeError(r["error"])
    return r


def cdp(method, session_id=None, **params):
    """Raw CDP. cdp('Page.navigate', url='...'), cdp('DOM.getDocument', depth=-1)."""
    return _send({"method": method, "params": params, "session_id": session_id}).get("result", {})


def drain_events():  return _send({"meta": "drain_events"})["events"]


# --- navigation / page ---
def goto(url):
    # Page.navigate висит, пока открыт диалог beforeunload («уйти без сохранения?» — LinkedIn admin/edit
    # и любые формы). Агент уходит со страницы намеренно, поэтому такой диалог принимаем сами.
    import threading
    res = {}
    def nav():
        try: res["r"] = cdp("Page.navigate", url=url)
        except Exception as e: res["e"] = e
    th = threading.Thread(target=nav, daemon=True); th.start(); th.join(2)
    if th.is_alive():
        try: cdp("Page.handleJavaScriptDialog", accept=True)
        except Exception: pass
        th.join(float(os.environ.get("BU_CALL_TIMEOUT", "60")))
    if "e" in res: raise res["e"]
    r = res.get("r", {})
    d = (Path(__file__).parent / "domain-skills" / (urlparse(url).hostname or "").removeprefix("www.").split(".")[0])
    return {**r, "domain_skills": sorted(p.name for p in d.rglob("*.md"))[:10]} if d.is_dir() else r

def page_info():
    """{url, title, w, h, sx, sy, pw, ph} — viewport + scroll + page size.

    If a native dialog (alert/confirm/prompt/beforeunload) is open, returns
    {dialog: {type, message, ...}} instead — the page's JS thread is frozen
    until the dialog is handled (see interaction-skills/dialogs.md)."""
    dialog = _send({"meta": "pending_dialog"}).get("dialog")
    if dialog:
        return {"dialog": dialog}
    r = cdp("Runtime.evaluate",
            expression="JSON.stringify({url:location.href,title:document.title,w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,pw:document.documentElement.scrollWidth,ph:document.documentElement.scrollHeight})",
            returnByValue=True)
    return json.loads(r["result"]["value"])

# --- input ---
def click(x, y, button="left", clicks=1):
    cdp("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=clicks)
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=clicks)

def type_text(text):
    cdp("Input.insertText", text=text)

_KEYS = {  # key → (windowsVirtualKeyCode, code, text)
    "Enter": (13, "Enter", "\r"), "Tab": (9, "Tab", "\t"), "Backspace": (8, "Backspace", ""),
    "Escape": (27, "Escape", ""), "Delete": (46, "Delete", ""), " ": (32, "Space", " "),
    "ArrowLeft": (37, "ArrowLeft", ""), "ArrowUp": (38, "ArrowUp", ""),
    "ArrowRight": (39, "ArrowRight", ""), "ArrowDown": (40, "ArrowDown", ""),
    "Home": (36, "Home", ""), "End": (35, "End", ""),
    "PageUp": (33, "PageUp", ""), "PageDown": (34, "PageDown", ""),
}
def press_key(key, modifiers=0):
    """Modifiers bitfield: 1=Alt, 2=Ctrl, 4=Meta(Cmd), 8=Shift.
    Special keys (Enter, Tab, Arrow*, Backspace, etc.) carry their virtual key codes
    so listeners checking e.keyCode / e.key all fire."""
    vk, code, text = _KEYS.get(key, (ord(key[0]) if len(key) == 1 else 0, key, key if len(key) == 1 else ""))
    base = {"key": key, "code": code, "modifiers": modifiers, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    cdp("Input.dispatchKeyEvent", type="keyDown", **base, **({"text": text} if text else {}))
    if text and len(text) == 1:
        cdp("Input.dispatchKeyEvent", type="char", text=text, **{k: v for k, v in base.items() if k != "text"})
    cdp("Input.dispatchKeyEvent", type="keyUp", **base)

def scroll(x, y, dy=-300, dx=0):
    cdp("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=dx, deltaY=dy)


# --- visual ---
def screenshot(path="/tmp/shot.png", full=False):
    r = cdp("Page.captureScreenshot", format="png", captureBeyondViewport=full)
    open(path, "wb").write(base64.b64decode(r["data"]))
    return path


# --- tabs ---
def list_tabs(include_chrome=True):
    out = []
    for t in cdp("Target.getTargets")["targetInfos"]:
        if t["type"] != "page": continue
        url = t.get("url", "")
        if not include_chrome and url.startswith(INTERNAL): continue
        out.append({"targetId": t["targetId"], "title": t.get("title", ""), "url": url})
    return out

def current_tab():
    tid = _send({"meta": "target"}).get("target_id") if AGENT else None
    t = (cdp("Target.getTargetInfo", targetId=tid) if tid else cdp("Target.getTargetInfo")).get("targetInfo", {})
    return {"targetId": t.get("targetId"), "url": t.get("url", ""), "title": t.get("title", "")}

def _mark_tab():
    """Prepend 🟢 to tab title so the user can see which tab the agent controls."""
    try: cdp("Runtime.evaluate", expression="if(!document.title.startsWith('\U0001F7E2'))document.title='\U0001F7E2 '+document.title")
    except Exception: pass

def switch_tab(target_id):
    # Unmark old tab
    try: cdp("Runtime.evaluate", expression="if(document.title.startsWith('\U0001F7E2 '))document.title=document.title.slice(2)")
    except Exception: pass
    if ACTIVATE: cdp("Target.activateTarget", targetId=target_id)
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    _send({"meta": "set_session", "session_id": sid, "target_id": target_id})
    _mark_tab()
    return sid

def new_tab(url="about:blank"):
    # Always create blank, then goto: passing url to createTarget races with
    # attach, so the brief about:blank is "complete" by the time the caller
    # polls and wait_for_load() returns before navigation actually starts.
    tid = cdp("Target.createTarget", url="about:blank")["targetId"]
    switch_tab(tid)
    if url != "about:blank":
        goto(url)
    return tid

def background_tab(url="about:blank"):
    """Open and attach to a new tab WITHOUT stealing focus from the user.

    The tab is created and navigated invisibly — Chrome never brings it to the front.
    Daemon session switches to this tab so all helpers (goto, js, screenshot, …) work normally.
    Returns (target_id, session_id).

    Typical pattern:
        saved = current_tab()
        tid, sid = background_tab("https://example.com")
        wait_for_load()
        data = js("document.body.innerText")
        close_tab(tid)
        switch_tab(saved["targetId"])   # restore user's visible tab
    """
    tid = cdp("Target.createTarget", url="about:blank")["targetId"]
    sid = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    _send({"meta": "set_session", "session_id": sid, "target_id": tid})
    if url != "about:blank":
        goto(url)
    return tid, sid

def close_tab(target_id):
    """Close a tab by target ID (works for any tab, including background ones)."""
    cdp("Target.closeTarget", targetId=target_id)

def ensure_real_tab():
    """Switch to a real user tab if current is chrome:// / internal / stale.
    У агента (AGENT) своя вкладка — остаётся в ней, чужие не трогает."""
    if AGENT:
        return current_tab()
    tabs = list_tabs(include_chrome=False)
    if not tabs:
        return None
    try:
        cur = current_tab()
        if cur["url"] and not cur["url"].startswith(INTERNAL):
            return cur
    except Exception:
        pass
    switch_tab(tabs[0]["targetId"])
    return tabs[0]

def open_url(url, match=None, reload=False):
    """Открыть страницу как человек: если своя вкладка уже на ней — НИЧЕГО не грузить.
    match — подстрока URL, по которой страница считается «той же» (по умолчанию url без #/хвостового /).
    Агенту (AGENT) не нужны new_tab/close_tab на каждый скрипт: демон держит ему одну фоновую вкладку
    между скриптами. Без AGENT (кроны) — новая вкладка, чтобы не затереть активную вкладку пользователя."""
    if not AGENT:
        new_tab(url); wait_for_load(); return {"reused": False, "url": url}
    cur = current_tab().get("url", "")
    key = match or url.split("#")[0].rstrip("/")
    if not reload and cur and key in cur:
        return {"reused": True, "url": cur}
    goto(url); wait_for_load()
    return {"reused": False, "url": url}

def human_pause(lo=0.8, hi=2.5):
    """Случайная пауза между действиями, чтобы ритм был человеческим."""
    import random; time.sleep(random.uniform(lo, hi))

def finish_task():
    """Конец ЗАДАЧИ (не скрипта): увести свою вкладку на about:blank (страница выгружается).
    Саму вкладку не закрываем: демон помнит её id, а простоявшую 30 мин закроет сам."""
    if AGENT: goto("about:blank")

def iframe_target(url_substr):
    """First iframe target whose URL contains `url_substr`. Use with js(..., target_id=...)."""
    for t in cdp("Target.getTargets")["targetInfos"]:
        if t["type"] == "iframe" and url_substr in t.get("url", ""):
            return t["targetId"]
    return None


# --- utility ---
def wait(seconds=1.0):
    time.sleep(seconds)

def wait_for_load(timeout=15.0):
    """Poll document.readyState == 'complete' or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if js("document.readyState") == "complete": return True
        time.sleep(0.3)
    return False

def js(expression, target_id=None):
    """Run JS in the attached tab (default) or inside an iframe target (via iframe_target())."""
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"] if target_id else None
    r = cdp("Runtime.evaluate", session_id=sid, expression=expression, returnByValue=True, awaitPromise=True)
    return r.get("result", {}).get("value")


_KC = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, " ": 32, "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40}


def dispatch_key(selector, key="Enter", event="keypress"):
    """Dispatch a DOM KeyboardEvent on the matched element.

    Use this when a site reacts to synthetic DOM key events on an element more reliably
    than to raw CDP input events.
    """
    kc = _KC.get(key, ord(key) if len(key) == 1 else 0)
    js(
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(e){{e.focus();e.dispatchEvent(new KeyboardEvent({json.dumps(event)},{{key:{json.dumps(key)},code:{json.dumps(key)},keyCode:{kc},which:{kc},bubbles:true}}));}}}})()"
    )

def upload_file(selector, path):
    """Set files on a file input via CDP DOM.setFileInputFiles. `path` is an absolute filepath (use tempfile.mkstemp if needed)."""
    doc = cdp("DOM.getDocument", depth=-1)
    nid = cdp("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector=selector)["nodeId"]
    if not nid: raise RuntimeError(f"no element for {selector}")
    cdp("DOM.setFileInputFiles", files=[path] if isinstance(path, str) else list(path), nodeId=nid)

_DL_HOOK = r"""(()=>{if(window.__bhDl)return 'ok';const st=window.__bhDl={items:[]};
const grab=(href,name)=>{const rec={href,name,state:'pending'};st.items.push(rec);
 fetch(href,{credentials:'include'}).then(async r=>{if(!r.ok)throw new Error('HTTP '+r.status);
  if(!rec.name){const cd=r.headers.get('content-disposition')||'';const m=cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i);
   rec.name=m?decodeURIComponent(m[1]):decodeURIComponent(new URL(r.url).pathname.split('/').pop()||'download');}
  const b=await r.blob();const fr=new FileReader();fr.onload=()=>{rec.data=String(fr.result).split(',')[1]||'';rec.state='done'};
  fr.onerror=()=>{rec.state='error';rec.err='read'};fr.readAsDataURL(b);}).catch(e=>{rec.state='error';rec.err=String(e)});};
const isFile=a=>a.hasAttribute('download')||/^(blob|data):/.test(a.href);
const orig=HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click=function(){if(isFile(this)){grab(this.href,this.getAttribute('download')||'');return}return orig.call(this)};
document.addEventListener('click',e=>{const a=e.composedPath().find(n=>n.tagName==='A');
 if(a&&isFile(a)){e.preventDefault();e.stopImmediatePropagation();grab(a.href,a.getAttribute('download')||'')}},true);
return 'installed'})()"""


def _dl_dir(dest_dir):
    import tempfile
    d = dest_dir or os.path.join(tempfile.gettempdir(), "bh-downloads", (AGENT or "manual")[:12])
    os.makedirs(d, exist_ok=True)
    return d


def _dl_save(dest_dir, name, b64):
    name = os.path.basename(name or "download") or "download"
    root, ext = os.path.splitext(name); path = os.path.join(dest_dir, name); i = 1
    while os.path.exists(path): path = os.path.join(dest_dir, f"{root} ({i}){ext}"); i += 1
    with open(path, "wb") as f: f.write(base64.b64decode(b64))
    return path


def download(trigger, dest_dir=None, timeout=120.0):
    """Скачать файл, который страница отдаёт ссылкой (<a download>, blob:, data:), в dest_dir.
    trigger — функция-клик (click/js). Хук на странице перехватывает ссылку и берёт байты fetch'ем с куками
    страницы; менеджер загрузок Chrome не участвует. Возвращает путь к файлу.
    Browser/Page.setDownloadBehavior на Chrome владельца демон отклоняет: любой такой вызов до перезапуска
    Chrome ломает «Открыть»/«Показать в папке» у ВСЕХ загрузок владельца (подмена делегата DevTools).
    Файл по прямому URL — fetch_file(url). Серверная выдача через POST-форму сюда не попадёт: бери агентский Chrome."""
    dest_dir = _dl_dir(dest_dir)
    js(_DL_HOOK)
    seen = js("window.__bhDl.items.length") or 0
    trigger()
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = js(f"(()=>{{const r=window.__bhDl&&window.__bhDl.items[{seen}];return r?JSON.stringify({{s:r.state,n:r.name,e:r.err||''}}):''}})()")
        if st:
            r = json.loads(st)
            if r["s"] == "error": raise RuntimeError(f"download failed: {r['e']}")
            if r["s"] == "done":
                b64 = js(f"(()=>{{const r=window.__bhDl.items[{seen}];const d=r.data;r.data='';return d}})()")
                return _dl_save(dest_dir, r["n"], b64)
        time.sleep(0.5)
    raise TimeoutError(f"no file link was clicked within {timeout:.0f}s — check the trigger or use fetch_file(url)")


def fetch_file(url, dest_dir=None, name=None):
    """Скачать URL fetch'ем изнутри текущей страницы (куки и сессия сайта) в dest_dir. Возвращает путь."""
    dest_dir = _dl_dir(dest_dir)
    r = js("fetch(%s,{credentials:'include'}).then(async r=>{if(!r.ok)throw new Error('HTTP '+r.status);"
           "const cd=r.headers.get('content-disposition')||'';const m=cd.match(/filename\\*?=(?:UTF-8'')?\"?([^\";]+)/i);"
           "const b=await r.blob();return await new Promise(res=>{const f=new FileReader();"
           "f.onload=()=>res(JSON.stringify({n:m?decodeURIComponent(m[1]):'',d:String(f.result).split(',')[1]||''}));f.readAsDataURL(b)})})" % json.dumps(url))
    if not r: raise RuntimeError(f"fetch_file failed for {url}")
    r = json.loads(r)
    return _dl_save(dest_dir, name or r["n"] or url.split("?")[0].rstrip("/").split("/")[-1], r["d"])


def http_get(url, headers=None, timeout=20.0):
    """Pure HTTP — no browser. Use for static pages / APIs. Wrap in ThreadPoolExecutor for bulk."""
    import urllib.request, gzip
    h = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
    if headers: h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip": data = gzip.decompress(data)
        return data.decode()
