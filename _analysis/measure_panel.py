"""Measure the result panel's real width, and test thumbnail scaling options.

The preview must fit under the 演习结果 panel on the right of a horizontal
PanedWindow, so its available width is a measured quantity, not a guess.
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
from gui.app import MGGBattleSimulatorGUI  # noqa: E402

with patch.object(tk.Tk, "mainloop"), \
     patch.object(MGGBattleSimulatorGUI, "_start_update_check"):
    app = MGGBattleSimulatorGUI()

try:
    app.root.update()
    tab = app.tactical_tab
    # The tab must actually be selected and mapped, or every widget reports a
    # width of 1 and the measurement is meaningless.
    for index, tab_id in enumerate(app.notebook.tabs()):
        if app.notebook.tab(tab_id, "text") == "战术演习":
            app.notebook.select(tab_id)
            break
    app.root.deiconify()
    app.root.update()
    app.root.update_idletasks()
    import time
    time.sleep(0.4)
    app.root.update()

    panel = tab._result_panel
    print("=== measured widths ===")
    print(f"    window        : {app.root.winfo_width()} x {app.root.winfo_height()}")
    print(f"    tab           : {tab.winfo_width()} x {tab.winfo_height()}")
    print(f"    result panel  : {panel.winfo_width()} x {panel.winfo_height()}")
    print(f"    panel notebook: {panel._notebook.winfo_width()}")
    print(f"    summary text  : {panel._summary_text.winfo_width()}")

    # What the character cards cost at various scales.
    from gui.widgets.formation_card import (
        CARD_W, CARD_H, MEM_W, MEM_H, SQ_W, SQ_H)
    print()
    print("=== card sizes available ===")
    print(f"    formation card : {CARD_W} x {CARD_H}  (x6 = {CARD_W * 6} px)")
    print(f"    square card    : {SQ_W} x {SQ_H}  (x6 = {SQ_W * 6} px)")
    print(f"    memory card    : {MEM_W} x {MEM_H}  (x6 = {MEM_W * 6} px)")

    avail = panel.winfo_width()
    print()
    print(f"=== what fits in {avail} px ===")
    for factor, label in ((1, "full"), (2, "half"), (3, "third")):
        cw, mw = CARD_W // factor, MEM_W // factor
        print(f"    formation /{factor} ({label}): {cw}px each -> 6 = {cw * 6}px "
              f"{'FITS' if cw * 6 <= avail else 'too wide'}")
    for factor in (1, 2):
        sw = SQ_W // factor
        print(f"    square    /{factor}: {sw}px each -> 6 = {sw * 6}px "
              f"{'FITS' if sw * 6 <= avail else 'too wide'}")

    # Verify Tk subsampling actually works and is cheap.
    print()
    print("=== Tk image scaling options ===")
    from gui.widgets.formation_card import load_memory_card_image, MEM_W, MEM_H
    photo = load_memory_card_image(30031, 3, (MEM_W, MEM_H))
    if photo is not None:
        print(f"    memory card loaded: {photo.width()}x{photo.height()}")
        # PhotoImage has no .subsample() method in this Python; the Tk `image
        # copy -subsample` subcommand is the available route.
        try:
            small = tk.PhotoImage()
            small.tk.call(small, "copy", str(photo), "-subsample", 2, 2)
            print(f"    Tk copy -subsample 2 -> {small.width()}x{small.height()}")
            app.root._keepalive_mem_small = small
        except tk.TclError as exc:
            print(f"    Tk copy -subsample failed: {exc}")
        # PIL route, which the loaders already use internally.
        try:
            from PIL import Image, ImageTk
            src = ROOT / "data" / "images" / "memory_cards" / "30031.png"
            if src.exists():
                img = Image.open(src).convert("RGBA").resize((74, 41), Image.LANCZOS)
                pil_small = ImageTk.PhotoImage(img)
                print(f"    PIL resize -> {pil_small.width()}x{pil_small.height()}")
                app.root._keepalive_mem_pil = pil_small
            else:
                print(f"    source art missing: {src}")
        except Exception as exc:
            print(f"    PIL route failed: {exc}")
    else:
        print("    memory card art missing")

finally:
    try:
        app.update_daemon.stop()
    except Exception:
        pass
    app.root.destroy()
