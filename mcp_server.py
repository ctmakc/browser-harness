#!/usr/bin/env python3
"""MCP server for browser-harness — exposes real Chrome via CDP over Unix socket."""
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("browser-harness")

SOCK = "/tmp/bu-default.sock"


def _send(req: dict):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk:
            break
        data += chunk
    s.close()
    r = json.loads(data)
    if "error" in r:
        raise RuntimeError(r["error"])
    return r


def _cdp(method, session_id=None, **params):
    return _send({"method": method, "params": params, "session_id": session_id}).get("result", {})


# ── navigation ─────────────────────────────────────────────────────────────────

@mcp.tool()
def navigate(url: str, new_tab: bool = False) -> dict:
    """Navigate to a URL. new_tab=True opens a fresh tab first."""
    if new_tab:
        tid = _cdp("Target.createTarget", url="about:blank")["targetId"]
        sid = _cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
        _send({"meta": "set_session", "session_id": sid})
    return _cdp("Page.navigate", url=url)


@mcp.tool()
def page_info() -> dict:
    """Return {url, title, w, h, sx, sy, pw, ph} for the current tab."""
    dialog = _send({"meta": "pending_dialog"}).get("dialog")
    if dialog:
        return {"dialog": dialog}
    r = _cdp(
        "Runtime.evaluate",
        expression='JSON.stringify({url:location.href,title:document.title,w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,pw:document.documentElement.scrollWidth,ph:document.documentElement.scrollHeight})',
        returnByValue=True,
    )
    return json.loads(r["result"]["value"])


@mcp.tool()
def wait_for_load(timeout: float = 15.0) -> bool:
    """Wait until document.readyState == 'complete'."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _cdp("Runtime.evaluate", expression="document.readyState", returnByValue=True)
            if r.get("result", {}).get("value") == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


# ── interaction ────────────────────────────────────────────────────────────────

@mcp.tool()
def click(x: int, y: int, button: str = "left") -> str:
    """Click at page coordinates (x, y)."""
    _cdp("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=1)
    _cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=1)
    return "clicked"


@mcp.tool()
def type_text(text: str) -> str:
    """Type text into the currently focused element."""
    _cdp("Input.insertText", text=text)
    return "typed"


@mcp.tool()
def press_key(key: str) -> str:
    """Press a key by name: Enter, Tab, Escape, Backspace, ArrowDown, etc."""
    _KEYS = {
        "Enter": (13, "\r"), "Tab": (9, "\t"), "Backspace": (8, ""),
        "Escape": (27, ""), "Delete": (46, ""), " ": (32, " "),
        "ArrowLeft": (37, ""), "ArrowUp": (38, ""), "ArrowRight": (39, ""), "ArrowDown": (40, ""),
    }
    vk, text = _KEYS.get(key, (ord(key[0]) if len(key) == 1 else 0, key if len(key) == 1 else ""))
    base = {"key": key, "code": key, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    _cdp("Input.dispatchKeyEvent", type="keyDown", **base, **({"text": text} if text else {}))
    if text and len(text) == 1:
        _cdp("Input.dispatchKeyEvent", type="char", text=text, **{k: v for k, v in base.items()})
    _cdp("Input.dispatchKeyEvent", type="keyUp", **base)
    return "pressed"


@mcp.tool()
def scroll(x: int, y: int, dy: int = -300, dx: int = 0) -> str:
    """Scroll at coordinates (x, y). dy negative = scroll down."""
    _cdp("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=dx, deltaY=dy)
    return "scrolled"


# ── JavaScript ─────────────────────────────────────────────────────────────────

@mcp.tool()
def js(expression: str) -> object:
    """Run arbitrary JavaScript in the current tab and return the result."""
    r = _cdp("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    return r.get("result", {}).get("value")


# ── screenshot ─────────────────────────────────────────────────────────────────

@mcp.tool()
def screenshot(path: str = "/tmp/shot.png", full_page: bool = False) -> str:
    """Take a screenshot. Returns the file path."""
    import base64
    r = _cdp("Page.captureScreenshot", format="png", captureBeyondViewport=full_page)
    open(path, "wb").write(base64.b64decode(r["data"]))
    return path


# ── tabs ───────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_tabs() -> list:
    """List all open page tabs with targetId, title, url."""
    INTERNAL = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://", "about:")
    out = []
    for t in _cdp("Target.getTargets")["targetInfos"]:
        if t["type"] != "page":
            continue
        url = t.get("url", "")
        if url.startswith(INTERNAL):
            continue
        out.append({"targetId": t["targetId"], "title": t.get("title", ""), "url": url})
    return out


@mcp.tool()
def switch_tab(target_id: str) -> str:
    """Switch active tab to the given targetId."""
    _cdp("Target.activateTarget", targetId=target_id)
    sid = _cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    _send({"meta": "set_session", "session_id": sid})
    return sid


@mcp.tool()
def close_tab(target_id: str) -> str:
    """Close the tab with the given targetId."""
    _cdp("Target.closeTarget", targetId=target_id)
    return "closed"


@mcp.tool()
def background_tab(url: str) -> dict:
    """Open a tab in background (no focus steal). Returns {target_id, session_id}."""
    tid = _cdp("Target.createTarget", url="about:blank")["targetId"]
    sid = _cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    _send({"meta": "set_session", "session_id": sid})
    if url != "about:blank":
        _cdp("Page.navigate", url=url)
    return {"target_id": tid, "session_id": sid}


if __name__ == "__main__":
    mcp.run(transport="stdio")
