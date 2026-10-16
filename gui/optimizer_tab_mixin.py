# -*- coding: utf-8 -*-
"""Shared optimizer hook for the mode tabs.

Adding the optimizer to a tab is meant to be three lines: build the button,
call :meth:`OptimizeTabMixin.open_optimizer`, and let the mixin do the rest.
Both the tactical-exercise and circle-battle pages use this, so the two entry
points cannot drift apart.

The mixin assumes nothing about the tab beyond the official contract that is
already true of both pages:

* ``self._get_selection()`` returns the current lineup dict
* ``self._result_panel`` is a ``ResultTablePanel``
* ``self.app`` exposes ``data_loader``, ``_build_panel_config_from_gui`` and
  ``global_tab.get_values()``
"""

import tkinter as tk
from tkinter import messagebox, ttk

from gui.dialogs.optimize_dialog import OptimizeDialog
from gui.optimizer_runner import OptimizerRunner
from src.optimizer import model as model_mod
from src.optimizer import objective as obj


class OptimizeTabMixin:
    """Adds one button and its wiring to a mode tab."""

    # Subclasses set this to the mode name used by the evaluator.
    _OPTIMIZE_MODE = "tactical"

    # ---------------------------------------------------------------- button
    def build_optimize_button(self, parent, column, text="⚙ 智能优化"):
        """Create the optimize button in an existing button row.

        Placed on the row's own column, but laid out so a second row can be added
        beneath without disturbing whatever else the tab put there.
        """
        self._optimize_btn = ttk.Button(parent, text=text, width=16,
                                        command=self.open_optimizer)
        self._optimize_btn.grid(row=0, column=column, padx=5, pady=5)
        # Row reserved for the run controls (stop / apply). Keeping it separate
        # from the tab's own row is what stops 应用最优站位 from being pushed past
        # the visible width when the tab already fills its row.
        self._optimize_action_row = ttk.Frame(parent)
        self._optimize_runner = None
        self._optimize_stop_btn = None
        self._optimize_apply_btn = None
        self._optimize_preview = None
        return self._optimize_btn

    def build_result_preview(self, parent):
        """Add the thumbnail strip under the result panel.

        The panel shows a text report, which cannot carry card art; the preview
        sits directly beneath it so a result can be recognised by the pictures
        rather than by names.
        """
        from gui.optimizer_preview import ResultPreview
        if self._optimize_preview is None:
            self._optimize_preview = ResultPreview(parent, self.app)
            self._optimize_preview.pack(fill="x", side="bottom")
        return self._optimize_preview

    # ------------------------------------------------------------------ entry
    def open_optimizer(self):
        """Open the settings dialog and, if confirmed, start the search."""
        if self._optimize_runner is not None and self._optimize_runner.busy():
            messagebox.showinfo("智能优化", "已有优化任务在运行；可先停止或等待完成。",
                                parent=self)
            return

        template, constraints, context = self._optimize_prepare()
        if template is None:
            return

        # The initial pool is the lineup's own six cards, and NOTHING is pinned.
        #
        # Defaulting to "all six pinned" was a design mistake: pinning every slot
        # leaves C(pool-6, 0) = 1 combination, so the pool would have no effect at
        # all and widening it would appear to do nothing. Leaving the pool
        # unpinned makes C(pool, 6) the real search space, which is what the user
        # is being asked to bound.
        dialog = OptimizeDialog(self, self.app, mode_label=self._optimize_mode_label(),
                                template=template,
                                pinned=(),
                                pool=template["memory_ids"])
        self.wait_window(dialog)
        if not dialog.result:
            return

        self._optimize_start(dialog.result, template, constraints, context)

    # --------------------------------------------------------------- assembly
    def _optimize_prepare(self):
        """Collect the current lineup, constraints and mode context.

        Returns ``(template, constraints, context)`` with ``template`` None when
        the lineup cannot be optimized (an incomplete formation).
        """
        selection = self._get_selection()
        if not selection.get("friends"):
            messagebox.showwarning("编队不完整", "请先选好己方阵容再优化", parent=self)
            return None, None, None

        global_vals = self.app.global_tab.get_values()
        panel = self.app._build_panel_config_from_gui(global_vals)

        enemy_id = selection.get("enemy_id")
        context = {}
        if self._OPTIMIZE_MODE == "circle":
            stage_data = self.app.data_loader.get_circle_battle_stage(
                selection.get("season"), selection.get("stage"))
            if not stage_data:
                messagebox.showwarning("阶段错误", "无法加载当前对抗压制战阶段数据",
                                       parent=self)
                return None, None, None
            context = dict(season=selection.get("season"), stage=selection.get("stage"),
                           stage_data=stage_data,
                           enemy_state_overrides=selection.get("enemy_state_overrides"))
        else:
            if not enemy_id:
                messagebox.showwarning("未选择敌方", "请先选择战术演习 Boss", parent=self)
                return None, None, None

        try:
            # The ported optimizer's own snapshot builder, so the state it receives
            # is exactly the shape its model validates and prepares. A circle stage
            # has no tactical boss, so its enemy check is skipped -- the circle
            # evaluator builds the enemy side from the stage lineup instead.
            template = model_mod.snapshot(selection, panel)
            circle = self._OPTIMIZE_MODE == "circle"
            model_mod.validate_snapshot(template, self.app.data_loader, affixes=False,
                                        check_enemy=not circle)
        except ValueError as exc:
            messagebox.showwarning("阵容无效", str(exc), parent=self)
            return None, None, None

        # Start from the optimizer's own default constraints (the equipped memories
        # required, everything else excluded), then let the dialog widen the pool.
        # The characters axis is always present: validate_constraints requires all
        # five lineup members be listed or the axis cannot be filled.
        constraints = model_mod.default_constraints(template)
        return template, constraints, context

    def _optimize_pinned_memories(self):
        """The memories currently equipped, offered as the initial pin set."""
        selection = self._get_selection()
        pinned = []
        for entry in selection.get("mems_friend", []):
            try:
                pinned.append(int(str(entry).split("]")[0].lstrip("[")))
            except (ValueError, AttributeError):
                continue
        return pinned

    def _optimize_mode_label(self):
        return "对抗压制战" if self._OPTIMIZE_MODE == "circle" else "战术演习"

    # ------------------------------------------------------------------- run
    def _optimize_start(self, choice, template, constraints, context):
        """Start the search from the dialog's chosen pool and pins.

        The constraints come straight from the dialog's pin/pool sets. The pool is
        NOT widened here: the whole point of asking for it is to search a bounded
        set, and silently expanding it back to the full catalogue would restore
        the unsearchable 24-billion-candidate space the user just narrowed.
        """
        settings = choice["settings"]
        pinned = sorted(choice.get("pinned") or ())
        pool = sorted(choice.get("pool") or ()) or pinned

        constraints = {
            "characters": dict(template and model_mod.default_constraints(template).get("characters", {})),
            "memories": {**{str(m): "必选" for m in pinned},
                         **{str(m): "候选" for m in pool if m not in set(pinned)}}}

        if settings.change_memories:
            need = 6 - len(pinned)
            available = [m for m in pool if m not in set(pinned)]
            if len(available) < need:
                messagebox.showwarning(
                    "候选卡池不足",
                    f"必选 {len(pinned)} 张，还需 {need} 张，"
                    f"但卡池只有 {len(available)} 张可选。请扩大候选卡池。",
                    parent=self)
                return

        # Memory pruning stays ON for circle as well: the evaluator supplies the
        # boss-position enemy as the reference unit, so pruning judges against the
        # unit this lineup actually fights rather than a tactical boss it never sees.

        from dataclasses import asdict
        request = {
            "base_path": self._optimize_base_path(),
            "user_data_dir": self._optimize_user_dir(),
            "state": template,
            "constraints": constraints,
            # The ported worker takes the settings as a plain mapping.
            "settings": asdict(settings),
            "output": None,
            # Circle-battle needs its own controller and stage lineup; the worker
            # builds the matching evaluator from these.
            "mode": self._OPTIMIZE_MODE,
            "circle": context or None,
        }

        self._optimize_set_controls(False)
        runner = OptimizerRunner(self.app, self,
                                 on_finish=self._optimize_finished,
                                 on_error=self._optimize_failed)
        self._optimize_runner = runner
        try:
            runner.start(request)
        except Exception as exc:
            self._optimize_runner = None
            self._optimize_set_controls(True)
            messagebox.showerror("启动失败", f"{type(exc).__name__}: {exc}", parent=self)
            return
        panel = getattr(self, "_result_panel", None)
        if panel is not None:
            panel.clear()
            panel.set_summary("智能优化启动中…\n")
        self._optimize_show_stop(True)

    def _optimize_all_memories(self):
        """Every memory the loader knows, for the pool picker's catalogue.

        This is the *browsing* set, not the search space: the dialog offers the
        whole catalogue to choose from but searches only what the user picks.
        """
        try:
            memories = self.app.data_loader.load_memories()
        except Exception:
            return []
        return sorted(int(mid) for mid in memories)

    def _optimize_base_path(self):
        """Repository root, taken from the same constant the app loads data with."""
        from gui.constants import _BASE_PATH
        return str(_BASE_PATH)

    def _optimize_user_dir(self):
        """User data directory, so the worker resolves the same account."""
        from gui.constants import _USER_DATA
        return str(_USER_DATA)

    # ------------------------------------------------------------- callbacks
    def _optimize_show_action_row(self, show):
        """Show or hide the second row that carries the run controls.

        The stop and apply buttons live on their OWN row under the tab's button
        row. Putting them on the same row pushed 应用最优站位 past the window's
        right edge once the tab's existing buttons were laid out, so it could not
        be reached; a second row cannot be squeezed out that way because the row
        is gridded with no fixed column budget.
        """
        row = getattr(self, "_optimize_action_row", None)
        if row is None:
            return
        if show:
            # Below the row the optimize button sits on, spanning the same frame.
            parent = self._optimize_btn.master
            row.grid(row=1, column=0, columnspan=12, sticky="w", padx=5, pady=(0, 5))
        else:
            row.grid_remove()

    def _optimize_show_stop(self, visible):
        """Show or hide the stop button on the action row."""
        row = getattr(self, "_optimize_action_row", None)
        if row is None:
            return
        if visible:
            if self._optimize_stop_btn is None:
                self._optimize_stop_btn = ttk.Button(
                    row, text="■ 停止优化", command=self._optimize_stop,
                    width=14)
                self._optimize_stop_btn.pack(side=tk.LEFT, padx=(0, 6))
            self._optimize_show_action_row(True)
        else:
            if self._optimize_stop_btn is not None:
                self._optimize_stop_btn.destroy()
                self._optimize_stop_btn = None
            if self._optimize_apply_btn is None:
                self._optimize_show_action_row(False)

    def _optimize_stop(self):
        if self._optimize_runner is not None:
            self._optimize_runner.stop()
            panel = getattr(self, "_result_panel", None)
            if panel is not None:
                panel.append_summary("正在停止；会等待当前一场战斗结束后保留结果…\n")

    def _optimize_set_controls(self, enabled):
        """Disable the tab's own battle buttons while optimizing."""
        state = "normal" if enabled else "disabled"
        for name in ("_start_btn", "_log_btn", "_optimize_btn"):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except tk.TclError:
                    pass
        if enabled:
            self._optimize_show_stop(False)

    def _optimize_finished(self, result):
        self._optimize_set_controls(True)
        if result is None:
            return
        # Draw the thumbnails first so the visual answer is visible without
        # scrolling the report.
        if self._optimize_preview is not None:
            try:
                self._optimize_preview.render(result, self.app.data_loader)
            except Exception:
                pass
        if result.get("best"):
            self._optimize_last_result = result
            row = getattr(self, "_optimize_action_row", None)
            if row is not None and self._optimize_apply_btn is None:
                self._optimize_apply_btn = ttk.Button(
                    row, text="✔ 应用最优站位",
                    command=self.apply_optimizer_result, width=16)
                self._optimize_apply_btn.pack(side=tk.LEFT)
            self._optimize_show_action_row(True)

    def _optimize_failed(self, message):
        self._optimize_set_controls(True)

    # ----------------------------------------------------------------- apply
    def apply_optimizer_result(self):
        """Write the winning lineup back into this tab. Always asks first."""
        result = getattr(self, "_optimize_last_result", None)
        if not result or not result.get("best"):
            messagebox.showinfo("应用最优结果", "尚无可应用的优化结果", parent=self)
            return
        best = result["best"]
        if not messagebox.askyesno(
                "应用最优结果",
                "将优化得到的最优站位与回忆应用到当前页面。\n"
                "这会替换当前页面的编队显示（不影响角色参数）。是否继续？",
                parent=self):
            return
        try:
            self._optimize_apply(best)
        except Exception as exc:
            messagebox.showerror("应用失败", f"{type(exc).__name__}: {exc}", parent=self)
            self._optimize_last_result = None

    def _optimize_apply(self, state):
        """Push a snapshot's positions and memories into the tab's slots.

        Both mode tabs inherit identical slot helpers from ``BattleTabMixin``
        (``_set_slot_char`` / ``_clear_slot`` / ``_set_mem_slot`` /
        ``_clear_mem_slot``), so one implementation covers the tactical and
        circle pages. Only the lineup display changes here; character parameters
        are never touched.
        """
        positions = list(state.get("friend_positions") or [])
        char_slots = self._get_char_slots()
        for index, slot in enumerate(char_slots):
            cid = positions[index] if index < len(positions) else None
            if cid is None:
                self._clear_slot(slot)
            else:
                self._set_slot_char(slot, cid)

        memories = list(state.get("memory_ids") or [])
        for index in range(len(self._get_mem_slots())):
            if index < len(memories):
                self._set_mem_slot(index, memories[index])
            else:
                self._clear_mem_slot(index)

        self._after_slot_changed()
        panel = getattr(self, "_result_panel", None)
        if panel is not None:
            panel.append_summary("\n✔ 已应用最优站位与回忆到当前页面。\n")
