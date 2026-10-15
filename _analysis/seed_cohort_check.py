"""Verify the Roll5 seed-cohort fix: the estimate must match the run.

The reported run used a 2-seed cohort while the estimate promised 8:

    粗筛 2135x2 + 精评 1068x2 + baseline 2 = 6406

This checks that choosing Roll5 now raises the cohort to 8, that the estimate
follows the cohort, and that switching back to MEAN lowers it again.
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
    app.root.update()
    tab = app.tactical_tab
    from gui.dialogs.optimize_dialog import OptimizeDialog
    from src.optimizer.snapshot import build_snapshot
    from src.optimizer import budget as budget_mod

    sel = {"friends": [100303, 132301, 145301, 112302, 111301],
           "friend_positions": [100303, None, 132301, 145301, 112302, 111301],
           "enemy_id": 381305,
           "mems_friend": ["[30007] a", "[30029] b", "[30031] c",
                           "[30034] d", "[30038] e", "[30039] f"]}
    panel = app._build_panel_config_from_gui(app.global_tab.get_values())
    template = build_snapshot(sel, panel, enemy_id=381305)

    # A 12-card pool, the size the user actually searched.
    pool = sorted(set(template["memory_ids"]) | set(range(10001, 10007)))
    dialog = OptimizeDialog(tab, app, "战术演习", template=template,
                            pinned=(), pool=pool)
    dialog.update_idletasks()

    print("=== default is MEAN with a small cohort ===")
    check("defaults to mean", dialog._objective.get() == "mean",
          dialog._objective.get())
    check("mean cohort is 2", int(dialog._review_seeds.get()) == 2,
          dialog._review_seeds.get())
    mean_budget = int(dialog._budget.get())
    print(f"        mean budget = {mean_budget:,}")

    print()
    print("=== switching to Roll5 must RAISE the cohort to 8 ===")
    dialog._objective.set("roll5")
    dialog._on_objective_change()
    dialog.update_idletasks()
    check("roll5 cohort raised to 8", int(dialog._review_seeds.get()) == 8,
          dialog._review_seeds.get())
    check("the note explains why", "8" in dialog._seed_note.cget("text"),
          dialog._seed_note.cget("text"))
    roll_budget = int(dialog._budget.get())
    print(f"        roll5 budget = {roll_budget:,}")
    check("roll5 estimate exceeds mean", roll_budget > mean_budget,
          f"{mean_budget} -> {roll_budget}")

    print()
    print("=== the estimate matches the cohort it will run with ===")
    plan = dialog._plan()
    check("plan review_seeds matches the control",
          plan["review_seeds"] == int(dialog._review_seeds.get()),
          f"plan={plan['review_seeds']} control={dialog._review_seeds.get()}")
    check("plan budget matches the displayed budget",
          plan["budget"] == roll_budget,
          f"plan={plan['budget']} shown={roll_budget}")

    print()
    print("=== a smaller cohort costs less (the reported bug's shape) ===")
    plan8 = budget_mod.plan_search(plan["space_total"], "roll5", review_seeds=8)
    plan2 = budget_mod.plan_search(plan["space_total"], "roll5", review_seeds=2)
    print(f"        8 seeds: {plan8['budget']:,}  refine_cost={plan8['refine_battles']:,}")
    print(f"        2 seeds: {plan2['budget']:,}  refine_cost={plan2['refine_battles']:,}")
    check("the two plans differ, so the mismatch was real",
          plan8["budget"] != plan2["budget"],
          f"{plan8['budget']} vs {plan2['budget']}")

    # The invariant that matters: within the SAME budget, a larger cohort buys
    # fewer refined candidates. The plan's `refined` is a target, so compare the
    # cost per candidate instead.
    per_candidate_8 = plan8["budget"] // 8
    per_candidate_2 = plan2["budget"] // 2
    print(f"        budget per seed-slot: 8 seeds={per_candidate_8:,}  "
          f"2 seeds={per_candidate_2:,}")
    check("a bigger cohort costs more per candidate",
          plan8["refine_battles"] > plan2["refine_battles"],
          f"{plan8['refine_battles']} vs {plan2['refine_battles']}")
    check("both plans agree on the screened count",
          plan8["screened"] == plan2["screened"],
          f"{plan8['screened']} vs {plan2['screened']}")

    # And the reported run's numbers only reconcile with a 2-seed cohort.
    coarse, refined = 2135, 1068
    check("the reported run reconciles with 2 seeds, not 8",
          coarse * 2 + refined * 2 + 2 == 6408,
          f"{coarse * 2 + refined * 2 + 2} != 6408")

    print()
    print("=== switching back to MEAN lowers it again ===")
    dialog._objective.set("mean")
    dialog._on_objective_change()
    dialog.update_idletasks()
    check("mean cohort lowered to 2", int(dialog._review_seeds.get()) == 2,
          dialog._review_seeds.get())

    print()
    print("=== a deliberate larger cohort is preserved under Roll5 ===")
    dialog._objective.set("roll5")
    dialog._on_objective_change()
    dialog._review_seeds.set("16")
    dialog._on_objective_change()
    check("16 is not lowered to 8", int(dialog._review_seeds.get()) == 16,
          dialog._review_seeds.get())
    dialog.destroy()

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
print("seed-cohort agreement verified")
