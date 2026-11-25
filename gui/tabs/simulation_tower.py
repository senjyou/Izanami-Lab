# -*- coding: utf-8 -*-
"""バトルシミュレート（爬塔）Tab。

5 座塔 × 550 层。选中层后展示该层 5 个敌方单位，
支持 6 人己方编队 + 回忆卡的批量胜率模拟。

结构与线程模型严格参照 gui/tabs/circle_battle.py：
编队槽位/拖拽/回忆卡复用 BattleTabMixin，批量模拟跑在 daemon 线程里，
结果一律通过 app.root.after(0, ...) 回到主线程更新。
"""

import json
import os
import random
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional

from gui.constants import (
    ENEMY_IMAGE_DIR,
    GRID_ALLY_POSITIONS,
    TOWER_PRESET_DIR,
    _BASE_PATH,
)
from gui.dialogs.enemy_detail import EnemyDetailDialog
from gui.utils import _format_special_notes_multi
from gui.widgets.result_table import ResultTablePanel
from gui.widgets.formation_card import (
    CARD_W,
    CARD_H,
    load_portrait,
    render_character_card,
    render_empty_card,
)
from gui.widgets.rdps import _build_rdps_summary, _build_rdps_tables

from gui.tabs.base import BattleTabMixin


# 属性 id → 中文名（与对抗压制战 / 战术演习保持一致）
ATTRIBUTE_NAMES = {1: "火", 2: "水", 3: "风", 4: "土", 5: "光", 6: "暗"}

# 敌方 slot（1-6）→ 中文站位名
SLOT_NAMES = {1: "左前", 2: "中前", 3: "右前", 4: "左后", 5: "中后", 6: "右后"}

# 敌方卡片沿用「编队与战斗」的卡框体系（CARD_W × CARD_H = 154 × 74，
# 与敌方原图 300×144 同比例），稀有度 / 属性 / 等级徽章由 render_character_card 统一绘制。


