# -*- coding: utf-8 -*-
"""战术演习 Tab（单体敌方无限复活，阶段递增）。

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
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController
from src.combat_v2.battle_narrative import BattleNarrativeWriter

from gui.constants import (
    _BASE_PATH,
    _DARK_ACCENT,
    _DARK_FG,
    _DARK_INPUT_BG,
    ALLOWED_ENEMY_IDS,
    AVATAR_DIR,
    ENEMY_AVATAR_MAP,
    ENEMY_SLOT_POSITION_MAP,
    GRID_ALLY_POSITIONS,
    TACTICAL_PRESET_DIR,
)
from gui.utils import _cjk_fit
from gui.widgets.result_table import ResultTablePanel
from gui.widgets.rdps import (
    _build_rdps_summary,
    _build_rdps_tables,
    _export_rdps_tracking_log,
)
from gui.dialogs.enemy_picker import EnemyPickerDialog

from gui.tabs.base import BattleTabMixin


class TacticalExerciseTab(BattleTabMixin, ttk.Frame):
    """战术演习模式 - 单体敌方无限复活，阶段递增"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._enemy_data: Dict[int, Dict] = self.app.data_loader.get_tactical_exercise_enemies()
        self.friend_slots: List[Dict[str, Any]] = []
        self.mem_friend_slots: List[Dict[str, Any]] = []
        self._drag_source = None
        self._drag_preview = None
        self._rdps_tracking_log: List[str] = []
        self._build()

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

        # ── 敌方选择 ──
        ttk.Label(f, text="=== 战术演习 - 敌方选择 ===", font=("Microsoft YaHei UI", 11, "bold")).pack(
            pady=(10, 5), padx=10, anchor="w")

        enemy_frame = ttk.LabelFrame(f, text="敌方单位")
        enemy_frame.pack(pady=5, fill="x", padx=10)

        # 左右分栏：左边约3/4，右边约1/4
        enemy_left = ttk.Frame(enemy_frame)
        enemy_left.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)

        enemy_right = ttk.Frame(enemy_frame)
        enemy_right.pack(side="right", fill="y", padx=(0, 5), pady=5)

        # ── 左侧：选择敌方按钮 + 阶段属性预览 ──
        select_frame = ttk.Frame(enemy_left)
        select_frame.pack(fill="x", pady=(0, 5))

        ttk.Label(select_frame, text="选择敌方:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 5))
        self._enemy_select_btn = ttk.Button(select_frame, text="点击选择敌方单位", command=self._open_enemy_picker, width=24)
        self._enemy_select_btn.pack(side=tk.LEFT)

        self._selected_enemy_id = None  # 当前选中的敌方ID

        # 阶段属性预览（合并原"阶段0属性预览"和"自定义阶段属性计算"）
        preview_outer = ttk.LabelFrame(enemy_left, text="阶段属性预览")
        preview_outer.pack(fill="x", pady=(0, 5))

        # 顶部：阶段输入行
        calc_frame = ttk.Frame(preview_outer)
        calc_frame.pack(padx=5, pady=(5, 2), fill="x")

        ttk.Label(calc_frame, text="阶段:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
        self._var_stage_input = tk.IntVar(value=0)
        self._stage_spinbox = ttk.Spinbox(calc_frame, from_=0, to=9999, textvariable=self._var_stage_input,
                                          width=6, command=self._update_stage_calc)
        self._stage_spinbox.pack(side=tk.LEFT, padx=(0, 3))
        self._stage_spinbox.bind("<Return>", lambda e: self._update_stage_calc())

        # 属性标签
        self._enemy_preview_frame = ttk.Frame(preview_outer)
        self._enemy_preview_frame.pack(fill="x", padx=5, pady=(0, 5))

        self._enemy_preview_labels: Dict[str, ttk.Label] = {}
        preview_items = [
            ("HP", "hp"), ("攻击力", "atk"), ("防御力", "def"),
            ("速度", "spd"), ("暴击率", "crit"), ("属性", "elem"),
            ("类型", "ctype"), ("定位", "role"),
        ]
        for i, (label_text, key) in enumerate(preview_items):
            r, c = divmod(i, 4)
            inner = ttk.Frame(self._enemy_preview_frame)
            inner.grid(row=r, column=c, padx=8, pady=2, sticky="w")
            ttk.Label(inner, text=label_text + ":", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
            lbl = ttk.Label(inner, text="--", font=("Microsoft YaHei UI", 9, "bold"))
            lbl.pack(side=tk.LEFT, padx=(3, 0))
            self._enemy_preview_labels[key] = lbl

        # ── 右侧：选中敌方头像（分辨率 110x140）──
        AVATAR_W, AVATAR_H = 110, 140
        self._enemy_avatar_display = tk.Canvas(enemy_right, width=AVATAR_W, height=AVATAR_H,
                                                bg=s["surface"], highlightthickness=0)
        self._enemy_avatar_display.pack(padx=5, pady=5)
        self._enemy_avatar_display._photo = None

        # ── 己方编队 + 己方回忆卡（同行） ──
        s = self.app._get_scheme()
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
        preset_frame = ttk.LabelFrame(f, text="配置预设（保存/加载当前阵容+敌方+回忆卡）")
        preset_frame.pack(pady=5, fill="x", padx=10)

        self._tactical_preset_listbox = tk.Listbox(preset_frame, height=4,
                                                    bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                                    selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                                    borderwidth=0, highlightthickness=0,
                                                    font=("Microsoft YaHei UI", 9))
        self._tactical_preset_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        preset_btn_frame = ttk.Frame(preset_frame)
        preset_btn_frame.pack(side=tk.RIGHT, padx=5, pady=5)
        ttk.Button(preset_btn_frame, text="保存", command=self._save_tactical_preset).pack(fill="x", pady=2)
        ttk.Button(preset_btn_frame, text="加载", command=self._load_tactical_preset).pack(fill="x", pady=2)
        ttk.Button(preset_btn_frame, text="删除", command=self._delete_tactical_preset).pack(fill="x", pady=2)
        self._tactical_preset_name_var = tk.StringVar(value="配置1")
        ttk.Entry(preset_btn_frame, textvariable=self._tactical_preset_name_var, width=14).pack(fill="x", pady=2)

        self._refresh_tactical_presets()

        # ── 战斗设置 ──
        battle_frame = ttk.LabelFrame(f, text="")
        battle_frame.pack(pady=(2, 5), fill="x", padx=10)

        ttk.Label(battle_frame, text="模拟次数:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self._var_sim_count = tk.IntVar(value=100)
        ttk.Spinbox(battle_frame, from_=1, to=99999, textvariable=self._var_sim_count, width=8).grid(
            row=0, column=1, padx=5, sticky="w")

        self._start_btn = ttk.Button(battle_frame, text="▶ 开始战术演习", command=self._start_battle, width=18)
        self._start_btn.grid(row=0, column=2, padx=5, pady=5)
        self._log_btn = ttk.Button(battle_frame, text="📋 单次演习+日志", command=self._start_single_battle_with_log, width=18)
        self._log_btn.grid(row=0, column=3, padx=5, pady=5)
        self._progress_var = tk.StringVar(value="")
        ttk.Label(battle_frame, textvariable=self._progress_var).grid(row=0, column=4, padx=5)
        self._rdps_log_btn = ttk.Button(battle_frame, text="📤 导出RDPS日志",
                                        command=lambda: _export_rdps_tracking_log(self, self._rdps_tracking_log),
                                        width=16)
        self._rdps_log_btn.grid(row=0, column=5, padx=5, pady=5)

        # ── 特殊值日志导出按钮 ──
        export_frame = ttk.LabelFrame(f, text="特殊值日志导出（多场模拟后可用）")
        export_frame.pack(pady=5, fill="x", padx=10)
        btn_row = ttk.Frame(export_frame)
        btn_row.pack(pady=5)
        self._export_max_btn = ttk.Button(btn_row, text="导出最高分日志", command=self._export_max_log, width=18)
        self._export_max_btn.pack(side=tk.LEFT, padx=3)
        self._export_min_btn = ttk.Button(btn_row, text="导出最低分日志", command=self._export_min_log, width=18)
        self._export_min_btn.pack(side=tk.LEFT, padx=3)
        self._export_q1_btn = ttk.Button(btn_row, text="导出Q1分日志", command=self._export_q1_log, width=18)
        self._export_q1_btn.pack(side=tk.LEFT, padx=3)
        self._export_q3_btn = ttk.Button(btn_row, text="导出Q3分日志", command=self._export_q3_log, width=18)
        self._export_q3_btn.pack(side=tk.LEFT, padx=3)

        # ── 结果输出 ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self._result_panel = ResultTablePanel(right_frame, self.app, title="演习结果")
        self._result_panel.pack(fill=tk.BOTH, expand=True)

        # 初始化敌方预览（自动选中第一个）
        self._refresh_enemy_selection()

    def _on_enemy_select(self, eid=None):
        """敌方选择变更时更新预览"""
        if eid is not None:
            self._selected_enemy_id = eid
        eid = self._selected_enemy_id
        if eid is None:
            return
        data = self._enemy_data.get(eid)
        if not data:
            return

        # 更新按钮文字
        pos_name = ["", "左前", "中前", "右前", "左后", "中后", "右后"][data.get("position", 2)]
        if self.app.is_developer_mode():
            self._enemy_select_btn.config(text=f"[{eid}] {data['character_name']} ({pos_name})")
        else:
            self._enemy_select_btn.config(text=f"{data['character_name']} ({pos_name})")

        # 更新右侧头像显示
        self._update_enemy_avatar_display(eid, data)

        # 更新属性预览（根据当前阶段输入计算）
        self._update_stage_calc()

    def _update_enemy_avatar_display(self, eid, data):
        """更新右侧敌方头像显示"""
        s = self.app._get_scheme()
        canvas = self._enemy_avatar_display
        canvas.delete("all")
        canvas._photo = None

        # 自动获取Canvas实际尺寸
        canvas.update_idletasks()
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw < 2 or ch < 2:
            cw, ch = 110, 140  # fallback

        avatar_cid = ENEMY_AVATAR_MAP.get(eid)
        if avatar_cid:
            photo = self._load_enemy_avatar(avatar_cid, cw, ch)
            if photo:
                canvas._photo = photo
                canvas.create_image(cw // 2, ch // 2, image=photo, anchor="center")

        if canvas._photo is None:
            canvas.create_text(cw // 2, ch // 2, text="无头像", fill=s["border"],
                              font=("Microsoft YaHei UI", 9))

    def _load_enemy_avatar(self, cid, w, h):
        """加载敌方头像（通过同名角色ID）"""
        from PIL import Image
        avatar_path = AVATAR_DIR / f"{cid}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            pil_img = pil_img.resize((w, h), Image.LANCZOS)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            pil_img.save(tmp_path, "PNG")
            photo = tk.PhotoImage(file=tmp_path)
            os.unlink(tmp_path)
            return photo
        except Exception:
            return None

    def _open_enemy_picker(self):
        """打开敌方选择二级弹窗"""
        dialog = EnemyPickerDialog(self, self.app, title="选择敌方单位")
        self.wait_window(dialog)
        if dialog.result is not None:
            self._on_enemy_select(dialog.result)

    def _refresh_enemy_selection(self):
        """刷新敌方选择区域（启动时调用）"""
        # 自动选中第一个可用敌方
        dev_mode = self.app.is_developer_mode()
        first_eid = None
        for eid, data in sorted(self._enemy_data.items(), key=lambda x: x[1]["character_name"]):
            if not dev_mode and eid not in ALLOWED_ENEMY_IDS:
                continue
            first_eid = eid
            break
        if first_eid is not None:
            self._on_enemy_select(first_eid)

    def _update_stage_calc(self, event=None):
        """根据当前阶段数更新属性预览标签"""
        eid = self._selected_enemy_id
        if eid is None:
            return
        data = self._enemy_data.get(eid)
        if not data:
            return

        n = self._var_stage_input.get()
        base_hp = data["hp"]
        base_atk = data["attack"]
        base_def = data["defense"]
        base_spd = data["speed"]
        base_crit = data["critical_rate"]

        # HP/ATK/DEF从阶段21起维持在阶段20的数值
        n_for_hp_atk_def = min(n, 20)
        linear_factor = 1.0 + 0.2 * n_for_hp_atk_def
        quadratic_factor = 0.005 * max(0, n_for_hp_atk_def - 3) * max(0, n_for_hp_atk_def - 2)
        stat_mult = linear_factor + quadratic_factor

        hp = int(base_hp * stat_mult)
        atk = int(base_atk * stat_mult)
        defense = int(base_def * stat_mult)
        spd = int(base_spd * (1.0 + 0.05 * n))
        crit = base_crit + 0.01 * n

        attr_names = {1: "火", 2: "水", 3: "风", 4: "土", 5: "光", 6: "暗"}
        type_names = {1: "物理", 2: "EN", 3: "敏捷"}
        role_names = {1: "物理攻击手", 2: "EN攻击手", 3: "坦克", 4: "辅助", 5: "控制"}

        self._enemy_preview_labels["hp"].config(text=str(hp))
        self._enemy_preview_labels["atk"].config(text=str(atk))
        self._enemy_preview_labels["def"].config(text=str(defense))
        self._enemy_preview_labels["spd"].config(text=str(spd))
        self._enemy_preview_labels["crit"].config(text=f"{crit:.4f}")
        self._enemy_preview_labels["elem"].config(text=attr_names.get(data["attribute"], "?"))
        self._enemy_preview_labels["ctype"].config(text=type_names.get(data["type"], "?"))
        self._enemy_preview_labels["role"].config(text=role_names.get(data["role_type"], "?"))

    def _get_selection(self) -> Dict[str, Any]:
        """获取当前选择"""
        friends = []
        friend_positions = []
        for slot in self.friend_slots:
            cid = slot["cid"]
            friend_positions.append(cid)
            if cid:
                friends.append(cid)

        enemy_id = self._selected_enemy_id

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
            "enemy_id": enemy_id,
            "mems_friend": [e for e in mem_friend_positions if e],
            "mem_friend_positions": mem_friend_positions,
        }

    def _start_battle(self):
        sel = self._get_selection()
        if not sel["friends"] or not sel["enemy_id"]:
            messagebox.showwarning("编队不完整", "请至少为己方选择1个角色，并选择敌方单位")
            return

        self._start_btn.config(state="disabled")
        self._log_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary("正在进行战术演习...\n")

        thread = threading.Thread(target=self._run_simulation, args=(sel,), daemon=True)
        thread.start()

    def _run_simulation(self, sel):
        try:
            global_vals = self.app.global_tab.get_values()
            sim_count = self._var_sim_count.get()

            panel_config = self.app._build_panel_config_from_gui(global_vals)

            friend_positions = sel.get("friend_positions", sel.get("friends", []))
            enemy_data = self._enemy_data.get(sel["enemy_id"])
            enemy_pos = ENEMY_SLOT_POSITION_MAP.get(
                enemy_data.get("position", 2), Position.ENEMY_CENTER_FRONT
            ) if enemy_data else Position.ENEMY_CENTER_FRONT

            from src.utils.batch_simulator import BatchSimulator

            sim = BatchSimulator(self.app.data_loader)

            def progress_cb(done, total):
                pct = done / total * 100 if total else 0
                self.app.root.after(0, lambda d=done, t=total, p=pct:
                                    self._progress_var.set(f"{d}/{t} ({p:.0f}%)"))

            result = sim.run_batch_tactical(
                panel_config=panel_config,
                friends_chars=sel.get("friends", []),
                friend_positions=friend_positions,
                enemy_data=enemy_data,
                enemy_pos=enemy_pos,
                total_runs=sim_count,
                positions_ally=GRID_ALLY_POSITIONS,
                progress_callback=progress_cb,
                memory_cards=self.app.team_tab._build_memory_cards(sel.get("mems_friend", [])),
                enable_rdps=global_vals.get("enable_rdps", True),
            )

            total_stages = result["total_stages"]
            total_turns = result["total_turns"]
            max_stages = result["max_stages"]
            losses = result["losses"]
            timeouts = result["timeouts"]

            # 构建计分统计数据（与原来一致）
            all_scores = result.get("all_scores", [])
            score_stats = {}
            if all_scores:
                score_records = result.get("score_records", [])
                sorted_records = sorted(score_records, key=lambda x: x[0])
                score_stats = self._compute_score_statistics(
                    all_scores,
                    result.get("all_ally_damage", []),
                    result.get("all_ally_received", []),
                    result.get("all_ally_healed", []),
                    result.get("all_enemy_damage", []),
                    result.get("all_enemy_received", []),
                    result.get("all_enemy_healed", []),
                    result.get("all_enemy_healing_received", []),
                )
                score_stats["max_record"] = sorted_records[-1] if sorted_records else None
                score_stats["min_record"] = sorted_records[0] if sorted_records else None
                score_stats["q1_record"] = self._find_quantile_record(sorted_records, 0.25)
                score_stats["q3_record"] = self._find_quantile_record(sorted_records, 0.75)
                score_stats["score_records"] = score_records
                score_stats["all_scores"] = all_scores
                score_stats["sel"] = sel
                score_stats["friend_positions"] = friend_positions
                score_stats["rate"] = result.get("rate", 0)
                score_stats["elapsed"] = result.get("elapsed", 0)
                score_stats["all_unit_stats"] = result.get("all_unit_stats", [])
                score_stats["rdps_avg"] = result.get("rdps_avg")

            self.app.root.after(0, lambda: self._display_results(
                sim_count, total_stages, total_turns, max_stages, losses, timeouts, score_stats))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _create_tactical_enemy(self, enemy_data: Dict, bf: BattlefieldState) -> Optional[UnitState]:
        """创建战术演习敌方单位"""
        pos = enemy_data.get("position", 2)
        enemy_pos = ENEMY_SLOT_POSITION_MAP.get(pos, Position.ENEMY_CENTER_FRONT)

        # 加载敌方技能
        skill_ids = enemy_data.get("skill_ids", [])
        # 使用 EnemySkillMaster.Level (导入时已提取), 回退到 15 (兼容旧数据)
        raw_skill_levels = enemy_data.get("skill_levels", {})
        if raw_skill_levels:
            skill_levels = {int(k): v for k, v in raw_skill_levels.items()}
        else:
            skill_levels = {sid: 15 for sid in skill_ids}

        # 计算最大EP
        max_ep = 0
        for sid in skill_ids:
            sk = self.app.data_loader.get_skill_by_id(sid)
            if sk and sk.skill_type == 3:
                max_ep = max(max_ep, sk.resource_cost)

        unit_id = f"E_{enemy_data['enemy_id']}"

        return UnitState(
            unit_id=unit_id,
            name=enemy_data["character_name"],
            side=Side.ENEMY,
            position=enemy_pos,
            character_id=enemy_data["enemy_id"],
            level=1,
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

    def _display_results(self, sim_count, total_stages, total_turns, max_stages, losses, timeouts, score_stats=None):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        self._progress_var.set("完成!")
        self._result_panel.clear()

        avg_stages = total_stages / sim_count if sim_count > 0 else 0
        avg_turns = total_turns / sim_count if sim_count > 0 else 0

        out = []
        out.append("=" * 60)
        out.append(f"  战术演习结果")
        out.append("=" * 60)
        out.append(f"  模拟场数: {sim_count}")
        out.append(f"  平均清除阶段数: {avg_stages:.2f}")
        out.append(f"  最高清除阶段数: {max_stages}")
        out.append(f"  平均回合数: {avg_turns:.2f}")
        out.append(f"  败北: {losses}  超时: {timeouts}")
        rate = score_stats.get("rate", 0) if score_stats else 0
        elapsed = score_stats.get("elapsed", 0) if score_stats else 0
        if rate > 0:
            out.append(f"  效率: {rate:.1f} 场/秒 | 耗时 {elapsed:.1f} 秒")
        out.append("=" * 60)

        tables = []
        if score_stats and score_stats.get("all_scores"):
            all_scores = score_stats["all_scores"]
            n = len(all_scores)

            if n == 1:
                # 单场模拟：显示完整的单场明细
                out.append("")
                rec = score_stats.get("score_records", [])
                if rec:
                    _, _, _, result = rec[0]
                    score_data = result.get("score", {})
                    if score_data:
                        self._append_score_display(out, score_data, tables)
            else:
                # 多场模拟：显示统计值
                self._append_multi_score_display(out, score_stats, n, tables)

        rdps_avg = score_stats.get("rdps_avg") if score_stats else None
        if rdps_avg:
            out.append(_build_rdps_summary(rdps_avg))
            tables.extend(_build_rdps_tables(rdps_avg))

        self._result_panel.set_summary("\n".join(out))
        if tables:
            self._result_panel.set_tables(tables)

    def _display_error(self, msg):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        self._progress_var.set("错误!")
        self._result_panel.append_summary(f"\n❌ 演习出错:\n{msg}\n")

    def _start_single_battle_with_log(self):
        sel = self._get_selection()
        if not sel["friends"] or not sel["enemy_id"]:
            messagebox.showwarning("编队不完整", "请至少为己方选择1个角色，并选择敌方单位")
            return

        self._start_btn.config(state="disabled")
        self._log_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary("正在单次战术演习并生成日志...\n")

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

            friend_positions = sel.get("friend_positions", sel.get("friends", []))
            bf = BattlefieldState()

            for i, cid in enumerate(friend_positions):
                if cid is not None:
                    u = self.app._create_unit(panel_config, player_config, stat_calculator,
                                              cid, Side.ALLY, GRID_ALLY_POSITIONS[i])
                    if u:
                        bf.add_unit(u)

            enemy_data = self._enemy_data.get(sel["enemy_id"])
            if enemy_data:
                enemy_unit = self._create_tactical_enemy(enemy_data, bf)
                if enemy_unit:
                    bf.add_unit(enemy_unit)

            bf.memory_cards = self.app.team_tab._build_memory_cards(sel.get("mems_friend", []))

            seed = int(time.time() * 1000000) % (2**31)
            random.seed(seed)

            config = BattleConfig()
            config.max_turns = 5
            config.enable_rdps = global_vals.get("enable_rdps", True)
            config.enable_rdps_tracking = True

            controller = TacticalExerciseController(bf, data_loader=self.app.data_loader,
                                                    config=config, narrative=narrative)
            result = controller.execute_battle()

            log_dir = _BASE_PATH / "data" / "battle_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"tactical_exercise_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            narrative.write(str(log_path))

            winner_text = "胜利" if result['winner'] == 'FRIEND' else ("败北" if result['winner'] == 'ENEMY' else "超时")
            stages = result.get("stages_cleared", 0)
            turns = result["total_turns"]
            score_data = result.get("score")
            rdps_data = result.get("rdps")
            tracking_log = result.get("rdps_tracking_log") or []

            self.app.root.after(0, lambda: self._display_single_result(
                winner_text, stages, turns, str(log_path), score_data, rdps_data, tracking_log))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_single_result(self, winner_text, stages, turns, log_path, score_data=None, rdps_data=None, tracking_log=None):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        if tracking_log is not None:
            self._rdps_tracking_log = tracking_log
        self._progress_var.set("完成!")
        self._result_panel.clear()
        out = []
        out.append("=" * 60)
        out.append(f"  战术演习结果: {winner_text}")
        out.append(f"  清除阶段数: {stages}")
        out.append(f"  总回合数: {turns}")
        out.append(f"  日志文件: {log_path}")
        if tracking_log:
            out.append(f"  RDPS追踪日志: {len(tracking_log)} 行（可点击\"导出RDPS日志\"按钮导出）")
        out.append("=" * 60)
        tables = []
        if score_data:
            self._append_score_display(out, score_data, tables)

        if rdps_data:
            out.append(_build_rdps_summary(rdps_data))
            tables.extend(_build_rdps_tables(rdps_data))

        self._result_panel.set_summary("\n".join(out))
        if tables:
            self._result_panel.set_tables(tables)

    def _append_score_display(self, out: list, score_data: dict, tables: list = None):
        """追加计分统计到输出列表

        Args:
            out: 摘要文本行列表
            score_data: 计分数据
            tables: 角色明细表数据列表（可选，传入则用Treeview表格呈现角色明细）
        """
        out.append("")
        out.append("─" * 60)
        out.append(f"  【计分统计】")
        out.append(f"  总得分: {score_data.get('total_score', 0):,}")
        out.append(f"")
        out.append(f"  得分明细:")
        out.append(f"    对敌方造成伤害: +{score_data.get('total_damage_to_enemies', 0):,}")
        out.append(f"    敌方受到回复:   -{score_data.get('enemy_healing_received', 0):,}")
        out.append("")

        # 我方统计
        out.append(f"  【我方合计】")
        out.append(f"    造成伤害: {score_data.get('ally_total_damage_dealt', 0):,}")
        out.append(f"    受到伤害: {score_data.get('ally_total_damage_received', 0):,}")
        out.append(f"    提供回复: {score_data.get('ally_total_hp_healed', 0):,}")
        out.append("")

        # 敌方统计
        out.append(f"  【敌方合计】")
        out.append(f"    造成伤害: {score_data.get('enemy_total_damage_dealt', 0):,}")
        out.append(f"    受到伤害: {score_data.get('enemy_total_damage_received', 0):,}")
        out.append(f"    提供回复: {score_data.get('enemy_total_hp_healed', 0):,}")
        out.append("")

        # 单位明细：转为 Treeview 表格（角色 / 造成伤害 / 受到伤害 / 提供回复）
        unit_stats = score_data.get("unit_stats", {})
        ally_units = {uid: s for uid, s in unit_stats.items() if s.get("side") == "ally"}
        enemy_units = {uid: s for uid, s in unit_stats.items() if s.get("side") == "enemy"}

        if tables is not None:
            # 角色明细用 Treeview 表格呈现（含存活/阵亡状态）
            columns = ["角色", "造成伤害", "受到伤害", "提供回复", "状态"]
            col_widths = [135, 120, 120, 120, 50]
            col_aligns = ["w", "e", "e", "e", "center"]

            if ally_units:
                ally_rows = []
                for uid, s in ally_units.items():
                    name = s.get("name", uid)[:18]
                    status = "存活" if s.get("alive") else "阵亡"
                    ally_rows.append([name,
                                      f"{s.get('damage_dealt', 0):,}",
                                      f"{s.get('damage_received', 0):,}",
                                      f"{s.get('hp_healed', 0):,}",
                                      status])
                tables.append({"title": "我方角色明细", "columns": columns,
                               "rows": ally_rows, "col_widths": col_widths,
                               "col_aligns": col_aligns})

            if enemy_units:
                enemy_rows = []
                for uid, s in enemy_units.items():
                    name = s.get("name", uid)[:18]
                    status = "存活" if s.get("alive") else "阵亡"
                    enemy_rows.append([name,
                                       f"{s.get('damage_dealt', 0):,}",
                                       f"{s.get('damage_received', 0):,}",
                                       f"{s.get('hp_healed', 0):,}",
                                       status])
                tables.append({"title": "敌方角色明细", "columns": columns,
                               "rows": enemy_rows, "col_widths": col_widths,
                               "col_aligns": col_aligns})
        else:
            # 回退：以文本形式输出角色明细（含存活/阵亡状态）
            if ally_units:
                out.append(f"  【我方角色明细】")
                out.append(f"    {_cjk_fit('角色', 20)} {'造成伤害':>12} {'受到伤害':>12} {'提供回复':>12} {'状态':>6}")
                for uid, s in ally_units.items():
                    name = s.get("name", uid)[:18]
                    status = "存活" if s.get("alive") else "阵亡"
                    out.append(f"    {_cjk_fit(name, 20)} {s['damage_dealt']:>12,} {s['damage_received']:>12,} {s['hp_healed']:>12,} {status:>6}")

            if enemy_units:
                out.append(f"")
                out.append(f"  【敌方角色明细】")
                out.append(f"    {_cjk_fit('角色', 20)} {'造成伤害':>12} {'受到伤害':>12} {'提供回复':>12} {'状态':>6}")
                for uid, s in enemy_units.items():
                    name = s.get("name", uid)[:18]
                    status = "存活" if s.get("alive") else "阵亡"
                    out.append(f"    {_cjk_fit(name, 20)} {s['damage_dealt']:>12,} {s['damage_received']:>12,} {s['hp_healed']:>12,} {status:>6}")

        out.append("─" * 60)

    def _append_multi_score_display(self, out: list, score_stats: dict, n: int, tables: list = None):
        """追加多场模拟计分统计到输出列表"""
        out.append("")
        out.append("─" * 60)
        out.append(f"  【计分统计 ({n} 场平均值)】")
        out.append(f"  场均得分: {score_stats.get('mean_score', 0):,.1f}")
        out.append(f"")
        out.append(f"  得分分布:")
        out.append(f"    最高分: {score_stats.get('max_score', 0):,}")
        out.append(f"    最低分: {score_stats.get('min_score', 0):,}")
        out.append(f"    Q1 (第25百分位): {score_stats.get('q1_score', 0):,.1f}")
        out.append(f"    Q3 (第75百分位): {score_stats.get('q3_score', 0):,.1f}")
        out.append(f"    标准差: {score_stats.get('stdev_score', 0):,.1f}")
        out.append(f"")

        # 得分明细（平均值）
        out.append(f"  得分明细（场均）:")
        out.append(f"    对敌方造成伤害: +{score_stats.get('mean_damage_to_enemies', 0):,.1f}")
        out.append(f"    敌方受到回复:   -{score_stats.get('mean_enemy_healing_received', 0):,.1f}")
        out.append("")

        # 我方统计（平均值）
        out.append(f"  【我方合计（场均）】")
        out.append(f"    造成伤害: {score_stats.get('mean_ally_damage', 0):,.1f}")
        out.append(f"    受到伤害: {score_stats.get('mean_ally_received', 0):,.1f}")
        out.append(f"    提供回复: {score_stats.get('mean_ally_healed', 0):,.1f}")
        out.append("")

        # 敌方统计（平均值）
        out.append(f"  【敌方合计（场均）】")
        out.append(f"    造成伤害: {score_stats.get('mean_enemy_damage', 0):,.1f}")
        out.append(f"    受到伤害: {score_stats.get('mean_enemy_received', 0):,.1f}")
        out.append(f"    提供回复: {score_stats.get('mean_enemy_healed', 0):,.1f}")
        out.append("")

        # 特殊值日志导出提示
        out.append(f"  ── 特殊值日志导出 ──")
        max_rec = score_stats.get("max_record")
        min_rec = score_stats.get("min_record")
        q1_rec = score_stats.get("q1_record")
        q3_rec = score_stats.get("q3_record")
        if max_rec:
            out.append(f"    最高分: {max_rec[0]:,} (第{max_rec[1]+1}场)")
        if min_rec:
            out.append(f"    最低分: {min_rec[0]:,} (第{min_rec[1]+1}场)")
        if q1_rec:
            out.append(f"    Q1分数: {q1_rec[0]:,} (第{q1_rec[1]+1}场)")
        if q3_rec:
            out.append(f"    Q3分数: {q3_rec[0]:,} (第{q3_rec[1]+1}场)")
        out.append(f"    （点击下方按钮导出对应战斗日志）")
        out.append("─" * 60)

        # 存储导出所需的上下文
        self._score_stats_cache = score_stats

        # 角色明细表格（场均）：聚合 all_unit_stats（含存活率）
        if tables is not None:
            all_unit_stats = score_stats.get("all_unit_stats", [])
            if all_unit_stats:
                ally_agg: Dict[str, Dict[str, Any]] = {}
                enemy_agg: Dict[str, Dict[str, Any]] = {}
                for unit_stats in all_unit_stats:
                    for uid, s in unit_stats.items():
                        side = s.get("side", "ally")
                        target = ally_agg if side == "ally" else enemy_agg
                        if uid not in target:
                            target[uid] = {"name": s.get("name", uid),
                                           "damage_dealt": 0, "damage_received": 0,
                                           "hp_healed": 0, "survivals": 0, "deaths": 0}
                        target[uid]["damage_dealt"] += s.get("damage_dealt", 0)
                        target[uid]["damage_received"] += s.get("damage_received", 0)
                        target[uid]["hp_healed"] += s.get("hp_healed", 0)
                        if s.get("alive"):
                            target[uid]["survivals"] += 1
                        else:
                            target[uid]["deaths"] += 1

                columns = ["角色", "造成伤害", "受到伤害", "提供回复", "存活率"]
                col_widths = [135, 120, 120, 120, 70]
                col_aligns = ["w", "e", "e", "e", "center"]

                if ally_agg:
                    ally_rows = []
                    for uid, s in ally_agg.items():
                        surv = s["survivals"]
                        death = s["deaths"]
                        sr = surv / (surv + death) * 100 if (surv + death) else 0
                        ally_rows.append([s["name"][:18],
                                          f"{s['damage_dealt'] / n:,.1f}",
                                          f"{s['damage_received'] / n:,.1f}",
                                          f"{s['hp_healed'] / n:,.1f}",
                                          f"{sr:.1f}%"])
                    tables.append({"title": "我方角色明细(场均)", "columns": columns,
                                   "rows": ally_rows, "col_widths": col_widths,
                                   "col_aligns": col_aligns})

                if enemy_agg:
                    enemy_rows = []
                    for uid, s in enemy_agg.items():
                        surv = s["survivals"]
                        death = s["deaths"]
                        sr = surv / (surv + death) * 100 if (surv + death) else 0
                        enemy_rows.append([s["name"][:18],
                                           f"{s['damage_dealt'] / n:,.1f}",
                                           f"{s['damage_received'] / n:,.1f}",
                                           f"{s['hp_healed'] / n:,.1f}",
                                           f"{sr:.1f}%"])
                    tables.append({"title": "敌方角色明细(场均)", "columns": columns,
                                   "rows": enemy_rows, "col_widths": col_widths,
                                   "col_aligns": col_aligns})

    @staticmethod
    def _calculate_quantile(data: list, q: float) -> float:
        """计算分位数（使用线性插值法）

        Args:
            data: 排序后的数值列表
            q: 分位点（0.0 ~ 1.0）

        Returns:
            分位数值。若数据不足则返回最接近的极值。
        """
        if not data:
            return 0.0
        n = len(data)
        if n == 1:
            return float(data[0])
        if n < 4:
            # 样本不足4个时，Q1返回最小，Q3返回最大
            if q <= 0.5:
                return float(data[0])
            else:
                return float(data[-1])

        idx = q * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo

        return data[lo] * (1 - frac) + data[hi] * frac

    @staticmethod
    def _find_quantile_record(sorted_records: list, q: float):
        """在排序后的记录列表中查找最接近指定分位数的记录

        Args:
            sorted_records: 按分数排序的 [(score, run_idx, seed, result), ...]
            q: 分位点

        Returns:
            最接近该分位数的记录元组
        """
        if not sorted_records:
            return None
        n = len(sorted_records)
        idx = int(q * (n - 1))
        idx = max(0, min(idx, n - 1))
        return sorted_records[idx]

    def _compute_score_statistics(self, all_scores, all_ally_damage, all_ally_received,
                                   all_ally_healed, all_enemy_damage, all_enemy_received,
                                   all_enemy_healed, all_enemy_healing_received) -> dict:
        """计算多场模拟的得分统计

        Returns:
            包含各类统计值的字典
        """
        sorted_scores = sorted(all_scores)

        def _mean(lst):
            return sum(lst) / len(lst) if lst else 0.0

        def _stdev(lst, mean_val):
            if len(lst) < 2:
                return 0.0
            variance = sum((x - mean_val) ** 2 for x in lst) / (len(lst) - 1)
            return variance ** 0.5

        mean_score = _mean(all_scores)

        return {
            "mean_score": mean_score,
            "max_score": max(all_scores),
            "min_score": min(all_scores),
            "q1_score": self._calculate_quantile(sorted_scores, 0.25),
            "q3_score": self._calculate_quantile(sorted_scores, 0.75),
            "stdev_score": _stdev(all_scores, mean_score),
            "mean_damage_to_enemies": _mean(all_ally_damage),
            "mean_enemy_healing_received": _mean(all_enemy_healing_received),
            "mean_ally_damage": _mean(all_ally_damage),
            "mean_ally_received": _mean(all_ally_received),
            "mean_ally_healed": _mean(all_ally_healed),
            "mean_enemy_damage": _mean(all_enemy_damage),
            "mean_enemy_received": _mean(all_enemy_received),
            "mean_enemy_healed": _mean(all_enemy_healed),
        }

    def _export_special_log(self, record, log_label: str, sel: dict):
        """导出特殊值对应的战斗日志

        Args:
            record: (score, run_idx, seed, result) 元组
            log_label: 日志标签（如 "最高分"、"Q1"）
            sel: 编队选择信息
        """
        if not record:
            messagebox.showwarning("无数据", f"没有可导出的{log_label}记录")
            return

        score, run_idx, seed, _ = record

        log_dir = _BASE_PATH / "data" / "battle_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"tactical_exercise_{log_label}_{score}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        self._start_btn.config(state="disabled")
        self._log_btn.config(state="disabled")
        self._progress_var.set(f"正在导出{log_label}日志...")

        def _do_export():
            try:
                # 先创建panel_config等（与批量运行一致，在seed之前）
                global_vals = self.app.global_tab.get_values()
                panel_config = self.app._build_panel_config_from_gui(global_vals)
                player_config = panel_config.get_player_config()
                lerp_data = self.app.data_loader.load_level_lerp_data()
                stat_calculator = StatCalculator(lerp_data, data_loader=self.app.data_loader)
                narrative = BattleNarrativeWriter()

                # seed在创建单位之前（与批量运行路径一致）
                random.seed(seed)

                friend_positions = sel.get("friend_positions", sel.get("friends", []))
                bf = BattlefieldState()

                for i, cid in enumerate(friend_positions):
                    if cid is not None:
                        u = self.app._create_unit(panel_config, player_config, stat_calculator,
                                                  cid, Side.ALLY, GRID_ALLY_POSITIONS[i])
                        if u:
                            bf.add_unit(u)

                enemy_data = self._enemy_data.get(sel["enemy_id"])
                if enemy_data:
                    enemy_unit = self._create_tactical_enemy(enemy_data, bf)
                    if enemy_unit:
                        bf.add_unit(enemy_unit)

                bf.memory_cards = self.app.team_tab._build_memory_cards(
                    sel.get("mems_friend", []))

                config = BattleConfig()
                config.max_turns = 5

                controller = TacticalExerciseController(bf, data_loader=self.app.data_loader,
                                                        config=config, narrative=narrative)
                result = controller.execute_battle()
                narrative.write(str(log_path))

                score_data = result.get("score", {})
                export_score = score_data.get("total_score", 0) if score_data else 0
                stages = result.get("stages_cleared", 0)

                def _on_done():
                    self._start_btn.config(state="normal")
                    self._log_btn.config(state="normal")
                    self._progress_var.set("完成!")
                    msg = (f"{log_label}日志已导出:\n{log_path}\n"
                           f"得分: {export_score:,}  阶段: {stages}")
                    if export_score != score:
                        msg += f"\n⚠ 注意: 导出得分({export_score:,})与记录得分({score:,})不一致，可能是计分逻辑已更新"
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
        """导出最高分日志"""
        cache = getattr(self, '_score_stats_cache', {})
        rec = cache.get("max_record")
        sel = cache.get("sel")
        if rec and sel:
            self._export_special_log(rec, "最高分", sel)

    def _export_min_log(self):
        """导出最低分日志"""
        cache = getattr(self, '_score_stats_cache', {})
        rec = cache.get("min_record")
        sel = cache.get("sel")
        if rec and sel:
            self._export_special_log(rec, "最低分", sel)

    def _export_q1_log(self):
        """导出Q1分日志"""
        cache = getattr(self, '_score_stats_cache', {})
        rec = cache.get("q1_record")
        sel = cache.get("sel")
        if rec and sel:
            self._export_special_log(rec, "Q1", sel)

    def _export_q3_log(self):
        """导出Q3分日志"""
        cache = getattr(self, '_score_stats_cache', {})
        rec = cache.get("q3_record")
        sel = cache.get("sel")
        if rec and sel:
            self._export_special_log(rec, "Q3", sel)

    # ── 配置预设管理 ──

    def _refresh_tactical_presets(self):
        """刷新战术演习预设列表"""
        self._tactical_preset_listbox.delete(0, tk.END)
        TACTICAL_PRESET_DIR.mkdir(parents=True, exist_ok=True)
        for f in sorted(TACTICAL_PRESET_DIR.glob("*.json")):
            self._tactical_preset_listbox.insert(tk.END, f.stem)

    def _save_tactical_preset(self):
        """保存战术演习配置"""
        name = self._tactical_preset_name_var.get().strip()
        if not name:
            messagebox.showwarning("名称", "请输入预设名称")
            return

        sel = self._get_selection()
        TACTICAL_PRESET_DIR.mkdir(parents=True, exist_ok=True)
        path = TACTICAL_PRESET_DIR / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sel, f, ensure_ascii=False, indent=2)
        self._refresh_tactical_presets()
        messagebox.showinfo("保存", f"战术演习配置 '{name}' 已保存")

    def _load_tactical_preset(self):
        """加载战术演习配置"""
        sel_idx = self._tactical_preset_listbox.curselection()
        if not sel_idx:
            return
        name = self._tactical_preset_listbox.get(sel_idx[0])
        path = TACTICAL_PRESET_DIR / f"{name}.json"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 加载己方编队
        friend_positions = data.get("friend_positions")
        if friend_positions is not None:
            for i, cid in enumerate(friend_positions):
                if i < len(self.friend_slots):
                    if cid is not None:
                        self._set_slot_char(self.friend_slots[i], cid)
                    else:
                        self._clear_slot(self.friend_slots[i])
            for i in range(len(friend_positions), len(self.friend_slots)):
                self._clear_slot(self.friend_slots[i])
        else:
            for i, cid in enumerate(data.get("friends", [])):
                if i < len(self.friend_slots):
                    self._set_slot_char(self.friend_slots[i], cid)
            for i in range(len(data.get("friends", [])), len(self.friend_slots)):
                self._clear_slot(self.friend_slots[i])

        # 加载敌方选择
        enemy_id = data.get("enemy_id")
        if enemy_id is not None and enemy_id in self._enemy_data:
            self._on_enemy_select(enemy_id)

        # 加载回忆卡
        mem_friend_positions = data.get("mem_friend_positions")
        if mem_friend_positions is not None:
            for i, mem_entry in enumerate(mem_friend_positions):
                if i < len(self.mem_friend_slots):
                    mid = self._parse_memory_card_id(mem_entry) if mem_entry else None
                    if mid is not None:
                        self._set_mem_slot(i, mid)
                    else:
                        self._clear_mem_slot(i)
            for i in range(len(mem_friend_positions), len(self.mem_friend_slots)):
                self._clear_mem_slot(i)
        else:
            mems = data.get("mems_friend", [])
            for i, mem_entry in enumerate(mems):
                if i < len(self.mem_friend_slots):
                    mid = self._parse_memory_card_id(mem_entry) if mem_entry else None
                    if mid is not None:
                        self._set_mem_slot(i, mid)
                    else:
                        self._clear_mem_slot(i)
            for i in range(len(mems), len(self.mem_friend_slots)):
                self._clear_mem_slot(i)

    def _delete_tactical_preset(self):
        """删除战术演习配置"""
        sel_idx = self._tactical_preset_listbox.curselection()
        if not sel_idx:
            return
        name = self._tactical_preset_listbox.get(sel_idx[0])
        path = TACTICAL_PRESET_DIR / f"{name}.json"
        if path.exists():
            os.remove(path)
            self._refresh_tactical_presets()
