# -*- coding: utf-8 -*-
"""对抗压制战 Tab（多敌方阵容，阶段1~100，回合耗尽未全灭判败）。

从 gui_app.py 抽取，槽位/拖拽/回忆卡等公共方法复用 BattleTabMixin。
"""

import json
import os
import random
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import ttk, messagebox

from src.data.stat_calculator import StatCalculator
from src.entities_v2.battlefield_state import BattlefieldState
from src.entities_v2.enums import Side, Position
from src.entities_v2.unit_state import UnitState
from src.combat_v2.battle_flow_controller import BattleConfig
from src.combat_v2.battle_narrative import BattleNarrativeWriter

from gui.constants import (
    _BASE_PATH,
    _DARK_ACCENT,
    _DARK_FG,
    _DARK_INPUT_BG,
    CIRCLE_PRESET_DIR,
    ENEMY_IMAGE_DIR,
    ENEMY_SLOT_POSITION_MAP,
    GRID_ALLY_POSITIONS,
)
from gui.widgets.result_table import ResultTablePanel
from gui.widgets.rdps import (
    _build_rdps_summary,
    _build_rdps_tables,
    _export_rdps_tracking_log,
)
from gui.dialogs.enemy_detail import EnemyDetailDialog

from gui.tabs.base import BattleTabMixin