class SimulationTowerTab(BattleTabMixin, ttk.Frame):
    """バトルシミュレート（爬塔）模式 - 5 塔 × 550 层，回合耗尽未全灭判败。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        # 塔数据（{str(tower_id): tower_dict}）与按 id 排序的列表
        try:
            self._tower_list: List[Dict[str, Any]] = self.app.data_loader.get_simulation_tower_list()
        except Exception:
            self._tower_list = []
        self._tower_by_id: Dict[str, Dict[str, Any]] = {
            str(t.get("tower_id")): t for t in self._tower_list
        }

        # 当前层的敌方数据，按真实 slot(1-6) 索引：{slot: enemy_dict}
        # 用 dict 而非 list，才能让「某格为空」精确留空（不对齐左填空）
        self._enemy_slots: Dict[int, Dict[str, Any]] = {}

        # BattleTabMixin 依赖的属性
        self.friend_slots: List[Dict[str, Any]] = []
        self.mem_friend_slots: List[Dict[str, Any]] = []
        self._drag_source = None
        self._drag_preview = None

        self._build()

    # ── UI 构建 ──

    def _build(self):
        s = self.app._get_scheme()
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=4)

        # ── 左侧滚动容器（与 circle_battle 完全一致） ──
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

        # ── 标题 ──
        ttk.Label(f, text="=== バトルシミュレート（爬塔） ===",
                  font=("Microsoft YaHei UI", 11, "bold")).pack(pady=(10, 5), padx=10, anchor="w")

        # ── 塔/层选择 ──
        config_frame = ttk.LabelFrame(f, text="塔/层选择")
        config_frame.pack(pady=5, fill="x", padx=10)

        row1 = ttk.Frame(config_frame)
        row1.pack(padx=5, pady=5, fill="x")

        ttk.Label(row1, text="塔:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._var_tower = tk.StringVar(value="")
        tower_labels = [self._tower_label(t) for t in self._tower_list] or ["（无塔数据）"]
        self._tower_combo = ttk.Combobox(row1, textvariable=self._var_tower, values=tower_labels,
                                         state="readonly", width=34,
                                         font=("Microsoft YaHei UI", 9))
        self._tower_combo.pack(side=tk.LEFT, padx=(0, 12))
        self._tower_combo.bind("<<ComboboxSelected>>", lambda e: self._on_tower_change())

        ttk.Label(row1, text="层:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._var_floor = tk.IntVar(value=1)
        self._floor_spinbox = ttk.Spinbox(
            row1, from_=1, to=550, textvariable=self._var_floor, width=6,
            command=self._on_floor_change,
        )
        self._floor_spinbox.pack(side=tk.LEFT, padx=(0, 6))
        self._floor_spinbox.bind("<Return>", lambda e: self._on_floor_change())
        self._floor_spinbox.bind("<FocusOut>", lambda e: self._on_floor_change())

        self._floor_scale = ttk.Scale(
            row1, from_=1, to=550, orient=tk.HORIZONTAL, length=220,
            command=self._on_scale_move,
        )
        self._floor_scale.set(1)
        self._floor_scale.pack(side=tk.LEFT, padx=(0, 12))

        # ── 塔信息行 ──
        row2 = ttk.Frame(config_frame)
        row2.pack(padx=5, pady=(0, 6), fill="x")

        ttk.Label(row2, text="场地:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._stage_label = ttk.Label(row2, text="--", font=("Microsoft YaHei UI", 9, "bold"))
        self._stage_label.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row2, text="敌方属性:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._enemy_attr_label = ttk.Label(row2, text="--", font=("Microsoft YaHei UI", 9, "bold"))
        self._enemy_attr_label.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row2, text="最大回合:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._max_turn_label = ttk.Label(row2, text="--", font=("Microsoft YaHei UI", 9, "bold"))
        self._max_turn_label.pack(side=tk.LEFT)

        # ── 编队限制提示（属性塔 2-5；不强制校验） ──
        self._restriction_label = tk.Label(
            config_frame, text="", anchor="w", justify="left",
            bg=s["surface"], fg=s["accent"], padx=8, pady=4,
            font=("Microsoft YaHei UI", 9),
        )
        self._restriction_label.pack(fill="x", padx=5, pady=(0, 6))

        # ── 敌方阵容预览（6 格固定站位，与我方镜像；点击卡片查看详情） ──
        enemy_frame = ttk.LabelFrame(f, text="敌方阵容（点击卡片查看详情）")
        enemy_frame.pack(pady=5, fill="x", padx=10)

        self._enemy_grid_frame = tk.Frame(enemy_frame, bg=s["bg"])
        self._enemy_grid_frame.pack(fill="x", padx=5, pady=5)
        # slot(1-6) -> widget；布局与「编队与战斗」敌方编队一致：
        # 上排 = 后排(4/5/6)，下排 = 前排(1/2/3)，与我方编队上下镜像。
        self._enemy_grid_widgets: Dict[int, Dict[str, Any]] = {}
        for slot in range(1, 7):
            widget = self._build_enemy_slot(self._enemy_grid_frame, slot)
            r = 0 if slot >= 4 else 1
            c = (slot - 1) % 3
            widget["outer_frame"].grid(row=r, column=c, padx=3, pady=3, sticky="nw")
            self._enemy_grid_widgets[slot] = widget

        # ── 己方编队 + 己方回忆卡（同行） ──
        ally_main = tk.Frame(f, bg=s["bg"])
        ally_main.pack(pady=(5, 0), fill="x", padx=10)
        self._ally_main = ally_main

        ttk.Label(ally_main, text="=== 己方编队 ===",
                  font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(5, 5))

        ally_form_frame = tk.Frame(ally_main, bg=s["bg"])
        ally_form_frame.grid(row=1, column=0, columnspan=3, sticky="nw")
        self._ally_form_frame = ally_form_frame

        friend_labels = ["左前(1)", "中前(2)", "右前(3)", "左后(4)", "中后(5)", "右后(6)"]
        for i, label in enumerate(friend_labels):
            frame = tk.Frame(ally_form_frame, bg=s["bg"],
                             highlightbackground=s["border"], highlightthickness=1)
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

        ttk.Label(ally_main, text="=== 己方回忆卡 ===",
                  font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=0, column=3, sticky="w", pady=(5, 5), padx=(15, 0))

        ally_mem_frame = tk.Frame(ally_main, bg=s["bg"])
        ally_mem_frame.grid(row=1, column=3, sticky="n", padx=(15, 0))
        self._ally_mem_frame = ally_mem_frame
        for i in range(6):
            r, c = divmod(i, 2)
            slot = self._build_mem_slot(ally_mem_frame, i)
            slot["frame"].grid(row=r, column=c, padx=2, pady=2)
            self.mem_friend_slots.append(slot)

        # ── 配置预设（保存/加载 当前阵容 + 塔/层 + 回忆卡） ──
        preset_frame = ttk.LabelFrame(f, text="配置预设（保存/加载 阵容 + 塔/层 + 回忆卡）")
        preset_frame.pack(pady=5, fill="x", padx=10)

        self._tower_preset_listbox = tk.Listbox(
            preset_frame, height=4,
            bg=s["input_bg"], fg=s["fg"],
            selectbackground=s["select_bg"], selectforeground=s["fg"],
            borderwidth=0, highlightthickness=0,
            font=("Microsoft YaHei UI", 9))
        self._tower_preset_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._tower_preset_listbox.bind("<Double-Button-1>", lambda e: self._load_tower_preset())

        preset_btn_frame = ttk.Frame(preset_frame)
        preset_btn_frame.pack(side=tk.RIGHT, padx=5, pady=5)
        ttk.Button(preset_btn_frame, text="保存", command=self._save_tower_preset).pack(fill="x", pady=2)
        ttk.Button(preset_btn_frame, text="加载", command=self._load_tower_preset).pack(fill="x", pady=2)
        ttk.Button(preset_btn_frame, text="删除", command=self._delete_tower_preset).pack(fill="x", pady=2)
        self._tower_preset_name_var = tk.StringVar(value="配置1")
        ttk.Entry(preset_btn_frame, textvariable=self._tower_preset_name_var, width=14).pack(fill="x", pady=2)

        self._refresh_tower_presets()

        # ── 战斗设置 ──
        battle_frame = ttk.LabelFrame(f, text="")
        battle_frame.pack(pady=(8, 5), fill="x", padx=10)

        ttk.Label(battle_frame, text="模拟场数:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self._var_sim_count = tk.IntVar(value=100)
        ttk.Spinbox(battle_frame, from_=1, to=99999,
                    textvariable=self._var_sim_count, width=8).grid(
            row=0, column=1, padx=5, sticky="w")

        self._start_btn = ttk.Button(battle_frame, text="▶ 开始批量模拟",
                                     command=self._start_battle, width=16)
        self._start_btn.grid(row=0, column=2, padx=5, pady=5)

        self._single_btn = ttk.Button(battle_frame, text="单次模拟+日志",
                                      command=self._start_single_with_log, width=13)
        self._single_btn.grid(row=0, column=3, padx=5, pady=5)

        self._progress_var = tk.StringVar(value="")
        ttk.Label(battle_frame, textvariable=self._progress_var).grid(row=0, column=4, padx=5)

        # ── 批量结果日志导出 ──
        log_frame = ttk.LabelFrame(f, text="叙事日志导出（批量结果）")
        log_frame.pack(pady=(0, 5), fill="x", padx=10)

        # 第一行：选择某一场（左栏宽度有限，按钮另起一行，避免被挤出可视区）
        row_sel = ttk.Frame(log_frame)
        row_sel.pack(fill="x", padx=5, pady=(5, 2))
        ttk.Label(row_sel, text="从上次批量结果中选择：").pack(side=tk.LEFT, padx=(0, 5))
        self._var_log_pick = tk.StringVar(value="（尚未批量模拟）")
        self._log_combo = ttk.Combobox(row_sel, textvariable=self._var_log_pick,
                                       state="readonly", width=40,
                                       font=("Microsoft YaHei UI", 9))
        self._log_combo.pack(side=tk.LEFT, fill="x", expand=True)
        self._log_combo.bind("<<ComboboxSelected>>", lambda e: None)

        # 第二行：导出按钮
        row_btn = ttk.Frame(log_frame)
        row_btn.pack(fill="x", padx=5, pady=(0, 5))
        self._export_log_btn = ttk.Button(row_btn, text="导出该场日志",
                                          command=self._export_selected_log, width=14,
                                          state="disabled")
        self._export_log_btn.pack(side=tk.LEFT, padx=(0, 5))

        self._export_all_logs_btn = ttk.Button(row_btn, text="导出全部败北场",
                                               command=lambda: self._export_batch_logs("ENEMY"),
                                               width=14, state="disabled")
        self._export_all_logs_btn.pack(side=tk.LEFT, padx=(0, 5))

        self._export_win_logs_btn = ttk.Button(row_btn, text="导出全部胜利场",
                                               command=lambda: self._export_batch_logs("FRIEND"),
                                               width=14, state="disabled")
        self._export_win_logs_btn.pack(side=tk.LEFT)

        self._run_records: List[Dict[str, Any]] = []
        self._last_batch_ctx: Optional[Dict[str, Any]] = None

        # ── 右侧结果面板 ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self._result_panel = ResultTablePanel(right_frame, self.app, title="战斗结果")
        self._result_panel.pack(fill=tk.BOTH, expand=True)

        # ── 初始化选择状态 ──
        if tower_labels:
            self._tower_combo.current(0)
        self._on_tower_change()

    # ── 塔/层选择器辅助 ──

    @staticmethod
    def _tower_label(tower: Dict[str, Any]) -> str:
        """构造塔下拉框显示文本：塔名 + 属性限制。"""
        tid = tower.get("tower_id")
        name = tower.get("name", "???")
        declared = tower.get("declared_attribute_name")
        if declared:
            return f"塔{tid} {name}（仅{declared}属性）"
        return f"塔{tid} {name}（属性自由）"

    def _selected_tower(self) -> Optional[Dict[str, Any]]:
        """返回当前选中的塔数据。"""
        label = self._var_tower.get()
        for tower in self._tower_list:
            if self._tower_label(tower) == label:
                return tower
        return None

    def _on_tower_change(self, event=None):
        """切换塔：更新层上限、属性限制提示并刷新敌方预览。"""
        tower = self._selected_tower()
        if not tower:
            return

        floor_count = int(tower.get("floor_count") or 550)
        self._floor_spinbox.config(from_=1, to=floor_count)
        self._floor_scale.config(from_=1, to=floor_count)

        # 层号越界时夹紧
        try:
            floor = int(self._var_floor.get())
        except (ValueError, tk.TclError):
            floor = 1
        floor = max(1, min(floor, floor_count))
        self._var_floor.set(floor)
        self._floor_scale.set(floor)

        # 属性限制提示（仅提示，不做强制校验：允许测试越级配置）
        declared = tower.get("declared_attribute_name")
        enemy_attr = tower.get("enemy_attribute_name")
        if tower.get("is_main_tower"):
            text = "主塔：不限制编队属性，可作为任意阵容的基准测试场。"
            fg = self.app._get_scheme()["fg"]
        elif declared:
            text = (f"本塔仅可使用 {declared} 属性角色"
                    + (f"（敌方主要属性：{enemy_attr}）" if enemy_attr else "")
                    + "。提示仅供参考，不强制校验。")
            fg = self.app._get_scheme()["accent"]
        else:
            text = ""
            fg = self.app._get_scheme()["fg"]
        self._restriction_label.config(
            text=text, fg=fg, bg=self.app._get_scheme()["surface"])

        self._on_floor_change()

    def _on_scale_move(self, value):
        """Scale 拖动：同步到层号并刷新预览（拖动过程不刷新，松开时再刷新）。"""
        try:
            floor = int(float(value))
        except (ValueError, tk.TclError):
            return
        if floor != self._var_floor.get():
            self._var_floor.set(floor)
            self._on_floor_change()

    def _on_floor_change(self, event=None):
        """层变更：刷新该层敌方预览。"""
        tower = self._selected_tower()
        if not tower:
            return
        floor_count = int(tower.get("floor_count") or 550)
        try:
            floor = int(self._var_floor.get())
        except (ValueError, tk.TclError):
            floor = 1
        floor = max(1, min(floor, floor_count))
        self._var_floor.set(floor)
        self._floor_scale.set(floor)

        floor_data = self.app.data_loader.get_simulation_floor(tower.get("tower_id"), floor)
        if not floor_data:
            self._stage_label.config(text="--")
            self._enemy_attr_label.config(text="--")
            self._max_turn_label.config(text="--")
            self._clear_enemy_preview()
            return

        self._stage_label.config(text=str(floor_data.get("display_name", f"第{floor}层")))
        self._max_turn_label.config(text=str(floor_data.get("max_turn", tower.get("max_turn", 10))))

        enemies = floor_data.get("enemies", []) or []
        attrs = {e.get("attribute") for e in enemies if e.get("attribute")}
        if len(attrs) == 1:
            self._enemy_attr_label.config(text=ATTRIBUTE_NAMES.get(attrs.pop(), "?"))
        elif attrs:
            self._enemy_attr_label.config(text="混合")
        else:
            self._enemy_attr_label.config(text="--")

        self._refresh_enemy_preview(floor_data)

    # ── 敌方预览 ──

    def _build_enemy_slot(self, parent, slot: int) -> Dict[str, Any]:
        """构建单个敌方预览卡片（游戏卡框 + 头像 + 稀有度/属性/等级，与「编队与战斗」一致）。

        只保留站位与名称两行文字，面板数值（HP/ATK/DEF/SPD/技能）不再占纵向空间，
        需要时点击卡片打开 EnemyDetailDialog 查看。
        """
        s = self.app._get_scheme()
        # 让 frame 按内容自然尺寸（卡 154×74 + 站位行 + 名称两行），不强制固定高度
        outer = tk.Frame(parent, bg=s["bg"])

        pos_label = tk.Label(outer, text=f"{SLOT_NAMES.get(slot, f'位置{slot}')}({slot})",
                             bg=s["bg"], fg=s["fg"], font=("Microsoft YaHei UI", 8), anchor="w")
        pos_label.grid(row=0, column=0, sticky="w", padx=(2, 0))

        avatar_canvas = tk.Canvas(outer, width=CARD_W, height=CARD_H,
                                  bg=s["bg"], highlightthickness=0, cursor="hand2")
        avatar_canvas.grid(row=1, column=0, padx=4, pady=(1, 1))
        avatar_canvas._card_photo = None

        name_label = tk.Label(outer, text="", bg=s["bg"], fg=s["fg"],
                              font=("Microsoft YaHei UI", 8), wraplength=CARD_W,
                              justify="center", anchor="center", height=2)
        name_label.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 2))

        for widget in (outer, avatar_canvas, name_label):
            widget.bind("<Button-1>", lambda e, s=slot: self._open_enemy_detail(s))

        return {"outer_frame": outer, "pos_label": pos_label, "avatar_label": avatar_canvas,
                "name_label": name_label, "slot": slot}

    def _clear_enemy_preview(self):
        """清空所有敌方预览卡片（6 格全部回到空位态）。"""
        self._enemy_slots = {}
        for slot, widget in self._enemy_grid_widgets.items():
            self._update_enemy_slot_display(widget, None)
            widget["pos_label"].config(text=f"{SLOT_NAMES.get(slot, f'位置{slot}')}({slot})")

    def _refresh_enemy_preview(self, floor_data: Dict[str, Any]):
        """按真实 slot 落位：某格为空就留空，不做左填空。

        爬塔每层固定 5 个敌人，但槽位不连续（例如 1/2/4/5/6），
        必须按 slot 原样摆放才能与游戏内的前后排镜像一致。
        """
        enemies = floor_data.get("enemies", []) or []
        self._enemy_slots = {int(e.get("slot", 0)): e for e in enemies}
        for slot, widget in self._enemy_grid_widgets.items():
            self._update_enemy_slot_display(widget, self._enemy_slots.get(slot))

    def _update_enemy_slot_display(self, widget: Dict[str, Any], enemy_data: Optional[Dict]):
        """更新单个敌方预览卡片内容（统一接主题色，空位显示占位文字）。"""
        s = self.app._get_scheme()
        canvas = widget["avatar_label"]
        pos_label = widget["pos_label"]
        name_label = widget["name_label"]
        outer = widget["outer_frame"]

        # 无论有无敌人，都同步主题色（tk 组件不随 ttk 主题自动刷新）
        outer.config(bg=s["bg"])
        for w in (pos_label, name_label):
            w.config(bg=s["bg"], fg=s["fg"])
        canvas.config(bg=s["bg"])

        canvas._card_photo = None

        if enemy_data is None:
            pos_label.config(text="-")
            render_empty_card(canvas)
            name_label.config(text="")
            return

        slot = enemy_data.get("slot", 0)
        pos_label.config(text=f"{SLOT_NAMES.get(slot, f'位置{slot}')}({slot})")

        # 卡框 + 头像 + 稀有度 / 属性 / 等级（与「编队与战斗」同一套渲染）
        asset_id = enemy_data.get("asset_id") or enemy_data.get("model_asset_id") or ""
        photo = load_portrait(path=ENEMY_IMAGE_DIR / f"{asset_id}.png", crop=False) if asset_id else None
        render_character_card(
            canvas, photo,
            is_enemy=True,
            is_back=int(enemy_data.get("slot", 1)) >= 4,
            rarity=enemy_data.get("rarity"),
            attribute=enemy_data.get("attribute"),
            level=enemy_data.get("level"),
        )
        if photo is None:
            canvas.create_text(CARD_W // 2, CARD_H // 2, text="无头像",
                               fill=s["border"], font=("Microsoft YaHei UI", 8))

        name_label.config(text=enemy_data.get("name", "???"))

    def _open_enemy_detail(self, slot: int):
        """打开敌方详情弹窗（复用通用对话框）。"""
        enemy_data = (self._enemy_slots or {}).get(slot)
        if not enemy_data:
            return
        dialog = EnemyDetailDialog(self, self.app, enemy_data, title="敌方详情")
        self.wait_window(dialog)

    # ── 叙事日志（单次 / 批量按场导出） ──

    def _start_single_with_log(self):
        """单次模拟同一层并导出该次的叙事日志。"""
        sel = self._get_selection()
        if not sel["friends"]:
            messagebox.showwarning("编队不完整", "请至少为己方选择1个角色")
            return
        tower = self._selected_tower()
        floor = sel["floor"]
        floor_data = self.app.data_loader.get_simulation_floor(sel["tower_id"], floor)
        if not floor_data or not floor_data.get("enemies"):
            messagebox.showwarning("层数据错误",
                                   f"无法加载塔{sel['tower_id']} 第{floor}层的敌方数据")
            return

        self._start_btn.config(state="disabled")
        self._single_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary(
            f"正在单次模拟 {tower.get('name', '')} 第{floor}层 并生成叙事日志...\n")

        thread = threading.Thread(target=self._run_single_with_log,
                                  args=(sel, floor_data, tower), daemon=True)
        thread.start()

    def _run_single_with_log(self, sel, floor_data, tower):
        """工作线程：单场战斗（固定 1 场）+ 写叙事日志。"""
        try:
            global_vals = self.app.global_tab.get_values()
            panel_config = self.app._build_panel_config_from_gui(global_vals)
            friend_positions = sel.get("friend_positions", sel.get("friends", []))
            max_turns = int(floor_data.get("max_turn") or tower.get("max_turn") or 10)

            seed = int(time.time() * 1000000) % (2**31)

            from src.utils.batch_simulator import BatchSimulator
            sim = BatchSimulator(self.app.data_loader)
            payload = sim.replay_tower_single(
                panel_config=panel_config,
                friend_positions=friend_positions,
                enemies_data=floor_data.get("enemies", []),
                max_turns=max_turns,
                seed=seed,
                positions_ally=GRID_ALLY_POSITIONS,
                memory_cards=self._build_memory_cards(sel.get("mems_friend", [])),
                enable_rdps=global_vals.get("enable_rdps", True),
                with_narrative=True,
            )

            result = payload["result"]
            narrative = payload["narrative"]

            log_dir = _BASE_PATH / "data" / "battle_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            tag = f"tower_s{sel['tower_id']}_f{sel['floor']}"
            log_path = log_dir / f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            if narrative is not None:
                narrative.write(str(log_path))

            self.app.root.after(0, lambda: self._display_single_result(
                result, str(log_path), seed))

        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_single_result(self, result, log_path, seed):
        """主线程：展示单场结果 + 指出日志路径。"""
        self._start_btn.config(state="normal")
        self._single_btn.config(state="normal")
        self._progress_var.set("单场完成")
        self._result_panel.clear()

        won = (result.get("result") == "FINISHED" and result.get("winner") == "FRIEND")
        winner_text = "胜利" if won else ("超时(判负)" if result.get("result") == "TIMEOUT" else "败北")
        turns = result.get("total_turns", 0)

        lines = [
            "=== 单次模拟 ===",
            f"结果: {winner_text}",
            f"回合: {turns}",
            f"seed: {seed}",
            f"叙事日志: {log_path}",
            "",
        ]
        self._result_panel.set_summary("\n".join(lines))

    # ── 批量结果按场导出 ──

    def _populate_log_picker(self, records: List[Dict[str, Any]]):
        """把上次批量的每场结果填入导出下拉框。"""
        self._run_records = records or []
        labels = []
        for rec in self._run_records:
            w = "胜" if rec.get("winner") == "FRIEND" else "负"
            labels.append(f"#{rec.get('index')} {w} {rec.get('turns')}回合 (seed {rec.get('seed')})")
        self._log_combo["values"] = labels
        has = bool(labels)
        if has:
            self._log_combo.current(len(labels) - 1)
        else:
            self._var_log_pick.set("（尚未批量模拟）")
        for btn in (self._export_log_btn, self._export_all_logs_btn, self._export_win_logs_btn):
            btn.config(state="normal" if has else "disabled")

    def _export_selected_log(self):
        """导出下拉框里选中的那一场的叙事日志。"""
        idx = self._log_combo.current()
        if idx < 0 or idx >= len(self._run_records):
            messagebox.showinfo("未选择", "请先在下拉框中选择一场战斗")
            return
        rec = self._run_records[idx]
        self._export_logs_for_records([rec], prefix="pick")

    def _export_batch_logs(self, winner_filter: str):
        """按胜负筛选批量导出（一次最多 50 场，避免误点写爆磁盘）。"""
        sel = [r for r in self._run_records if r.get("winner") == winner_filter]
        if not sel:
            messagebox.showinfo("无可导出场次",
                                "本次批量结果中没有" + ("胜利" if winner_filter == "FRIEND" else "败北") + "场")
            return
        if len(sel) > 50:
            if not messagebox.askyesno("场次较多",
                                       f"符合条件的共 {len(sel)} 场，只导出前 50 场，是否继续？"):
                return
            sel = sel[:50]
        self._export_logs_for_records(sel, prefix="FRIEND" if winner_filter == "FRIEND" else "ENEMY")

    def _export_logs_for_records(self, records: List[Dict[str, Any]], prefix: str):
        """后台线程：按 seed 逐场复现并写叙事日志。"""
        ctx = self._last_batch_ctx
        if not ctx:
            messagebox.showinfo("无上下文", "请先执行一次批量模拟")
            return
        self._export_log_btn.config(state="disabled")
        self._export_all_logs_btn.config(state="disabled")
        self._export_win_logs_btn.config(state="disabled")
        self._progress_var.set(f"正在导出 {len(records)} 场日志...")

        thread = threading.Thread(target=self._run_export_logs,
                                  args=(records, prefix, ctx), daemon=True)
        thread.start()

    def _run_export_logs(self, records, prefix, ctx):
        try:
            from src.utils.batch_simulator import BatchSimulator
            sim = BatchSimulator(self.app.data_loader)
            log_dir = _BASE_PATH / "data" / "battle_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            written = 0
            written_paths = []

            for rec in records:
                payload = sim.replay_tower_single(
                    panel_config=ctx["panel_config"],
                    friend_positions=ctx["friend_positions"],
                    enemies_data=ctx["enemies_data"],
                    max_turns=ctx["max_turns"],
                    seed=rec["seed"],
                    positions_ally=GRID_ALLY_POSITIONS,
                    memory_cards=ctx["memory_cards"],
                    enable_rdps=ctx["enable_rdps"],
                    with_narrative=True,
                )
                narrative = payload["narrative"]
                if narrative is None:
                    continue
                tag = f"tower_s{ctx['tower_id']}_f{ctx['floor']}_{prefix}_{rec['index']}"
                path = log_dir / f"{tag}_{stamp}.txt"
                narrative.write(str(path))
                written += 1
                written_paths.append(str(path))

            self.app.root.after(0, lambda: self._display_export_done(written, written_paths))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_export_done(self, written, paths):
        self._export_log_btn.config(state="normal")
        self._export_all_logs_btn.config(state="normal")
        self._export_win_logs_btn.config(state="normal")
        self._progress_var.set(f"已导出 {written} 场日志")
        out = [f"=== 叙事日志导出完成 ===", f"场次: {written}", ""]
        if paths:
            folder = str(Path(paths[0]).parent)
            out.append(f"目录: {folder}")
            out.append("")
            out.extend(Path(p).name for p in paths[:20])
            if len(paths) > 20:
                out.append(f"...（共 {len(paths)} 个文件）")
        self._result_panel.set_summary("\n".join(out))

    # ── 配置预设（阵容 + 塔/层 + 回忆卡） ──

    def _refresh_tower_presets(self):
        """刷新预设列表。"""
        try:
            self._tower_preset_listbox.delete(0, tk.END)
            TOWER_PRESET_DIR.mkdir(parents=True, exist_ok=True)
            for f in sorted(TOWER_PRESET_DIR.glob("*.json")):
                self._tower_preset_listbox.insert(tk.END, f.stem)
        except Exception:
            pass

    def _preset_payload(self) -> Dict[str, Any]:
        """收集当前状态：阵容 + 塔/层 + 回忆卡。"""
        sel = self._get_selection()
        tower = self._selected_tower() or {}
        return {
            "version": 1,
            "tower_id": tower.get("tower_id"),
            "floor": sel.get("floor"),
            "friend_positions": sel.get("friend_positions", []),
            "mem_friend_positions": sel.get("mem_friend_positions", []),
        }

    def _save_tower_preset(self):
        name = self._tower_preset_name_var.get().strip()
        if not name:
            messagebox.showwarning("名称为空", "请输入预设名称")
            return
        payload = self._preset_payload()
        try:
            TOWER_PRESET_DIR.mkdir(parents=True, exist_ok=True)
            path = TOWER_PRESET_DIR / f"{name}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return
        self._refresh_tower_presets()
        messagebox.showinfo("保存", f"配置预设 '{name}' 已保存")

    def _load_tower_preset(self):
        idx = self._tower_preset_listbox.curselection()
        if not idx:
            messagebox.showwarning("未选择", "请先选择一个预设")
            return
        name = self._tower_preset_listbox.get(idx[0])
        path = TOWER_PRESET_DIR / f"{name}.json"
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            return

        # ── 先恢复塔/层（层上限依赖塔，必须在编队之前） ──
        tower_id = data.get("tower_id")
        if tower_id is not None:
            for tower in self._tower_list:
                if int(tower.get("tower_id")) == int(tower_id):
                    self._var_tower.set(self._tower_label(tower))
                    self._on_tower_change()
                    break
        floor = data.get("floor")
        if floor is not None:
            try:
                self._var_floor.set(int(floor))
            except (ValueError, tk.TclError):
                pass
            self._on_floor_change()

        # ── 恢复己方阵容 ──
        friend_positions = data.get("friend_positions", [])
        for i, cid in enumerate(friend_positions):
            if i < len(self.friend_slots):
                if cid is None:
                    self._clear_slot(self.friend_slots[i])
                else:
                    self._set_slot_char(self.friend_slots[i], cid)
        for i in range(len(friend_positions), len(self.friend_slots)):
            self._clear_slot(self.friend_slots[i])

        # ── 恢复回忆卡 ──
        mem_positions = data.get("mem_friend_positions", [])
        for i, entry in enumerate(mem_positions):
            if i < len(self.mem_friend_slots):
                mid = self._parse_memory_card_id(entry) if entry else None
                if mid is None:
                    self._clear_mem_slot(i)
                else:
                    self._set_mem_slot(i, mid)
        for i in range(len(mem_positions), len(self.mem_friend_slots)):
            self._clear_mem_slot(i)

    def _delete_tower_preset(self):
        idx = self._tower_preset_listbox.curselection()
        if not idx:
            return
        name = self._tower_preset_listbox.get(idx[0])
        if not messagebox.askyesno("删除预设", f"确定删除 '{name}' 吗？"):
            return
        path = TOWER_PRESET_DIR / f"{name}.json"
        try:
            if path.exists():
                os.remove(path)
        except Exception as e:
            messagebox.showerror("删除失败", str(e))
            return
        self._refresh_tower_presets()

    # ── 数据收集 ──

    def _get_selection(self) -> Dict[str, Any]:
        """收集当前编队与塔/层选择。"""
        friends: List[int] = []
        friend_positions: List[Optional[int]] = []
        for slot in self.friend_slots:
            cid = slot["cid"]
            friend_positions.append(cid)
            if cid:
                friends.append(cid)

        mem_friend_positions: List[str] = []
        for slot in self.mem_friend_slots:
            mid = slot["mid"]
            if mid is not None:
                mem = self.app.data_loader.get_memory(mid)
                mem_friend_positions.append(f"[{mid}] {mem.name}" if mem else f"[{mid}]")
            else:
                mem_friend_positions.append("")

        tower = self._selected_tower() or {}
        return {
            "friends": friends,
            "friend_positions": friend_positions,
            "mems_friend": [e for e in mem_friend_positions if e],
            "mem_friend_positions": mem_friend_positions,
            "tower_id": tower.get("tower_id"),
            "floor": self._var_floor.get(),
        }

    # ── 批量模拟 ──

    def _start_battle(self):
        """开始批量模拟：主线程只做校验与 UI 禁用，实际计算进 daemon 线程。"""
        if not self._tower_list:
            messagebox.showwarning("无塔数据", "未加载到 simulation_tower.json，无法模拟")
            return

        sel = self._get_selection()
        if not sel["friends"]:
            messagebox.showwarning("编队不完整", "请至少为己方选择1个角色")
            return

        tower = self._selected_tower()
        floor = sel["floor"]
        floor_data = self.app.data_loader.get_simulation_floor(sel["tower_id"], floor)
        if not floor_data or not floor_data.get("enemies"):
            messagebox.showwarning("层数据错误",
                                   f"无法加载塔{sel['tower_id']} 第{floor}层的敌方数据")
            return

        self._start_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary(
            f"正在模拟 {tower.get('name', '')} 第{floor}层"
            f"（{floor_data.get('display_name', '')}）...\n")

        thread = threading.Thread(target=self._run_simulation,
                                  args=(sel, floor_data, tower), daemon=True)
        thread.start()

    def _run_simulation(self, sel, floor_data, tower):
        """工作线程：调用 BatchSimulator.run_batch_simulation_tower 并回主线程展示。"""
        try:
            global_vals = self.app.global_tab.get_values()
            sim_count = int(self._var_sim_count.get())
            panel_config = self.app._build_panel_config_from_gui(global_vals)

            friend_positions = sel.get("friend_positions", sel.get("friends", []))
            max_turns = int(floor_data.get("max_turn") or tower.get("max_turn") or 10)

            from src.utils.batch_simulator import BatchSimulator

            sim = BatchSimulator(self.app.data_loader)

            def progress_cb(done, total):
                pct = done / total * 100 if total else 0
                self.app.root.after(
                    0,
                    lambda d=done, t=total, p=pct:
                    self._progress_var.set(f"{d}/{t} ({p:.0f}%)"))

            result = sim.run_batch_simulation_tower(
                panel_config=panel_config,
                friends_chars=sel.get("friends", []),
                friend_positions=friend_positions,
                enemies_data=floor_data.get("enemies", []),
                max_turns=max_turns,
                total_runs=sim_count,
                positions_ally=GRID_ALLY_POSITIONS,
                progress_callback=progress_cb,
                memory_cards=self._build_memory_cards(sel.get("mems_friend", [])),
                enable_rdps=global_vals.get("enable_rdps", True),
            )

            # 记录批量上下文（导出日志时按 seed 复现需要同一套构建参数）
            self._last_batch_ctx = {
                "panel_config": panel_config,
                "friend_positions": list(friend_positions),
                "enemies_data": list(floor_data.get("enemies", [])),
                "max_turns": max_turns,
                "memory_cards": self._build_memory_cards(sel.get("mems_friend", [])),
                "enable_rdps": global_vals.get("enable_rdps", True),
                "tower_id": sel.get("tower_id"),
                "floor": sel.get("floor"),
            }
            self.app.root.after(
                0, lambda: self._display_results(sim_count, result, sel, floor_data, tower))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_results(self, sim_count, result, sel, floor_data, tower):
        """主线程：展示批量模拟结果摘要 + 明细表格。"""
        self._start_btn.config(state="normal")
        self._progress_var.set("完成!")
        self._result_panel.clear()
        # 把每场结果灌进导出下拉框（供事后按场导出叙事日志）
        self._populate_log_picker(result.get("run_records", []))

        wins = result.get("wins", 0)
        losses = result.get("losses", 0)
        pass_rate = result.get("pass_rate", 0)
        elapsed = result.get("elapsed", 0)
        rate = result.get("rate", 0)
        total_turns = result.get("total_turns", 0)
        avg_turns = (total_turns / sim_count) if sim_count else 0

        out: List[str] = []
        out.append("=" * 60)
        out.append(f"  バトルシミュレート - {tower.get('name', '')} 第{sel['floor']}层"
                   f"（{floor_data.get('display_name', '')}）")
        out.append("=" * 60)
        out.append(f"  模拟场数: {sim_count}")
        out.append(f"  胜利: {wins}  失败: {losses}")
        out.append(f"  胜率: {pass_rate:.2%}")
        out.append(f"  平均回合: {avg_turns:.2f}")
        if rate > 0:
            out.append(f"  效率: {rate:.1f} 场/秒 | 耗时 {elapsed:.1f} 秒")
        out.append("=" * 60)

        # 属性塔提示（仅提示，不校验）
        declared = tower.get("declared_attribute_name")
        if declared:
            out.append(f"  编队限制提示: 本塔仅可使用 {declared} 属性角色（不强制校验）")
            out.append("=" * 60)

        # 特殊备注（心色EX / 隣歩む想いAS2 追踪）
        notes_lines = _format_special_notes_multi(result.get("special_notes_list", []), sim_count)
        if notes_lines:
            out.append("")
            out.extend(notes_lines)

        rdps_avg = result.get("rdps_avg")
        if rdps_avg:
            out.append(_build_rdps_summary(rdps_avg))

        self._result_panel.set_summary("\n".join(out))

        # ── 单位统计（所有场次求平均）→ 表格 ──
        all_unit_stats = result.get("all_unit_stats", []) or []
        tables: List[Dict[str, Any]] = []
        if all_unit_stats:
            ally_agg: Dict[str, Dict[str, Any]] = {}
            enemy_agg: Dict[str, Dict[str, Any]] = {}
            for unit_stats in all_unit_stats:
                for uid, stats in (unit_stats or {}).items():
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
                        }
                    target[uid]["damage_dealt"] += stats.get("damage_dealt", 0)
                    target[uid]["damage_received"] += stats.get("damage_received", 0)
                    target[uid]["hp_healed"] += stats.get("hp_healed", 0)
                    target[uid]["hp_received"] += stats.get("hp_received", 0)
                    if stats.get("alive"):
                        target[uid]["survivals"] += 1
                    else:
                        target[uid]["deaths"] += 1

            n = len(all_unit_stats)
            cols = ["角色", "造成伤害", "受到伤害", "提供回复", "存活率"]
            widths = [135, 110, 110, 110, 70]
            aligns = ["w", "e", "e", "e", "center"]

            for title, agg in (("我方角色明细(场均)", ally_agg), ("敌方角色明细(场均)", enemy_agg)):
                if not agg:
                    continue
                rows = []
                for uid, st in agg.items():
                    surv = st["survivals"]
                    death = st["deaths"]
                    sr = surv / (surv + death) * 100 if (surv + death) else 0
                    rows.append([
                        st["name"],
                        f"{st['damage_dealt'] / n:,.1f}",
                        f"{st['damage_received'] / n:,.1f}",
                        f"{st['hp_healed'] / n:,.1f}",
                        f"{sr:.1f}%",
                    ])
                tables.append({"title": title, "columns": cols,
                               "rows": rows, "col_widths": widths, "col_aligns": aligns})

            # 合计（场均）
            ally_dmg = sum(st["damage_dealt"] for st in ally_agg.values()) / n
            ally_recv = sum(st["damage_received"] for st in ally_agg.values()) / n
            ally_heal = sum(st["hp_healed"] for st in ally_agg.values()) / n
            enemy_dmg = sum(st["damage_dealt"] for st in enemy_agg.values()) / n
            enemy_recv = sum(st["damage_received"] for st in enemy_agg.values()) / n
            enemy_heal = sum(st["hp_healed"] for st in enemy_agg.values()) / n
            tables.append({
                "title": "合计(场均)",
                "columns": ["阵营", "造成伤害", "受到伤害", "提供回复"],
                "rows": [
                    ["我方", f"{ally_dmg:,.1f}", f"{ally_recv:,.1f}", f"{ally_heal:,.1f}"],
                    ["敌方", f"{enemy_dmg:,.1f}", f"{enemy_recv:,.1f}", f"{enemy_heal:,.1f}"],
                ],
                "col_widths": [135, 110, 110, 110],
                "col_aligns": ["w", "e", "e", "e"],
            })

        if rdps_avg:
            tables.extend(_build_rdps_tables(rdps_avg))

        if tables:
            self._result_panel.set_tables(tables)

    def _display_error(self, msg: str):
        """主线程：展示错误并恢复按钮。"""
        self._start_btn.config(state="normal")
        self._progress_var.set("错误!")
        self._result_panel.append_summary(f"\n❌ 战斗出错:\n{msg}\n")

    # ── 主题刷新 ──

    def apply_theme(self):
        """主题切换后刷新原生 tk 组件配色（敌方卡片 + 限制提示条）。"""
        s = self.app._get_scheme()
        try:
            self._restriction_label.config(bg=s["surface"], fg=s["accent"])
            self._enemy_grid_frame.config(bg=s["bg"])
            # 卡片自身由 _update_enemy_slot_display 统一重绘（含卡框/徽章），
            # 这里只需要把 frame 底色同步过去。
            for widget in self._enemy_grid_widgets.values():
                widget["outer_frame"].config(bg=s["bg"])
            # 预设列表（原生 Listbox 不随 ttk 主题变化）
            self._tower_preset_listbox.config(
                bg=s["input_bg"], fg=s["fg"],
                selectbackground=s["select_bg"], selectforeground=s["fg"])
            self._on_tower_change()
        except Exception:
            pass
