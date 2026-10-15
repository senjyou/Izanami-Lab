"""Screenshot the optimizer dialog's checkboxes in BOTH colour schemes.

The tick indicator is generated from the active scheme's colours, so the dark
scheme needs its own look rather than being assumed to work. This writes one
image per scheme for eyeball confirmation.
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
from PIL import Image  # noqa: E402

from gui.app import MGGBattleSimulatorGUI  # noqa: E402

with patch.object(tk.Tk, "mainloop"), \
     patch.object(MGGBattleSimulatorGUI, "_start_update_check"):
    app = MGGBattleSimulatorGUI()

tiles = []
try:
    app.root.deiconify()
    app.root.update()

    for scheme_name in ("light", "dark"):
        # Apply the scheme the way the app's own theme switcher does.
        app._current_scheme = scheme_name
        app._apply_ttk_style()
        app.root.update_idletasks()
        app.root.update()

        scheme = app._get_scheme()
        probe = tk.Toplevel(app.root)
        probe.title(scheme_name)
        probe.configure(bg=scheme["bg"])
        probe.geometry("260x120+90+90")
        ttk.Label(probe, text=f"{scheme_name} 配色",
                  font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        v1 = tk.BooleanVar(value=True)
        v2 = tk.BooleanVar(value=False)
        ttk.Checkbutton(probe, text="已勾选", variable=v1).pack(anchor="w", padx=10, pady=3)
        ttk.Checkbutton(probe, text="未勾选", variable=v2).pack(anchor="w", padx=10, pady=3)
        rv = tk.StringVar(value="a")
        ttk.Radiobutton(probe, text="单选（应保持圆点）", variable=rv,
                        value="a").pack(anchor="w", padx=10, pady=3)
        probe.update_idletasks()
        probe.update()
        probe.lift()
        probe.attributes("-topmost", True)
        import time
        time.sleep(0.5)
        probe.update()
        try:
            from PIL import ImageGrab
            x, y = probe.winfo_rootx(), probe.winfo_rooty()
            w, h = probe.winfo_width(), probe.winfo_height()
            tiles.append((scheme_name, ImageGrab.grab(bbox=(x, y, x + w, y + h))))
            print(f"  {scheme_name}: captured {w}x{h}")
        except Exception as exc:
            print(f"  {scheme_name}: grab failed {exc}")
        probe.destroy()

    if tiles:
        width = max(t[1].width for t in tiles)
        height = sum(t[1].height for t in tiles) + 10 * (len(tiles) - 1)
        sheet = Image.new("RGB", (width, height), "white")
        yy = 0
        for _name, img in tiles:
            sheet.paste(img, (0, yy))
            yy += img.height + 10
        sheet = sheet.resize((sheet.width * 2, sheet.height * 2), 0)
        out = ROOT / "_analysis" / "checkmark_schemes.png"
        sheet.save(out)
        print(f"  saved: {out} ({sheet.width}x{sheet.height})")

finally:
    try:
        app.update_daemon.stop()
    except Exception:
        pass
    app.root.destroy()
