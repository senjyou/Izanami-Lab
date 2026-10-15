"""Measure whether the preview keeps a constant height across results.

The pagination bar is only drawn when there is more than one page. The claim that
the strip does not change height therefore depends on the spacer matching the
pager's real height -- so measure both rather than assume.

Compares results with the same number of candidates drawn but different page
counts, which isolates the pager row from the candidate rows.
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


def make_result(count):
    cands = []
    for i in range(count):
        cands.append({
            "rank": i + 1,
            "is_baseline": False,
            "arrangement": [100303, None, 132301, 117302, 104302, 113301],
            "memory_ids": [30007, 30029, 30031, 30034, 30038, 30039],
            "summary": {"rank": 120_000_000 - i * 100_000, "sd": 300_000,
                        "cv": 0.3, "n": 2},
        })
    return {"objective": "mean",
            "best_summary": cands[0]["summary"] if cands else None,
            "baseline_summary": {"rank": 108_581_142, "sd": 1_236_337,
                                 "cv": 1.1, "n": 2},
            "candidates": cands}


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
    preview = tab._optimize_preview

    def measure(count, label):
        preview.render(make_result(count), app.data_loader)
        app.root.update_idletasks()
        app.root.update()
        h = preview.winfo_reqheight()
        header = preview.winfo_children()[0] if preview.winfo_children() else None
        print(f"    {label:32s} pages={preview.page_count:2d}  "
              f"requested height={h}")
        return h

    print("=== isolate the pager row (same candidates drawn, different page count) ===")
    h_1page = measure(3, "3 candidates -> 1 page")
    h_2page = measure(6, "6 candidates -> 2 pages")
    h_9page = measure(27, "27 candidates -> 9 pages")
    print()
    print(f"    delta 1 page vs 2 pages : {h_2page - h_1page:+d} px")
    print(f"    delta 2 pages vs 9 pages: {h_9page - h_2page:+d} px")
    print()
    if h_2page == h_1page:
        print("    => the spacer exactly matches the pager: height is constant")
    else:
        print(f"    => MISMATCH of {h_2page - h_1page} px: the spacer does not")
        print(f"       match the pager's real height, so the strip changes size")

    # Measure the pager row itself.
    print()
    print("=== the pager row's real height ===")
    preview.render(make_result(6), app.data_loader)
    app.root.update_idletasks()
    app.root.update()
    header = preview.winfo_children()[0]
    print(f"    header requested height = {header.winfo_reqheight()}")
    preview.render(make_result(3), app.data_loader)
    app.root.update_idletasks()
    app.root.update()
    header = preview.winfo_children()[0]
    print(f"    header (spacer) height  = {header.winfo_reqheight()}")

finally:
    try:
        app.update_daemon.stop()
    except Exception:
        pass
    app.root.destroy()
