"""Screenshot the real 智能优化 dialog, and compare theme indicators.

Two things to establish:

1. That the "X" the user sees is the dialog's own checkbox indicator (rather than
   something else in the window).
2. Which available theme draws a checkmark or a dot instead, so the fix is chosen
   from evidence rather than guessed.

Tk's `clam` theme draws the selected checkbutton indicator as a filled square
containing a glyph; what that glyph looks like at 16px is exactly what the user is
reporting, so it is rendered side by side with the alternatives.
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
from PIL import Image, ImageDraw  # noqa: E402

from gui.app import MGGBattleSimulatorGUI  # noqa: E402

with patch.object(tk.Tk, "mainloop"), \
     patch.object(MGGBattleSimulatorGUI, "_start_update_check"):
    app = MGGBattleSimulatorGUI()

try:
    for tab_id in app.notebook.tabs():
        if app.notebook.tab(tab_id, "text") == "战术演习":
            app.notebook.select(tab_id)
            break
    app.root.deiconify()
    app.root.update()
    import time
    time.sleep(0.4)
    app.root.update()

    tab = app.tactical_tab
    from src.optimizer.snapshot import build_snapshot
    from gui.dialogs.optimize_dialog import OptimizeDialog

    sel = {"friends": [100303, 132301, 145301, 112302, 111301],
           "friend_positions": [100303, None, 132301, 145301, 112302, 111301],
           "enemy_id": 381305,
           "mems_friend": ["[30007] a", "[30029] b", "[30031] c",
                           "[30034] d", "[30038] e", "[30039] f"]}
    panel = app._build_panel_config_from_gui(app.global_tab.get_values())
    template = build_snapshot(sel, panel, enemy_id=381305)

    dialog = OptimizeDialog(tab, app, "战术演习", template=template,
                            pinned=(), pool=template["memory_ids"])
    dialog.update_idletasks()
    dialog.update()
    dialog.lift()
    dialog.attributes("-topmost", True)
    time.sleep(0.6)
    dialog.update()

    # Report what style the dialog's own checkboxes ended up using, so the
    # screenshot is backed by a checkable fact rather than by eye alone.
    print("=== the dialog's checkbutton styles ===")
    found = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Checkbutton):
                found.append(child.cget("style") or "(default)")
            walk(child)

    walk(dialog)
    print(f"    checkbuttons found: {len(found)}")
    for style_name in found:
        print(f"      style = {style_name!r}")
    bad = [s for s in found if not s.startswith("Tick.TCheckbutton")]
    print(f"    -> all on the tick style: {not bad}"
          + (f"   offenders: {bad}" if bad else ""))

    print()
    print("=== grabbing the real 智能优化 dialog ===")
    try:
        from PIL import ImageGrab
        x, y = dialog.winfo_rootx(), dialog.winfo_rooty()
        w, h = dialog.winfo_width(), dialog.winfo_height()
        print(f"    at {x},{y} size {w}x{h}")
        shot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        out = ROOT / "_analysis" / "dialog_indicator.png"
        shot.save(out)
        print(f"    saved: {out} ({shot.width}x{shot.height})")
    except Exception as exc:
        print(f"    grab failed: {type(exc).__name__}: {exc}")

    dialog.destroy()

    # Now compare what each theme draws for a SELECTED checkbutton.
    print()
    print("=== comparing themes: what does a SELECTED checkbox look like? ===")
    style = ttk.Style()
    tiles = []
    for theme in ("clam", "alt", "default", "classic", "vista", "winnative", "xpnative"):
        try:
            style.theme_use(theme)
        except tk.TclError as exc:
            print(f"    {theme:10} unavailable ({exc})")
            continue
        probe = tk.Toplevel(app.root)
        probe.configure(bg="#eff1f5")
        var = tk.BooleanVar(value=True)
        ttk.Checkbutton(probe, text=f"{theme} 已选", variable=var).pack(
            anchor="w", padx=8, pady=6)
        probe.geometry("220x46+60+60")
        probe.update_idletasks()
        probe.update()
        probe.lift()
        probe.attributes("-topmost", True)
        time.sleep(0.35)
        probe.update()
        try:
            from PIL import ImageGrab
            px, py = probe.winfo_rootx(), probe.winfo_rooty()
            pw, ph = probe.winfo_width(), probe.winfo_height()
            img = ImageGrab.grab(bbox=(px, py, px + pw, py + ph))
            tiles.append((theme, img))
            print(f"    {theme:10} captured {img.width}x{img.height}")
        except Exception as exc:
            print(f"    {theme:10} grab failed: {exc}")
        probe.destroy()

    if tiles:
        width = max(t[1].width for t in tiles)
        height = sum(t[1].height for t in tiles)
        sheet = Image.new("RGB", (width, height), "white")
        yy = 0
        for _theme, img in tiles:
            sheet.paste(img, (0, yy))
            yy += img.height
        sheet = sheet.resize((sheet.width * 2, sheet.height * 2), 0)
        out = ROOT / "_analysis" / "theme_indicators.png"
        sheet.save(out)
        print(f"    comparison sheet: {out} ({sheet.width}x{sheet.height})")

finally:
    try:
        app.update_daemon.stop()
    except Exception:
        pass
    app.root.destroy()
