"""GUI check for the reworked optimizer dialog: pool, auto-budget, effort.

Runs the real application headless (mainloop patched) and drives the dialog the
way a user would, asserting the behaviours that were broken:

  * the default pool is the lineup's own cards, NOT the whole catalogue
  * the budget is estimated from the pool+objective and updates when the pool
    changes -- a small pool must yield a smaller estimate than a huge one
  * a pool too small to fill six slots is refused rather than searched
  * a budget below the floor is refused
  * Roll5 raises the seed default off 1
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
    print(f"  ({name} stubbed: not installed, unused by this check)")


class _FakeSession:
    def __init__(self, *a, **k):
        self.headers = {}
        self.trust_env = True

    def mount(self, *a, **k):
        return None

    def get(self, *a, **k):
        raise RuntimeError("network stubbed")


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

print("=== building the app (mainloop patched) ===")
with patch.object(tk.Tk, "mainloop"), \
     patch.object(MGGBattleSimulatorGUI, "_start_update_check"):
    app = MGGBattleSimulatorGUI()

try:
    app.root.update()
    tab = app.tactical_tab

    # Build a realistic template the way the mixin does.
    from src.optimizer.snapshot import build_snapshot
    sel = {"friends": [100303, 132301, 145301, 112302, 111301],
           "friend_positions": [100303, None, 132301, 145301, 112302, 111301],
           "enemy_id": 381305,
           "mems_friend": ["[30031] a", "[30025] b", "[30013] c",
                           "[30042] d", "[20041] e", "[30007] f"]}
    global_vals = app.global_tab.get_values()
    panel = app._build_panel_config_from_gui(global_vals)
    template = build_snapshot(sel, panel, enemy_id=381305)

    from gui.dialogs.optimize_dialog import OptimizeDialog, MEMORY_SLOTS
    print()
    print("=== default pool is the lineup, not the catalogue ===")
    # Mirrors the mixin: the lineup's cards as the pool, nothing pinned.
    dialog = OptimizeDialog(tab, app, "战术演习", template=template,
                            pinned=(), pool=template["memory_ids"])
    dialog.update_idletasks()
    check("dialog builds", dialog.winfo_exists() == 1)
    check("pool defaults to the 6 equipped cards",
          len(dialog._pool) == 6, sorted(dialog._pool))
    check("nothing is pinned by default", len(dialog._pinned) == 0,
          sorted(dialog._pinned))
    catalogue = app.data_loader.load_memories()
    check("pool is NOT the whole catalogue",
          len(dialog._pool) < len(catalogue),
          f"pool={len(dialog._pool)} catalogue={len(catalogue)}")

    print()
    print("=== budget is estimated, and tracks the pool ===")
    small_budget = int(dialog._budget.get())
    check("budget auto-filled", small_budget > 0, dialog._budget.get())
    check("budget field is read-only by default",
          str(dialog._budget_entry.cget("state")) == "readonly")
    note_small = dialog._space_note.cget("text")
    print(f"        small pool -> {small_budget:,} battles")
    print(f"        note: {note_small}")

    # Widen the pool and confirm the estimate and the space both grow.
    dialog._pool = set(sorted(catalogue)[:40])
    dialog._refresh_memory_labels()
    dialog._refresh_space_note()
    dialog.update_idletasks()
    big_budget = int(dialog._budget.get())
    note_big = dialog._space_note.cget("text")
    print(f"        wide pool  -> {big_budget:,} battles")
    print(f"        note: {note_big}")
    check("wider pool raises the estimated budget", big_budget > small_budget,
          f"{small_budget} -> {big_budget}")
    check("note mentions the space size", "候选" in note_big, note_big)

    print()
    print("=== Roll5 costs more than mean (two coarse seeds) ===")
    dialog._objective.set("mean")
    dialog._on_objective_change()
    mean_budget = int(dialog._budget.get())
    dialog._objective.set("roll5")
    dialog._on_objective_change()
    roll_budget = int(dialog._budget.get())
    print(f"        mean={mean_budget:,}  roll5={roll_budget:,}")
    check("roll5 estimate >= mean estimate", roll_budget >= mean_budget,
          f"{mean_budget} -> {roll_budget}")
    check("roll5 raised the seed default",
          int(dialog._review_seeds.get()) >= 2, dialog._review_seeds.get())

    print()
    print("=== a pool too small to fill six slots is refused ===")
    dialog._pinned = set()
    dialog._pool = {1, 2, 3}          # only 3 cards, need 6
    dialog.update_idletasks()
    with patch("gui.dialogs.optimize_dialog.messagebox.showwarning") as warn:
        dialog._on_start()
    check("small pool refused", len(warn.call_args_list) == 1,
          warn.call_args_list[:1])
    check("no result produced", dialog.result is None)

    print()
    print("=== a budget below the floor is refused ===")
    dialog._pinned = set(template["memory_ids"])
    dialog._pool = set(template["memory_ids"])
    dialog._refresh_space_note()
    dialog._manual_budget.set(True)
    dialog._budget.set("5")           # far below any usable floor
    dialog.update_idletasks()
    with patch("gui.dialogs.optimize_dialog.messagebox.showwarning") as warn:
        dialog._on_start()
    check("low budget refused", len(warn.call_args[0]) >= 1, warn.call_args_list)
    check("warning names the floor requirement",
          "至少" in str(warn.call_args_list[0]) if warn.call_args_list else False,
          warn.call_args_list[:1])

    print()
    print("=== a valid configuration starts ===")
    dialog._budget.set(str(big_budget))
    with patch("gui.dialogs.optimize_dialog.messagebox.showwarning") as warn:
        dialog._on_start()
    check("valid config accepted", dialog.result is not None)
    check("no warning raised", len(warn.call_args_list) == 0)
    if dialog.result:
        check("result carries the pool", "pool" in dialog.result)
        check("result carries the pinned set", "pinned" in dialog.result)
        check("result carries the plan", "plan" in dialog.result)
        plan = dialog.result["plan"]
        print(f"        plan: screened={plan['screened']:,} "
              f"refined={plan['refined']} budget={plan['budget']:,}")

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
print("all dialog checks passed")
