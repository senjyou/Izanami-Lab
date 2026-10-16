# -*- coding: utf-8 -*-
"""The optimizer's settings dialog: a small modal opened from a mode tab.

Deliberately minimal. The dialog is the objective, the memory card pool, a search
effort, and an auto-estimated battle budget; the few remaining knobs live behind
a collapsed "advanced" section because they have sensible defaults.

Design notes
------------
* No new tab. The dialog is opened by a button on the tactical-exercise /
  circle-battle page and reports its result back to that page, which then shows
  progress and results in its existing result panel.
* The objective is the headline choice because it changes what "best" means:
  均值 optimizes the average score, Roll5 optimizes the best of five daily
  attempts. Measured on real lineups the two pick different champions about a
  third of the time.
* **The card pool is the second headline choice**, and often the decisive one.
  Searching all 164 memories is C(164,6) = 24.6 billion combinations -- before
  positions multiply that by 720. No budget reaches that, so an unbounded search
  is not a thorough search, it is a random sample. Naming a pool is what makes
  the result meaningful, so the pool is asked for up front.
* The budget is ESTIMATED from the objective and the pool rather than guessed,
  and the dialog states what the estimate covers. A budget is only meaningful
  relative to a space size, so asking the user for a bare number was asking them
  to guess at something the dialog already knows.
"""

import math
import os
import tkinter as tk
from tkinter import messagebox, ttk

from gui.dialogs.optimize_memory_picker import MemoryMultiPicker, MAX_PINNED
from gui.widgets.modal import _bind_modal_minimize_restore
from src.optimizer import objective as obj
from src.optimizer.search import SearchSettings

# A lineup equips exactly this many shared memories.
MEMORY_SLOTS = 6

# How deep the quick-review ladder may climb, per objective. Derived, not picked:
# the elimination rule (mean(D) > max(threshold*leader, 3*SE)) inverts to
# n ~= 9*(sd(D)/(r*mean))^2, so an estimator with k times the variance of the mean
# needs k times the seeds for the same resolution. Measured variance ratios:
#
#   mean   1.00x  -> 128 seeds (the ported ladder's own top rung; unchanged)
#   roll5  1.68x  -> 128*1.68 = 216, so the ladder's next rung, 256
#                 (analytic check: 1 + C5^2/2 = 1.676, matches the measurement)
#   floor  2.81x  -> 128*2.81 = 360; the ladder stops at 256, so 256 is the deepest
#                 available and the floor is still ~1.4x short of its ideal depth.
#                 That shortfall is a real limitation, not a hidden assumption.
REVIEW_DEPTH = {"mean": 128, "roll5": 256, "floor": 256}

DEFAULT_SEED = 2026
DEFAULT_MEAN_SEEDS = 2
DEFAULT_ROLL5_SEEDS = 8

# "自动" resolves to one battle process per logical CPU, the same default the
# official batch simulator uses.
# official batch simulator uses.
AUTO_WORKERS_LABEL = "自动"


def _cpu_count():
    return max(1, os.cpu_count() or 1)


