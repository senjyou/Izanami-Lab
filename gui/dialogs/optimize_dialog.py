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
from src.optimizer.budget import (
    EFFORT_FAST, EFFORT_LABELS, EFFORT_STANDARD, EFFORT_THOROUGH,
    minimum_budget, plan_search, seeds_for)
from src.optimizer.search import SearchSettings

# A lineup equips exactly this many shared memories.
MEMORY_SLOTS = 6

DEFAULT_SEED = 2026
DEFAULT_MEAN_SEEDS = 2
DEFAULT_ROLL5_SEEDS = 8

# "自动" resolves to one battle process per logical CPU, the same default the
# official batch simulator uses.
AUTO_WORKERS_LABEL = "自动"


def _cpu_count():
    return max(1, os.cpu_count() or 1)


class _PlanSettings:
    """Minimal settings object so ``space_size`` can size the search."""

    def __init__(self, positions, memories):
        self.change_positions = bool(positions)
        self.change_memories = bool(memories)
        self.seed = 0


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
        self.result = None

        self._objective = tk.StringVar(value=objective or obj.OBJECTIVE_MEAN)
        self._positions = tk.BooleanVar(value=True)
        self._memories = tk.BooleanVar(value=True)
        self._budget = tk.StringVar(value="")
        self._manual_budget = tk.BooleanVar(value=False)
        self._effort = tk.StringVar(value=EFFORT_STANDARD)
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
        self._build_effort(body)
        self._build_memories(body)
        self._build_budget(body)
        self._build_advanced(body)
        self._build_actions(body)

    def _build_objective(self, parent):
        box = ttk.LabelFrame(parent, text="优化目标", padding=8)
        box.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(
            box, text="均值（稳定）—— 追求平均得分最高",
            variable=self._objective, value=obj.OBJECTIVE_MEAN,
            command=self._on_objective_change).pack(anchor="w")
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
        from src.optimizer.budget import describe_plan
        self._space_note.configure(text=describe_plan(plan))
        # The estimate becomes the budget unless the user has taken it over.
        if not self._manual_budget.get():
            self._budget.set(str(plan["budget"]))

    def _plan(self):
        """Compute the search plan for the current objective, pool and seeds.

        The seed count comes from the same control the run will use, so the
        estimate cannot promise an 8-seed refinement while the search performs a
        2-seed one.
        """
        from src.optimizer import budget as budget_mod
        from src.optimizer import space as space_mod
        constraints = self._constraints()
        template = self._template
        if template is None:
            raise ValueError("没有可用的阵容")
        positions, memories, combined = space_mod.space_size(
            template, constraints, _PlanSettings(self._positions.get(),
                                                 self._memories.get()))
        # Only the position axis matters when memories are fixed, so the smaller
        # figure is the honest one to plan against.
        space = combined if self._memories.get() else positions
        try:
            seeds = int(self._review_seeds.get())
        except (AttributeError, TypeError, ValueError):
            seeds = None
        return budget_mod.plan_search(space, self._objective.get(),
                                      effort=self._effort.get(),
                                      review_seeds=seeds)

    def _constraints(self):
        """The memory constraints implied by the current pin/pool selection."""
        pinned = {str(m): "必选" for m in sorted(self._pinned)}
        pool = {str(m): "候选" for m in sorted(self._pool - self._pinned)}
        return {"memories": {**pinned, **pool}}

    def _build_budget(self, parent):
        box = ttk.LabelFrame(parent, text="战斗预算", padding=8)
        box.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Checkbutton(row, text="手动指定",
                        variable=self._manual_budget,
                        command=self._on_budget_mode).pack(side="left")
        self._budget_entry = ttk.Entry(row, textvariable=self._budget, width=10,
                                       state="readonly")
        self._budget_entry.pack(side="left", padx=6)
        ttk.Label(row, text="场").pack(side="left")

        self._space_note = ttk.Label(box, text="", wraplength=380,
                                     justify="left")
        self._space_note.pack(anchor="w", pady=(4, 0))
        self._budget_note = ttk.Label(box, text="", wraplength=380,
                                      justify="left")
        self._budget_note.pack(anchor="w")

    def _on_budget_mode(self):
        """Switch between the estimate and a hand-set budget."""
        manual = self._manual_budget.get()
        self._budget_entry.configure(state="normal" if manual else "readonly")
        if not manual:
            self._refresh_space_note()
        else:
            self._budget_note.configure(
                text="手动预算：低于下限时会拒绝运行，以免白跑一场。")

    def _build_effort(self, parent):
        box = ttk.LabelFrame(parent, text="搜索强度", padding=8)
        box.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(box)
        row.pack(fill="x")
        for value in (EFFORT_FAST, EFFORT_STANDARD, EFFORT_THOROUGH):
            ttk.Radiobutton(row, text=EFFORT_LABELS[value], value=value,
                            variable=self._effort,
                            command=self._refresh_space_note).pack(side="left", padx=4)

    def _build_advanced(self, parent):
        ttk.Checkbutton(parent, text="高级选项（精评种子数 / 随机种子）",
                        variable=self._advanced,
                        command=self._toggle_advanced).pack(anchor="w")
        self._advanced_box = ttk.LabelFrame(parent, text="高级", padding=8)

        self._review_seeds = tk.StringVar(value=str(DEFAULT_MEAN_SEEDS))
        row = ttk.Frame(self._advanced_box)
        row.pack(fill="x")
        ttk.Label(row, text="精评种子数").pack(side="left")
        self._seeds_combo = ttk.Combobox(
            row, textvariable=self._review_seeds, width=6, state="readonly",
            values=("1", "2", "4", "8", "16", "32"))
        self._seeds_combo.pack(side="left", padx=4)
        # Changing the cohort changes the cost, so the estimate must follow it.
        self._seeds_combo.bind("<<ComboboxSelected>>",
                              lambda _event: self._refresh_space_note())
        ttk.Label(row, text="（越多越稳，消耗预算）").pack(side="left")

        row2 = ttk.Frame(self._advanced_box)
        row2.pack(fill="x", pady=(4, 0))
        ttk.Label(row2, text="随机种子").pack(side="left")
        ttk.Entry(row2, textvariable=self._seed, width=10).pack(side="left", padx=4)
        ttk.Label(row2, text="（相同种子可复现）").pack(side="left")

        # Battle processes. "自动" matches the official batch simulator, which uses
        # one process per logical CPU; that parallelism is the single biggest
        # factor in how fast a search finishes.
        row3 = ttk.Frame(self._advanced_box)
        row3.pack(fill="x", pady=(4, 0))
        ttk.Label(row3, text="战斗进程数").pack(side="left")
        self._workers = tk.StringVar(value=AUTO_WORKERS_LABEL)
        ttk.Combobox(row3, textvariable=self._workers, width=10, state="readonly",
                     values=(AUTO_WORKERS_LABEL, "1", "2", "4", "6", "8", "12", "16")
                     ).pack(side="left", padx=4)
        ttk.Label(row3, text=f"（自动 = {_cpu_count()} 核）").pack(side="left")

        self._seed_note = ttk.Label(self._advanced_box, text="", wraplength=380,
                                    justify="left")
        self._seed_note.pack(anchor="w", pady=(4, 0))
        self._on_objective_change()

    def _build_actions(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="开始优化", command=self._on_start).pack(side="right")
        ttk.Button(row, text="取消", command=self._on_cancel).pack(side="right", padx=6)

    # --------------------------------------------------------------- behaviour
    def _toggle_advanced(self):
        if self._advanced.get():
            self._advanced_box.pack(fill="x", pady=(4, 8), before=self._actions_anchor())
        else:
            self._advanced_box.pack_forget()

    def _actions_anchor(self):
        """The widget the advanced box should be inserted before."""
        children = self.winfo_children()[0].winfo_children()
        return children[-1]

    def _on_objective_change(self):
        """Align the seed cohort and the estimate with the chosen objective.

        The cohort is taken from the budget planner, which is the same source the
        estimate uses. That matters: the previous version only raised the seed
        count when it was exactly 1, so switching to Roll5 while the field held 2
        left a **two-sample** cohort in place. A two-sample spread is far too
        noisy for a best-of-five, and the estimate (which assumed 8) then
        disagreed with the run -- the reported budget asked for 8 seeds while the
        search used 2, producing 1068 "refined" candidates that were each only
        two battles deep.
        """
        if not hasattr(self, "_seed_note"):
            return
        coarse, review = seeds_for(self._objective.get())
        if self._objective.get() == obj.OBJECTIVE_ROLL5:
            # Only raise, never lower: a user who deliberately chose 16 keeps it.
            if int(self._review_seeds.get() or 0) < review:
                self._review_seeds.set(str(review))
            self._seed_note.configure(
                text=f"Roll5 需要估计上尾，精评需 {review} 个种子；"
                     f"少于 2 个种子时结果基本是噪声。")
            self._seeds_combo.configure(values=("2", "4", "8", "16", "32"))
        else:
            if int(self._review_seeds.get() or 0) > review:
                self._review_seeds.set(str(review))
            self._seed_note.configure(
                text=f"均值目标下 {review} 个精评种子已足够。")
            self._seeds_combo.configure(values=("1", "2", "4", "8", "16", "32"))
        self._refresh_space_note()

    def _selected_workers(self):
        """Translate the worker choice into a SearchSettings value (0 = auto)."""
        text = (self._workers.get() or "").strip()
        if not text or text == AUTO_WORKERS_LABEL:
            return 0
        try:
            return max(1, int(text))
        except (TypeError, ValueError):
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
            seeds = int(self._review_seeds.get())
        except (TypeError, ValueError):
            seeds = DEFAULT_MEAN_SEEDS
        try:
            seed = int(self._seed.get())
        except (TypeError, ValueError):
            messagebox.showwarning("随机种子", "随机种子必须是整数", parent=self)
            return

        # The budget: the estimate, or the user's number -- but never below the
        # floor at which the search could rank anything, because a run that
        # cannot produce a candidate is worse than a refusal.
        floor = minimum_budget(plan["space_total"], objective)
        try:
            budget = int(self._budget.get())
        except (TypeError, ValueError):
            messagebox.showwarning("战斗预算", "预算必须是正整数", parent=self)
            return
        if budget < floor:
            messagebox.showwarning(
                "预算过低",
                f"当前空间下至少需要 {floor:,} 场才能完成一次可排序的精评"
                f"（当前 {budget:,} 场）。提高预算，或缩小卡池。",
                parent=self)
            return

        if objective == obj.OBJECTIVE_ROLL5 and seeds < 2:
            messagebox.showwarning(
                "精评种子数", "Roll5 目标至少需要 2 个精评种子才能估计波动",
                parent=self)
            return
        try:
            settings = SearchSettings(
                objective=objective, budget=budget, seed=seed,
                change_positions=self._positions.get(),
                change_memories=self._memories.get(),
                review_seeds=seeds,
                workers=self._selected_workers(),
                # A volatile candidate cannot be judged from one draw, so Roll5
                # screens with a two-seed cohort.
                coarse_seeds=2 if objective == obj.OBJECTIVE_ROLL5 else 1)
        except ValueError as exc:
            messagebox.showwarning("设置无效", str(exc), parent=self)
            return

        self.result = dict(settings=settings, pinned=sorted(self._pinned),
                           pool=sorted(self._pool), plan=plan)
        self.destroy()

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
