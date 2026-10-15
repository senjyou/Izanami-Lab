"""GUI integration check with the cosmetic Windows-only dependency stubbed.

``pywinstyles`` styles the window frame/title on Windows and is imported by the
official ``gui/app.py``. It is not installed here and pip cannot reach the
network, so this run injects a no-op stub into ``sys.modules`` first. That is
legitimate for this check because the module only affects appearance -- it is
never consulted for layout, data or battle logic.

The check runs the real application (with ``mainloop`` patched out, as the
project's own GUI tests do) and verifies:
  * both mode tabs still build, with their optimize button present
  * no optimizer tab was added to the notebook
  * the settings dialog and the memory multi-picker construct and behave
"""

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))

# Isolate user data before anything imports gui.constants. The directory is
# created under the workspace, which is the writable area in this environment.
_check_root = ROOT / "_analysis" / "_gui_check_appdata"
_check_root.mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(_check_root)

# Stub the two optional runtime dependencies that are genuinely missing here.
# Both are only used for cosmetic/network features -- window frame styling and
# the update checker -- neither of which this layout/behaviour check exercises.
import importlib.util  # noqa: E402


def _stub(name, **attrs):
    if importlib.util.find_spec(name) is not None:
        return
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    print(f"  ({name} stubbed: not installed, unused by this check)")


class _FakeSession:
    """Just enough of requests.Session for import-time module construction."""

    def __init__(self, *a, **k):
        self.headers = {}
        self.trust_env = True

    def mount(self, *a, **k):
        return None

    def get(self, *a, **k):
        raise RuntimeError("network is stubbed out in this check")


class _FakeResponse:
    pass


_stub(
    "pywinstyles",
    apply_style=lambda *a, **k: None,
    change_header_color=lambda *a, **k: None,
    change_title_color=lambda *a, **k: None,
    change_border_color=lambda *a, **k: None,
)
_stub(
    "requests",
    Session=_FakeSession,
    Response=_FakeResponse,
    exceptions=types.SimpleNamespace(
        RequestException=Exception, Timeout=Exception, ConnectionError=Exception),
    get=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stubbed")),
)

from unittest.mock import patch  # noqa: E402
import tkinter as tk  # noqa: E402

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK    {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


from gui.app import MGGBattleSimulatorGUI  # noqa: E402

print("=== building the real main window (mainloop patched) ===")
with patch.object(tk.Tk, "mainloop"), \
     patch.object(MGGBattleSimulatorGUI, "_start_update_check"):
    app = MGGBattleSimulatorGUI()

try:
    app.root.update()

    names = [app.notebook.tab(t, "text") for t in app.notebook.tabs()]
    print(f"  tabs ({len(names)}): {names}")
    check("official 8 tabs present", len(names) == 8, names)
    check("no optimizer tab added", not any("优化" in n for n in names), names)

    for label, tab in (("战术演习", app.tactical_tab), ("对抗压制战", app.circle_tab)):
        has_btn = hasattr(tab, "_optimize_btn")
        check(f"{label}: optimize button exists", has_btn)
        if has_btn:
            info = tab._optimize_btn.grid_info()
            check(f"{label}: button gridded", bool(info), info)
            check(f"{label}: button text is 智能优化",
                  "智能优化" in str(tab._optimize_btn.cget("text")),
                  tab._optimize_btn.cget("text"))
            check(f"{label}: not disabled by default",
                  str(tab._optimize_btn.cget("state")) == "normal",
                  tab._optimize_btn.cget("state"))
        check(f"{label}: _optimize_apply implemented",
              callable(getattr(tab, "_optimize_apply", None)))
        sel = tab._get_selection()
        check(f"{label}: selection readable", isinstance(sel, dict))

    mode = getattr(app.circle_tab, "_OPTIMIZE_MODE", None)
    check("circle tab declares circle mode", mode == "circle", mode)
    check("tactical tab defaults to tactical mode",
          getattr(app.tactical_tab, "_OPTIMIZE_MODE", "tactical") == "tactical")

    print()
    print("=== settings dialog ===")
    from src.optimizer.snapshot import build_snapshot
    from gui.dialogs.optimize_dialog import OptimizeDialog
    # Build a real template so the dialog can size the space, the way the mixin
    # hands it one.
    sel = {"friends": [100303, 132301, 145301, 112302, 111301],
           "friend_positions": [100303, None, 132301, 145301, 112302, 111301],
           "enemy_id": 381305,
           "mems_friend": ["[30031] a", "[30025] b", "[30013] c",
                           "[30042] d", "[20041] e", "[30007] f"]}
    try:
        panel = app._build_panel_config_from_gui(app.global_tab.get_values())
        template = build_snapshot(sel, panel, enemy_id=381305)
    except Exception as exc:
        template = None
        print(f"        (template unavailable: {exc})")
    dialog = OptimizeDialog(app.tactical_tab, app, "战术演习",
                            template=template, pinned=(),
                            pool=(template["memory_ids"] if template else []))
    dialog.update_idletasks()
    check("dialog builds", dialog.winfo_exists() == 1)
    check("defaults to mean objective", dialog._objective.get() == "mean",
          dialog._objective.get())
    dialog._review_seeds.set("1")
    dialog._objective.set("roll5")
    dialog._on_objective_change()
    check("roll5 raises review seeds above 1",
          int(dialog._review_seeds.get()) >= 2, dialog._review_seeds.get())
    dialog._objective.set("mean")
    dialog._on_objective_change()
    check("mean keeps a small cohort",
          int(dialog._review_seeds.get()) >= 1, dialog._review_seeds.get())

    # Start with no search axis must be refused, not silently accepted.
    dialog._positions.set(False)
    dialog._memories.set(False)
    dialog._objective.set("roll5")
    before = dialog.result
    with patch("gui.dialogs.optimize_dialog.messagebox.showwarning") as warn:
        dialog._on_start()
    check("empty search scope is refused", len(warn.call_args_list) == 1)
    check("dialog did not produce a result", dialog.result is before)
    dialog.destroy()

    print()
    print("=== memory multi-picker ===")
    from gui.dialogs.optimize_memory_picker import MemoryMultiPicker
    picker = MemoryMultiPicker(app.tactical_tab, app, preselected=[30031, 30025])
    picker.update_idletasks()
    check("picker builds", picker.winfo_exists() == 1)
    check("preselection restored", sorted(picker.result) == [30025, 30031], picker.result)
    picker._on_select(30013)
    check("toggles a card on", picker.pinned == [30013, 30025, 30031], picker.pinned)
    picker._on_select(30013)
    check("toggles a card off", picker.pinned == [30025, 30031], picker.pinned)
    picker._clear()
    check("clear empties the selection", picker.pinned == [], picker.pinned)
    # Re-selecting and confirming must hand the ids back to the caller.
    picker._on_select(30042)
    picker._on_confirm()
    check("confirm returns the pinned ids", picker.result == [30042], picker.result)
    check("count label present", hasattr(picker, "_count_var"))
    picker.destroy()

    print()
    print("=== runner wiring ===")
    from gui.optimizer_runner import OptimizerRunner
    runner = OptimizerRunner(app, app.tactical_tab)
    check("runner starts idle", runner.busy() is False)
    # format_report is now an instance method: it needs the app's data loader to
    # resolve ids into names.
    empty_report = runner.format_report(
        {"settings": {}, "objective": "mean", "battles": 0,
         "candidates": [], "space": {}})
    check("report renders for an empty result", "没有候选" in empty_report,
          empty_report[:80])
    check("empty report suggests a next step", "缩小" in empty_report)
    runner.close()

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
print("all GUI integration checks passed")