class OptimizeDialog(tk.Toplevel):
    """Collect search options. ``result`` is a dict, or None if cancelled.

    ``template`` is the current lineup snapshot: the dialog needs it to size the
    space, since the cost of a search depends on how many slots and cards the
    user is actually varying.
    """

    def __init__(self, parent, app, mode_label, template=None,
                 pinned=None, pool=None, objective=None):
        super().__init__(parent)
        self.app = app
        self.mode_label = mode_label
        self._template = template
        # 对抗压制战 battles are all real and all count, which changes both the
        # objective offered and its sensible seed depth.
        self._circle_mode = "对抗" in str(mode_label)
        # The ported algorithm's own model validates against the real catalogue, so
        # the dialog needs the loader the app already holds.
        self._data_loader = getattr(app, "data_loader", None)
        self.result = None

        self._objective = tk.StringVar(value=objective or obj.OBJECTIVE_MEAN)
        self._positions = tk.BooleanVar(value=True)
        self._memories = tk.BooleanVar(value=True)
        self._seed = tk.StringVar(value=str(DEFAULT_SEED))
        self._advanced = tk.BooleanVar(value=False)

        self._pinned = set(pinned or ())
        # Default pool: whatever the lineup carries plus the pinned set. Not the
        # whole catalogue -- that is the unsearchable space this dialog exists to
        # avoid, and the user widens it deliberately.
        self._pool = set(pool or ()) | self._pinned

        self.title(f"智能优化 · {mode_label}")
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(False, False)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.update_idletasks()
        self._centre_on(parent)

    # ------------------------------------------------------------------ layout
    def _build(self):
        s = self.app._get_scheme()
        self.configure(bg=s["bg"])
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        self._build_objective(body)
        self._build_scope(body)
        self._build_memories(body)
        self._build_plan_note(body)
        self._build_actions(body)

    def _build_objective(self, parent):
        box = ttk.LabelFrame(parent, text="优化目标", padding=8)
        box.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(
            box, text="均值（稳定）—— 追求平均得分最高",
            variable=self._objective, value=obj.OBJECTIVE_MEAN,
            command=self._on_objective_change).pack(anchor="w")
        # The second objective depends on the mode, and offering the wrong one would
        # be misleading rather than merely useless:
        #   * tactical exercise gives five daily attempts and only the best counts,
        #     so best-of-five (Roll5) is the objective that matters there;
        #   * a circle stage's battles are all real and all count, so the guarantee
        #     matters more than the upside -- maximise the lowest score instead.
        if self._circle_mode:
            ttk.Radiobutton(
                box, text="保底（最差 10%）—— 每次战斗都真实有效，追求最差一成抬升",
                variable=self._objective, value=obj.OBJECTIVE_FLOOR,
                command=self._on_objective_change).pack(anchor="w")
        else:
            ttk.Radiobutton(
                box, text="当日最高 Roll5 —— 追求每日 5 次中的最好一次",
                variable=self._objective, value=obj.OBJECTIVE_ROLL5,
                command=self._on_objective_change).pack(anchor="w")

    def _build_scope(self, parent):
        box = ttk.LabelFrame(parent, text="搜索维度", padding=8)
        box.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(box, text="角色站位（6 个站位排列）",
                        variable=self._positions,
                        command=self._refresh_space_note).pack(anchor="w")
        ttk.Checkbutton(box, text="共享回忆（在卡池内组合）",
                        variable=self._memories,
                        command=self._refresh_space_note).pack(anchor="w")

    def _build_memories(self, parent):
        """Pinned memories and the candidate pool.

        The pool is the important half. Pinning only decides which cards are
        forced in; whatever is left over becomes the space the search draws from,
        and the whole catalogue is far too large to search (164 cards give
        C(164,6) = 24.6 billion combinations before positions are multiplied in).
        Naming the pool explicitly is what turns an unsearchable space into a
        searchable one, and it is the single biggest lever on the result.
        """
        box = ttk.LabelFrame(parent, text="回忆卡池（搜索范围）", padding=8)
        box.pack(fill="x", pady=(0, 8))

        pinned_row = ttk.Frame(box)
        pinned_row.pack(fill="x")
        ttk.Button(pinned_row, text="必选回忆…",
                   command=self._pick_pinned).pack(side="left")
        self._pinned_label = ttk.Label(pinned_row, text="", wraplength=250,
                                       justify="left")
        self._pinned_label.pack(side="left", padx=6)

        pool_row = ttk.Frame(box)
        pool_row.pack(fill="x", pady=(4, 0))
        ttk.Button(pool_row, text="候选卡池…",
                   command=self._pick_pool).pack(side="left")
        self._pool_label = ttk.Label(pool_row, text="", wraplength=250,
                                     justify="left")
        self._pool_label.pack(side="left", padx=6)

        ttk.Label(box, text="搜索只会在候选卡池内进行；必选回忆始终上场且不参与替换。"
                             "卡池越小，同样预算覆盖得越彻底。",
                  wraplength=380, justify="left").pack(anchor="w", pady=(4, 0))
        self._refresh_memory_labels()
        self._refresh_space_note()

    def _pick_pinned(self):
        """Choose the forced memories. At most six; may be empty."""
        dialog = MemoryMultiPicker(self, self.app, title="选择必选回忆",
                                   preselected=self._pinned, maximum=MAX_PINNED,
                                   noun="固定", allow_empty=True)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self._pinned = set(dialog.result)
        # A pinned card must also be in the pool, or the pool cannot build a
        # legal lineup that contains it.
        self._pool |= self._pinned
        self._refresh_memory_labels()
        self._refresh_space_note()

    def _pick_pool(self):
        """Choose the memories the search may draw from.

        At least six, because a lineup equips six: a smaller pool has no legal
        completion and the search could only report failure.
        """
        dialog = MemoryMultiPicker(self, self.app, title="选择候选卡池",
                                   preselected=self._pool, maximum=None,
                                   minimum=MEMORY_SLOTS,
                                   noun="选择", allow_empty=False)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self._pool = set(dialog.result) | self._pinned
        self._refresh_memory_labels()
        self._refresh_space_note()

    def _refresh_memory_labels(self):
        pinned_names = [self._memory_name(m) for m in sorted(self._pinned)]
        self._pinned_label.configure(
            text=("无（6 张全部由搜索决定）" if not pinned_names
                  else "、".join(pinned_names)))
        pool_names = [self._memory_name(m) for m in sorted(self._pool)]
        summary = self._pool_summary()
        self._pool_label.configure(
            text=f"{len(self._pool)} 张{summary}"
                 + (f"：{'、'.join(pool_names[:4])}"
                    + ("…" if len(pool_names) > 4 else "") if pool_names else ""))

    def _memory_name(self, mid):
        memory = self.app.data_loader.get_memory(mid)
        return memory.name if memory else str(mid)

    def _pool_summary(self):
        """The size of the combination space this pool creates."""
        try:
            need = max(0, MEMORY_SLOTS - len(self._pinned))
            usable = len(self._pool - self._pinned)
            if need == 0:
                return "（组合唯一）"
            if usable < need:
                return f"（不足 {need} 张，无法搜索）"
            return f"，组合 C({usable},{need}) = {math.comb(usable, need):,}"
        except Exception:
            return ""

    def _refresh_space_note(self):
        """Show the estimated cost of the search this pool implies."""
        if not hasattr(self, "_space_note"):
            return
        try:
            plan = self._plan()
        except Exception as exc:
            self._space_note.configure(text=f"无法估算：{exc}")
            return
        self._space_note.configure(text=self._describe_plan(plan))

    def _describe_plan(self, plan):
        """A short, wrapped summary of what the algorithm will actually do.

        No budget figure appears here: the dialog has no budget field to feed, so a
        suggested number would be text the user cannot act on.
        """
        positions = plan.get("legal_positions")
        memories = plan.get("legal_memories")
        joint = plan.get("theoretical_joint_configurations")
        parts = []
        if positions is not None and memories is not None:
            parts.append(f"空间 {positions} 站位 × {memories} 回忆"
                         f" = {joint:,} 种组合")
        if plan.get("bare_basic_cost"):
            parts.append(f"含裸装站位预选 {plan['bare_basic_cost']:,} 场")
        if plan.get("filter_enabled"):
            parts.append("已启用裸装淘汰与无效回忆剪枝")
        if plan.get("review_strategy") == "quick":
            # The ladder shown is the one this objective will actually climb, not the
            # ported default: Roll5 and the floor run one rung deeper (see
            # REVIEW_DEPTH), and saying 128 for them would misdescribe the run.
            depth = REVIEW_DEPTH.get(self._objective.get(), 128)
            rungs = [n for n in (8, 16, 32, 64, 128, 256) if n <= depth]
            ladder = "→".join(str(n) for n in rungs)
            note = "共同种子逐轮淘汰"
            if depth > 128:
                note += "（本目标需更深种子组，比均值多一轮）"
            if self._objective.get() == "floor":
                # The docstring rationale, surfaced where the user can see it.
                note += "；保底按最差 10% 分位评分"
            parts.append(f"复评走 {ladder} {note}")
        return "\n".join(parts) if parts else "无法估算"

    def _plan(self):
        """The ported V3.2 cost model for the current pool, objective and seeds.

        Uses `layered_recommendation` -- the algorithm's own planner -- rather than a
        local re-derivation, so the number shown here cannot drift from the number
        the search will actually spend.
        """
        from src.optimizer import model as model_mod
        from src.optimizer.layered_search import layered_recommendation
        template = self._template
        if template is None:
            raise ValueError("没有可用的阵容")
        constraints = self._constraints()
        model_mod.validate_constraints(template, constraints, self._data_loader,
                                       require_current=False)
        settings = self._build_settings(budget=1)   # budget is irrelevant to planning
        plan = layered_recommendation(template, constraints, settings,
                                      loader=self._data_loader)
        plan = dict(plan)
        plan["budget"] = plan.get("recommended_budget")
        return plan

    def _constraints(self):
        """The constraints implied by the current pin/pool selection.

        Both axes are always present. `validate_constraints` requires at least five
        characters and six memories to be listed, because anything unlisted is
        auto-excluded -- omitting the characters axis would leave it unfillable
        rather than unrestricted. The five lineup members are pinned because the V3.2
        layered mode fixes the characters and searches only positions and memories.
        """
        pinned = {str(m): "必选" for m in sorted(self._pinned)}
        pool = {str(m): "候选" for m in sorted(self._pool - self._pinned)}
        memories = {**pinned, **pool}
        characters = {}
        template = self._template or {}
        for cid in template.get("friend_positions", []):
            if cid is not None:
                characters[str(cid)] = "必选"
        # If the template is unavailable or short, fall back to whatever the pool
        # covers so the axis is never left empty.
        if len(characters) < 5:
            for cid in (template.get("friend_positions") or []):
                if cid is not None:
                    characters[str(cid)] = "必选"
        return {"characters": characters, "memories": memories}

    def _build_plan_note(self, parent):
        """What the algorithm will spend and how deep it will review, read-only.

        The search strength, budget and review-seed controls are gone: this engine
        self-allocates (the bare preselection runs 2->4->8, the joint coverage deepens
        to four seeds when the budget allows, and the review climbs to its cap), so a
        hand setting would only fight the algorithm. The numbers shown are the ones
        the run will actually use, so they cannot mislead.
        """
        box = ttk.LabelFrame(parent, text="本次搜索规模（自动）", padding=8)
        box.pack(fill="x", pady=(0, 8))
        self._space_note = ttk.Label(box, text="", wraplength=380, justify="left")
        self._space_note.pack(anchor="w")

    def _build_actions(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="开始优化", command=self._on_start).pack(side="right")
        ttk.Button(row, text="取消", command=self._on_cancel).pack(side="right", padx=6)

    # --------------------------------------------------------------- behaviour
    def _toggle_advanced(self):
        """There is no longer an advanced section to toggle."""
        pass

    def _actions_anchor(self):
        """The widget the (removed) advanced box should be inserted before."""
        children = self.winfo_children()[0].winfo_children()
        return children[-1]

    def _on_objective_change(self):
        """Objective changes only refresh the cost note -- no seeds to realign.

        The review depth, cohort and budget are all decided by the engine itself,
        so there is nothing on this side of the dialog for an objective switch to
        touch. Only the estimate label updates.
        """
        self._refresh_space_note()

    def _selected_workers(self):
        """Battle processes are always auto (one per core). No dialog control.

        The advanced section that held the worker picker was removed along with the
        strength/budget controls -- the algorithm self-allocates everything that
        mattered -- so "auto" is the only sensible answer now.
        """
        return 0

    def _on_start(self):
        """Validate, then hand back the settings and the chosen constraint set."""
        if not self._positions.get() and not self._memories.get():
            messagebox.showwarning("搜索维度", "至少要选择一个搜索维度", parent=self)
            return

        # A memory search needs a pool that can fill the unpinned slots.
        pool_only = self._pool - self._pinned
        need = MEMORY_SLOTS - len(self._pinned)
        if self._memories.get() and len(pool_only) < need:
            messagebox.showwarning(
                "候选卡池不足",
                f"必选 {len(self._pinned)} 张，还需从卡池补 {need} 张，"
                f"但卡池里只有 {len(pool_only)} 张可选。请扩大候选卡池。",
                parent=self)
            return

        objective = self._objective.get()
        try:
            plan = self._plan()
        except Exception as exc:
            messagebox.showwarning("无法估算预算", str(exc), parent=self)
            return
        try:
            seed = int(self._seed.get())
        except (TypeError, ValueError):
            messagebox.showwarning("随机种子", "随机种子必须是整数", parent=self)
            return

        # Budget and cohort depth are decided by the engine: the bare preselection
        # runs 2->4->8, the joint coverage deepens to four seeds when the budget
        # allows, and the review climbs to its cap. The plan's recommended budget is
        # the value the run actually uses.
        budget = int(plan.get("budget") or plan.get("recommended_budget") or 1)
        try:
            settings = self._build_settings(budget=budget, seed=seed)
        except ValueError as exc:
            messagebox.showwarning("设置无效", str(exc), parent=self)
            return

        self.result = dict(settings=settings, pinned=sorted(self._pinned),
                           pool=sorted(self._pool), plan=plan)
        self.destroy()

    def _build_settings(self, budget, seed=DEFAULT_SEED):
        """Build the ported algorithm's settings from this dialog's controls.

        The ported engine splits the work by ``search_kind``, and each kind fixes the
        dimensions it is allowed to move:

          * ``layered``   -- positions AND memories together (the V3.2 pipeline)
          * ``positions`` -- positions only, other dimensions pinned
          * ``memory``    -- memories only, other dimensions pinned

        So the dialog's two checkboxes select the kind rather than being passed
        through as loose flags, which is what the algorithm's own validation expects.
        """
        positions = bool(self._positions.get())
        memories = bool(self._memories.get())
        if positions and memories:
            kind = "layered"
        elif positions:
            kind = "positions"
        elif memories:
            kind = "memory"
        else:
            raise ValueError("请至少选择一个搜索维度")
        settings = SearchSettings(
            objective=self._objective.get(),
            budget=int(budget),
            seed=int(seed),
            search_kind=kind,
            # The V3.2 layered path requires the characters and affixes pinned and
            # both search axes live; that is exactly the (False, True, True, False)
            # combination its validation demands for `layered`.
            change_fifth=False,
            change_positions=positions,
            change_memories=memories,
            change_affixes=False,
            automatic=True,
            battle_workers=self._selected_workers(),
            # Everything else -- seed depth, the review ladder, the coverage cohort
            # count -- is decided by the algorithm itself, so none is set here.
            layered_filter=True,
            layered_base_seeds=2,
            layered_max_seeds=4,
            layered_review_percent=10,
            review_strategy="quick",
            layered_memory_pruning=True,
            quick_max_seeds=REVIEW_DEPTH[self._objective.get()],
            validation_seeds=10,
        )
        settings.validate()
        return settings

    def _on_cancel(self):
        self.result = None
        self.destroy()

    def _centre_on(self, parent):
        try:
            pw, ph = parent.winfo_width(), parent.winfo_height()
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 3)}")
        except tk.TclError:
            pass