class CircleBattleTab(BattleTabMixin, ttk.Frame):
    """对抗压制战模式 - 多敌方阵容，阶段1~100，回合耗尽未全灭判败"""

    # 当前支持的赛季（初期仅第5赛季）
    SUPPORTED_SEASONS = [5]

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._circle_data: Dict[str, Dict] = self.app.data_loader.get_circle_battle_enemies()
        self.friend_slots: List[Dict[str, Any]] = []
        self.mem_friend_slots: List[Dict[str, Any]] = []
        self._drag_source = None
        self._drag_preview = None
        self._rdps_tracking_log: List[str] = []
        self._build()

    # ── UI 构建 ──

    def _build(self):
        s = self.app._get_scheme()
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=4)

        canvas = tk.Canvas(left_frame, bg=s["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _bind_canvas_width(event):
            canvas.itemconfig(1, width=event.width)

        canvas.bind("<Configure>", _bind_canvas_width)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _bind_canvas(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_canvas(event):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_canvas)
        canvas.bind("<Leave>", _unbind_canvas)

        f = scroll_frame

        # ── 赛季/阶段选择 ──
        ttk.Label(f, text="=== 对抗压制战 ===", font=("Microsoft YaHei UI", 11, "bold")).pack(
            pady=(10, 5), padx=10, anchor="w")

        config_frame = ttk.LabelFrame(f, text="赛季/阶段选择")
        config_frame.pack(pady=5, fill="x", padx=10)

        row1 = ttk.Frame(config_frame)
        row1.pack(padx=5, pady=5, fill="x")

        ttk.Label(row1, text="赛季:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._var_season = tk.StringVar(value="6")
        self._season_spinbox = ttk.Spinbox(
            row1, from_=1, to=99, textvariable=self._var_season, width=6,
            command=self._on_season_change,
        )
        self._season_spinbox.pack(side=tk.LEFT, padx=(0, 15))
        self._season_spinbox.bind("<Return>", lambda e: self._on_season_change())

        ttk.Label(row1, text="阶段:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._var_stage = tk.IntVar(value=100)
        self._stage_spinbox = ttk.Spinbox(
            row1, from_=1, to=100, textvariable=self._var_stage, width=6,
            command=self._on_stage_change,
        )
        self._stage_spinbox.pack(side=tk.LEFT, padx=(0, 15))
        self._stage_spinbox.bind("<Return>", lambda e: self._on_stage_change())

        ttk.Label(row1, text="弱点属性:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._weakness_label = ttk.Label(row1, text="--", font=("Microsoft YaHei UI", 9, "bold"))
        self._weakness_label.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row1, text="最大回合:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._max_turn_label = ttk.Label(row1, text="--", font=("Microsoft YaHei UI", 9, "bold"))
        self._max_turn_label.pack(side=tk.LEFT)

        # ── 敌方阵容预览（2x3网格，参考己方编队布局） ──
        enemy_frame = ttk.LabelFrame(f, text="敌方阵容（点击头像查看详情）")
        enemy_frame.pack(pady=5, fill="x", padx=10)

        self._enemy_grid_frame = tk.Frame(enemy_frame, bg=s["bg"])
        self._enemy_grid_frame.pack(fill="x", padx=5, pady=5)
        self._enemy_slots: List[Optional[Dict[str, Any]]] = [None] * 6
        self._enemy_grid_widgets: List[Dict[str, Any]] = []
        self._enemy_hp_vars: List[tk.StringVar] = [tk.StringVar(value="") for _ in range(6)]
        self._enemy_dead_vars: List[tk.BooleanVar] = [tk.BooleanVar(value=False) for _ in range(6)]

        enemy_slot_labels = ["左前(1)", "中前(2)", "右前(3)", "左后(4)", "中后(5)", "右后(6)"]
        for i, label in enumerate(enemy_slot_labels):
            frame = tk.Frame(self._enemy_grid_frame, bg=s["bg"],
                              highlightbackground=s["border"], highlightthickness=1)
            r = 0 if i >= 3 else 1
            c = i % 3
            frame.grid(row=r, column=c, padx=3, pady=3)
            frame.grid_propagate(False)
            frame.configure(width=164, height=180)
            pos_label = ttk.Label(frame, text=label, font=("Microsoft YaHei UI", 8))
            pos_label.grid(row=0, column=0, sticky="w", padx=(3, 0))

            slot = self._build_enemy_slot(frame, i)
            slot["frame"].grid(row=1, column=0, padx=5, pady=(2, 2))
            slot["outer_frame"] = frame
            self._enemy_grid_widgets.append(slot)

        # ── 批量操作按钮 ──
        batch_btn_frame = ttk.Frame(enemy_frame)
        batch_btn_frame.pack(fill="x", padx=5, pady=(2, 5))
        ttk.Button(batch_btn_frame, text="小怪全死", width=10,
                   command=self._set_small_enemies_dead).pack(side=tk.LEFT, padx=2)
        ttk.Button(batch_btn_frame, text="全部满血复活", width=12,
                   command=self._reset_all_enemy_states).pack(side=tk.LEFT, padx=2)

        # ── 己方编队 + 己方回忆卡（同行） ──
        ally_main = tk.Frame(f, bg=s["bg"])
        ally_main.pack(pady=(5, 0), fill="x", padx=10)
        self._ally_main = ally_main

        ttk.Label(ally_main, text="=== 己方编队 ===", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(5, 5))

        ally_form_frame = tk.Frame(ally_main, bg=s["bg"])
        ally_form_frame.grid(row=1, column=0, columnspan=3, sticky="nw")
        self._ally_form_frame = ally_form_frame

        friend_labels = ["左前(1)", "中前(2)", "右前(3)", "左后(4)", "中后(5)", "右后(6)"]
        for i, label in enumerate(friend_labels):
            frame = tk.Frame(ally_form_frame, bg=s["bg"], highlightbackground=s["border"], highlightthickness=1)
            r = 1 if i >= 3 else 0
            c = i % 3
            frame.grid(row=r, column=c, padx=3, pady=3)
            frame.grid_propagate(False)
            frame.configure(width=164, height=140)
            pos_label = ttk.Label(frame, text=label, font=("Microsoft YaHei UI", 8))
            pos_label.grid(row=0, column=0, sticky="w", padx=(3, 0))
            clear_btn = tk.Label(frame, text="\u00d7", fg=s["border"], bg=s["bg"],
                                  font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2")
            clear_btn.grid(row=0, column=1, sticky="e", padx=(0, 3))
            clear_btn.bind("<Button-1>", lambda e, idx=i: self._clear_slot_by_idx(idx))
            clear_btn.grid_remove()
            slot = self._build_slot(frame, i)
            slot["frame"].grid(row=1, column=0, columnspan=2, padx=5, pady=(2, 2))
            slot["clear_btn"] = clear_btn
            slot["outer_frame"] = frame
            self.friend_slots.append(slot)

        ttk.Label(ally_main, text="=== 己方回忆卡 ===", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=0, column=3, sticky="w", pady=(5, 5), padx=(15, 0))

        ally_mem_frame = tk.Frame(ally_main, bg=s["bg"])
        ally_mem_frame.grid(row=1, column=3, sticky="n", padx=(15, 0))
        self._ally_mem_frame = ally_mem_frame
        for i in range(6):
            r, c = divmod(i, 2)
            slot = self._build_mem_slot(ally_mem_frame, i)
            slot["frame"].grid(row=r, column=c, padx=2, pady=2)
            self.mem_friend_slots.append(slot)

        # ── 配置预设管理 ──
        preset_frame = ttk.LabelFrame(f, text="配置预设（保存/加载当前阵容+阶段+回忆卡）")
        preset_frame.pack(pady=5, fill="x", padx=10)

        self._circle_preset_listbox = tk.Listbox(preset_frame, height=4,
                                                  bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                                  selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                                  borderwidth=0, highlightthickness=0,
                                                  font=("Microsoft YaHei UI", 9))
        self._circle_preset_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        preset_btn_frame = ttk.Frame(preset_frame)
        preset_btn_frame.pack(side=tk.RIGHT, padx=5, pady=5)
        ttk.Button(preset_btn_frame, text="保存", command=self._save_circle_preset).pack(fill="x", pady=2)
        ttk.Button(preset_btn_frame, text="加载", command=self._load_circle_preset).pack(fill="x", pady=2)
        ttk.Button(preset_btn_frame, text="删除", command=self._delete_circle_preset).pack(fill="x", pady=2)
        self._circle_preset_name_var = tk.StringVar(value="配置1")
        ttk.Entry(preset_btn_frame, textvariable=self._circle_preset_name_var, width=14).pack(fill="x", pady=2)

        self._refresh_circle_presets()

        # ── 战斗设置 ──
        battle_frame = ttk.LabelFrame(f, text="")
        battle_frame.pack(pady=(2, 5), fill="x", padx=10)

        ttk.Label(battle_frame, text="模拟次数:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self._var_sim_count = tk.IntVar(value=100)
        ttk.Spinbox(battle_frame, from_=1, to=99999, textvariable=self._var_sim_count, width=8).grid(
            row=0, column=1, padx=5, sticky="w")

        self._start_btn = ttk.Button(battle_frame, text="▶ 开始批量模拟", command=self._start_battle, width=18)
        self._start_btn.grid(row=0, column=2, padx=5, pady=5)
        self._log_btn = ttk.Button(battle_frame, text="📋 单次战斗+日志", command=self._start_single_battle_with_log, width=18)
        self._log_btn.grid(row=0, column=3, padx=5, pady=5)
        self._progress_var = tk.StringVar(value="")
        ttk.Label(battle_frame, textvariable=self._progress_var).grid(row=0, column=4, padx=5)
        self._rdps_log_btn = ttk.Button(battle_frame, text="📤 导出RDPS日志",
                                        command=lambda: _export_rdps_tracking_log(self, self._rdps_tracking_log),
                                        width=16)
        self._rdps_log_btn.grid(row=0, column=5, padx=5, pady=5)

        # ── 特殊值日志导出按钮 ──
        export_frame = ttk.LabelFrame(f, text="特殊值日志导出（批量模拟后可用，以我方伤害为标准）")
        export_frame.pack(pady=5, fill="x", padx=10)
        btn_row = ttk.Frame(export_frame)
        btn_row.pack(pady=5)
        self._export_max_btn = ttk.Button(btn_row, text="导出最高伤害日志", command=self._export_max_log, width=18)
        self._export_max_btn.pack(side=tk.LEFT, padx=3)
        self._export_min_btn = ttk.Button(btn_row, text="导出最低伤害日志", command=self._export_min_log, width=18)
        self._export_min_btn.pack(side=tk.LEFT, padx=3)
        self._export_q1_btn = ttk.Button(btn_row, text="导出Q1伤害日志", command=self._export_q1_log, width=18)
        self._export_q1_btn.pack(side=tk.LEFT, padx=3)
        self._export_q3_btn = ttk.Button(btn_row, text="导出Q3伤害日志", command=self._export_q3_log, width=18)
        self._export_q3_btn.pack(side=tk.LEFT, padx=3)

        # ── 结果输出 ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self._result_panel = ResultTablePanel(right_frame, self.app, title="战斗结果")
        self._result_panel.pack(fill=tk.BOTH, expand=True)

        # 初始化敌方预览
        self._on_stage_change()

    # ── 赛季/阶段切换 ──

    def _on_season_change(self, event=None):
        self._on_stage_change()

    def _on_stage_change(self, event=None):
        """阶段变更时刷新敌方阵容预览"""
        season = int(self._var_season.get())
        stage = self._var_stage.get()

        stage_data = self.app.data_loader.get_circle_battle_stage(season, stage)
        if not stage_data:
            self._weakness_label.config(text="--")
            self._max_turn_label.config(text="--")
            self._clear_enemy_preview()
            return

        attr_names = {1: "火", 2: "水", 3: "风", 4: "土", 5: "光", 6: "暗"}
        weakness = stage_data.get("weakness_attribute")
        self._weakness_label.config(text=attr_names.get(weakness, "?"))
        self._max_turn_label.config(text=str(stage_data.get("max_turn", 5)))

        self._refresh_enemy_preview(stage_data)

    def _clear_enemy_preview(self):
        """清空所有敌方槽位"""
        self._enemy_slots = [None] * 6
        for widget in self._enemy_grid_widgets:
            self._update_enemy_slot_display(widget, None)

    def _refresh_enemy_preview(self, stage_data: Dict):
        """刷新敌方阵容预览（2x3网格），重置HP/死亡状态"""
        enemies = stage_data.get("enemies", [])

        # 先清空所有槽位
        self._enemy_slots = [None] * 6

        # 重置HP/死亡状态（阶段切换时清空用户覆盖）
        for i in range(6):
            self._enemy_hp_vars[i].set("")
            self._enemy_dead_vars[i].set(False)

        # 按slot填充敌方数据
        for enemy in enemies:
            slot_idx = enemy.get("slot", 1) - 1  # slot 1-6 → index 0-5
            if 0 <= slot_idx < 6:
                self._enemy_slots[slot_idx] = enemy

        # 更新所有槽位显示
        for i, widget in enumerate(self._enemy_grid_widgets):
            enemy_data = self._enemy_slots[i]
            self._update_enemy_slot_display(widget, enemy_data)

    def _on_dead_toggle(self, slot_idx):
        """死亡复选框切换时启用/禁用HP输入框"""
        widget = self._enemy_grid_widgets[slot_idx]
        hp_entry = widget.get("hp_entry")
        if not hp_entry:
            return
        is_dead = self._enemy_dead_vars[slot_idx].get()
        hp_entry.config(state="disabled" if is_dead else "normal")

    def _set_small_enemies_dead(self):
        """批量设置：除HP最高的单位（BOSS）外，所有敌方小怪初始死亡"""
        # 找出当前所有已加载敌人的HP，定位最高HP的槽位作为BOSS
        loaded_slots = []
        max_hp = -1
        boss_slot_idx = -1
        for i, enemy_data in enumerate(self._enemy_slots):
            if enemy_data is not None:
                hp = enemy_data.get("hp", 0)
                loaded_slots.append(i)
                if hp > max_hp:
                    max_hp = hp
                    boss_slot_idx = i

        if not loaded_slots:
            messagebox.showinfo("提示", "当前无可操作的敌方单位")
            return

        for i in loaded_slots:
            if i == boss_slot_idx:
                # BOSS保持存活满血
                self._enemy_dead_vars[i].set(False)
                enemy = self._enemy_slots[i]
                if enemy:
                    self._enemy_hp_vars[i].set(str(enemy.get("hp", 0)))
            else:
                # 小怪标记死亡
                self._enemy_dead_vars[i].set(True)
            # 更新HP输入框状态
            self._on_dead_toggle(i)

    def _reset_all_enemy_states(self):
        """批量重置：所有敌方单位满血存活"""
        for i, enemy_data in enumerate(self._enemy_slots):
            self._enemy_dead_vars[i].set(False)
            if enemy_data is not None:
                self._enemy_hp_vars[i].set(str(enemy_data.get("hp", 0)))
            self._on_dead_toggle(i)

    def _collect_enemy_state_overrides(self) -> Dict[int, Dict[str, Any]]:
        """从GUI收集敌方初始状态覆盖"""
        overrides = {}
        for i, enemy_data in enumerate(self._enemy_slots):
            if enemy_data is None:
                continue
            slot = i + 1  # 0-indexed → 1-indexed
            is_dead = self._enemy_dead_vars[i].get()
            hp_str = self._enemy_hp_vars[i].get().strip()
            max_hp = enemy_data.get("hp", 0)

            if is_dead:
                overrides[slot] = {"dead": True}
            elif hp_str:
                try:
                    hp_val = int(hp_str)
                    if hp_val != max_hp and hp_val > 0:
                        overrides[slot] = {"current_hp": min(hp_val, max_hp)}
                    elif hp_val <= 0:
                        # HP<=0 也视为死亡
                        overrides[slot] = {"dead": True}
                except ValueError:
                    pass
        return overrides

    def _apply_enemy_state_overrides(self, overrides: Dict[int, Dict[str, Any]]):
        """从预设数据恢复敌方初始状态覆盖到GUI"""
        # 先重置所有
        for i in range(6):
            self._enemy_dead_vars[i].set(False)
            enemy_data = self._enemy_slots[i]
            if enemy_data:
                self._enemy_hp_vars[i].set(str(enemy_data.get("hp", 0)))

        # 应用预设覆盖
        for slot, override in overrides.items():
            i = slot - 1  # 1-indexed → 0-indexed
            if 0 <= i < 6:
                if override.get("dead"):
                    self._enemy_dead_vars[i].set(True)
                elif "current_hp" in override:
                    self._enemy_hp_vars[i].set(str(override["current_hp"]))
                self._on_dead_toggle(i)

    def _build_enemy_slot(self, parent, slot_idx):
        """构建单个敌方槽位（横版头像，可点击查看详情，含HP覆盖和死亡开关）"""
        BANNER_W, BANNER_H = 154, 76
        s = self.app._get_scheme()

        slot_frame = tk.Frame(parent, bg=s["bg"])

        avatar_canvas = tk.Canvas(slot_frame, width=BANNER_W, height=BANNER_H,
                                   bg=s["bg"], highlightthickness=0,
                                   cursor="hand2")
        avatar_canvas.pack()
        avatar_canvas._banner_photo = None

        name_label = tk.Label(slot_frame, text="", bg=s["bg"], fg=s["fg"],
                               font=("Microsoft YaHei UI", 8), wraplength=BANNER_W,
                               justify="center", height=2)
        name_label.pack(pady=(1, 0))

        # ── HP覆盖 + 死亡开关 ──
        state_frame = tk.Frame(slot_frame, bg=s["bg"])
        state_frame.pack(pady=(1, 0))

        ttk.Label(state_frame, text="HP:", font=("Microsoft YaHei UI", 7)).pack(side=tk.LEFT)
        hp_entry = ttk.Entry(state_frame, textvariable=self._enemy_hp_vars[slot_idx],
                             width=7, font=("Microsoft YaHei UI", 7))
        hp_entry.pack(side=tk.LEFT, padx=(1, 3))

        dead_check = ttk.Checkbutton(state_frame, text="死亡", variable=self._enemy_dead_vars[slot_idx],
                                     command=lambda idx=slot_idx: self._on_dead_toggle(idx))
        dead_check.pack(side=tk.LEFT)

        # 点击头像/名称打开详情弹窗
        for widget in [slot_frame, avatar_canvas, name_label]:
            widget.bind("<Button-1>", lambda e, idx=slot_idx: self._open_enemy_detail(idx))

        return {"frame": slot_frame, "avatar_label": avatar_canvas,
                "name_label": name_label, "slot_idx": slot_idx,
                "hp_entry": hp_entry, "dead_check": dead_check,
                "state_frame": state_frame}

    def _update_enemy_slot_display(self, widget, enemy_data):
        """更新敌方槽位显示"""
        canvas = widget["avatar_label"]
        name_label = widget["name_label"]
        hp_entry = widget.get("hp_entry")
        dead_check = widget.get("dead_check")
        state_frame = widget.get("state_frame")
        s = self.app._get_scheme()
        BANNER_W, BANNER_H = 154, 76
        slot_idx = widget["slot_idx"]

        # 无论是否有敌人，都同步主题色（bg/fg）
        name_label.config(bg=s["bg"], fg=s["fg"])

        canvas.delete("all")
        canvas.config(bg=s["bg"])
        canvas._banner_photo = None

        # 同步HP覆盖框架背景（tk.Frame不会随ttk主题自动更新）
        if state_frame:
            state_frame.config(bg=s["bg"])

        if enemy_data is None:
            canvas.create_text(BANNER_W // 2, BANNER_H // 2, text="空位",
                               fill=s["border"], font=("Microsoft YaHei UI", 8))
            name_label.config(text="")
            name_label.pack_forget()
            # 隐藏HP/死亡控件
            if state_frame:
                state_frame.pack_forget()
            self._enemy_hp_vars[slot_idx].set("")
            self._enemy_dead_vars[slot_idx].set(False)
        else:
            model_id = enemy_data.get("model_asset_id", "")
            photo = self._load_enemy_avatar(model_id)
            if photo:
                canvas._banner_photo = photo
                canvas.create_image(BANNER_W // 2, BANNER_H // 2, image=photo, anchor="center")
            else:
                canvas.create_text(BANNER_W // 2, BANNER_H // 2, text="无头像",
                                   fill=s["border"], font=("Microsoft YaHei UI", 8))
            name = enemy_data.get("name", "???")
            name_label.config(text=name)
            name_label.pack(pady=(1, 0))

            # 显示HP/死亡控件，默认HP为max_hp
            if state_frame:
                state_frame.pack(pady=(1, 0))
            # 仅在HP为空时设置默认值（避免覆盖用户输入）
            if not self._enemy_hp_vars[slot_idx].get():
                self._enemy_hp_vars[slot_idx].set(str(enemy_data.get("hp", 0)))
            # 根据死亡状态启用/禁用HP输入
            if hp_entry:
                hp_entry.config(state="disabled" if self._enemy_dead_vars[slot_idx].get() else "normal")

    def _load_enemy_avatar(self, model_asset_id: str):
        """加载敌方头像（按ModelAssetId命名）"""
        if not model_asset_id:
            return None
        from PIL import Image
        BANNER_W, BANNER_H = 154, 76

        avatar_path = ENEMY_IMAGE_DIR / f"{model_asset_id}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            # 原图为300x144，按比例缩放到154x76
            pil_img = pil_img.resize((BANNER_W, BANNER_H), Image.LANCZOS)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            pil_img.save(tmp_path, "PNG")
            photo = tk.PhotoImage(file=tmp_path)
            os.unlink(tmp_path)
            return photo
        except Exception:
            return None

    def _open_enemy_detail(self, slot_idx):
        """打开敌方详情弹窗"""
        if slot_idx < 0 or slot_idx >= 6:
            return
        enemy_data = self._enemy_slots[slot_idx]
        if enemy_data is None:
            return
        dialog = EnemyDetailDialog(self, self.app, enemy_data, title="敌方详情")
        self.wait_window(dialog)

    def _get_selection(self) -> Dict[str, Any]:
        """获取当前选择"""
        friends = []
        friend_positions = []
        for slot in self.friend_slots:
            cid = slot["cid"]
            friend_positions.append(cid)
            if cid:
                friends.append(cid)

        mem_friend_positions = []
        for slot in self.mem_friend_slots:
            mid = slot["mid"]
            if mid is not None:
                mem = self.app.data_loader.get_memory(mid)
                mem_friend_positions.append(f"[{mid}] {mem.name}" if mem else f"[{mid}]")
            else:
                mem_friend_positions.append("")

        return {
            "friends": friends,
            "friend_positions": friend_positions,
            "mems_friend": [e for e in mem_friend_positions if e],
            "mem_friend_positions": mem_friend_positions,
            "season": int(self._var_season.get()),
            "stage": self._var_stage.get(),
            "enemy_state_overrides": self._collect_enemy_state_overrides(),
        }

    # ── 敌方单位创建 ──

    def _create_circle_battle_enemy(self, enemy_data: Dict) -> UnitState:
        """创建对抗压制战敌方单位"""
        pos = enemy_data.get("position", 1)
        enemy_pos = ENEMY_SLOT_POSITION_MAP.get(pos, Position.ENEMY_LEFT_FRONT)

        skill_ids = enemy_data.get("skill_ids", [])
        # 使用 EnemySkillMaster.Level (导入时已提取), 回退到 15 (兼容旧数据)
        raw_skill_levels = enemy_data.get("skill_levels", {})
        if raw_skill_levels:
            # JSON 的 key 是 str, 需转为 int
            skill_levels = {int(k): v for k, v in raw_skill_levels.items()}
        else:
            skill_levels = {sid: 15 for sid in skill_ids}

        max_ep = 0
        for sid in skill_ids:
            sk = self.app.data_loader.get_skill_by_id(sid)
            if sk and sk.skill_type == 3:
                max_ep = max(max_ep, sk.resource_cost)

        unit_id = f"E_{enemy_data['enemy_id']}_{enemy_data['slot']}"

        return UnitState(
            unit_id=unit_id,
            name=enemy_data["name"],
            side=Side.ENEMY,
            position=enemy_pos,
            character_id=enemy_data["enemy_id"],
            level=enemy_data["level"],
            element=enemy_data["attribute"],
            character_type=enemy_data["type"],
            max_hp=enemy_data["hp"],
            current_hp=enemy_data["hp"],
            attack=enemy_data["attack"],
            defense=enemy_data["defense"],
            speed=enemy_data["speed"],
            crit_rate=enemy_data["critical_rate"],
            crit_damage=0.0,
            advantage_damage=0.0,
            initial_active_point=enemy_data.get("action_point", 2),
            initial_passive_point=enemy_data.get("passive_point", 2),
            max_extra_point=max_ep,
            current_ap=enemy_data.get("action_point", 2),
            current_pp=enemy_data.get("passive_point", 2),
            current_ep=0,
            skills=skill_ids,
            skill_levels=skill_levels,
            skill_cooldowns={},
            role_type=enemy_data.get("role_type", 0),
            position_type=3,
        )

    # ── 战斗启动 ──

    def _start_battle(self):
        sel = self._get_selection()
        if not sel["friends"]:
            messagebox.showwarning("编队不完整", "请至少为己方选择1个角色")
            return

        season = sel["season"]
        stage = sel["stage"]
        stage_data = self.app.data_loader.get_circle_battle_stage(season, stage)
        if not stage_data:
            messagebox.showwarning("阶段错误", f"无法加载第{season}赛季阶段{stage}数据")
            return

        self._start_btn.config(state="disabled")
        self._log_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary(f"正在进行对抗压制战 第{season}赛季 阶段{stage}...\n")

        thread = threading.Thread(target=self._run_simulation, args=(sel, stage_data), daemon=True)
        thread.start()

    def _run_simulation(self, sel, stage_data):
        try:
            global_vals = self.app.global_tab.get_values()
            sim_count = self._var_sim_count.get()

            panel_config = self.app._build_panel_config_from_gui(global_vals)

            friend_positions = sel.get("friend_positions", sel.get("friends", []))
            enemies_data = stage_data["enemies"]
            max_turns = stage_data["max_turn"]

            from src.utils.batch_simulator import BatchSimulator

            sim = BatchSimulator(self.app.data_loader)

            def progress_cb(done, total):
                pct = done / total * 100 if total else 0
                self.app.root.after(0, lambda d=done, t=total, p=pct:
                                    self._progress_var.set(f"{d}/{t} ({p:.0f}%)"))

            result = sim.run_batch_circle(
                panel_config=panel_config,
                friends_chars=sel.get("friends", []),
                friend_positions=friend_positions,
                enemies_data=enemies_data,
                max_turns=max_turns,
                total_runs=sim_count,
                season=sel["season"],
                stage=sel["stage"],
                positions_ally=GRID_ALLY_POSITIONS,
                progress_callback=progress_cb,
                enable_rdps=global_vals.get("enable_rdps", True),
                memory_cards=self._build_memory_cards(sel.get("mems_friend", [])),
                enemy_state_overrides=sel.get("enemy_state_overrides"),
            )

            self.app.root.after(0, lambda: self._display_results(sim_count, result, sel, stage_data))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_results(self, sim_count, result, sel, stage_data):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        self._progress_var.set("完成!")
        self._result_panel.clear()

        wins = result.get("wins", 0)
        losses = result.get("losses", 0)
        pass_rate = result.get("pass_rate", 0)
        elapsed = result.get("elapsed", 0)
        rate = result.get("rate", 0)

        out = []
        out.append("=" * 60)
        out.append(f"  对抗压制战结果 - 第{sel['season']}赛季 阶段{sel['stage']}")
        out.append("=" * 60)
        out.append(f"  模拟场数: {sim_count}")
        out.append(f"  通过: {wins}  失败: {losses}")
        out.append(f"  关卡通过率: {pass_rate:.2%}")
        if rate > 0:
            out.append(f"  效率: {rate:.1f} 场/秒 | 耗时 {elapsed:.1f} 秒")
        out.append("=" * 60)

        # 若通过率 < 100%: 输出未击杀目标的平均每次模拟受到的伤害量
        if pass_rate < 1.0 and sim_count > 0:
            failed_enemy_damage = result.get("failed_enemy_damage_received", [])
            if failed_enemy_damage:
                avg_failed_damage = sum(failed_enemy_damage) / len(failed_enemy_damage)
                out.append("")
                out.append("─" * 60)
                out.append(f"  【未击杀目标统计】")
                out.append(f"  失败场次数: {len(failed_enemy_damage)}")
                out.append(f"  平均每次失败模拟敌方受到的伤害量: {avg_failed_damage:,.1f}")
                out.append(f"  最高: {max(failed_enemy_damage):,}")
                out.append(f"  最低: {min(failed_enemy_damage):,}")
                out.append("─" * 60)

        # 特殊值日志导出（以我方对敌方造成伤害为标准）
        score_records = result.get("score_records", [])
        if score_records:
            sorted_records = sorted(score_records, key=lambda x: x[0])
            max_rec = sorted_records[-1]
            min_rec = sorted_records[0]
            q1_rec = self._find_quantile_record(sorted_records, 0.25)
            q3_rec = self._find_quantile_record(sorted_records, 0.75)

            out.append("")
            out.append("─" * 60)
            out.append(f"  【特殊值日志导出（我方伤害标准）】")
            if max_rec:
                out.append(f"    最高伤害: {max_rec[0]:,} (第{max_rec[1]+1}场)")
            if min_rec:
                out.append(f"    最低伤害: {min_rec[0]:,} (第{min_rec[1]+1}场)")
            if q1_rec:
                out.append(f"    Q1伤害: {q1_rec[0]:,} (第{q1_rec[1]+1}场)")
            if q3_rec:
                out.append(f"    Q3伤害: {q3_rec[0]:,} (第{q3_rec[1]+1}场)")
            out.append(f"    （点击下方按钮导出对应战斗日志）")
            out.append("─" * 60)

            # 存储导出所需的上下文
            self._score_stats_cache = {
                "max_record": max_rec,
                "min_record": min_rec,
                "q1_record": q1_rec,
                "q3_record": q3_rec,
                "sel": sel,
                "stage_data": stage_data,
            }

        rdps_avg = result.get("rdps_avg")
        if rdps_avg:
            out.append(_build_rdps_summary(rdps_avg))

        self._result_panel.set_summary("\n".join(out))

        # 单位统计（取所有场次的平均值）→ 表格化
        all_unit_stats = result.get("all_unit_stats", [])
        tables = []
        if all_unit_stats:
            # 聚合每个单位的统计
            ally_agg = {}
            enemy_agg = {}
            for unit_stats in all_unit_stats:
                for uid, stats in unit_stats.items():
                    target = ally_agg if stats.get("side") == "ally" else enemy_agg
                    if uid not in target:
                        target[uid] = {
                            "name": stats.get("name", uid),
                            "damage_dealt": 0,
                            "damage_received": 0,
                            "hp_healed": 0,
                            "hp_received": 0,
                            "survivals": 0,
                            "deaths": 0,
                            "count": 0,
                        }
                    target[uid]["damage_dealt"] += stats.get("damage_dealt", 0)
                    target[uid]["damage_received"] += stats.get("damage_received", 0)
                    target[uid]["hp_healed"] += stats.get("hp_healed", 0)
                    target[uid]["hp_received"] += stats.get("hp_received", 0)
                    if stats.get("alive"):
                        target[uid]["survivals"] += 1
                    else:
                        target[uid]["deaths"] += 1
                    target[uid]["count"] += 1

            n = len(all_unit_stats)

            cols = ["角色", "造成伤害", "受到伤害", "提供回复", "存活率"]
            widths = [135, 110, 110, 110, 70]
            aligns = ["w", "e", "e", "e", "center"]

            if ally_agg:
                rows = []
                for uid, s in ally_agg.items():
                    surv = s["survivals"]
                    death = s["deaths"]
                    sr = surv / (surv + death) * 100 if (surv + death) else 0
                    rows.append([
                        s["name"],
                        f"{s['damage_dealt'] / n:,.1f}",
                        f"{s['damage_received'] / n:,.1f}",
                        f"{s['hp_healed'] / n:,.1f}",
                        f"{sr:.1f}%",
                    ])
                tables.append({"title": "我方角色明细(场均)", "columns": cols,
                               "rows": rows, "col_widths": widths, "col_aligns": aligns})

            if enemy_agg:
                rows = []
                for uid, s in enemy_agg.items():
                    surv = s["survivals"]
                    death = s["deaths"]
                    sr = surv / (surv + death) * 100 if (surv + death) else 0
                    rows.append([
                        s["name"],
                        f"{s['damage_dealt'] / n:,.1f}",
                        f"{s['damage_received'] / n:,.1f}",
                        f"{s['hp_healed'] / n:,.1f}",
                        f"{sr:.1f}%",
                    ])
                tables.append({"title": "敌方角色明细(场均)", "columns": cols,
                               "rows": rows, "col_widths": widths, "col_aligns": aligns})

            # 合计（场均）
            ally_dmg = sum(s["damage_dealt"] for s in ally_agg.values()) / n
            ally_recv = sum(s["damage_received"] for s in ally_agg.values()) / n
            ally_heal = sum(s["hp_healed"] for s in ally_agg.values()) / n
            enemy_dmg = sum(s["damage_dealt"] for s in enemy_agg.values()) / n
            enemy_recv = sum(s["damage_received"] for s in enemy_agg.values()) / n
            enemy_heal = sum(s["hp_healed"] for s in enemy_agg.values()) / n
            sum_cols = ["阵营", "造成伤害", "受到伤害", "提供回复"]
            sum_widths = [135, 110, 110, 110]
            sum_aligns = ["w", "e", "e", "e"]
            sum_rows = [
                ["我方", f"{ally_dmg:,.1f}", f"{ally_recv:,.1f}", f"{ally_heal:,.1f}"],
                ["敌方", f"{enemy_dmg:,.1f}", f"{enemy_recv:,.1f}", f"{enemy_heal:,.1f}"],
            ]
            tables.append({"title": "合计(场均)", "columns": sum_cols,
                           "rows": sum_rows, "col_widths": sum_widths, "col_aligns": sum_aligns})

        if rdps_avg:
            tables.extend(_build_rdps_tables(rdps_avg))

        if tables:
            self._result_panel.set_tables(tables)

    def _display_error(self, msg):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        self._progress_var.set("错误!")
        self._result_panel.append_summary(f"\n❌ 战斗出错:\n{msg}\n")

    # ── 单次战斗+日志 ──

    def _start_single_battle_with_log(self):
        sel = self._get_selection()
        if not sel["friends"]:
            messagebox.showwarning("编队不完整", "请至少为己方选择1个角色")
            return

        season = sel["season"]
        stage = sel["stage"]
        stage_data = self.app.data_loader.get_circle_battle_stage(season, stage)
        if not stage_data:
            messagebox.showwarning("阶段错误", f"无法加载第{season}赛季阶段{stage}数据")
            return

        self._start_btn.config(state="disabled")
        self._log_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary(f"正在单次战斗并生成日志 第{season}赛季 阶段{stage}...\n")

        thread = threading.Thread(target=self._run_single_with_log, args=(sel, stage_data), daemon=True)
        thread.start()

    def _run_single_with_log(self, sel, stage_data):
        try:
            global_vals = self.app.global_tab.get_values()

            panel_config = self.app._build_panel_config_from_gui(global_vals)
            player_config = panel_config.get_player_config()
            lerp_data = self.app.data_loader.load_level_lerp_data()
            stat_calculator = StatCalculator(lerp_data, data_loader=self.app.data_loader)

            narrative = BattleNarrativeWriter()

            friend_positions = sel.get("friend_positions", sel.get("friends", []))
            bf = BattlefieldState()

            for i, cid in enumerate(friend_positions):
                if cid is not None:
                    u = self.app._create_unit(panel_config, player_config, stat_calculator,
                                              cid, Side.ALLY, GRID_ALLY_POSITIONS[i])
                    if u:
                        bf.add_unit(u)

            for enemy_data in stage_data["enemies"]:
                enemy_unit = self._create_circle_battle_enemy(enemy_data)
                if enemy_unit:
                    bf.add_unit(enemy_unit)

            bf.memory_cards = self._build_memory_cards(sel.get("mems_friend", []))

            seed = int(time.time() * 1000000) % (2**31)
            random.seed(seed)

            config = BattleConfig()
            config.max_turns = stage_data["max_turn"]
            config.enable_rdps = global_vals.get("enable_rdps", True)
            config.enable_rdps_tracking = True

            from src.combat_v2.circle_battle_controller import CircleBattleController
            controller = CircleBattleController(bf, data_loader=self.app.data_loader,
                                                config=config, narrative=narrative,
                                                season=sel["season"], stage=sel["stage"],
                                                enemy_state_overrides=sel.get("enemy_state_overrides"))
            result = controller.execute_battle()

            log_dir = _BASE_PATH / "data" / "battle_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"circle_battle_s{sel['season']}_st{sel['stage']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            narrative.write(str(log_path))

            winner = result.get('winner')
            if winner == 'FRIEND':
                winner_text = "胜利"
            elif winner == 'ENEMY':
                winner_text = "失败"
            else:
                winner_text = "超时"

            turns = result["total_turns"]
            score_data = result.get("score")
            rdps_data = result.get("rdps")
            tracking_log = result.get("rdps_tracking_log") or []

            self.app.root.after(0, lambda: self._display_single_result(
                winner_text, turns, str(log_path), score_data, sel, stage_data, rdps_data, tracking_log))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_single_result(self, winner_text, turns, log_path, score_data, sel, stage_data, rdps_data=None, tracking_log=None):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        if tracking_log is not None:
            self._rdps_tracking_log = tracking_log
        self._progress_var.set("完成!")
        self._result_panel.clear()
        out = []
        out.append("=" * 60)
        out.append(f"  对抗压制战 第{sel['season']}赛季 阶段{sel['stage']}: {winner_text}")
        out.append(f"  总回合数: {turns}")
        out.append(f"  日志文件: {log_path}")
        if tracking_log:
            out.append(f"  RDPS追踪日志: {len(tracking_log)} 行（可点击\"导出RDPS日志\"按钮导出）")
        out.append("=" * 60)

        tables = []
        if score_data:
            self._append_score_display(out, score_data)
            # 构建角色明细 + 合计表格
            unit_stats = score_data.get("unit_stats", {})
            ally_units = {uid: s for uid, s in unit_stats.items() if s.get("side") == "ally"}
            enemy_units = {uid: s for uid, s in unit_stats.items() if s.get("side") == "enemy"}

            cols = ["角色", "造成伤害", "受到伤害", "提供回复", "状态"]
            widths = [135, 110, 110, 110, 50]
            aligns = ["w", "e", "e", "e", "center"]

            if ally_units:
                rows = []
                for uid, s in ally_units.items():
                    status = "存活" if s.get("alive") else "阵亡"
                    rows.append([
                        s.get("name", uid),
                        f"{s['damage_dealt']:,}",
                        f"{s['damage_received']:,}",
                        f"{s['hp_healed']:,}",
                        status,
                    ])
                tables.append({"title": "我方角色明细", "columns": cols,
                               "rows": rows, "col_widths": widths, "col_aligns": aligns})

            if enemy_units:
                rows = []
                for uid, s in enemy_units.items():
                    status = "存活" if s.get("alive") else "阵亡"
                    rows.append([
                        s.get("name", uid),
                        f"{s['damage_dealt']:,}",
                        f"{s['damage_received']:,}",
                        f"{s['hp_healed']:,}",
                        status,
                    ])
                tables.append({"title": "敌方角色明细", "columns": cols,
                               "rows": rows, "col_widths": widths, "col_aligns": aligns})

            # 合计表（从单位明细汇总）
            ally_total_dmg = sum(s.get("damage_dealt", 0) for s in ally_units.values())
            ally_total_recv = sum(s.get("damage_received", 0) for s in ally_units.values())
            ally_total_heal = sum(s.get("hp_healed", 0) for s in ally_units.values())
            enemy_total_dmg = sum(s.get("damage_dealt", 0) for s in enemy_units.values())
            enemy_total_recv = sum(s.get("damage_received", 0) for s in enemy_units.values())
            enemy_total_heal = sum(s.get("hp_healed", 0) for s in enemy_units.values())
            sum_cols = ["阵营", "造成伤害", "受到伤害", "提供回复"]
            sum_widths = [135, 110, 110, 110]
            sum_aligns = ["w", "e", "e", "e"]
            sum_rows = [
                ["我方", f"{ally_total_dmg:,}", f"{ally_total_recv:,}", f"{ally_total_heal:,}"],
                ["敌方", f"{enemy_total_dmg:,}", f"{enemy_total_recv:,}", f"{enemy_total_heal:,}"],
            ]
            tables.append({"title": "合计", "columns": sum_cols,
                           "rows": sum_rows, "col_widths": sum_widths, "col_aligns": sum_aligns})

        if rdps_data:
            out.append(_build_rdps_summary(rdps_data))
            tables.extend(_build_rdps_tables(rdps_data))

        self._result_panel.set_summary("\n".join(out))
        if tables:
            self._result_panel.set_tables(tables)

    def _append_score_display(self, out: list, score_data: dict):
        """追加计分统计摘要到输出列表（仅摘要文本，表格由调用方构建）"""
        out.append("")
        out.append("─" * 60)
        out.append(f"  【结算数据】")
        out.append(f"  我方合计:")
        out.append(f"    造成伤害: {score_data.get('ally_total_damage_dealt', 0):,}")
        out.append(f"    受到伤害: {score_data.get('ally_total_damage_received', 0):,}")
        out.append(f"    提供回复: {score_data.get('ally_total_hp_healed', 0):,}")
        out.append(f"  敌方合计:")
        out.append(f"    造成伤害: {score_data.get('enemy_total_damage_dealt', 0):,}")
        out.append(f"    受到伤害: {score_data.get('enemy_total_damage_received', 0):,}")
        out.append(f"    提供回复: {score_data.get('enemy_total_hp_healed', 0):,}")
        out.append("─" * 60)

    # ── 特殊值日志导出 ──

    @staticmethod
    def _find_quantile_record(sorted_records: list, q: float):
        """在排序后的记录列表中查找最接近指定分位数的记录"""
        if not sorted_records:
            return None
        n = len(sorted_records)
        idx = int(q * (n - 1))
        idx = max(0, min(idx, n - 1))
        return sorted_records[idx]

    def _export_special_log(self, record, log_label: str, sel: dict, stage_data: dict):
        """导出特殊值对应的战斗日志（以我方伤害为标准）

        Args:
            record: (ally_damage, run_idx, seed, stats) 元组
            log_label: 日志标签（如 "最高伤害"、"Q1"）
            sel: 编队选择信息
            stage_data: 阶段数据
        """
        if not record:
            messagebox.showwarning("无数据", f"没有可导出的{log_label}记录")
            return

        ally_damage, run_idx, seed, stats = record

        log_dir = _BASE_PATH / "data" / "battle_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"circle_battle_{log_label}_{ally_damage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        self._start_btn.config(state="disabled")
        self._log_btn.config(state="disabled")
        self._progress_var.set(f"正在导出{log_label}日志...")

        def _do_export():
            try:
                global_vals = self.app.global_tab.get_values()
                panel_config = self.app._build_panel_config_from_gui(global_vals)
                player_config = panel_config.get_player_config()
                lerp_data = self.app.data_loader.load_level_lerp_data()
                stat_calculator = StatCalculator(lerp_data, data_loader=self.app.data_loader)
                narrative = BattleNarrativeWriter()

                random.seed(seed)

                friend_positions = sel.get("friend_positions", sel.get("friends", []))
                bf = BattlefieldState()

                for i, cid in enumerate(friend_positions):
                    if cid is not None:
                        u = self.app._create_unit(panel_config, player_config, stat_calculator,
                                                  cid, Side.ALLY, GRID_ALLY_POSITIONS[i])
                        if u:
                            bf.add_unit(u)

                for enemy_data in stage_data["enemies"]:
                    enemy_unit = self._create_circle_battle_enemy(enemy_data)
                    if enemy_unit:
                        bf.add_unit(enemy_unit)

                bf.memory_cards = self._build_memory_cards(sel.get("mems_friend", []))

                config = BattleConfig()
                config.max_turns = stage_data["max_turn"]

                from src.combat_v2.circle_battle_controller import CircleBattleController
                controller = CircleBattleController(bf, data_loader=self.app.data_loader,
                                                    config=config, narrative=narrative,
                                                    season=sel["season"], stage=sel["stage"],
                                                    enemy_state_overrides=sel.get("enemy_state_overrides"))
                result = controller.execute_battle()
                narrative.write(str(log_path))

                score_data = result.get("score", {})
                export_damage = score_data.get("ally_total_damage_dealt", 0) if score_data else 0
                turns = result.get("total_turns", 0)

                def _on_done():
                    self._start_btn.config(state="normal")
                    self._log_btn.config(state="normal")
                    self._progress_var.set("完成!")
                    msg = (f"{log_label}日志已导出:\n{log_path}\n"
                           f"我方伤害: {export_damage:,}  回合数: {turns}")
                    if export_damage != ally_damage:
                        msg += (f"\n⚠ 注意: 导出伤害({export_damage:,})与记录伤害({ally_damage:,})不一致，"
                                f"可能是战斗逻辑已更新")
                    self._result_panel.append_summary(f"\n{msg}\n")

                self.app.root.after(0, _on_done)
            except Exception as e:
                import traceback
                err_msg = str(e) + "\n" + traceback.format_exc()

                def _on_err():
                    self._start_btn.config(state="normal")
                    self._log_btn.config(state="normal")
                    self._progress_var.set("错误!")
                    self._result_panel.append_summary(f"\n❌ 导出{log_label}日志出错:\n{err_msg}\n")

                self.app.root.after(0, _on_err)

        thread = threading.Thread(target=_do_export, daemon=True)
        thread.start()

    def _export_max_log(self):
        """导出最高伤害日志"""
        cache = getattr(self, '_score_stats_cache', {})
        rec = cache.get("max_record")
        sel = cache.get("sel")
        stage_data = cache.get("stage_data")
        if rec and sel and stage_data:
            self._export_special_log(rec, "最高伤害", sel, stage_data)

    def _export_min_log(self):
        """导出最低伤害日志"""
        cache = getattr(self, '_score_stats_cache', {})
        rec = cache.get("min_record")
        sel = cache.get("sel")
        stage_data = cache.get("stage_data")
        if rec and sel and stage_data:
            self._export_special_log(rec, "最低伤害", sel, stage_data)

    def _export_q1_log(self):
        """导出Q1伤害日志"""
        cache = getattr(self, '_score_stats_cache', {})
        rec = cache.get("q1_record")
        sel = cache.get("sel")
        stage_data = cache.get("stage_data")
        if rec and sel and stage_data:
            self._export_special_log(rec, "Q1伤害", sel, stage_data)

    def _export_q3_log(self):
        """导出Q3伤害日志"""
        cache = getattr(self, '_score_stats_cache', {})
        rec = cache.get("q3_record")
        sel = cache.get("sel")
        stage_data = cache.get("stage_data")
        if rec and sel and stage_data:
            self._export_special_log(rec, "Q3伤害", sel, stage_data)

    # ── 配置预设管理 ──

    def _refresh_circle_presets(self):
        try:
            self._circle_preset_listbox.delete(0, tk.END)
            if CIRCLE_PRESET_DIR.exists():
                for f in sorted(CIRCLE_PRESET_DIR.glob("*.json")):
                    self._circle_preset_listbox.insert(tk.END, f.stem)
        except Exception:
            pass

    def _save_circle_preset(self):
        CIRCLE_PRESET_DIR.mkdir(parents=True, exist_ok=True)
        name = self._circle_preset_name_var.get().strip()
        if not name:
            messagebox.showwarning("名称为空", "请输入预设名称")
            return
        sel = self._get_selection()
        path = CIRCLE_PRESET_DIR / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sel, f, ensure_ascii=False, indent=2)
        self._refresh_circle_presets()

    def _load_circle_preset(self):
        sel_idx = self._circle_preset_listbox.curselection()
        if not sel_idx:
            messagebox.showwarning("未选择", "请先选择一个预设")
            return
        name = self._circle_preset_listbox.get(sel_idx[0])
        path = CIRCLE_PRESET_DIR / f"{name}.json"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 恢复赛季/阶段
        if "season" in data:
            self._var_season.set(str(data["season"]))
        if "stage" in data:
            self._var_stage.set(data["stage"])
        self._on_stage_change()

        # 恢复己方编队
        friend_positions = data.get("friend_positions", [])
        for i, cid in enumerate(friend_positions):
            if i < len(self.friend_slots):
                if cid is None:
                    self._clear_slot(self.friend_slots[i])
                else:
                    self._set_slot_char(self.friend_slots[i], cid)

        # 恢复回忆卡
        mem_positions = data.get("mem_friend_positions", [])
        for i, entry in enumerate(mem_positions):
            if i < len(self.mem_friend_slots):
                mid = self._parse_memory_card_id(entry)
                if mid is None:
                    self._clear_mem_slot(i)
                else:
                    self._set_mem_slot(i, mid)

        # 恢复敌方初始状态覆盖
        enemy_overrides = data.get("enemy_state_overrides", {})
        if enemy_overrides:
            # JSON键为字符串，转为int
            normalized = {}
            for k, v in enemy_overrides.items():
                try:
                    normalized[int(k)] = v
                except (ValueError, TypeError):
                    pass
            self._apply_enemy_state_overrides(normalized)

    def _delete_circle_preset(self):
        sel_idx = self._circle_preset_listbox.curselection()
        if not sel_idx:
            return
        name = self._circle_preset_listbox.get(sel_idx[0])
        path = CIRCLE_PRESET_DIR / f"{name}.json"
        if path.exists():
            os.remove(path)
            self._refresh_circle_presets()
