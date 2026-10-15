"""Check the result panel's layout: no blank block, and results still work.

Two things are pinned:

  1. **No dead space.** The panel's PanedWindow gave the table notebook
     ``weight=2`` against the summary's ``weight=1``. With no tables the notebook
     still reserved most of the height and drew as a large blank area -- which is
     what the user saw after an optimizer run. The notebook must be collapsed
     while empty and restored when tables arrive.

  2. **Battle results are unaffected.** This panel is shared by five tabs that DO
     fill it with tables; collapsing must not break them.
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

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK    {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


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
    panel = tab._result_panel

    print("=== an empty panel collapses its table area ===")
    panel.clear()
    app.root.update_idletasks()
    app.root.update()
    panes = panel._paned.panes()
    print(f"    panes in the PanedWindow: {len(panes)}")
    check("notebook is removed while empty",
          str(panel._notebook) not in [str(p) for p in panes], panes)
    check("summary remains", str(panel._summary_text) in [str(p) for p in panes],
          panes)

    # With the table area gone the summary should own the whole height.
    app.root.update_idletasks()
    app.root.update()
    summary_h = panel._summary_text.winfo_height()
    panel_h = panel.winfo_height()
    print(f"    summary height={summary_h}  panel height={panel_h}")
    check("summary fills most of the panel", summary_h >= panel_h * 0.6,
          f"{summary_h} / {panel_h}")

    print()
    print("=== a text-only report leaves no blank block ===")
    # This is exactly what the optimizer does: text, no tables.
    panel.set_summary("【智能优化 · 均值】\n" + "测试行\n" * 30)
    panel.set_tables([])
    app.root.update_idletasks()
    app.root.update()
    panes = panel._paned.panes()
    check("still collapsed after set_tables([])",
          str(panel._notebook) not in [str(p) for p in panes], panes)
    empty_h = panel._notebook.winfo_height()
    print(f"    notebook height while empty: {empty_h}")

    print()
    print("=== battle results still work (the other four tabs) ===")
    table = {"title": "测试表", "columns": ["A", "B"],
             "rows": [["1", "2"], ["3", "4"]],
             "col_widths": [80, 80], "col_aligns": ["w", "w"]}
    panel.set_tables([table])
    app.root.update_idletasks()
    app.root.update()
    panes = panel._paned.panes()
    check("notebook returns when tables arrive",
          str(panel._notebook) in [str(p) for p in panes], panes)
    check("the table was added", len(panel._notebook.tabs()) == 1,
          panel._notebook.tabs())
    table_h = panel._notebook.winfo_height()
    print(f"    notebook height with a table: {table_h}")
    check("table area has real height", table_h > 40, table_h)

    print()
    print("=== clearing again collapses once more ===")
    panel.clear()
    app.root.update_idletasks()
    app.root.update()
    panes = panel._paned.panes()
    check("collapsed again after clear",
          str(panel._notebook) not in [str(p) for p in panes], panes)

    print()
    print("=== the panel never raises on repeated cycles ===")
    ok = True
    for _ in range(5):
        try:
            panel.set_tables([table])
            panel.clear()
            panel.set_summary("x")
            panel.set_tables([])
        except Exception as exc:
            ok = False
            print(f"        raised: {exc}")
    check("repeated set/clear cycles are safe", ok)

finally:
    try:
        app.update_daemon.stop()
    except Exception:
        pass
    app.root.destroy()

print()
if failures:
    print(f"FAILED ({len(failures)}): " + ", ".join(failures))
    sys.exit(1)
print("panel layout checks passed")
