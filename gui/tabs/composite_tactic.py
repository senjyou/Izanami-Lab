# -*- coding: utf-8 -*-
"""复合战术演习 Tab（3队依次出战，对BOSS总伤害=分数）。

从 gui_app.py 抽取，槽位/拖拽/回忆卡等公共方法复用 BattleTabMixin。
差异通过钩子方法处理：
    - _get_char_slots / _get_mem_slots 返回当前队伍的槽位
    - _after_slot_changed 刷新队伍列表
    - _on_post_display 绘制重复角色惩罚标识
    - _swap_slots 先交换数据再刷新显示（避免重复惩罚误判）
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
    AVATAR_DIR,
    BANNER_DIR,
    COMPOSITE_PRESET_DIR,
    ENEMY_IMAGE_DIR,
    ENEMY_SLOT_POSITION_MAP,
    GRID_ALLY_POSITIONS,
    MEMORY_CARD_DIR,
)
from gui.widgets.result_table import ResultTablePanel
from gui.widgets.rdps import (
    _build_rdps_summary,
    _build_rdps_tables,
    _export_rdps_tracking_log,
)
from gui.dialogs.enemy_detail import EnemyDetailDialog
from gui.utils import _format_special_notes_single, _format_special_notes_multi

from gui.tabs.base import BattleTabMixin


class CompositeTacticExerciseTab(BattleTabMixin, ttk.Frame):
    """复合战术演习模式 - 3队依次出战，对BOSS总伤害=分数"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._composite_data: Dict[str, Any] = self.app.data_loader.get_composite_tactic_enemies()
        self._endless_data: Dict[str, Any] = self._composite_data.get("endless", {})

        # 3支队伍的槽位：每队6角色槽 + 6回忆卡槽
        self._teams_slots: List[List[Dict[str, Any]]] = [[], [], []]
        self._teams_mem_slots: List[List[Dict[str, Any]]] = [[], [], []]
        self._current_team_index = 0
        self._drag_source = None
        self._drag_preview = None

        # 敌方预览槽位
        self._enemy_slots: List[Optional[Dict[str, Any]]] = [None] * 6
        self._enemy_grid_widgets: List[Dict[str, Any]] = []
        self._rdps_tracking_log: List[str] = []

        self._build()

    # ─────────────────── 钩子方法覆盖 ───────────────────

    def _get_char_slots(self, is_enemy: bool = False):
        """返回当前队伍的角色槽位（忽略 is_enemy）。"""
        return self._teams_slots[self._current_team_index]

    def _get_mem_slots(self, is_enemy: bool = False):
        """返回当前队伍的回忆卡槽位。"""
        return self._teams_mem_slots[self._current_team_index]

    def _after_slot_changed(self):
        """槽位变更后刷新队伍列表。"""
        self._refresh_team_list()

    def _on_post_display(self, slot, cid):
        """_update_slot_display 完成后在 banner 右上角绘制重复角色惩罚标识。"""
        if cid is None:
            return
        penalty = self._get_duplicate_penalty(cid)
        if penalty:
            pval = "↓99%" if "99" in penalty else "↓50%"
            BANNER_W = 154
            px, py = BANNER_W - 26, 11
            canvas = slot["avatar_label"]
            canvas.create_rectangle(px - 20, py - 8, px + 20, py + 8,
                                    fill="#cc3333", outline="white", width=1)
            canvas.create_text(px, py, text=pval, fill="white",
                               font=("Microsoft YaHei UI", 7, "bold"))

    def _swap_slots(self, src_slot, dst_slot, src_cid, dst_cid):
        """先交换数据再刷新显示（避免 _update_slot_display 时重复惩罚误判）。"""
        if dst_cid is not None:
            dst_slot["cid"] = src_cid
            src_slot["cid"] = dst_cid
            self._update_slot_display(dst_slot, src_cid)
            self._update_slot_display(src_slot, dst_cid)
        else:
            dst_slot["cid"] = src_cid
            src_slot["cid"] = None
            self._update_slot_display(dst_slot, src_cid)
            self._update_slot_display(src_slot, None)

    # ─────────────────── 方法覆盖 ───────────────────

    def _load_slot_avatar(self, cid):
        """加载槽位横版头像（简单 resize，不裁剪）。"""
        from PIL import Image
        BANNER_W, BANNER_H = 154, 76

        banner_path = BANNER_DIR / f"{cid}.png"
        if banner_path.exists():
            try:
                pil_img = Image.open(banner_path)
                pil_img = pil_img.resize((BANNER_W, BANNER_H), Image.LANCZOS)
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                pil_img.save(tmp_path, "PNG")
                photo = tk.PhotoImage(file=tmp_path)
                os.unlink(tmp_path)
                return photo
            except Exception:
                pass

        avatar_path = AVATAR_DIR / f"{cid}.png"
        if avatar_path.exists():
            try:
                pil_img = Image.open(avatar_path)
                pil_img = pil_img.resize((BANNER_W, BANNER_H), Image.LANCZOS)
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                pil_img.save(tmp_path, "PNG")
                photo = tk.PhotoImage(file=tmp_path)
                os.unlink(tmp_path)
                return photo
            except Exception:
                pass
        return None

    def _open_char_picker(self, slot_idx, is_enemy: bool = False):
        """打开角色选择弹窗（使用当前队伍的槽位）。"""
        dialog = CharacterPickerDialog(self, self.app, title="选择角色")
        self.wait_window(dialog)
        if dialog.result is not None:
            team_idx = self._current_team_index
            self._set_slot_char(self._teams_slots[team_idx][slot_idx], dialog.result)
            self._refresh_team_list()

    def _open_mem_picker(self, slot_idx, is_enemy: bool = False):
        """打开回忆卡选择弹窗（使用当前队伍的回忆卡槽位）。"""
        team_idx = self._current_team_index
        exclude = set()
        for s in self._teams_mem_slots[team_idx]:
            if s["mid"] is not None:
                exclude.add(s["mid"])
        current_mid = self._teams_mem_slots[team_idx][slot_idx]["mid"]
        exclude.discard(current_mid)

        dialog = MemoryPickerDialog(self, self.app, title="选择回忆卡", exclude_ids=exclude)
        self.wait_window(dialog)
        if dialog.result is not None:
            self._set_mem_slot(slot_idx, dialog.result)

    def _set_mem_slot(self, slot_idx, mid, is_enemy: bool = False):
        """设置回忆卡槽位内容（使用当前队伍）。"""
        team_idx = self._current_team_index
        slot = self._teams_mem_slots[team_idx][slot_idx]
        slot["mid"] = mid
        self._update_mem_slot_display(slot, mid)

    def _clear_mem_slot(self, slot_idx, is_enemy: bool = False):
        """清空回忆卡槽位（使用当前队伍）。"""
        team_idx = self._current_team_index
        slot = self._teams_mem_slots[team_idx][slot_idx]
        slot["mid"] = None
        self._update_mem_slot_display(slot, None)

    def _clear_slot_by_idx(self, slot_idx, is_enemy: bool = False):
        """通过索引清除槽位（使用当前队伍）。"""
        team_idx = self._current_team_index
        self._clear_slot(self._teams_slots[team_idx][slot_idx])
        self._refresh_team_list()

    def _update_mem_slot_display(self, slot, mid):
        """更新回忆卡槽位显示（CompositeTactic 特有：使用 memory name 作为回退文本）。"""
        canvas = slot["canvas"]
        s = self.app._get_scheme()
        CARD_W, CARD_H = 120, 68

        canvas.delete("all")
        canvas.config(bg=s["bg"])
        canvas._card_photo = None

        if mid is None:
            canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                               fill=s["border"], font=("Microsoft YaHei UI", 8))
            try:
                slot["clear_btn"].place_forget()
            except Exception:
                pass
        else:
            mem = self.app.data_loader.get_memory(mid)
            if not mem:
                slot["mid"] = None
                self._update_mem_slot_display(slot, None)
                return

            mem_path = MEMORY_CARD_DIR / f"{mid}.png"
            if mem_path.exists():
                from PIL import Image
                try:
                    pil_img = Image.open(mem_path)
                    pil_img = pil_img.resize((CARD_W, CARD_H), Image.LANCZOS)
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        tmp_path = tmp.name
                    pil_img.save(tmp_path, "PNG")
                    photo = tk.PhotoImage(file=tmp_path)
                    os.unlink(tmp_path)
                    canvas._card_photo = photo
                    canvas.create_image(CARD_W // 2, CARD_H // 2, image=photo, anchor="center")
                except Exception:
                    canvas.create_text(CARD_W // 2, CARD_H // 2, text=mem.name[:6],
                                       fill=s["fg"], font=("Microsoft YaHei UI", 8))
            else:
                canvas.create_text(CARD_W // 2, CARD_H // 2, text=mem.name[:6],
                                   fill=s["fg"], font=("Microsoft YaHei UI", 8))

            try:
                slot["clear_btn"].place(relx=1.0, rely=0.0, anchor="ne", x=-2, y=2)
            except Exception:
                pass

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

        # ── 标题 ──
        ttk.Label(f, text="=== 复合战术演习 ===", font=("Microsoft YaHei UI", 11, "bold")).pack(
            pady=(10, 5), padx=10, anchor="w")

        # ── 关卡信息 ──
        info_frame = ttk.LabelFrame(f, text="关卡信息")
        info_frame.pack(pady=5, fill="x", padx=10)

        info_row = ttk.Frame(info_frame)
        info_row.pack(padx=5, pady=5, fill="x")
        ttk.Label(info_row, text="难度:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Label(info_row, text="ENDLESS", font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(info_row, text="每队最大回合:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._max_turn_label = ttk.Label(info_row, text=str(self._endless_data.get("max_turn", 5)),
                                          font=("Microsoft YaHei UI", 9, "bold"))
        self._max_turn_label.pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(info_row, text="队伍数:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Label(info_row, text="3", font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT)

        # ── 敌方阵容预览 ──
        enemy_frame = ttk.LabelFrame(f, text="敌方阵容（点击头像查看详情，★为BOSS）")
        enemy_frame.pack(pady=5, fill="x", padx=10)

        self._enemy_grid_frame = tk.Frame(enemy_frame, bg=s["bg"])
        self._enemy_grid_frame.pack(fill="x", padx=5, pady=5)

        enemy_slot_labels = ["左前(1)", "中前(2)", "右前(3)", "左后(4)", "中后(5)", "右后(6)"]
        for i, label in enumerate(enemy_slot_labels):
            frame = tk.Frame(self._enemy_grid_frame, bg=s["bg"],
                              highlightbackground=s["border"], highlightthickness=1)
            r = 0 if i >= 3 else 1
            c = i % 3
            frame.grid(row=r, column=c, padx=3, pady=3)
            frame.grid_propagate(False)
            frame.configure(width=164, height=140)
            pos_label = ttk.Label(frame, text=label, font=("Microsoft YaHei UI", 8))
            pos_label.grid(row=0, column=0, sticky="w", padx=(3, 0))

            slot = self._build_enemy_slot(frame, i)
            slot["frame"].grid(row=1, column=0, padx=5, pady=(2, 2))
            slot["outer_frame"] = frame
            self._enemy_grid_widgets.append(slot)

        self._refresh_enemy_preview()

        # ── 队伍管理区 ──
        team_mgmt_frame = ttk.LabelFrame(f, text="队伍管理（出战顺序：队伍1→队伍2→队伍3）")
        team_mgmt_frame.pack(pady=5, fill="x", padx=10)

        # 上方：队伍列表 + 顺序调整按钮（水平排列）
        team_list_frame = tk.Frame(team_mgmt_frame, bg=s["bg"])
        team_list_frame.pack(side=tk.TOP, fill="x", padx=5, pady=(5, 2))
        self._team_list_frame = team_list_frame

        ttk.Label(team_list_frame, text="队伍列表", font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))

        self._team_listbox = tk.Listbox(team_list_frame, height=3, width=24,
                                         bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                         selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                         borderwidth=0, highlightthickness=0,
                                         font=("Microsoft YaHei UI", 9))
        self._team_listbox.pack(side=tk.LEFT, fill=tk.Y)
        self._team_listbox.bind("<<ListboxSelect>>", self._on_team_select)

        # 顺序调整按钮（右侧水平排列）
        order_btn_frame = tk.Frame(team_list_frame, bg=s["bg"])
        order_btn_frame.pack(side=tk.LEFT, padx=10)
        self._order_btn_frame = order_btn_frame
        ttk.Button(order_btn_frame, text="↑ 上移", command=lambda: self._move_team(-1), width=8).grid(row=0, column=0, padx=1, pady=1)
        ttk.Button(order_btn_frame, text="↓ 下移", command=lambda: self._move_team(1), width=8).grid(row=0, column=1, padx=1, pady=1)
        ttk.Button(order_btn_frame, text="交换 1↔2", command=lambda: self._swap_teams(0, 1), width=8).grid(row=1, column=0, padx=1, pady=1)
        ttk.Button(order_btn_frame, text="交换 2↔3", command=lambda: self._swap_teams(1, 2), width=8).grid(row=1, column=1, padx=1, pady=1)
        ttk.Button(order_btn_frame, text="交换 1↔3", command=lambda: self._swap_teams(0, 2), width=8).grid(row=1, column=2, padx=1, pady=1)

        # 下方：选中队伍的编队面板
        team_detail_frame = tk.Frame(team_mgmt_frame, bg=s["bg"])
        team_detail_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(2, 5))
        self._team_detail_frame = team_detail_frame

        self._build_team_detail(team_detail_frame)

        # ── 配置预设管理 ──
        preset_frame = ttk.LabelFrame(f, text="配置预设（保存/加载3队阵容+回忆卡）")
        preset_frame.pack(pady=5, fill="x", padx=10)

        self._composite_preset_listbox = tk.Listbox(preset_frame, height=4,
                                                     bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                                     selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                                     borderwidth=0, highlightthickness=0,
                                                     font=("Microsoft YaHei UI", 9))
        self._composite_preset_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        preset_btn_frame = ttk.Frame(preset_frame)
        preset_btn_frame.pack(side=tk.RIGHT, padx=5, pady=5)
        ttk.Button(preset_btn_frame, text="保存", command=self._save_composite_preset).pack(fill="x", pady=2)
        ttk.Button(preset_btn_frame, text="加载", command=self._load_composite_preset).pack(fill="x", pady=2)
        ttk.Button(preset_btn_frame, text="删除", command=self._delete_composite_preset).pack(fill="x", pady=2)
        self._composite_preset_name_var = tk.StringVar(value="配置1")
        ttk.Entry(preset_btn_frame, textvariable=self._composite_preset_name_var, width=14).pack(fill="x", pady=2)

        self._refresh_composite_presets()

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

        # ── 结果输出 ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self._result_panel = ResultTablePanel(right_frame, self.app, title="战斗结果")
        self._result_panel.pack(fill=tk.BOTH, expand=True)

        # 初始化队伍列表显示
        self._refresh_team_list()
        self._select_team(0)

    def _build_team_detail(self, parent):
        """构建选中队伍的编队详情面板"""
        s = self.app._get_scheme()

        # 队伍标题
        self._team_title_label = ttk.Label(parent, text="队伍 1", font=("Microsoft YaHei UI", 11, "bold"))
        self._team_title_label.pack(pady=(0, 5), anchor="w")

        # 角色编队 + 回忆卡（同行）
        ally_main = tk.Frame(parent, bg=s["bg"])
        ally_main.pack(fill="x")
        self._ally_main = ally_main

        ttk.Label(ally_main, text="=== 己方编队 ===", font=("Microsoft YaHei UI", 10, "bold")).grid(
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
            self._teams_slots[self._current_team_index].append(slot)

        ttk.Label(ally_main, text="=== 回忆卡 ===", font=("Microsoft YaHei UI", 10, "bold")).grid(
            row=0, column=3, sticky="w", pady=(5, 5), padx=(15, 0))

        ally_mem_frame = tk.Frame(ally_main, bg=s["bg"])
        ally_mem_frame.grid(row=1, column=3, sticky="n", padx=(15, 0))
        self._ally_mem_frame = ally_mem_frame
        for i in range(6):
            r, c = divmod(i, 2)
            slot = self._build_mem_slot(ally_mem_frame, i)
            slot["frame"].grid(row=r, column=c, padx=2, pady=2)
            self._teams_mem_slots[self._current_team_index].append(slot)

        # 为队伍1和2创建slot字典，共享队伍0的GUI组件引用，但数据(cid/mid)独立
        # 这样切换队伍时_refresh_team_detail_display能用当前队伍数据更新共享GUI组件
        for team_idx in range(1, 3):
            for i in range(6):
                gui_slot = self._teams_slots[0][i]
                self._teams_slots[team_idx].append({
                    "cid": None, "frame": gui_slot["frame"],
                    "avatar_label": gui_slot["avatar_label"],
                    "name_label": gui_slot["name_label"],
                    "clear_btn": gui_slot["clear_btn"],
                    "outer_frame": gui_slot["outer_frame"], "slot_idx": i,
                })
                gui_mem_slot = self._teams_mem_slots[0][i]
                self._teams_mem_slots[team_idx].append({
                    "mid": None, "frame": gui_mem_slot["frame"],
                    "canvas": gui_mem_slot["canvas"],
                    "name_label": gui_mem_slot["name_label"],
                    "clear_btn": gui_mem_slot["clear_btn"], "slot_idx": i,
                })

    # ── 敌方预览 ──

    def _refresh_enemy_preview(self):
        """刷新敌方阵容预览"""
        enemies = self._endless_data.get("enemies", [])
        self._enemy_slots = [None] * 6

        for enemy in enemies:
            slot_idx = enemy.get("slot", 1) - 1
            if 0 <= slot_idx < 6:
                self._enemy_slots[slot_idx] = enemy

        for i, widget in enumerate(self._enemy_grid_widgets):
            enemy_data = self._enemy_slots[i]
            self._update_enemy_slot_display(widget, enemy_data)

    def _build_enemy_slot(self, parent, slot_idx):
        """构建单个敌方槽位"""
        BANNER_W, BANNER_H = 154, 76
        s = self.app._get_scheme()

        slot_frame = tk.Frame(parent, bg=s["bg"])
        avatar_canvas = tk.Canvas(slot_frame, width=BANNER_W, height=BANNER_H,
                                   bg=s["bg"], highlightthickness=0, cursor="hand2")
        avatar_canvas.pack()
        avatar_canvas._banner_photo = None

        name_label = tk.Label(slot_frame, text="", bg=s["bg"], fg=s["fg"],
                               font=("Microsoft YaHei UI", 8), wraplength=BANNER_W,
                               justify="center", height=2)

        for widget in [slot_frame, avatar_canvas, name_label]:
            widget.bind("<Button-1>", lambda e, idx=slot_idx: self._open_enemy_detail(idx))

        return {"frame": slot_frame, "avatar_label": avatar_canvas,
                "name_label": name_label, "slot_idx": slot_idx}

    def _update_enemy_slot_display(self, widget, enemy_data):
        """更新敌方槽位显示"""
        canvas = widget["avatar_label"]
        name_label = widget["name_label"]
        s = self.app._get_scheme()
        BANNER_W, BANNER_H = 154, 76

        name_label.config(bg=s["bg"], fg=s["fg"])
        canvas.delete("all")
        canvas.config(bg=s["bg"])
        canvas._banner_photo = None

        if enemy_data is None:
            canvas.create_text(BANNER_W // 2, BANNER_H // 2, text="空位",
                               fill=s["border"], font=("Microsoft YaHei UI", 8))
            name_label.config(text="")
            name_label.pack_forget()
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
            is_boss = enemy_data.get("is_boss", False)
            if is_boss:
                name = "★ " + name
            name_label.config(text=name)
            name_label.pack(pady=(1, 0))

    def _load_enemy_avatar(self, model_asset_id: str):
        """加载敌方头像"""
        if not model_asset_id:
            return None
        from PIL import Image
        BANNER_W, BANNER_H = 154, 76

        avatar_path = ENEMY_IMAGE_DIR / f"{model_asset_id}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
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

    # ── 队伍管理 ──

    def _refresh_team_list(self):
        """刷新队伍列表显示"""
        self._team_listbox.delete(0, tk.END)
        for i in range(3):
            team_slots = self._teams_slots[i]
            char_count = sum(1 for s in team_slots if s["cid"] is not None)
            self._team_listbox.insert(tk.END, f"队伍 {i + 1} ({char_count}/5角色)")

    def _select_team(self, team_index: int):
        """选中某支队伍并显示其编队"""
        if team_index < 0 or team_index >= 3:
            return
        self._current_team_index = team_index
        self._team_listbox.selection_clear(0, tk.END)
        self._team_listbox.selection_set(team_index)
        self._team_title_label.config(text=f"队伍 {team_index + 1}")
        self._refresh_team_detail_display()

    def _on_team_select(self, event=None):
        """队伍列表选中事件"""
        sel = self._team_listbox.curselection()
        if sel:
            self._select_team(sel[0])

    def _refresh_team_detail_display(self):
        """刷新当前队伍的编队显示"""
        idx = self._current_team_index
        for slot in self._teams_slots[idx]:
            self._update_slot_display(slot, slot["cid"])
        for slot in self._teams_mem_slots[idx]:
            self._update_mem_slot_display(slot, slot["mid"])

    def _move_team(self, direction: int):
        """上移/下移当前队伍（交换出战顺序）"""
        idx = self._current_team_index
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= 3:
            return
        self._teams_slots[idx], self._teams_slots[new_idx] = \
            self._teams_slots[new_idx], self._teams_slots[idx]
        self._teams_mem_slots[idx], self._teams_mem_slots[new_idx] = \
            self._teams_mem_slots[new_idx], self._teams_mem_slots[idx]
        self._select_team(new_idx)
        self._refresh_team_list()

    def _swap_teams(self, idx1: int, idx2: int):
        """交换两支队伍"""
        self._teams_slots[idx1], self._teams_slots[idx2] = \
            self._teams_slots[idx2], self._teams_slots[idx1]
        self._teams_mem_slots[idx1], self._teams_mem_slots[idx2] = \
            self._teams_mem_slots[idx2], self._teams_mem_slots[idx1]
        self._select_team(idx1)
        self._refresh_team_list()

    # ── 角色槽位（特有） ──

    def _get_duplicate_penalty(self, cid: int) -> str:
        """获取角色重复编组惩罚标识

        只对非首次出现的队伍显示惩罚：
        - 当前队伍是该角色第2次出现：↓50%
        - 当前队伍是该角色第3次出现：↓99%
        """
        # 统计当前队伍之前（不含当前队伍）已出现这个角色的队伍数
        prior_count = 0
        for idx in range(self._current_team_index):
            for slot in self._teams_slots[idx]:
                if slot["cid"] == cid:
                    prior_count += 1
                    break  # 每队只算一次

        if prior_count >= 2:
            return "×99%"
        elif prior_count == 1:
            return "×50%"
        return ""

    # ── 数据收集 ──

    def _get_selection(self) -> Dict[str, Any]:
        """获取3支队伍的编队数据"""
        teams_positions = []
        teams_mem_ids = []
        for team_idx in range(3):
            positions = []
            for slot in self._teams_slots[team_idx]:
                positions.append(slot["cid"])
            teams_positions.append(positions)

            # 保存所有6个槽位的mid（包括None），保留位置信息
            mem_ids = []
            for slot in self._teams_mem_slots[team_idx]:
                mem_ids.append(slot["mid"])
            teams_mem_ids.append(mem_ids)

        return {
            "teams_positions": teams_positions,
            "teams_mem_ids": teams_mem_ids,
        }

    def _create_composite_enemy(self, enemy_data: Dict) -> UnitState:
        """创建复合战术演习敌方单位"""
        pos = enemy_data.get("position", 1)
        enemy_pos = ENEMY_SLOT_POSITION_MAP.get(pos, Position.ENEMY_LEFT_FRONT)

        skill_ids = enemy_data.get("skill_ids", [])
        raw_levels = enemy_data.get("skill_levels", {})
        skill_levels = {}
        for sid in skill_ids:
            sid_str = str(sid)
            skill_levels[sid] = int(raw_levels.get(sid_str, raw_levels.get(sid, 1)))

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
        total_chars = sum(sum(1 for c in t if c is not None) for t in sel["teams_positions"])
        if total_chars == 0:
            messagebox.showwarning("编队不完整", "请至少为1支队伍选择角色")
            return

        self._start_btn.config(state="disabled")
        self._log_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary("正在进行复合战术演习批量模拟...\n")

        thread = threading.Thread(target=self._run_simulation, args=(sel,), daemon=True)
        thread.start()

    def _run_simulation(self, sel):
        try:
            global_vals = self.app.global_tab.get_values()
            sim_count = self._var_sim_count.get()

            panel_config = self.app._build_panel_config_from_gui(global_vals)

            enemies_data = self._endless_data["enemies"]
            max_turns = self._endless_data["max_turn"]

            from src.utils.batch_simulator import BatchSimulator

            sim = BatchSimulator(self.app.data_loader)

            def progress_cb(done, total):
                pct = done / total * 100 if total else 0
                self.app.root.after(0, lambda d=done, t=total, p=pct:
                                    self._progress_var.set(f"{d}/{t} ({p:.0f}%)"))

            result = sim.run_batch_composite_tactic(
                panel_config=panel_config,
                teams_positions=sel["teams_positions"],
                enemies_data=enemies_data,
                max_turns=max_turns,
                total_runs=sim_count,
                positions_ally=GRID_ALLY_POSITIONS,
                progress_callback=progress_cb,
                teams_mem_cards=sel["teams_mem_ids"],
                enable_rdps=global_vals.get("enable_rdps", True),
            )

            self.app.root.after(0, lambda: self._display_results(sim_count, result))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_results(self, sim_count, result):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        self._progress_var.set("完成!")
        self._result_panel.clear()

        out = []
        out.append("=" * 60)
        out.append("  复合战术演习结果")
        out.append("=" * 60)
        out.append(f"  模拟场数: {sim_count}")
        out.append(f"  平均分数: {result.get('avg_score', 0):,.1f}")
        out.append(f"  最高分数: {result.get('max_score', 0):,}")
        out.append(f"  最低分数: {result.get('min_score', 0):,}")
        out.append(f"  BOSS平均被击杀次数: {result.get('avg_boss_kills', 0):.2f}")
        out.append(f"  BOSS平均到达阶段: {result.get('avg_boss_stage', 0):.2f}")
        out.append(f"  平均总回合数: {result.get('avg_turns', 0):.1f}")
        elapsed = result.get("elapsed", 0)
        rate = result.get("rate", 0)
        if rate > 0:
            out.append(f"  效率: {rate:.1f} 场/秒 | 耗时 {elapsed:.1f} 秒")
        out.append("=" * 60)

        # 各队平均伤害
        team_damages = result.get("team_avg_damages", [0, 0, 0])
        out.append("")
        out.append("─" * 60)
        out.append("  【各队伍平均得分】")
        for i, dmg in enumerate(team_damages):
            out.append(f"    队伍{i + 1}: {dmg:,.1f}")
        out.append("─" * 60)

        rdps_avg = result.get("rdps_avg")
        if rdps_avg:
            out.append(_build_rdps_summary(rdps_avg))

        # 特殊备注信息（心色見つめるムードメーカー EX追踪）
        notes_lines = _format_special_notes_multi(result.get("special_notes_list", []), sim_count)
        if notes_lines:
            out.append("")
            out.extend(notes_lines)

        self._result_panel.set_summary("\n".join(out))

        # 按队伍分组的单位统计
        team_ally_agg = result.get("team_ally_agg", [{}, {}, {}])
        enemy_agg = result.get("enemy_agg", {})
        n = sim_count if sim_count > 0 else 1

        tables = []
        columns = ["角色", "造成伤害", "受到伤害", "提供回复"]
        col_widths = [135, 120, 120, 120]
        col_aligns = ["w", "e", "e", "e"]

        for team_idx in range(3):
            team_units = team_ally_agg[team_idx] if team_idx < len(team_ally_agg) else {}
            if not team_units:
                continue
            rows = []
            sorted_units = sorted(team_units.items(), key=lambda x: x[1]["damage_dealt"], reverse=True)
            for uid, s in sorted_units:
                rows.append([
                    s.get("name", uid),
                    f"{s.get('damage_dealt', 0) / n:,.1f}",
                    f"{s.get('damage_received', 0) / n:,.1f}",
                    f"{s.get('hp_healed', 0) / n:,.1f}",
                ])
            tables.append({
                "title": f"队伍{team_idx + 1}角色明细(场均)",
                "columns": columns,
                "rows": rows,
                "col_widths": col_widths,
                "col_aligns": col_aligns,
            })

        if enemy_agg:
            rows = []
            for uid, s in enemy_agg.items():
                rows.append([
                    s.get("name", uid),
                    f"{s.get('damage_dealt', 0) / n:,.1f}",
                    f"{s.get('damage_received', 0) / n:,.1f}",
                    f"{s.get('hp_healed', 0) / n:,.1f}",
                ])
            tables.append({
                "title": "敌方角色明细(场均)",
                "columns": columns,
                "rows": rows,
                "col_widths": col_widths,
                "col_aligns": col_aligns,
            })

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
        total_chars = sum(sum(1 for c in t if c is not None) for t in sel["teams_positions"])
        if total_chars == 0:
            messagebox.showwarning("编队不完整", "请至少为1支队伍选择角色")
            return

        self._start_btn.config(state="disabled")
        self._log_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary("正在单次战斗并生成日志...\n")

        thread = threading.Thread(target=self._run_single_with_log, args=(sel,), daemon=True)
        thread.start()

    def _run_single_with_log(self, sel):
        try:
            global_vals = self.app.global_tab.get_values()
            panel_config = self.app._build_panel_config_from_gui(global_vals)
            player_config = panel_config.get_player_config()
            lerp_data = self.app.data_loader.load_level_lerp_data()
            stat_calculator = StatCalculator(lerp_data, data_loader=self.app.data_loader)

            narrative = BattleNarrativeWriter()

            enemies_data = self._endless_data["enemies"]
            max_turns = self._endless_data["max_turn"]

            # 创建3支队伍
            teams_units = []
            for team_idx, team_positions in enumerate(sel["teams_positions"]):
                team_units = []
                for i, cid in enumerate(team_positions):
                    if cid is not None:
                        u = self.app._create_unit(panel_config, player_config, stat_calculator,
                                                  cid, Side.ALLY, GRID_ALLY_POSITIONS[i])
                        if u:
                            existing_ids = {x.unit_id for x in team_units}
                            if u.unit_id in existing_ids:
                                suffix = 1
                                while f"{u.unit_id}_{suffix}" in existing_ids:
                                    suffix += 1
                                u.unit_id = f"{u.unit_id}_{suffix}"
                            team_units.append(u)
                teams_units.append(team_units)

            # 创建敌方
            bf = BattlefieldState()
            for enemy_data in enemies_data:
                enemy_unit = self._create_composite_enemy(enemy_data)
                if enemy_unit:
                    bf.add_unit(enemy_unit)

            # BOSS unit_id
            boss_unit_id = ""
            for ed in enemies_data:
                if ed.get("is_boss"):
                    boss_unit_id = f"E_{ed['enemy_id']}_{ed['slot']}"
                    break

            # 回忆卡
            teams_mem_cards = []
            for team_idx, mem_ids in enumerate(sel["teams_mem_ids"]):
                teams_mem_cards.append(self._build_memory_cards(mem_ids))

            seed = int(time.time() * 1000000) % (2**31)
            random.seed(seed)

            config = BattleConfig()
            config.max_turns = max_turns
            config.enable_rdps = global_vals.get("enable_rdps", True)
            config.enable_rdps_tracking = True

            from src.combat_v2.composite_tactic_controller import CompositeTacticController
            controller = CompositeTacticController(
                bf, data_loader=self.app.data_loader, config=config, narrative=narrative,
                teams=teams_units, team_memories=teams_mem_cards,
                boss_unit_id=boss_unit_id,
            )
            result = controller.execute_battle()

            log_dir = _BASE_PATH / "data" / "battle_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"composite_tactic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            narrative.write(str(log_path))

            tracking_log = result.get("rdps_tracking_log") or []
            special_notes = result.get("special_notes")
            self.app.root.after(0, lambda: self._display_single_result(result, str(log_path), tracking_log, special_notes))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_single_result(self, result, log_path, tracking_log=None, special_notes=None):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        if tracking_log is not None:
            self._rdps_tracking_log = tracking_log
        self._progress_var.set("完成!")
        self._result_panel.clear()

        out = []
        out.append("=" * 60)
        out.append("  复合战术演习 - 单次战斗结果")
        out.append("=" * 60)
        out.append(f"  总分数: {result.get('score', 0):,}")
        out.append(f"  BOSS被击杀次数: {result.get('boss_killed_count', 0)}")
        out.append(f"  BOSS最终阶段: {result.get('boss_stage', 0)}")
        out.append(f"  总回合数: {result.get('total_turns', 0)}")
        out.append(f"  日志文件: {log_path}")
        if tracking_log:
            out.append(f"  RDPS追踪日志: {len(tracking_log)} 行（可点击\"导出RDPS日志\"按钮导出）")
        out.append("=" * 60)

        # 各队结果（含单位详情）
        team_results = result.get("team_results", [])
        tables = []
        ally_cols = ["角色", "造成伤害", "受到伤害", "提供回复", "状态"]
        ally_widths = [120, 110, 110, 110, 50]
        ally_aligns = ["w", "e", "e", "e", "center"]

        # 聚合敌方统计（跨队伍累计受到伤害，取最终剩余HP）
        enemy_agg: Dict[str, Dict[str, Any]] = {}

        # 摘要中输出每队得分
        if team_results:
            out.append("")
            out.append("  【各队得分】")
            for tr in team_results:
                idx = tr.get("team_index", 0) + 1
                dmg = tr.get("damage_to_boss", 0)
                rounds = tr.get("rounds_survived", 0)
                wiped = "团灭" if tr.get("team_wiped", False) else "存活"
                out.append(f"    队伍{idx}: 得分={dmg:,} 回合={rounds} {wiped}")
            out.append("=" * 60)

        for tr in team_results:
            idx = tr.get("team_index", 0) + 1

            ally_stats = tr.get("ally_stats", [])
            if ally_stats:
                rows = []
                for s in sorted(ally_stats, key=lambda x: x.get("damage_dealt", 0), reverse=True):
                    status = "存活" if s.get("alive") else "阵亡"
                    rows.append([
                        s.get("name", "?"),
                        f"{s.get('damage_dealt', 0):,}",
                        f"{s.get('damage_received', 0):,}",
                        f"{s.get('hp_healed', 0):,}",
                        status,
                    ])
                tables.append({
                    "title": f"队伍{idx}",
                    "columns": ally_cols,
                    "rows": rows,
                    "col_widths": ally_widths,
                    "col_aligns": ally_aligns,
                })

            # 聚合敌方统计
            enemy_stats = tr.get("enemy_stats", [])
            for s in enemy_stats:
                name = s.get("name", "?")
                if name not in enemy_agg:
                    enemy_agg[name] = {
                        "name": name,
                        "total_damage_received": 0,
                        "current_hp": s.get("current_hp", 0),
                        "max_hp": s.get("max_hp", 0),
                    }
                enemy_agg[name]["total_damage_received"] += s.get("damage_received", 0)
                enemy_agg[name]["current_hp"] = s.get("current_hp", 0)
                enemy_agg[name]["max_hp"] = s.get("max_hp", 0)

        if enemy_agg:
            enemy_cols = ["角色", "受到伤害", "剩余HP"]
            enemy_widths = [120, 110, 110]
            enemy_aligns = ["w", "e", "center"]
            rows = []
            for name, s in enemy_agg.items():
                rows.append([
                    s["name"],
                    f"{s['total_damage_received']:,}",
                    f"{s['current_hp']}/{s['max_hp']}",
                ])
            tables.append({
                "title": "敌方角色明细",
                "columns": enemy_cols,
                "rows": rows,
                "col_widths": enemy_widths,
                "col_aligns": enemy_aligns,
            })

        rdps_data = result.get("rdps")
        if rdps_data:
            out.append(_build_rdps_summary(rdps_data))
            tables.extend(_build_rdps_tables(rdps_data))

        # 特殊备注信息（心色見つめるムードメーカー EX追踪）
        notes_lines = _format_special_notes_single(special_notes)
        if notes_lines:
            out.append("")
            out.extend(notes_lines)

        self._result_panel.set_summary("\n".join(out))
        if tables:
            self._result_panel.set_tables(tables)

    # ── 配置预设管理 ──

    def _refresh_composite_presets(self):
        try:
            self._composite_preset_listbox.delete(0, tk.END)
            if COMPOSITE_PRESET_DIR.exists():
                for f in sorted(COMPOSITE_PRESET_DIR.glob("*.json")):
                    self._composite_preset_listbox.insert(tk.END, f.stem)
        except Exception:
            pass

    def _save_composite_preset(self):
        COMPOSITE_PRESET_DIR.mkdir(parents=True, exist_ok=True)
        name = self._composite_preset_name_var.get().strip()
        if not name:
            messagebox.showwarning("名称为空", "请输入预设名称")
            return
        sel = self._get_selection()
        path = COMPOSITE_PRESET_DIR / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sel, f, ensure_ascii=False, indent=2)
        self._refresh_composite_presets()

    def _load_composite_preset(self):
        sel_idx = self._composite_preset_listbox.curselection()
        if not sel_idx:
            messagebox.showwarning("未选择", "请先选择一个预设")
            return
        name = self._composite_preset_listbox.get(sel_idx[0])
        path = COMPOSITE_PRESET_DIR / f"{name}.json"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        teams_positions = data.get("teams_positions", [[None] * 6] * 3)
        teams_mem_ids = data.get("teams_mem_ids", [[None] * 6] * 3)

        for team_idx in range(3):
            positions = teams_positions[team_idx] if team_idx < len(teams_positions) else [None] * 6
            for i, cid in enumerate(positions):
                if i < 6:
                    if cid is None:
                        self._clear_slot(self._teams_slots[team_idx][i])
                    else:
                        self._set_slot_char(self._teams_slots[team_idx][i], cid)

            # 直接操作对应队伍的slot数据，不依赖_current_team_index
            mem_ids = teams_mem_ids[team_idx] if team_idx < len(teams_mem_ids) else [None] * 6
            for i in range(6):
                slot = self._teams_mem_slots[team_idx][i]
                if i < len(mem_ids) and mem_ids[i] is not None:
                    slot["mid"] = mem_ids[i]
                else:
                    slot["mid"] = None

        self._refresh_team_list()
        self._select_team(0)

    def _delete_composite_preset(self):
        sel_idx = self._composite_preset_listbox.curselection()
        if not sel_idx:
            return
        name = self._composite_preset_listbox.get(sel_idx[0])
        path = COMPOSITE_PRESET_DIR / f"{name}.json"
        if path.exists():
            os.remove(path)
            self._refresh_composite_presets()
