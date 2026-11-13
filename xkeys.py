"""Настоящие системные клавиши (X11 XTest) в окно Chrome владельца — для fill_saved_password().
Нужны потому, что всплывающая подсказка менеджера паролей Chrome — нативное окно браузера:
CDP Input.dispatchKeyEvent до неё не доходит, XTest доходит. Клавиши шлются, только если фокус X сейчас у Chrome.
Запуск: python3 xkeys.py Down Tab   (код 3 — фокус не у Chrome, ничего не нажато)."""
import os, sys, time
from Xlib import X, XK, display
from Xlib.ext import xtest

d = display.Display(os.environ.get("BU_XDISPLAY", ":0"))
w = d.get_input_focus().focus
cls = None
while w and not isinstance(w, int):
    try:
        cls = w.get_wm_class()
    except Exception:
        cls = None
    if cls:
        break
    try:
        w = w.query_tree().parent
    except Exception:
        break
if not cls or "chrome" not in " ".join(cls).lower():
    print(f"xkeys: фокус не у Chrome ({cls}), клавиши не отправлены", file=sys.stderr)
    sys.exit(3)
for k in sys.argv[1:]:
    kc = d.keysym_to_keycode(XK.string_to_keysym(k))
    xtest.fake_input(d, X.KeyPress, kc); d.sync(); time.sleep(0.05)
    xtest.fake_input(d, X.KeyRelease, kc); d.sync(); time.sleep(0.4)
