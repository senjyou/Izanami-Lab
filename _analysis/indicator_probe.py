"""Capture what the dialog's selection indicators actually look like.

The user reports the selected marker renders as a cross ("叉"). The dialog uses
ttk.Checkbutton / ttk.Radiobutton under the "clam" theme, so the indicator is
drawn by Tk's theme engine, not by our code -- which means the only reliable way
to know what it looks like is to render it and look.

The dialog is opened, raised, and the region around its checkboxes is grabbed to
PNG so the glyph can be inspected directly.
"""
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
os.environ["APPDATA"] = str(ROOT / "_analysis" / "_gui_check_appdata")

import importlib.util  # noqa: E402


def _stub(name, **attrs):
    if importlib.util.find_spec(name) is not None:
        return
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


class _FakeSession:
    def __init__(self, *a, **k):
        self.headers = {}
        self.trust_env = True

    def mount(self, *a, **k):
        return None

    def get(self, *a, **k):
        raise RuntimeError("stubbed")


_stub("pywinstyles", apply_style=lambda *a, **k: None,
      change_header_color=lambda *a, **k: None,
      change_title_color=lambda *a, **k: None,
      change_border_color=lambda *a, **k: None)
_stub("requests", Session=_FakeSession, Response=type("R", (), {}),
      exceptions=types.SimpleNamespace(RequestException=Exception,
                                       Timeout=Exception, ConnectionError=Exception),
      get=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stubbed")))

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

from gui.app import MGGBattleSimulatorGUI  # noqa: E402

with patch.object(tk.Tk, "mainloop"), \
     patch.object(MGGBattleSimulatorGUI, "_start_update_check"):
    app = MGGBattleSimulatorGUI()

try:
    app.root.deiconify()
    app.root.update()

    # What theme is in force, and what do the indicator elements expose?
    style = ttk.Style()
    print(f"  current theme : {style.theme_use()}")
    print(f"  available     : {style.theme_names()}")
    print()
    print("  Checkbutton layout :", style.layout("TCheckbutton"))
    print()
    print("  Radiobutton layout :", style.layout("TRadiobutton"))
    print()
    for opt in ("indicatorcolor", "indicatorforeground", "background",
                "foreground", "focuscolor"):
        try:
            print(f"    TCheckbutton {opt:22} = {style.lookup('TCheckbutton', opt)}")
        except tk.TclError as exc:
            print(f"    TCheckbutton {opt:22} = <error {exc}>")
    print()
    for state in ((), ("selected",), ("disabled",)):
        try:
            print(f"    TCheckbutton indicatorcolor {str(state):20} = "
                  f"{style.lookup('TCheckbutton', 'indicatorcolor', state)}")
        except tk.TclError as exc:
            print(f"    {state} -> error {exc}")

    # Build a panel with one selected and one unselected control of each kind,
    # on the app's own background, then grab it.
    probe = tk.Toplevel(app.root)
    probe.title("indicator probe")
    probe.geometry("360x150+80+80")
    scheme = app._get_scheme()
    probe.configure(bg=scheme["bg"])

    var_cb = tk.BooleanVar(value=True)
    var_rb = tk.StringVar(value="a")
    ttk.Checkbutton(probe, text="已勾选（选中态）", variable=var_cb).pack(anchor="w", padx=12, pady=6)
    var_cb2 = tk.BooleanVar(value=False)
    ttk.Checkbutton(probe, text="未勾选", variable=var_cb2).pack(anchor="w", padx=12, pady=6)
    ttk.Radiobutton(probe, text="已选中的单选", variable=var_rb, value="a").pack(anchor="w", padx=12, pady=6)
    ttk.Radiobutton(probe, text="未选中的单选", variable=var_rb, value="b").pack(anchor="w", padx=12, pady=6)

    probe.update_idletasks()
    probe.update()
    probe.lift()
    probe.attributes("-topmost", True)
    probe.update()
    import time
    time.sleep(0.6)
    probe.update()

    # Grab the whole probe window.
    try:
        from PIL import ImageGrab
        x = probe.winfo_rootx()
        y = probe.winfo_rooty()
        w = probe.winfo_width()
        h = probe.winfo_height()
        print()
        print(f"  grabbing probe at {x},{y} size {w}x{h}")
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        out = ROOT / "_analysis" / "indicator_probe.png"
        # Scale up so the glyph is legible.
        img = img.resize((img.width * 3, img.height * 3), 0)
        img.save(out)
        print(f"  saved: {out}  ({img.width}x{img.height})")
    except Exception as exc:
        print(f"  grab failed: {type(exc).__name__}: {exc}")

    probe.destroy()

finally:
    try:
        app.update_daemon.stop()
    except Exception:
        pass
    app.root.destroy()
