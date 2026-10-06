# -*- coding: utf-8 -*-
"""逐步暴击 Tab - 精确控制每hit暴击结果，用于对照视频debug。

从 gui_app.py 抽取，通过 self.app 访问主类。
"""

import json
import os
import random
import time
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from src.data.stat_calculator import StatCalculator
from src.entities_v2.battlefield_state import BattlefieldState
from src.entities_v2.enums import Side
from src.combat_v2.battle_flow_controller import BattleFlowController, BattleConfig
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController
from src.combat_v2.battle_narrative import BattleNarrativeWriter

from gui.constants import (
    _BASE_PATH,
    _DARK_ACCENT,
    _DARK_FG,
    _DARK_INPUT_BG,
    _DARK_SELECT_BG,
    _DARK_SELECT_FG,
    CIRCLE_PRESET_DIR,
    COMPOSITE_PRESET_DIR,
    CRIT_SEQUENCE_DIR,
    GRID_ALLY_POSITIONS,
    GRID_ENEMY_POSITIONS,
    PRESET_DIR,
    TACTICAL_PRESET_DIR,
)
from gui.utils import _cjk_fit


class StepCritTab(ttk.Frame):
    """逐步暴击模拟器 - 精确控制每hit暴击结果，用于对照视频debug"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._simulator = None
        self._battle_thread = None
        self._poll_after_id = None
        # 战斗配置缓存（用于回退重启）
        self._last_battle_sel = None
        self._last_battle_seed = None
        self._last_battle_preset_type = None
        # 分支决策状态
        self._branch_btns = []  # 动态生成的分支候选按钮列表
        self._branch_candidate_block_ids = []  # 当前分支决策点的候选 block_id 列表
        self._current_branch_decision_type = "branch"  # 当前分支决策点类型: "branch" / "random_draw"
        # Canvas 引用（用于滚动）
        self._left_canvas = None
        # 命令台日志内存捕获 handler（交互式模式中途导出用）
        self._console_log_handler = None
        self._build()

    def _build(self):
        s = self.app._get_scheme()
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ── 左侧：配置面板（带滚动条） ──
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=3)

        # Canvas + Scrollbar 实现滚动
        left_canvas = tk.Canvas(left_frame, bg=s["surface"], highlightthickness=0)
        left_scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)

        left_scrollbar.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill=tk.BOTH, expand=True)

        f = ttk.Frame(left_canvas)
        f.bind("<Configure>", lambda e: left_canvas.configure(
            scrollregion=left_canvas.bbox("all")
        ))
        _canvas_window = left_canvas.create_window((0, 0), window=f, anchor="nw",
                                                    width=left_canvas.winfo_width())
        # Canvas 宽度变化时同步更新内部 frame 宽度
        def _on_canvas_resize(event):
            left_canvas.itemconfig(_canvas_window, width=event.width)
        left_canvas.bind("<Configure>", _on_canvas_resize)
        # 鼠标滚轮支持（参考其他页面：Enter/Leave + bind_all/unbind_all）
        def _on_mousewheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _enter_canvas(event):
            left_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _leave_canvas(event):
            left_canvas.unbind_all("<MouseWheel>")
        left_canvas.bind("<Enter>", _enter_canvas)
        left_canvas.bind("<Leave>", _leave_canvas)
        # 记录以便清理
        self._left_canvas = left_canvas

        # ── 模式选择 ──
        mode_frame = ttk.LabelFrame(f, text="模式选择")
        mode_frame.pack(fill="x", padx=10, pady=5)

        self.mode_var = tk.StringVar(value="sequence")
        ttk.Radiobutton(mode_frame, text="预填序列模式", variable=self.mode_var,
                        value="sequence", command=self._on_mode_change).pack(anchor="w", padx=5)
        ttk.Radiobutton(mode_frame, text="交互式模式", variable=self.mode_var,
                        value="interactive", command=self._on_mode_change).pack(anchor="w", padx=5)

        # ── 预设选择 ──
        preset_frame = ttk.LabelFrame(f, text="预设选择")
        preset_frame.pack(fill="x", padx=10, pady=5)

        # 战斗模式：编队与战斗 / 战术演习 / 对抗压制战 / 复合战术演习
        battle_mode_frame = ttk.Frame(preset_frame)
        battle_mode_frame.pack(fill="x", padx=5, pady=2)
        self.battle_mode_var = tk.StringVar(value="team")
        ttk.Radiobutton(battle_mode_frame, text="编队与战斗", variable=self.battle_mode_var,
                        value="team", command=self._on_battle_mode_change).pack(side="left", padx=5)
        ttk.Radiobutton(battle_mode_frame, text="战术演习", variable=self.battle_mode_var,
                        value="tactical", command=self._on_battle_mode_change).pack(side="left", padx=5)
        ttk.Radiobutton(battle_mode_frame, text="对抗压制战", variable=self.battle_mode_var,
                        value="circle", command=self._on_battle_mode_change).pack(side="left", padx=5)
        ttk.Radiobutton(battle_mode_frame, text="复合战术演习", variable=self.battle_mode_var,
                        value="composite", command=self._on_battle_mode_change).pack(side="left", padx=5)

        # 预设列表
        preset_list_frame = ttk.Frame(preset_frame)
        preset_list_frame.pack(fill="x", padx=5, pady=2)

        self._preset_listbox = tk.Listbox(preset_list_frame, height=5, width=30,
                                          bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                          selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                          borderwidth=0, highlightthickness=0,
                                          font=("Microsoft YaHei UI", 9))
        self._preset_listbox.pack(side="left", fill="both", expand=True)

        preset_btn_frame = ttk.Frame(preset_list_frame)
        preset_btn_frame.pack(side="right", padx=5)
        ttk.Button(preset_btn_frame, text="加载预设", command=self._load_preset).pack(fill="x", pady=2)
        ttk.Button(preset_btn_frame, text="刷新列表", command=self._refresh_presets).pack(fill="x", pady=2)

        # 当前预设信息
        self._preset_info_var = tk.StringVar(value="未加载预设（将使用「编队与战斗」标签页的配置）")
        ttk.Label(preset_frame, textvariable=self._preset_info_var, font=("Microsoft YaHei UI", 8),
                  foreground="gray", wraplength=400, justify="left").pack(fill="x", padx=5, pady=2)

        self._loaded_preset_data = None  # 当前加载的预设数据
        self._loaded_preset_type = None  # "team" / "tactical" / "circle" / "composite"

        self._refresh_presets()

        # ── 预填序列 ──
        seq_frame = ttk.LabelFrame(f, text="暴击序列（C=暴击, N=不暴击, 空格/逗号分隔可选）")
        seq_frame.pack(fill="x", padx=10, pady=5)

        self.seq_var = tk.StringVar(value="")
        self.seq_entry = ttk.Entry(seq_frame, textvariable=self.seq_var, width=50)
        self.seq_entry.pack(fill="x", padx=5, pady=2)

        hint = ttk.Label(seq_frame, text="示例: CNNCCN 或 C,N,N,C,C,N  序列用完后回退随机",
                         font=("Microsoft YaHei UI", 8), foreground="gray")
        hint.pack(anchor="w", padx=5)

        # ── 随机种子 ──
        seed_frame = ttk.LabelFrame(f, text="随机种子（序列用完后的回退随机用）")
        seed_frame.pack(fill="x", padx=10, pady=5)

        seed_inner = ttk.Frame(seed_frame)
        seed_inner.pack(fill="x", padx=5, pady=2)
        self.seed_var = tk.StringVar(value="")
        ttk.Entry(seed_inner, textvariable=self.seed_var, width=20).pack(side="left", padx=2)
        ttk.Button(seed_inner, text="随机", command=self._random_seed).pack(side="left", padx=2)

        # ── 交互式控制 ──
        self.interact_frame = ttk.LabelFrame(f, text="交互式控制")
        self.interact_frame.pack(fill="x", padx=10, pady=5)

        # 预填序列（交互式模式下自动应用到指定步骤）
        prefill_frame = ttk.Frame(self.interact_frame)
        prefill_frame.pack(fill="x", padx=5, pady=2)
        ttk.Label(prefill_frame, text="预填序列:").pack(side="left")
        self.prefill_var = tk.StringVar(value="")
        self.prefill_entry = ttk.Entry(prefill_frame, textvariable=self.prefill_var, width=30)
        self.prefill_entry.pack(side="left", padx=2, fill="x", expand=True)
        ttk.Label(prefill_frame, text="(自动应用到指定步骤后切换交互)", font=("Microsoft YaHei UI", 7),
                  foreground="gray").pack(side="left", padx=2)

        self.current_decision_label = ttk.Label(self.interact_frame, text="等待开始...",
                                                font=("Microsoft YaHei UI", 10), wraplength=400, justify="left")
        self.current_decision_label.pack(fill="x", padx=5, pady=5)

        btn_frame = ttk.Frame(self.interact_frame)
        btn_frame.pack(fill="x", padx=5, pady=2)

        self.crit_btn = ttk.Button(btn_frame, text="★ 暴击 (C)", command=lambda: self._make_decision(True),
                                   state="disabled")
        self.crit_btn.pack(side="left", padx=5, expand=True, fill="x")

        self.no_crit_btn = ttk.Button(btn_frame, text="· 不暴击 (N)", command=lambda: self._make_decision(False),
                                      state="disabled")
        self.no_crit_btn.pack(side="left", padx=5, expand=True, fill="x")

        self.undo_btn = ttk.Button(btn_frame, text="↩ 回退", command=self._undo_step,
                                   state="disabled")
        self.undo_btn.pack(side="left", padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self._stop_interactive,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=5)

        # 序列保存/加载按钮行
        seq_action_frame = ttk.Frame(self.interact_frame)
        seq_action_frame.pack(fill="x", padx=5, pady=2)

        self.save_seq_btn = ttk.Button(seq_action_frame, text="保存序列", command=self._save_sequence,
                                       state="disabled")
        self.save_seq_btn.pack(side="left", padx=2)

        self.load_seq_btn = ttk.Button(seq_action_frame, text="加载序列", command=self._load_sequence)
        self.load_seq_btn.pack(side="left", padx=2)

        self.delete_seq_btn = ttk.Button(seq_action_frame, text="删除序列", command=self._delete_sequence)
        self.delete_seq_btn.pack(side="left", padx=2)

        self.export_console_btn = ttk.Button(seq_action_frame, text="导出命令台",
                                             command=self._export_console_log, state="disabled")
        self.export_console_btn.pack(side="left", padx=2)

        # 当前序列进度显示
        self.seq_progress_var = tk.StringVar(value="")
        ttk.Label(seq_action_frame, textvariable=self.seq_progress_var, font=("Microsoft YaHei UI", 8),
                  foreground="gray", wraplength=350, justify="left").pack(side="left", padx=5)

        # ── 分支决策面板（random_choice / probability 分支选择） ──
        self.branch_frame = ttk.LabelFrame(f, text="分支决策")
        self.branch_frame.pack(fill="x", padx=10, pady=5)

        # 分支预填序列
        branch_prefill_frame = ttk.Frame(self.branch_frame)
        branch_prefill_frame.pack(fill="x", padx=5, pady=2)
        ttk.Label(branch_prefill_frame, text="分支预填:").pack(side="left")
        self.branch_prefill_var = tk.StringVar(value="")
        self.branch_prefill_entry = ttk.Entry(branch_prefill_frame, textvariable=self.branch_prefill_var, width=30)
        self.branch_prefill_entry.pack(side="left", padx=2, fill="x", expand=True)
        ttk.Label(branch_prefill_frame, text="(block_id逗号分隔, 如 1,2,5,6)",
                  font=("Microsoft YaHei UI", 7), foreground="gray").pack(side="left", padx=2)

        # 当前分支决策点信息
        self.branch_decision_label = ttk.Label(self.branch_frame, text="等待分支决策点...",
                                               font=("Microsoft YaHei UI", 10), wraplength=400, justify="left")
        self.branch_decision_label.pack(fill="x", padx=5, pady=5)

        # 候选分支按钮容器（动态生成）
        self._branch_btn_frame = ttk.Frame(self.branch_frame)
        self._branch_btn_frame.pack(fill="x", padx=5, pady=2)

        # ── 操作按钮 ──
        action_frame = ttk.Frame(f)
        action_frame.pack(fill="x", padx=10, pady=5)

        self.start_btn = ttk.Button(action_frame, text="开始模拟", command=self._start_simulation)
        self.start_btn.pack(side="left", padx=5)

        self.report_btn = ttk.Button(action_frame, text="生成报告", command=self._show_report,
                                     state="disabled")
        self.report_btn.pack(side="left", padx=5)

        # ── 统计信息 ──
        self.stats_label = ttk.Label(f, text="", font=("Microsoft YaHei UI", 9))
        self.stats_label.pack(fill="x", padx=10, pady=2)

        # ── 右侧：输出面板 ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=7)

        self.output_text = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD,
                                                      font=("Consolas", 9), state="disabled",
                                                      bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                                      insertbackground=_DARK_FG,
                                                      selectbackground=_DARK_SELECT_BG,
                                                      selectforeground=_DARK_SELECT_FG)
        self.output_text.pack(fill=tk.BOTH, expand=True)

        # 键盘快捷键
        self.bind("<Key-c>", lambda e: self._make_decision(True))
        self.bind("<Key-n>", lambda e: self._make_decision(False))
        self.bind("<Key-z>", lambda e: self._undo_step())
        self.output_text.bind("<Key-c>", lambda e: self._make_decision(True))
        self.output_text.bind("<Key-n>", lambda e: self._make_decision(False))
        self.output_text.bind("<Key-z>", lambda e: self._undo_step())
        # 数字键 1-9 快速选择分支候选
        for i in range(1, 10):
            self.bind(f"<Key-{i}>", lambda e, idx=i - 1: self._branch_quick_select(idx))
            self.output_text.bind(f"<Key-{i}>", lambda e, idx=i - 1: self._branch_quick_select(idx))

        self._on_mode_change()

    def _on_mode_change(self):
        is_interactive = self.mode_var.get() == "interactive"
        self.seq_entry.config(state="normal" if not is_interactive else "disabled")
        self.prefill_entry.config(state="normal" if is_interactive else "disabled")
        self.crit_btn.config(state="normal" if is_interactive and self._simulator and self._simulator.is_interactive_running() else "disabled")
        self.no_crit_btn.config(state="normal" if is_interactive and self._simulator and self._simulator.is_interactive_running() else "disabled")

    def _on_battle_mode_change(self):
        """战斗模式切换时刷新预设列表"""
        self._refresh_presets()
        self._loaded_preset_data = None
        self._loaded_preset_type = None
        self._preset_info_var.set("未加载预设（将使用「编队与战斗」标签页的配置）")

    def _refresh_presets(self):
        """刷新预设列表"""
        self._preset_listbox.delete(0, tk.END)
        mode = self.battle_mode_var.get()
        if mode == "team":
            PRESET_DIR.mkdir(parents=True, exist_ok=True)
            for f in sorted(PRESET_DIR.glob("*.json")):
                self._preset_listbox.insert(tk.END, f"[编队] {f.stem}")
        elif mode == "tactical":
            TACTICAL_PRESET_DIR.mkdir(parents=True, exist_ok=True)
            for f in sorted(TACTICAL_PRESET_DIR.glob("*.json")):
                self._preset_listbox.insert(tk.END, f"[演习] {f.stem}")
        elif mode == "circle":
            CIRCLE_PRESET_DIR.mkdir(parents=True, exist_ok=True)
            for f in sorted(CIRCLE_PRESET_DIR.glob("*.json")):
                self._preset_listbox.insert(tk.END, f"[压制] {f.stem}")
        elif mode == "composite":
            COMPOSITE_PRESET_DIR.mkdir(parents=True, exist_ok=True)
            for f in sorted(COMPOSITE_PRESET_DIR.glob("*.json")):
                self._preset_listbox.insert(tk.END, f"[复合] {f.stem}")

    def _load_preset(self):
        """加载选中的预设"""
        sel = self._preset_listbox.curselection()
        if not sel:
            messagebox.showwarning("预设", "请先选择一个预设")
            return

        item_text = self._preset_listbox.get(sel[0])
        # 解析预设名称（去掉前缀 "[编队] " / "[演习] " / "[压制] " / "[复合] "）
        preset_name = item_text.split("] ", 1)[1] if "] " in item_text else item_text

        mode = self.battle_mode_var.get()
        if mode == "team":
            path = PRESET_DIR / f"{preset_name}.json"
        elif mode == "tactical":
            path = TACTICAL_PRESET_DIR / f"{preset_name}.json"
        elif mode == "circle":
            path = CIRCLE_PRESET_DIR / f"{preset_name}.json"
        else:
            path = COMPOSITE_PRESET_DIR / f"{preset_name}.json"

        if not path.exists():
            messagebox.showerror("预设", f"预设文件不存在: {path}")
            return

        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)

        self._loaded_preset_data = data
        self._loaded_preset_type = mode

        # 显示预设信息
        if mode == "team":
            friends = [cid for cid in data.get("friend_positions", data.get("friends", [])) if cid]
            enemies = [cid for cid in data.get("enemy_positions", data.get("enemies", [])) if cid]
            if self.app.is_developer_mode():
                self._preset_info_var.set(
                    f"已加载编队预设: {preset_name}\n"
                    f"己方: {friends} | 敌方: {enemies}"
                )
            else:
                friend_names = [self.app.format_char_name(self.app.data_loader.get_character_by_id(cid)) or str(cid) for cid in friends]
                enemy_names = [self.app.format_char_name(self.app.data_loader.get_character_by_id(cid)) or str(cid) for cid in enemies]
                self._preset_info_var.set(
                    f"已加载编队预设: {preset_name}\n"
                    f"己方: {', '.join(friend_names)} | 敌方: {', '.join(enemy_names)}"
                )
        elif mode == "tactical":
            friends = [cid for cid in data.get("friend_positions", data.get("friends", [])) if cid]
            enemy_id = data.get("enemy_id", "?")
            if self.app.is_developer_mode():
                self._preset_info_var.set(
                    f"已加载演习预设: {preset_name}\n"
                    f"己方: {friends} | 敌方ID: {enemy_id}"
                )
            else:
                friend_names = [self.app.format_char_name(self.app.data_loader.get_character_by_id(cid)) or str(cid) for cid in friends]
                enemy_data = self.app.data_loader.get_tactical_exercise_enemies().get(enemy_id)
                enemy_name = enemy_data["character_name"] if enemy_data else str(enemy_id)
                self._preset_info_var.set(
                    f"已加载演习预设: {preset_name}\n"
                    f"己方: {', '.join(friend_names)} | 敌方: {enemy_name}"
                )
        elif mode == "circle":
            friends = [cid for cid in data.get("friend_positions", data.get("friends", [])) if cid]
            season = data.get("season", "?")
            stage = data.get("stage", "?")
            if self.app.is_developer_mode():
                self._preset_info_var.set(
                    f"已加载压制战预设: {preset_name}\n"
                    f"己方: {friends} | 赛季{season} 阶段{stage}"
                )
            else:
                friend_names = [self.app.format_char_name(self.app.data_loader.get_character_by_id(cid)) or str(cid) for cid in friends]
                self._preset_info_var.set(
                    f"已加载压制战预设: {preset_name}\n"
                    f"己方: {', '.join(friend_names)} | 赛季{season} 阶段{stage}"
                )
        else:  # composite
            teams_positions = data.get("teams_positions", [])
            if self.app.is_developer_mode():
                teams_desc = " | ".join(
                    f"队{i+1}: {[c for c in t if c]}"
                    for i, t in enumerate(teams_positions)
                )
                self._preset_info_var.set(f"已加载复合演习预设: {preset_name}\n{teams_desc}")
            else:
                parts = []
                for i, t in enumerate(teams_positions):
                    names = []
                    for cid in t:
                        if cid:
                            char = self.app.data_loader.get_character_by_id(cid)
                            names.append(self.app.format_char_name(char) if char else str(cid))
                    parts.append(f"队{i+1}: {', '.join(names) if names else '空'}")
                self._preset_info_var.set(f"已加载复合演习预设: {preset_name}\n{' | '.join(parts)}")

    def _random_seed(self):
        import random as _r
        self.seed_var.set(str(_r.randint(0, 2**31 - 1)))

    def _make_decision(self, is_crit: bool):
        if self._simulator and self._simulator.is_interactive_running():
            self._simulator.make_interactive_decision(is_crit)
            label = "★暴击" if is_crit else "·不暴击"
            self._append_output(f"\n  → 用户选择: {label}\n")
            self._update_seq_progress()

    # ─── 分支决策方法 ───

    def _make_branch_decision(self, block_id: int):
        """用户选择分支"""
        if self._simulator and self._simulator.is_interactive_running():
            self._simulator.make_interactive_branch_decision(block_id)
            if self._current_branch_decision_type == "random_draw":
                # 找到候选索引对应的描述
                cand_desc = ""
                for i, bid in enumerate(self._branch_candidate_block_ids):
                    if bid == block_id and i < len(self._branch_btns):
                        cand_desc = self._branch_btns[i].cget('text')
                        break
                self._append_output(f"\n  → 用户选择抽取: {cand_desc}\n")
            else:
                self._append_output(f"\n  → 用户选择分支: block {block_id}\n")
            # 禁用分支按钮
            for btn in self._branch_btns:
                btn.config(state="disabled")
            self.branch_decision_label.config(text="分支已选择，继续战斗...")
            # 恢复暴击按钮（如果还在交互模式）
            if self._simulator.is_interactive_running():
                self.crit_btn.config(state="normal")
                self.no_crit_btn.config(state="normal")

    def _branch_quick_select(self, idx: int):
        """数字键快速选择分支候选"""
        if idx < len(self._branch_btns):
            btn = self._branch_btns[idx]
            if str(btn.cget('state')) == 'normal' and idx < len(self._branch_candidate_block_ids):
                self._make_branch_decision(self._branch_candidate_block_ids[idx])

    def _show_branch_candidates(self, point):
        """显示分支候选按钮"""
        # 清空旧按钮
        for widget in self._branch_btn_frame.winfo_children():
            widget.destroy()
        self._branch_btns = []
        self._branch_candidate_block_ids = []
        self._current_branch_decision_type = getattr(point, 'decision_type', 'branch')

        # 动态生成候选按钮
        for i, cand in enumerate(point.candidates):
            btn_text = f"[{i+1}] {cand.probability * 100:.1f}% {cand.description}"
            btn = ttk.Button(self._branch_btn_frame, text=btn_text,
                             command=lambda b=cand.block_id: self._make_branch_decision(b),
                             state="normal")
            btn.pack(fill="x", padx=2, pady=1)
            self._branch_btns.append(btn)
            self._branch_candidate_block_ids.append(cand.block_id)

    def _clear_branch_candidates(self):
        """清空分支候选按钮"""
        for widget in self._branch_btn_frame.winfo_children():
            widget.destroy()
        self._branch_btns = []
        self._branch_candidate_block_ids = []
        self._current_branch_decision_type = "branch"
        self.branch_decision_label.config(text="等待分支决策点...")

    def _undo_step(self):
        """回退一步：停止当前战斗，用去掉最后一步的序列重启"""
        if not self._simulator:
            return

        # 获取当前所有决策
        dps = self._simulator.get_decision_points()
        if len(dps) <= 0:
            return

        # 去掉最后一步
        last_dp = dps[-1]
        new_seq = "".join("C" if dp.is_crit else "N" for dp in dps[:-1])

        self._append_output(f"\n=== 回退: 移除步骤 #{last_dp.index} ({'暴击' if last_dp.is_crit else '不暴击'}) ===\n")
        self._append_output(f"新预填序列: {new_seq if new_seq else '(空，从头开始)'}\n")

        # 保存待重启的序列
        self._pending_restart_seq = new_seq

        # 禁用按钮，防止重复操作
        self.crit_btn.config(state="disabled")
        self.no_crit_btn.config(state="disabled")
        self.undo_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")
        self.current_decision_label.config(text="回退中，等待战斗线程结束...")

        # 停止当前战斗（非阻塞）
        if self._simulator:
            self._simulator.stop_interactive()
        # 取消轮询
        if self._poll_after_id:
            self.app.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None

        # 重置叙事对象引用（旧线程可能还在写入）
        self._interactive_narrative = None

        # 异步等待战斗线程结束后重启（最多等3秒）
        self._undo_wait_count = 0
        self._wait_for_undo_restart()

    def _wait_for_undo_restart(self):
        """异步轮询等待旧战斗线程结束，然后重启"""
        self._undo_wait_count += 1

        # 超时保护：最多等3秒（60次 × 50ms）
        if self._undo_wait_count > 60:
            self._append_output("回退超时，强制重启...\n")
            self._do_restart()
            return

        if self._simulator and hasattr(self._simulator, '_battle_thread') and self._simulator._battle_thread:
            if self._simulator._battle_thread.is_alive():
                # 线程仍在运行，50ms后再检查
                self._poll_after_id = self.app.root.after(50, self._wait_for_undo_restart)
                return

        # 线程已结束，执行重启
        self._do_restart()

    def _do_restart(self):
        """执行回退重启"""
        self.prefill_var.set(self._pending_restart_seq)
        self._restart_with_prefill(self._pending_restart_seq)

    def _restart_with_prefill(self, prefill_seq: str):
        """使用预填序列重启交互式战斗"""
        from src.combat_v2.step_crit_simulator import StepCritSimulator

        if not self._last_battle_sel:
            messagebox.showwarning("回退", "无法回退：未找到上次战斗配置")
            return

        sel = self._last_battle_sel
        seed = self._last_battle_seed
        preset_type = self._last_battle_preset_type

        # 创建新的模拟器
        self._simulator = StepCritSimulator()

        # 设置预填序列
        if prefill_seq.strip():
            self._simulator.set_interactive_prefill(prefill_seq)

        # 设置分支预填序列（回退时保留之前的分支预填）
        branch_prefill_str = self.branch_prefill_var.get().strip()
        if branch_prefill_str:
            try:
                branch_prefill_ids = [int(x.strip()) for x in branch_prefill_str.split(",") if x.strip()]
                self._simulator.set_interactive_branch_prefill(branch_prefill_ids)
            except ValueError:
                pass

        # 设置随机种子
        random.seed(seed)

        # 重置叙事和控制器引用
        self._interactive_narrative = None
        self._interactive_controller = None

        # 挂载命令台日志内存捕获（回退重启后从新战斗开头重新捕获）
        self._attach_console_log_handler()

        # 清空输出
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state="disabled")

        self._append_output(f"=== 逐步暴击模拟器（回退重启） ===\n")
        prefill_count = len([c for c in prefill_seq if c in 'CN10'])
        self._append_output(f"模式: 交互式（预填 {prefill_count} 步）\n")
        type_names = {"team": "编队与战斗", "tactical": "战术演习", "circle": "对抗压制战", "composite": "复合战术演习"}
        self._append_output(f"战斗类型: {type_names.get(preset_type, preset_type)}\n")
        self._append_output(f"随机种子: {seed}\n")
        self._append_output(f"预填序列: {prefill_seq}\n\n")

        # 启用交互式控制
        self.crit_btn.config(state="normal")
        self.no_crit_btn.config(state="normal")
        self.stop_btn.config(state="normal")
        self.undo_btn.config(state="disabled")  # 预填阶段禁用回退
        self.save_seq_btn.config(state="disabled")
        self.export_console_btn.config(state="disabled")  # 预填阶段禁用，到达决策点后启用
        self.start_btn.config(state="disabled")
        self.report_btn.config(state="disabled")
        self.current_decision_label.config(text=f"预填序列执行中... ({prefill_count} 步)")
        self._narrative_line_count = 0
        self._clear_branch_candidates()

        # 保存参数供线程使用
        self._interactive_sel = sel
        self._interactive_seed = seed
        self._interactive_preset_type = preset_type

        def battle_func():
            global_vals = self.app.global_tab.get_values()
            max_turns = global_vals["max_turns"]

            panel_config = self.app._build_panel_config_from_gui(global_vals)
            player_config = panel_config.get_player_config()
            lerp_data = self.app.data_loader.load_level_lerp_data()
            stat_calculator = StatCalculator(lerp_data, data_loader=self.app.data_loader)

            narrative = BattleNarrativeWriter()

            # 构建战场/队伍
            if preset_type == "composite":
                bf, teams_units, teams_mem_cards, boss_unit_id, comp_max_turns = self._build_composite_setup(
                    sel, panel_config, player_config, stat_calculator)
                max_turns = comp_max_turns
            else:
                bf = self._build_battlefield(sel, preset_type, panel_config, player_config, stat_calculator)
                if preset_type == "circle":
                    stage_data = self.app.data_loader.get_circle_battle_stage(sel.get("season"), sel.get("stage"))
                    max_turns = stage_data["max_turn"] if stage_data else max_turns

            random.seed(seed)

            # 创建控制器
            if preset_type == "tactical":
                config = BattleConfig()
                config.max_turns = 5
                controller = TacticalExerciseController(bf, data_loader=self.app.data_loader,
                                                        config=config, narrative=narrative)
            elif preset_type == "circle":
                from src.combat_v2.circle_battle_controller import CircleBattleController
                config = BattleConfig()
                config.max_turns = max_turns
                controller = CircleBattleController(bf, data_loader=self.app.data_loader,
                                                    config=config, narrative=narrative,
                                                    season=sel["season"], stage=sel["stage"],
                                                    enemy_state_overrides=sel.get("enemy_state_overrides"))
            elif preset_type == "composite":
                from src.combat_v2.composite_tactic_controller import CompositeTacticController
                config = BattleConfig()
                config.max_turns = max_turns
                controller = CompositeTacticController(bf, data_loader=self.app.data_loader,
                                                       config=config, narrative=narrative,
                                                       teams=teams_units, team_memories=teams_mem_cards,
                                                       boss_unit_id=boss_unit_id)
            else:
                controller = BattleFlowController(bf, data_loader=self.app.data_loader,
                                                  config=BattleConfig(max_turns=max_turns),
                                                  narrative=narrative)

            # 设置暴击覆盖
            override_func = self._simulator.create_crit_override_func("interactive")
            controller.damage_service.set_crit_override(override_func)

            # 设置分支选择覆盖
            branch_override_func = self._simulator.create_branch_override_func("interactive")
            controller.skill_service.set_branch_override(branch_override_func)

            # 设置random_draw覆盖（概率技能目标抽取，如ミッドサマー・ラブ）
            random_draw_override_func = self._simulator.create_random_draw_override_func("interactive")
            controller.skill_service.set_random_draw_override(random_draw_override_func)

            self._interactive_controller = controller
            self._interactive_narrative = narrative

            result = controller.execute_battle()

            # 清除覆盖
            controller.damage_service.clear_crit_override()
            controller.skill_service.clear_branch_override()
            controller.skill_service.clear_random_draw_override()

            return result

        self._simulator.start_interactive_battle(battle_func)
        self._start_polling()

    def _save_sequence(self):
        """保存当前暴击序列到文件"""
        if not self._simulator:
            return

        seq_str = self._simulator.generate_sequence_string()
        # 分支决策序列（random_choice/probability分支/random_draw抽取选择，如 ミッドサマー・ラブ）
        branch_seq_str = self._simulator.generate_branch_sequence_string()
        if not seq_str and not branch_seq_str:
            messagebox.showinfo("保存序列", "当前没有决策记录")
            return

        # 弹出输入框让用户命名
        from tkinter import simpledialog
        name = simpledialog.askstring("保存序列", "请输入序列名称:", parent=self)
        if not name:
            return

        # 保存到文件
        seq_dir = CRIT_SEQUENCE_DIR
        seq_dir.mkdir(parents=True, exist_ok=True)
        seq_path = seq_dir / f"{name}.txt"

        # 同时保存编队信息（如果有）
        save_data = {
            "sequence": seq_str,
            "branch_sequence": branch_seq_str,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "decision_count": len(self._simulator.get_decision_points()),
            "branch_decision_count": len(self._simulator.get_branch_decision_points()),
        }
        if self._last_battle_sel:
            save_data["preset_type"] = self._last_battle_preset_type
            save_data["seed"] = self._last_battle_seed
            # 保存编队摘要
            if self._last_battle_preset_type == "composite":
                save_data["teams_positions"] = self._last_battle_sel.get("teams_positions", [])
            else:
                friends = [cid for cid in self._last_battle_sel.get("friend_positions",
                            self._last_battle_sel.get("friends", [])) if cid]
                save_data["friends"] = friends
                if self._last_battle_preset_type == "tactical":
                    save_data["enemy_id"] = self._last_battle_sel.get("enemy_id")
                elif self._last_battle_preset_type == "circle":
                    save_data["season"] = self._last_battle_sel.get("season")
                    save_data["stage"] = self._last_battle_sel.get("stage")
                else:
                    enemies = [cid for cid in self._last_battle_sel.get("enemy_positions",
                                self._last_battle_sel.get("enemies", [])) if cid]
                    save_data["enemies"] = enemies

        with open(seq_path, "w", encoding="utf-8") as fp:
            json.dump(save_data, fp, ensure_ascii=False, indent=2)

        self._append_output(f"序列已保存: {seq_path}\n")
        save_info = f"序列已保存到: {name}\n暴击序列: {seq_str or '(无)'}"
        if branch_seq_str:
            save_info += f"\n分支序列: {branch_seq_str}"
        messagebox.showinfo("保存序列", save_info)

    def _load_sequence(self):
        """从文件加载暴击序列"""
        seq_dir = CRIT_SEQUENCE_DIR
        seq_dir.mkdir(parents=True, exist_ok=True)

        # 列出可用序列
        seq_files = sorted(seq_dir.glob("*.txt"))
        if not seq_files:
            messagebox.showinfo("加载序列", "没有已保存的序列")
            return

        # 弹出选择对话框
        from tkinter import simpledialog
        names = [f.stem for f in seq_files]
        choice = simpledialog.askstring(
            "加载序列",
            f"可用序列:\n" + "\n".join(f"  {i+1}. {n}" for i, n in enumerate(names)) + "\n\n请输入序号或名称:",
            parent=self
        )
        if not choice:
            return

        # 解析选择
        selected_file = None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(seq_files):
                selected_file = seq_files[idx]
        except ValueError:
            for f in seq_files:
                if f.stem == choice:
                    selected_file = f
                    break

        if not selected_file or not selected_file.exists():
            messagebox.showwarning("加载序列", "无效的选择")
            return

        with open(selected_file, "r", encoding="utf-8") as fp:
            data = json.load(fp)

        seq_str = data.get("sequence", "")
        self.prefill_var.set(seq_str)

        # 同时设置预填序列输入框（预填序列模式也可用）
        self.seq_var.set(seq_str)

        # 加载分支决策序列（random_choice/probability分支/random_draw抽取选择，如 ミッドサマー・ラブ）
        branch_seq_str = data.get("branch_sequence", "")
        if branch_seq_str:
            self.branch_prefill_var.set(branch_seq_str)

        info = f"已加载序列: {selected_file.stem}\n序列: {seq_str or '(无)'}"
        if branch_seq_str:
            info += f"\n分支序列: {branch_seq_str}"
        if "friends" in data:
            info += f"\n己方: {data['friends']}"
        self._append_output(info + "\n")
        messagebox.showinfo("加载序列", info)

    def _delete_sequence(self):
        """删除已保存的暴击序列"""
        seq_dir = CRIT_SEQUENCE_DIR
        seq_dir.mkdir(parents=True, exist_ok=True)

        seq_files = sorted(seq_dir.glob("*.txt"))
        if not seq_files:
            messagebox.showinfo("删除序列", "没有已保存的序列")
            return

        from tkinter import simpledialog
        names = [f.stem for f in seq_files]
        choice = simpledialog.askstring(
            "删除序列",
            f"可用序列:\n" + "\n".join(f"  {i+1}. {n}" for i, n in enumerate(names)) + "\n\n请输入序号或名称删除:",
            parent=self
        )
        if not choice:
            return

        selected_file = None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(seq_files):
                selected_file = seq_files[idx]
        except ValueError:
            for f in seq_files:
                if f.stem == choice:
                    selected_file = f
                    break

        if not selected_file or not selected_file.exists():
            messagebox.showwarning("删除序列", "无效的选择")
            return

        confirm = messagebox.askyesno("确认删除", f"确定要删除序列 '{selected_file.stem}' 吗？")
        if not confirm:
            return

        os.remove(selected_file)
        messagebox.showinfo("删除序列", f"序列 '{selected_file.stem}' 已删除")
        self._append_output(f"序列已删除: {selected_file.stem}\n")

    def _update_seq_progress(self):
        """更新序列进度显示"""
        if not self._simulator:
            return
        dps = self._simulator.get_decision_points()
        if not dps:
            self.seq_progress_var.set("")
            return
        seq_str = "".join("C" if dp.is_crit else "N" for dp in dps)
        total = len(dps)
        crit_count = sum(1 for d in dps if d.is_crit)
        # 显示最近20步 + 总计
        if len(seq_str) > 20:
            display_seq = "..." + seq_str[-20:]
        else:
            display_seq = seq_str
        self.seq_progress_var.set(f"序列: {display_seq} ({total}步, {crit_count}暴击)")

    def _stop_interactive(self):
        if self._simulator:
            self._simulator.stop_interactive()
        self.crit_btn.config(state="disabled")
        self.no_crit_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")
        self.undo_btn.config(state="disabled")
        self.save_seq_btn.config(state="normal")
        self.export_console_btn.config(state="normal")  # 停止后仍可导出已捕获命令台日志
        self.start_btn.config(state="normal")
        self.report_btn.config(state="normal")
        self.current_decision_label.config(text="已停止")
        self._clear_branch_candidates()
        self._append_output("\n=== 用户停止模拟 ===\n")
        # 取消轮询
        if self._poll_after_id:
            self.app.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None

    def _start_simulation(self):
        from src.combat_v2.step_crit_simulator import StepCritSimulator

        # 确定编队配置来源
        if self._loaded_preset_data is not None:
            sel = self._loaded_preset_data
            preset_type = self._loaded_preset_type
        else:
            # 从TeamBattleTab获取
            sel = self.app.team_tab._get_selection()
            preset_type = "team"

        # 验证编队完整性
        if preset_type == "team":
            if not sel.get("friends") and not any(cid for cid in sel.get("friend_positions", [])):
                messagebox.showwarning("编队不完整", "请加载预设或在「编队与战斗」标签页配置己方角色")
                return
            if not sel.get("enemies") and not any(cid for cid in sel.get("enemy_positions", [])):
                messagebox.showwarning("编队不完整", "请加载预设或在「编队与战斗」标签页配置敌方角色")
                return
        elif preset_type == "tactical":
            if not sel.get("friends") and not any(cid for cid in sel.get("friend_positions", [])):
                messagebox.showwarning("编队不完整", "请加载包含己方角色的演习预设")
                return
            if not sel.get("enemy_id"):
                messagebox.showwarning("编队不完整", "请加载包含敌方单位的演习预设")
                return
        elif preset_type == "circle":
            if not sel.get("friends") and not any(cid for cid in sel.get("friend_positions", [])):
                messagebox.showwarning("编队不完整", "请加载包含己方角色的压制战预设")
                return
            if not sel.get("season") or not sel.get("stage"):
                messagebox.showwarning("编队不完整", "请加载包含赛季/阶段信息的压制战预设")
                return
        elif preset_type == "composite":
            teams_positions = sel.get("teams_positions", [])
            total_chars = sum(sum(1 for c in t if c is not None) for t in teams_positions)
            if total_chars == 0:
                messagebox.showwarning("编队不完整", "请加载包含至少1支队伍角色的复合演习预设")
                return

        self._simulator = StepCritSimulator()
        mode = self.mode_var.get()

        # 设置预填序列
        if mode == "sequence":
            seq_str = self.seq_var.get().strip()
            if seq_str:
                self._simulator.set_crit_sequence(seq_str)
        elif mode == "interactive":
            # 交互式模式：设置预填序列（自动应用到指定步骤后切换交互）
            prefill_str = self.prefill_var.get().strip()
            if prefill_str:
                self._simulator.set_interactive_prefill(prefill_str)

        # 设置随机种子
        seed_str = self.seed_var.get().strip()
        if seed_str:
            try:
                seed = int(seed_str)
            except ValueError:
                seed = int(hash(seed_str)) % (2**31)
        else:
            seed = int(time.time() * 1000000) % (2**31)
        random.seed(seed)

        # 缓存战斗配置（用于回退重启）
        self._last_battle_sel = sel
        self._last_battle_seed = seed
        self._last_battle_preset_type = preset_type

        # 清空输出
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state="disabled")

        self._append_output(f"=== 逐步暴击模拟器 ===\n")
        self._append_output(f"模式: {'预填序列' if mode == 'sequence' else '交互式'}\n")
        type_names = {"team": "编队与战斗", "tactical": "战术演习", "circle": "对抗压制战", "composite": "复合战术演习"}
        self._append_output(f"战斗类型: {type_names.get(preset_type, preset_type)}\n")
        if mode == "sequence" and self._simulator.get_crit_sequence_length() > 0:
            self._append_output(f"序列长度: {self._simulator.get_crit_sequence_length()}\n")
        self._append_output(f"随机种子: {seed}\n")

        # 显示编队信息
        if preset_type == "composite":
            teams_positions = sel.get("teams_positions", [])
            for i, t in enumerate(teams_positions):
                chars = [c for c in t if c]
                self._append_output(f"队伍{i+1}: {chars}\n")
            self._append_output("\n")
        elif preset_type == "circle":
            friends = [cid for cid in sel.get("friend_positions", sel.get("friends", [])) if cid]
            self._append_output(f"己方: {friends} | 赛季{sel.get('season')} 阶段{sel.get('stage')}\n\n")
        elif preset_type == "tactical":
            friends = [cid for cid in sel.get("friend_positions", sel.get("friends", [])) if cid]
            self._append_output(f"己方: {friends} | 敌方ID: {sel.get('enemy_id')}\n\n")
        else:
            friends = [cid for cid in sel.get("friend_positions", sel.get("friends", [])) if cid]
            enemies = [cid for cid in sel.get("enemy_positions", sel.get("enemies", [])) if cid]
            self._append_output(f"己方: {friends} | 敌方: {enemies}\n\n")

        self.start_btn.config(state="disabled")
        self.report_btn.config(state="disabled")

        if mode == "sequence":
            # 预填模式：同步执行
            self._run_sequence_mode(sel, seed, preset_type)
        else:
            # 交互式模式：后台线程执行
            self._run_interactive_mode(sel, seed, preset_type)

    def _build_battlefield(self, sel, preset_type, panel_config, player_config, stat_calculator):
        """根据预设类型构建战场（composite模式请用 _build_composite_setup）"""
        bf = BattlefieldState()

        # 创建己方单位
        for i, cid in enumerate(sel.get("friend_positions", sel.get("friends", []))):
            if cid is not None:
                u = self.app._create_unit(panel_config, player_config, stat_calculator,
                                          cid, Side.ALLY, GRID_ALLY_POSITIONS[i])
                if u:
                    bf.add_unit(u)

        # 创建敌方单位
        if preset_type == "tactical":
            # 战术演习：从tactical_exercise_enemies.json获取敌方数据
            enemy_id = sel.get("enemy_id")
            enemy_data = self.app.tactical_tab._enemy_data.get(enemy_id) if hasattr(self.app, 'tactical_tab') else None
            if enemy_data:
                enemy_unit = self.app.tactical_tab._create_tactical_enemy(enemy_data, bf)
                if enemy_unit:
                    bf.add_unit(enemy_unit)
        elif preset_type == "circle":
            # 对抗压制战：从circle_battle_enemies获取阶段数据
            season = sel.get("season")
            stage = sel.get("stage")
            stage_data = self.app.data_loader.get_circle_battle_stage(season, stage)
            if stage_data:
                for enemy_data in stage_data.get("enemies", []):
                    enemy_unit = self.app.circle_tab._create_circle_battle_enemy(enemy_data)
                    if enemy_unit:
                        bf.add_unit(enemy_unit)
        else:
            # 编队与战斗：从预设中的敌方角色ID创建
            for i, cid in enumerate(sel.get("enemy_positions", sel.get("enemies", []))):
                if cid is not None:
                    u = self.app._create_unit(panel_config, player_config, stat_calculator,
                                              cid, Side.ENEMY, GRID_ENEMY_POSITIONS[i])
                    if u:
                        bf.add_unit(u)

        # 回忆卡
        if preset_type == "circle":
            bf.memory_cards = self.app.circle_tab._build_memory_cards(sel.get("mems_friend", []))
        else:
            bf.memory_cards = self.app.team_tab._build_memory_cards(sel.get("mems_friend", []))

        return bf

    def _build_composite_setup(self, sel, panel_config, player_config, stat_calculator):
        """构建复合战术演习的战场和3支队伍

        Returns:
            (bf, teams_units, teams_mem_cards, boss_unit_id, max_turns)
        """
        ct = self.app.composite_tab
        endless_data = ct._endless_data
        enemies_data = endless_data["enemies"]
        max_turns = endless_data["max_turn"]

        # 创建敌方
        bf = BattlefieldState()
        for enemy_data in enemies_data:
            enemy_unit = ct._create_composite_enemy(enemy_data)
            if enemy_unit:
                bf.add_unit(enemy_unit)

        # BOSS unit_id
        boss_unit_id = ""
        for ed in enemies_data:
            if ed.get("is_boss"):
                boss_unit_id = f"E_{ed['enemy_id']}_{ed['slot']}"
                break

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

        # 回忆卡
        teams_mem_cards = []
        for mem_ids in sel.get("teams_mem_ids", []):
            teams_mem_cards.append(ct._build_memory_cards(mem_ids))

        return bf, teams_units, teams_mem_cards, boss_unit_id, max_turns

    def _run_sequence_mode(self, sel, seed, preset_type):
        """预填序列模式执行"""
        from src.combat_v2.step_crit_simulator import StepCritSimulator
        from src.combat_v2.tactical_exercise_controller import TacticalExerciseController

        try:
            global_vals = self.app.global_tab.get_values()
            max_turns = global_vals["max_turns"]

            panel_config = self.app._build_panel_config_from_gui(global_vals)
            player_config = panel_config.get_player_config()
            lerp_data = self.app.data_loader.load_level_lerp_data()
            stat_calculator = StatCalculator(lerp_data, data_loader=self.app.data_loader)

            narrative = BattleNarrativeWriter()

            # 构建战场/队伍
            if preset_type == "composite":
                bf, teams_units, teams_mem_cards, boss_unit_id, comp_max_turns = self._build_composite_setup(
                    sel, panel_config, player_config, stat_calculator)
                max_turns = comp_max_turns
            else:
                bf = self._build_battlefield(sel, preset_type, panel_config, player_config, stat_calculator)
                if preset_type == "circle":
                    stage_data = self.app.data_loader.get_circle_battle_stage(sel.get("season"), sel.get("stage"))
                    max_turns = stage_data["max_turn"] if stage_data else max_turns

            random.seed(seed)

            # 创建控制器
            if preset_type == "tactical":
                config = BattleConfig()
                config.max_turns = 5
                controller = TacticalExerciseController(bf, data_loader=self.app.data_loader,
                                                        config=config, narrative=narrative)
            elif preset_type == "circle":
                from src.combat_v2.circle_battle_controller import CircleBattleController
                config = BattleConfig()
                config.max_turns = max_turns
                controller = CircleBattleController(bf, data_loader=self.app.data_loader,
                                                    config=config, narrative=narrative,
                                                    season=sel["season"], stage=sel["stage"],
                                                    enemy_state_overrides=sel.get("enemy_state_overrides"))
            elif preset_type == "composite":
                from src.combat_v2.composite_tactic_controller import CompositeTacticController
                config = BattleConfig()
                config.max_turns = max_turns
                controller = CompositeTacticController(bf, data_loader=self.app.data_loader,
                                                       config=config, narrative=narrative,
                                                       teams=teams_units, team_memories=teams_mem_cards,
                                                       boss_unit_id=boss_unit_id)
            else:
                controller = BattleFlowController(bf, data_loader=self.app.data_loader,
                                                  config=BattleConfig(max_turns=max_turns),
                                                  narrative=narrative)

            # 设置暴击覆盖
            override_func = self._simulator.create_crit_override_func("sequence")
            controller.damage_service.set_crit_override(override_func)

            # 设置分支选择覆盖（序列模式使用 sequence 模式，无暂停）
            branch_prefill_str = self.branch_prefill_var.get().strip()
            if branch_prefill_str:
                try:
                    branch_prefill_ids = [int(x.strip()) for x in branch_prefill_str.split(",") if x.strip()]
                    self._simulator.set_interactive_branch_prefill(branch_prefill_ids)
                except ValueError:
                    self._append_output("警告: 分支预填序列格式错误，已忽略（应为逗号分隔的block_id）\n")
            branch_override_func = self._simulator.create_branch_override_func("sequence")
            controller.skill_service.set_branch_override(branch_override_func)

            # 设置random_draw覆盖（概率技能目标抽取）
            random_draw_override_func = self._simulator.create_random_draw_override_func("sequence")
            controller.skill_service.set_random_draw_override(random_draw_override_func)

            result = controller.execute_battle()

            # 清除覆盖
            controller.damage_service.clear_crit_override()
            controller.skill_service.clear_branch_override()
            controller.skill_service.clear_random_draw_override()

            # 输出结果
            self._append_output(self._simulator.generate_report())
            self._append_output("\n")

            # 结果显示
            if preset_type == "composite":
                score = result.get("score", 0)
                boss_stage = result.get("boss_stage", 0)
                killed = result.get("boss_killed_count", 0)
                self._append_output(f"战斗结果: 总分数={score:,} | BOSS阶段={boss_stage} | 击杀次数={killed} | 回合数={result['total_turns']}\n")
            else:
                winner_text = "胜利" if result.get('winner') == 'FRIEND' else ("败北" if result.get('winner') == 'ENEMY' else "超时")
                if preset_type == "tactical":
                    stages = result.get("stages_cleared", 0)
                    self._append_output(f"战斗结果: {winner_text} | 回合数: {result['total_turns']} | 清除阶段: {stages}\n")
                else:
                    self._append_output(f"战斗结果: {winner_text} | 回合数: {result['total_turns']}\n")

            # 输出生成的序列字符串（可用于复现）
            seq_str = self._simulator.generate_sequence_string()
            self._append_output(f"\n暴击序列（可用于复现）: {seq_str}\n")

            # 更新统计
            dps = self._simulator.get_decision_points()
            total = len(dps)
            crit_count = sum(1 for d in dps if d.is_crit)
            self.stats_label.config(text=f"决策点: {total} | 暴击: {crit_count} | 不暴击: {total - crit_count}")

            # 写入叙事日志
            log_dir = _BASE_PATH / "data" / "battle_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"step_crit_{preset_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            narrative.write(str(log_path))
            self._append_output(f"叙事日志: {log_path}\n")

        except Exception as e:
            import traceback
            self._append_output(f"\n错误: {e}\n{traceback.format_exc()}\n")
        finally:
            self.start_btn.config(state="normal")
            self.report_btn.config(state="normal")

    def _run_interactive_mode(self, sel, seed, preset_type):
        """交互式模式执行"""
        from src.combat_v2.step_crit_simulator import StepCritSimulator
        from src.combat_v2.tactical_exercise_controller import TacticalExerciseController

        # 重置叙事和控制器引用
        self._interactive_narrative = None
        self._interactive_controller = None

        # 挂载命令台日志内存捕获（战斗线程启动前，确保从开头捕获）
        self._attach_console_log_handler()

        self.crit_btn.config(state="normal")
        self.no_crit_btn.config(state="normal")
        self.stop_btn.config(state="normal")
        self.undo_btn.config(state="disabled")  # 预填阶段禁用回退
        self.save_seq_btn.config(state="disabled")
        self.export_console_btn.config(state="disabled")  # 预填阶段禁用，到达决策点后启用
        self.current_decision_label.config(text="等待第一个暴击决策点...")
        self._narrative_line_count = 0  # 叙事日志行数追踪
        self._clear_branch_candidates()

        # 保存参数供线程使用
        self._interactive_sel = sel
        self._interactive_seed = seed
        self._interactive_preset_type = preset_type

        # 设置分支预填序列
        branch_prefill_str = self.branch_prefill_var.get().strip()
        if branch_prefill_str:
            try:
                branch_prefill_ids = [int(x.strip()) for x in branch_prefill_str.split(",") if x.strip()]
                self._simulator.set_interactive_branch_prefill(branch_prefill_ids)
            except ValueError:
                self._append_output("警告: 分支预填序列格式错误，已忽略（应为逗号分隔的block_id）\n")

        def battle_func():
            global_vals = self.app.global_tab.get_values()
            max_turns = global_vals["max_turns"]

            panel_config = self.app._build_panel_config_from_gui(global_vals)
            player_config = panel_config.get_player_config()
            lerp_data = self.app.data_loader.load_level_lerp_data()
            stat_calculator = StatCalculator(lerp_data, data_loader=self.app.data_loader)

            narrative = BattleNarrativeWriter()

            # 构建战场/队伍
            if preset_type == "composite":
                bf, teams_units, teams_mem_cards, boss_unit_id, comp_max_turns = self._build_composite_setup(
                    sel, panel_config, player_config, stat_calculator)
                max_turns = comp_max_turns
            else:
                bf = self._build_battlefield(sel, preset_type, panel_config, player_config, stat_calculator)
                if preset_type == "circle":
                    stage_data = self.app.data_loader.get_circle_battle_stage(sel.get("season"), sel.get("stage"))
                    max_turns = stage_data["max_turn"] if stage_data else max_turns

            random.seed(seed)

            # 创建控制器
            if preset_type == "tactical":
                config = BattleConfig()
                config.max_turns = 5
                controller = TacticalExerciseController(bf, data_loader=self.app.data_loader,
                                                        config=config, narrative=narrative)
            elif preset_type == "circle":
                from src.combat_v2.circle_battle_controller import CircleBattleController
                config = BattleConfig()
                config.max_turns = max_turns
                controller = CircleBattleController(bf, data_loader=self.app.data_loader,
                                                    config=config, narrative=narrative,
                                                    season=sel["season"], stage=sel["stage"],
                                                    enemy_state_overrides=sel.get("enemy_state_overrides"))
            elif preset_type == "composite":
                from src.combat_v2.composite_tactic_controller import CompositeTacticController
                config = BattleConfig()
                config.max_turns = max_turns
                controller = CompositeTacticController(bf, data_loader=self.app.data_loader,
                                                       config=config, narrative=narrative,
                                                       teams=teams_units, team_memories=teams_mem_cards,
                                                       boss_unit_id=boss_unit_id)
            else:
                controller = BattleFlowController(bf, data_loader=self.app.data_loader,
                                                  config=BattleConfig(max_turns=max_turns),
                                                  narrative=narrative)

            # 设置暴击覆盖
            override_func = self._simulator.create_crit_override_func("interactive")
            controller.damage_service.set_crit_override(override_func)

            # 设置分支选择覆盖
            branch_override_func = self._simulator.create_branch_override_func("interactive")
            controller.skill_service.set_branch_override(branch_override_func)

            # 设置random_draw覆盖（概率技能目标抽取，如ミッドサマー・ラブ）
            random_draw_override_func = self._simulator.create_random_draw_override_func("interactive")
            controller.skill_service.set_random_draw_override(random_draw_override_func)

            self._interactive_controller = controller
            self._interactive_narrative = narrative

            result = controller.execute_battle()

            # 清除覆盖
            controller.damage_service.clear_crit_override()
            controller.skill_service.clear_branch_override()
            controller.skill_service.clear_random_draw_override()

            return result

        self._simulator.start_interactive_battle(battle_func)
        self._start_polling()

    def _start_polling(self):
        """开始轮询交互式信息"""
        self._poll_interactive()

    def _poll_interactive(self):
        """轮询交互式战斗状态"""
        if not self._simulator:
            return

        # 批量输出叙事日志（一次性追加，减少GUI重绘）
        if hasattr(self, '_interactive_narrative') and self._interactive_narrative:
            lines = self._interactive_narrative._lines
            if len(lines) > self._narrative_line_count:
                new_lines = lines[self._narrative_line_count:]
                self._narrative_line_count = len(lines)
                if new_lines:
                    batch_text = "".join(line + "\n" for line in new_lines)
                    self._append_output(batch_text, scroll=False)

        # 限制每次轮询处理的事件数量，防止GUI卡死
        infos = self._simulator.poll_interactive_info()
        max_events_per_poll = 50
        infos = infos[:max_events_per_poll]

        for event_type, data in infos:
            if event_type == "prefill_step":
                # 预填序列自动执行的步骤
                dp = data
                source_labels = {
                    "main_attack": "技能攻击",
                    "enchant": "附魔伤害",
                    "sub_unit": "子单位伤害",
                    "heal": "治疗",
                }
                source_label = source_labels.get(dp.source, dp.source)
                crit_str = "★暴击" if dp.is_crit else "·不暴击"
                self._append_output(f"[#{dp.index:03d}] [预填] {dp.attacker_name} → {dp.target_name} | "
                                    f"{dp.skill_name} | {source_label} | "
                                    f"Hit {dp.hit_number}/{dp.total_hits} | {crit_str}\n", scroll=False)
                self._update_seq_progress()

            elif event_type == "crit_decision":
                # 显示决策点信息
                dp = data
                source_labels = {
                    "main_attack": "技能攻击",
                    "enchant": "附魔伤害",
                    "sub_unit": "子单位伤害",
                    "heal": "治疗",
                }
                source_label = source_labels.get(dp.source, dp.source)

                info_text = (
                    f"[#{dp.index:03d}] {dp.attacker_name} → {dp.target_name}\n"
                    f"  技能: {dp.skill_name} (ID:{dp.skill_id})\n"
                )
                if dp.source == "sub_unit" and dp.sub_unit_name:
                    info_text += f"  子单位: {dp.sub_unit_name}\n"
                info_text += (
                    f"  类型: {source_label} | Hit: {dp.hit_number}/{dp.total_hits}\n"
                    f"  暴击率: {dp.crit_rate * 100:.1f}%"
                )

                self.current_decision_label.config(text=info_text)
                self._append_output(f"\n[#{dp.index:03d}] {dp.attacker_name} → {dp.target_name} | "
                                    f"{dp.skill_name} | {source_label} | "
                                    f"Hit {dp.hit_number}/{dp.total_hits} | "
                                    f"暴击率: {dp.crit_rate * 100:.1f}%\n", scroll=False)

                # 预填序列用完，启用回退和保存按钮
                self.undo_btn.config(state="normal")
                self.save_seq_btn.config(state="normal")
                self.export_console_btn.config(state="normal")

                # 更新统计
                dps = self._simulator.get_decision_points()
                total = len(dps)
                crit_count = sum(1 for d in dps if d.is_crit)
                self.stats_label.config(text=f"决策点: {total} | 暴击: {crit_count} | 不暴击: {total - crit_count}")

            elif event_type == "battle_complete":
                self._append_output(f"\n=== 战斗结束 ===\n")
                result = data
                preset_type = getattr(self, '_interactive_preset_type', 'team')
                if preset_type == "composite":
                    score = result.get("score", 0)
                    boss_stage = result.get("boss_stage", 0)
                    killed = result.get("boss_killed_count", 0)
                    self._append_output(f"结果: 总分数={score:,} | BOSS阶段={boss_stage} | 击杀次数={killed} | 回合数={result['total_turns']}\n")
                else:
                    winner_text = "胜利" if result.get('winner') == 'FRIEND' else ("败北" if result.get('winner') == 'ENEMY' else "超时")
                    if preset_type == "tactical":
                        stages = result.get("stages_cleared", 0)
                        score_result = result.get("score_result")
                        score_text = ""
                        if score_result:
                            score_text = f" | 得分: {score_result.total_score:,} (伤害:{score_result.total_damage_to_enemies:,} - 回血:{score_result.enemy_healing_received:,})"
                        self._append_output(f"结果: {winner_text} | 回合数: {result['total_turns']} | 清除阶段: {stages}{score_text}\n")

                        # 输出计分统计到GUI日志和叙事日志
                        if score_result:
                            score_lines = self._build_score_display_lines(score_result)
                            self._append_output("\n".join(score_lines) + "\n")
                            # 追加到叙事日志文件
                            if hasattr(self, '_interactive_narrative') and self._interactive_narrative:
                                for line in score_lines:
                                    self._interactive_narrative._add(line)
                    else:
                        self._append_output(f"结果: {winner_text} | 回合数: {result['total_turns']}\n")

                # 输出报告
                self._append_output("\n" + self._simulator.generate_report())

                # 序列字符串
                seq_str = self._simulator.generate_sequence_string()
                self._append_output(f"\n暴击序列（可用于复现）: {seq_str}\n")

                # 分支序列字符串
                if self._simulator.get_branch_decision_points():
                    branch_seq_str = self._simulator.generate_branch_sequence_string()
                    self._append_output(f"分支序列（可用于复现）: {branch_seq_str}\n")

                # 写入叙事日志
                if hasattr(self, '_interactive_narrative') and self._interactive_narrative:
                    log_dir = _BASE_PATH / "data" / "battle_logs"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    log_path = log_dir / f"step_crit_{preset_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    self._interactive_narrative.write(str(log_path))
                    self._append_output(f"叙事日志: {log_path}\n")

                self.crit_btn.config(state="disabled")
                self.no_crit_btn.config(state="disabled")
                self.stop_btn.config(state="disabled")
                self.undo_btn.config(state="disabled")
                self.save_seq_btn.config(state="normal")
                self.export_console_btn.config(state="normal")  # 战斗结束后仍可导出完整命令台日志
                self.start_btn.config(state="normal")
                self.report_btn.config(state="normal")
                self.current_decision_label.config(text="战斗结束")
                self._clear_branch_candidates()

                # 更新统计
                dps = self._simulator.get_decision_points()
                total = len(dps)
                crit_count = sum(1 for d in dps if d.is_crit)
                self.stats_label.config(text=f"决策点: {total} | 暴击: {crit_count} | 不暴击: {total - crit_count}")
                # 最终滚动到底部
                self.output_text.config(state="normal")
                self.output_text.see(tk.END)
                self.output_text.config(state="disabled")
                return  # 停止轮询

            elif event_type == "battle_error":
                self._append_output(f"\n错误: {data}\n")
                self.crit_btn.config(state="disabled")
                self.no_crit_btn.config(state="disabled")
                self.stop_btn.config(state="disabled")
                self.undo_btn.config(state="disabled")
                self.save_seq_btn.config(state="normal")
                self.export_console_btn.config(state="disabled")
                self.start_btn.config(state="normal")
                self.current_decision_label.config(text="战斗出错")
                self._clear_branch_candidates()
                return  # 停止轮询

        # 处理分支事件
        if self._simulator and self._simulator.is_interactive_running():
            branch_infos = self._simulator.poll_branch_interactive_info()
            branch_infos = branch_infos[:max_events_per_poll]
            for event_type, data in branch_infos:
                if event_type == "branch_decision":
                    # 需要用户选择分支
                    bp = data
                    if getattr(bp, 'decision_type', 'branch') == 'random_draw':
                        info_text = (
                            f"[#{bp.index:03d}] {bp.caster_name} - {bp.skill_name} (ID:{bp.skill_id})\n"
                            f"  随机抽取: 第{bp.group_id + 1}次"
                        )
                        label = "随机抽取"
                    else:
                        info_text = (
                            f"[#{bp.index:03d}] {bp.caster_name} - {bp.skill_name} (ID:{bp.skill_id})\n"
                            f"  分组: group={bp.group_id}"
                        )
                        label = "分支决策"
                    self.branch_decision_label.config(text=info_text)
                    self._show_branch_candidates(bp)
                    self._append_output(f"\n[#{bp.index:03d}] {label}: {bp.caster_name} - {bp.skill_name} "
                                        f"(group={bp.group_id}, {len(bp.candidates)}个候选)\n", scroll=False)
                    # 禁用暴击按钮，强制用户先完成分支选择
                    self.crit_btn.config(state="disabled")
                    self.no_crit_btn.config(state="disabled")

                elif event_type == "branch_prefill_step":
                    # 预填分支选择已执行
                    bp = data
                    if getattr(bp, 'decision_type', 'branch') == 'random_draw':
                        self._append_output(f"  [预填] 随机抽取: 候选索引 {bp.selected_block_id}\n", scroll=False)
                    else:
                        self._append_output(f"  [预填] 分支选择: block {bp.selected_block_id}\n", scroll=False)

        # 不自动滚动，让用户自由查看历史日志

        # 继续轮询
        if self._simulator.is_interactive_running():
            self._poll_after_id = self.app.root.after(100, self._poll_interactive)

    def _show_report(self):
        """显示暴击决策报告"""
        if self._simulator:
            report = self._simulator.generate_report()
            self._append_output("\n" + report)

    def _build_score_display_lines(self, score_result) -> list:
        """从BattleScoreResult对象构建计分统计文本行"""
        out = []
        out.append("")
        out.append("─" * 60)
        out.append(f"  【计分统计】")
        out.append(f"  总得分: {score_result.total_score:,}")
        out.append(f"")
        out.append(f"  得分明细:")
        out.append(f"    对敌方造成伤害: +{score_result.total_damage_to_enemies:,}")
        out.append(f"    敌方受到回复:   -{score_result.enemy_healing_received:,}")
        out.append("")
        out.append(f"  【我方合计】")
        out.append(f"    造成伤害: {score_result.ally_total_damage_dealt:,}")
        out.append(f"    受到伤害: {score_result.ally_total_damage_received:,}")
        out.append(f"    提供回复: {score_result.ally_total_hp_healed:,}")
        out.append("")
        out.append(f"  【敌方合计】")
        out.append(f"    造成伤害: {score_result.enemy_total_damage_dealt:,}")
        out.append(f"    受到伤害: {score_result.enemy_total_damage_received:,}")
        out.append(f"    提供回复: {score_result.enemy_total_hp_healed:,}")
        out.append("")

        # 单位明细
        unit_stats = score_result.unit_stats
        ally_units = {uid: s for uid, s in unit_stats.items() if s.side == "ally"}
        enemy_units = {uid: s for uid, s in unit_stats.items() if s.side == "enemy"}

        if ally_units:
            out.append(f"  【我方角色明细】")
            out.append(f"    {_cjk_fit('角色', 20)} {'造成伤害':>12} {'受到伤害':>12} {'提供回复':>12}")
            for uid, s in ally_units.items():
                name = s.name[:18]
                out.append(f"    {_cjk_fit(name, 20)} {s.damage_dealt:>12,} {s.damage_received:>12,} {s.hp_healed:>12,}")

        if enemy_units:
            out.append(f"")
            out.append(f"  【敌方角色明细】")
            out.append(f"    {_cjk_fit('角色', 20)} {'造成伤害':>12} {'受到伤害':>12} {'提供回复':>12}")
            for uid, s in enemy_units.items():
                name = s.name[:18]
                out.append(f"    {_cjk_fit(name, 20)} {s.damage_dealt:>12,} {s.damage_received:>12,} {s.hp_healed:>12,}")

        out.append("─" * 60)
        return out

    def _attach_console_log_handler(self):
        """挂载/重置命令台日志内存捕获 handler。

        在每次交互式战斗（含回退重启）开始时调用，确保从战斗开始捕获命令台日志，
        旧 handler 先移除以避免重复捕获与内存累积。
        """
        from src.combat_v2.battle_logger import battle_logger, MemoryLogHandler

        logger = battle_logger()
        if self._console_log_handler is not None:
            try:
                logger.removeHandler(self._console_log_handler)
            except Exception:
                pass
            self._console_log_handler.clear()

        handler = MemoryLogHandler()
        logger.addHandler(handler)
        self._console_log_handler = handler

    def _export_console_log(self):
        """导出从战斗开始到当前暴击点的命令台日志到文件。"""
        if self._console_log_handler is None or self._console_log_handler.count() == 0:
            messagebox.showinfo("导出命令台", "当前无可导出的命令台日志（请先开始交互式模拟）。")
            return

        lines = self._console_log_handler.get_lines()
        preset_type = getattr(self, '_interactive_preset_type', 'team')
        seed = getattr(self, '_interactive_seed', '')
        decision_count = 0
        if self._simulator:
            decision_count = len(self._simulator.get_decision_points())

        type_names = {"team": "编队与战斗", "tactical": "战术演习",
                      "circle": "对抗压制战", "composite": "复合战术演习"}
        preset_label = type_names.get(preset_type, preset_type)

        log_dir = _BASE_PATH / "data" / "battle_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = log_dir / f"step_crit_console_{preset_type}_{ts}.txt"

        header = [
            f"# 逐步暴击 - 命令台日志导出",
            f"# 战斗类型: {preset_label} ({preset_type})",
            f"# 随机种子: {seed}",
            f"# 暴击决策点数: {decision_count}",
            f"# 日志行数: {len(lines)}",
            f"# 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 80,
            "",
        ]
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(header))
            f.write("\n".join(lines))
            if lines:
                f.write("\n")

        self._append_output(f"命令台日志: {log_path} (共 {len(lines)} 行)\n")

    def _append_output(self, text: str, scroll: bool = True):
        """向输出区域追加文本"""
        self.output_text.config(state="normal")
        self.output_text.insert(tk.END, text)
        if scroll:
            self.output_text.see(tk.END)
        self.output_text.config(state="disabled")


