# -*- coding: utf-8 -*-
"""编队与战斗 Tab（己方 vs 敌方，支持对抗压制战敌方加载）。

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
from src.entities_v2.enums import Side
from src.combat_v2.battle_flow_controller import BattleFlowController, BattleConfig
from src.combat_v2.battle_narrative import BattleNarrativeWriter

from gui.constants import (
    _BASE_PATH,
    _DARK_ACCENT,
    _DARK_FG,
    _DARK_INPUT_BG,
    AVATAR_DIR,
    BANNER_DIR,
    ENEMY_IMAGE_DIR,
    GRID_ALLY_POSITIONS,
    GRID_ENEMY_POSITIONS,
    PRESET_DIR,
)
from gui.widgets.result_table import ResultTablePanel
from gui.widgets.rdps import (
    _build_rdps_summary,
    _build_rdps_tables,
    _export_rdps_tracking_log,
)

from gui.tabs.base import BattleTabMixin


class TeamBattleTab(BattleTabMixin, ttk.Frame):
    """编队与战斗模式 - 己方 vs 敌方（可加载对抗压制战敌方阵容）"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.friend_slots: List[Dict[str, Any]] = []  # {cid, enemy_data, frame, avatar_label, name_label, clear_btn}
        self.enemy_slots: List[Dict[str, Any]] = []
        self.mem_options = ["(空)"] + self._build_memory_options()
        self._rdps_tracking_log: List[str] = []
        self._drag_source = None
        self._drag_preview = None
        self._build_char_options()
        self._build()

    # ─────────────────── 钩子方法覆盖 ───────────────────

    def _get_char_slots(self, is_enemy: bool = False):
        """返回指定阵营的角色槽位列表。"""
        return self.enemy_slots if is_enemy else self.friend_slots

    def _get_mem_slots(self, is_enemy: bool = False):
        """返回指定阵营的回忆卡槽位列表。"""
        return self.mem_enemy_slots if is_enemy else self.mem_friend_slots

    def _slot_has_content(self, slot) -> bool:
        """判断槽位是否有内容（cid 或 enemy_data）。"""
        return slot["cid"] is not None or slot.get("enemy_data") is not None

    def _swap_slots(self, src_slot, dst_slot, src_cid, dst_cid):
        """交换两个槽位（同时处理 cid 和 enemy_data 的互斥交换）。"""
        src_ed = src_slot.get("enemy_data")
        dst_ed = dst_slot.get("enemy_data")
        if src_ed is not None:
            self._set_slot_circle_enemy(dst_slot, src_ed)
        else:
            self._set_slot_char(dst_slot, src_cid)
        if dst_ed is not None:
            self._set_slot_circle_enemy(src_slot, dst_ed)
        elif dst_cid is not None:
            self._set_slot_char(src_slot, dst_cid)
        else:
            self._clear_slot(src_slot)

    # ─────────────────── 方法覆盖 ───────────────────

    def _build_slot(self, parent, slot_idx, is_enemy: bool = False):
        """构建单个编队槽位（在 Mixin 基础上附加 enemy_data 字段）。"""
        slot = super()._build_slot(parent, slot_idx, is_enemy)
        slot["enemy_data"] = None
        return slot

    def _set_slot_char(self, slot, cid):
        """设置槽位角色（同时清除 enemy_data）。"""
        slot["cid"] = cid
        slot["enemy_data"] = None
        self._update_slot_display(slot, cid)

    def _set_slot_circle_enemy(self, slot, enemy_data):
        """设置槽位为对抗压制战敌方"""
        slot["cid"] = None
        slot["enemy_data"] = enemy_data
        self._update_slot_display(slot, None)

    def _clear_slot(self, slot):
        """清除槽位（同时清除 cid 和 enemy_data）"""
        slot["cid"] = None
        slot["enemy_data"] = None
        self._update_slot_display(slot, None)

    def _update_slot_display(self, slot, cid):
        """更新槽位显示（avatar_label 现在是 Canvas，clear_btn 由外层管理）"""
        canvas = slot["avatar_label"]
        name_label = slot["name_label"]
        s = self.app._get_scheme()
        BANNER_W, BANNER_H = 154, 76

        # 清空画布
        canvas.delete("all")
        canvas.config(bg=s["bg"])
        canvas._banner_photo = None

        # 对抗压制战敌方分支
        enemy_data = slot.get("enemy_data")
        if enemy_data is not None:
            model_id = enemy_data.get("model_asset_id", "")
            photo = self._load_circle_enemy_avatar(model_id)
            if photo:
                canvas._banner_photo = photo
                canvas.create_image(BANNER_W // 2, BANNER_H // 2, image=photo, anchor="center")
            else:
                canvas.create_text(BANNER_W // 2, BANNER_H // 2, text="无头像",
                                   fill=s["border"], font=("Microsoft YaHei UI", 8))
            name_label.config(text=enemy_data.get("name", "???"))
            name_label.pack(pady=(1, 0))
            self._set_clear_btn_visible(slot, True)
            return

        if cid is None:
            canvas.create_text(BANNER_W // 2, BANNER_H // 2, text="点击选择",
                               fill=s["border"], font=("Microsoft YaHei UI", 8))
            name_label.config(text="")
            name_label.pack_forget()
            self._set_clear_btn_visible(slot, False)
        else:
            char = self.app.data_loader.get_character_by_id(cid)
            if not char:
                self._clear_slot(slot)
                return
            # 加载头像
            photo = self._load_slot_avatar(cid)
            if photo:
                canvas._banner_photo = photo
                canvas.create_image(BANNER_W // 2, BANNER_H // 2, image=photo, anchor="center")
            else:
                slot_text = f"[{cid}]" if self.app.is_developer_mode() else "???"
                canvas.create_text(BANNER_W // 2, BANNER_H // 2, text=slot_text,
                                   fill=s["border"], font=("Microsoft YaHei UI", 8))
            name = self.app.format_char_name(char)
            name_label.config(text=name)
            name_label.pack(pady=(1, 0))  # 恢复显示
            self._set_clear_btn_visible(slot, True)

    def _load_circle_enemy_avatar(self, model_asset_id):
        """加载对抗压制战敌方头像（按ModelAssetId命名，300x144→154x76）"""
        if not model_asset_id:
            return None
        from PIL import Image
        import tempfile, os
        BANNER_W, BANNER_H = 154, 76
        avatar_path = ENEMY_IMAGE_DIR / f"{model_asset_id}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            pil_img = pil_img.resize((BANNER_W, BANNER_H), Image.LANCZOS)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            pil_img.save(tmp_path, "PNG")
            photo = tk.PhotoImage(file=tmp_path)
            os.unlink(tmp_path)
            return photo
        except Exception:
            return None

    def _load_slot_avatar(self, cid):
        """加载槽位横版头像（优先从char_banners加载，回退到char_avatars裁剪）"""
        from PIL import Image
        BANNER_W, BANNER_H = 154, 76  # 显示尺寸，图片缩放填满画布

        # 优先使用横版头像
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

        # 回退：从竖版头像中心裁剪为横版比例
        avatar_path = AVATAR_DIR / f"{cid}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            # 从竖版头像中心裁剪出横版区域（保持原始内容）
            orig_w, orig_h = pil_img.size
            # 裁剪为原始比例的横版区域（约25:12）
            crop_h = int(orig_w * 144 / 300)
            top = (orig_h - crop_h) // 2
            if top < 0:
                top = 0
                crop_h = orig_h
            pil_img = pil_img.crop((0, top, orig_w, top + crop_h))
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

    # ─────────────────── 对抗压制战敌方加载 ───────────────────

    def _open_circle_enemy_loader(self):
        """打开对抗压制战敌方加载对话框"""
        s = self.app._get_scheme()
        dlg = tk.Toplevel(self)
        dlg.title("加载对抗压制战敌方")
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg=s["bg"])
        dlg.resizable(False, False)

        var_season = tk.StringVar(value="6")
        var_stage = tk.StringVar(value="1")

        row = ttk.Frame(dlg)
        row.pack(padx=15, pady=(15, 5))
        ttk.Label(row, text="赛季:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Spinbox(row, from_=1, to=99, textvariable=var_season, width=6).pack(side=tk.LEFT)
        ttk.Label(row, text="阶段:").pack(side=tk.LEFT, padx=(15, 5))
        ttk.Spinbox(row, from_=1, to=100, textvariable=var_stage, width=6).pack(side=tk.LEFT)

        btn_row = ttk.Frame(dlg)
        btn_row.pack(padx=15, pady=(5, 15))
        ttk.Button(btn_row, text="加载", command=lambda: self._on_circle_loader_confirm(dlg, var_season, var_stage)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _on_circle_loader_confirm(self, dlg, var_season, var_stage):
        """对抗压制战敌方加载对话框确认"""
        try:
            season = int(var_season.get())
            stage = int(var_stage.get())
        except (ValueError, TypeError):
            from tkinter import messagebox
            messagebox.showwarning("输入错误", "赛季和阶段必须是整数", parent=dlg)
            return
        stage_data = self.app.data_loader.get_circle_battle_stage(season, stage)
        if not stage_data:
            from tkinter import messagebox
            messagebox.showwarning("数据不存在", f"赛季{season} 阶段{stage} 的数据不存在", parent=dlg)
            return
        dlg.destroy()
        self._load_circle_enemies(stage_data)

    def _load_circle_enemies(self, stage_data):
        """加载对抗压制战敌方到敌方slot"""
        for slot in self.enemy_slots:
            self._clear_slot(slot)
        for enemy in stage_data.get("enemies", []):
            s = enemy.get("slot", 0)
            if 1 <= s <= 6:
                self._set_slot_circle_enemy(self.enemy_slots[s - 1], enemy)

    # ─────────────────── UI 构建 ───────────────────

    def _build_char_options(self):
        self.char_names = []
        for cid in self.app.char_ids:
            char = self.app.data_loader.get_character_by_id(cid)
            if char:
                self.char_names.append(f"[{cid}] {self.app.format_char_name(char)}")
        for cid, char_data in self.app.data_loader.get_all_custom_dummies().items():
            self.char_names.append(f"[{cid}] {char_data.name}")
        self.char_options = ["(空)"] + self.char_names

    def _refresh_char_options(self):
        self._build_char_options()
        for slot in self.friend_slots + self.enemy_slots:
            if slot.get("enemy_data") is not None:
                self._update_slot_display(slot, None)
                continue
            if slot["cid"] is not None:
                char = self.app.data_loader.get_character_by_id(slot["cid"])
                if char:
                    self._update_slot_display(slot, slot["cid"])
                else:
                    self._clear_slot(slot)
            else:
                self._update_slot_display(slot, None)

    def _build(self):
        s = self.app._get_scheme()
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=5)

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

        # ── 敌方编队 + 敌方回忆卡（同行） ──
        enemy_main = tk.Frame(f, bg=s["bg"])
        enemy_main.pack(pady=(10, 0), fill="x", padx=10)
        self._enemy_main = enemy_main

        ttk.Label(enemy_main, text="=== 敌方编队 ===", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(5, 5))
        ttk.Button(enemy_main, text="对抗压制战敌方", command=self._open_circle_enemy_loader,
                   width=12).grid(row=0, column=2, sticky="e", pady=(5, 5))

        enemy_form_frame = tk.Frame(enemy_main, bg=s["bg"])
        enemy_form_frame.grid(row=1, column=0, columnspan=3, sticky="nw")
        self._enemy_form_frame = enemy_form_frame

        s = self.app._get_scheme()
        enemy_labels = ["左前(1)", "中前(2)", "右前(3)", "左后(4)", "中后(5)", "右后(6)"]
        for i, label in enumerate(enemy_labels):
            frame = tk.Frame(enemy_form_frame, bg=s["bg"], highlightbackground=s["border"], highlightthickness=1)
            r = 0 if i >= 3 else 1
            c = i % 3
            frame.grid(row=r, column=c, padx=3, pady=3)
            # 固定外框尺寸，防止内容撑大（留足空间给两行角色名）
            frame.grid_propagate(False)
            frame.configure(width=164, height=140)
            # Row 0: 位置标签（左） + 清除按钮（右）
            pos_label = ttk.Label(frame, text=label, font=("Microsoft YaHei UI", 8))
            pos_label.grid(row=0, column=0, sticky="w", padx=(3, 0))
            clear_btn = tk.Label(frame, text="\u00d7", fg=s["border"], bg=s["bg"],
                                  font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2")
            clear_btn.grid(row=0, column=1, sticky="e", padx=(0, 3))
            clear_btn.bind("<Button-1>", lambda e, idx=i: self._clear_slot_by_idx(idx, True))
            clear_btn.grid_remove()  # 默认隐藏
            # Row 1: 槽位内容（头像画布 + 角色名），加大内外框间距
            slot = self._build_slot(frame, i, is_enemy=True)
            slot["frame"].grid(row=1, column=0, columnspan=2, padx=5, pady=(2, 2))
            slot["clear_btn"] = clear_btn
            slot["outer_frame"] = frame
            self.enemy_slots.append(slot)

        ttk.Label(enemy_main, text="=== 敌方回忆卡 ===", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=0, column=3, sticky="w", pady=(5, 5), padx=(15, 0))

        enemy_mem_frame = tk.Frame(enemy_main, bg=s["bg"])
        enemy_mem_frame.grid(row=1, column=3, sticky="n", padx=(15, 0))
        self._enemy_mem_frame = enemy_mem_frame
        self.mem_enemy_slots: List[Dict[str, Any]] = []
        for i in range(6):
            r, c = divmod(i, 2)
            slot = self._build_mem_slot(enemy_mem_frame, i, is_enemy=True)
            slot["frame"].grid(row=r, column=c, padx=2, pady=2)
            self.mem_enemy_slots.append(slot)

        # ── 己方编队 + 己方回忆卡（同行） ──
        ally_main = tk.Frame(f, bg=s["bg"])
        ally_main.pack(pady=(20, 0), fill="x", padx=10)
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
            # 固定外框尺寸，防止内容撑大（留足空间给两行角色名）
            frame.grid_propagate(False)
            frame.configure(width=164, height=140)
            # Row 0: 位置标签（左） + 清除按钮（右）
            pos_label = ttk.Label(frame, text=label, font=("Microsoft YaHei UI", 8))
            pos_label.grid(row=0, column=0, sticky="w", padx=(3, 0))
            clear_btn = tk.Label(frame, text="\u00d7", fg=s["border"], bg=s["bg"],
                                  font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2")
            clear_btn.grid(row=0, column=1, sticky="e", padx=(0, 3))
            clear_btn.bind("<Button-1>", lambda e, idx=i: self._clear_slot_by_idx(idx, False))
            clear_btn.grid_remove()  # 默认隐藏
            # Row 1: 槽位内容（头像画布 + 角色名），加大内外框间距
            slot = self._build_slot(frame, i, is_enemy=False)
            slot["frame"].grid(row=1, column=0, columnspan=2, padx=5, pady=(2, 2))
            slot["clear_btn"] = clear_btn
            slot["outer_frame"] = frame
            self.friend_slots.append(slot)

        ttk.Label(ally_main, text="=== 己方回忆卡 ===", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=0, column=3, sticky="w", pady=(5, 5))

        ally_mem_frame = tk.Frame(ally_main, bg=s["bg"])
        ally_mem_frame.grid(row=1, column=3, sticky="n", padx=(15, 0))
        self._ally_mem_frame = ally_mem_frame
        self.mem_friend_slots: List[Dict[str, Any]] = []
        for i in range(6):
            r, c = divmod(i, 2)
            slot = self._build_mem_slot(ally_mem_frame, i, is_enemy=False)
            slot["frame"].grid(row=r, column=c, padx=2, pady=2)
            self.mem_friend_slots.append(slot)

        # ── 预设管理 ──
        preset_frame = ttk.LabelFrame(f, text="预设管理")
        preset_frame.pack(pady=10, fill="x", padx=10)

        self.preset_listbox = tk.Listbox(preset_frame, height=5,
                                         bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                         selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                         borderwidth=0, highlightthickness=0,
                                         font=("Microsoft YaHei UI", 9))
        self.preset_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        btn_frame = ttk.Frame(preset_frame)
        btn_frame.pack(side=tk.RIGHT, padx=5, pady=5)
        ttk.Button(btn_frame, text="保存", command=self._save_preset).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="加载", command=self._load_preset).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="删除", command=self._delete_preset).pack(fill="x", pady=2)
        self.preset_name_var = tk.StringVar(value="预设1")
        ttk.Entry(btn_frame, textvariable=self.preset_name_var, width=14).pack(fill="x", pady=2)

        self._refresh_presets()

        # ── 开始按钮 ──
        ctrl_frame = ttk.Frame(f)
        ctrl_frame.pack(pady=10, fill="x", padx=10)
        self.start_btn = ttk.Button(ctrl_frame, text="▶ 开始模拟", command=self._start_battle, width=20)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.log_btn = ttk.Button(ctrl_frame, text="📋 单次模拟+日志", command=self._start_single_battle_with_log, width=20)
        self.log_btn.pack(side=tk.LEFT, padx=5)
        self.rdps_log_btn = ttk.Button(ctrl_frame, text="📤 导出RDPS日志",
                                       command=lambda: _export_rdps_tracking_log(self, self._rdps_tracking_log),
                                       width=18)
        self.rdps_log_btn.pack(side=tk.LEFT, padx=5)
        self.progress_var = tk.StringVar(value="")
        ttk.Label(ctrl_frame, textvariable=self.progress_var).pack(side=tk.LEFT, padx=10)

        # ── 结果输出 ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self._result_panel = ResultTablePanel(right_frame, self.app, title="模拟结果")
        self._result_panel.pack(fill=tk.BOTH, expand=True)

    # ─────────────────── 选择与选项 ───────────────────

    def _get_char_id_from_combo(self, value: str) -> Optional[int]:
        if value.startswith("[") and "] " in value:
            return int(value.split("]")[0][1:])
        return None

    def _build_memory_options(self):
        options = []
        try:
            memories = self.app.data_loader.load_memories()
            for mid, mem in memories.items():
                options.append(f"[{mid}] {mem.name}")
        except Exception:
            pass
        return options

    def _get_selection(self) -> Dict[str, Any]:
        friends = []
        friend_positions = []
        for slot in self.friend_slots:
            cid = slot["cid"]
            friend_positions.append(cid)
            if cid:
                friends.append(cid)
        enemies = []
        enemy_positions = []
        enemy_names = {}
        for slot in self.enemy_slots:
            ed = slot.get("enemy_data")
            if ed is not None:
                enemy_positions.append(ed)
                eid = ed["enemy_id"]
                enemies.append(eid)
                enemy_names[eid] = ed.get("name", str(eid))
            else:
                cid = slot["cid"]
                enemy_positions.append(cid)
                if cid:
                    enemies.append(cid)
        # 回忆卡：从可视化槽位获取 mid
        mem_friend_positions = []
        for slot in self.mem_friend_slots:
            mid = slot["mid"]
            if mid is not None:
                mem = self.app.data_loader.get_memory(mid)
                mem_friend_positions.append(f"[{mid}] {mem.name}" if mem else f"[{mid}]")
            else:
                mem_friend_positions.append("")
        mem_enemy_positions = []
        for slot in self.mem_enemy_slots:
            mid = slot["mid"]
            if mid is not None:
                mem = self.app.data_loader.get_memory(mid)
                mem_enemy_positions.append(f"[{mid}] {mem.name}" if mem else f"[{mid}]")
            else:
                mem_enemy_positions.append("")
        return {
            "friends": friends,
            "friend_positions": friend_positions,
            "enemies": enemies,
            "enemy_positions": enemy_positions,
            "enemy_names": enemy_names,
            "mems_friend": [e for e in mem_friend_positions if e],
            "mem_friend_positions": mem_friend_positions,
            "mems_enemy": [e for e in mem_enemy_positions if e],
            "mem_enemy_positions": mem_enemy_positions,
        }

    # ─────────────────── 战斗模拟 ───────────────────

    def _start_battle(self):
        sel = self._get_selection()
        if not sel["friends"] or not sel["enemies"]:
            messagebox.showwarning("编队不完整", "请至少为己方和敌方各选择1个角色")
            return

        self.start_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary("正在模拟...\n")

        thread = threading.Thread(target=self._run_simulation, args=(sel,), daemon=True)
        thread.start()

    def _run_simulation(self, sel):
        try:
            # 保存自定义假人数据到磁盘，确保worker进程能加载
            self.app.data_loader.save_custom_dummies()
            global_vals = self.app.global_tab.get_values()
            results = self._run_batch(sel, global_vals)

            self.app.root.after(0, lambda: self._display_results(results))
        except Exception as e:
            err_msg = str(e)
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _run_batch(self, sel, global_vals):
        friends_chars = sel.get("friends", [])
        friend_positions = sel.get("friend_positions", friends_chars)
        enemies_chars = sel.get("enemies", [])
        enemy_positions = sel.get("enemy_positions", enemies_chars)
        total_runs = global_vals["runs"]
        max_turns = global_vals["max_turns"]
        # 未设置时自动检测CPU核心数
        n_workers = int(global_vals.get("workers", 0) or 0)
        if n_workers <= 1:
            n_workers = None  # BatchSimulator 将自动使用 CPU 核心数

        panel_config = self.app._build_panel_config_from_gui(global_vals)

        from src.utils.batch_simulator import BatchSimulator

        sim = BatchSimulator(self.app.data_loader, max_workers=n_workers)

        # 进度回调（从worker线程通过after投递到GUI主线程）
        def progress_cb(done, total):
            pct = done / total * 100 if total else 0
            self.app.root.after(0, lambda d=done, t=total, p=pct:
                                self.progress_var.set(f"{d}/{t} ({p:.0f}%)"))

        result = sim.run_batch(
            panel_config=panel_config,
            friends_chars=friends_chars,
            friend_positions=friend_positions,
            enemies_chars=enemies_chars,
            enemy_positions=enemy_positions,
            total_runs=total_runs,
            max_turns=max_turns,
            positions_ally=GRID_ALLY_POSITIONS,
            positions_enemy=GRID_ENEMY_POSITIONS,
            progress_callback=progress_cb,
            memory_cards=self._build_memory_cards(sel.get("mems_friend", [])),
            enable_rdps=global_vals.get("enable_rdps", True),
        )

        return {
            "wins": result.wins, "losses": result.losses,
            "total_runs": result.total_runs,
            "total_turns": result.total_turns,
            "turn_list": result.turn_list,
            "char_dmg": result.char_dmg,
            "char_actions": result.char_actions,
            "char_survivals": result.char_survivals,
            "char_deaths": result.char_deaths,
            "friends_chars": result.friends_chars,
            "enemies_chars": result.enemies_chars,
            "enemy_names": sel.get("enemy_names", {}),
            "rate": result.rate,
            "elapsed": result.elapsed,
            "all_ally_damage": result.all_ally_damage,
            "all_ally_received": result.all_ally_received,
            "all_ally_healed": result.all_ally_healed,
            "all_enemy_damage": result.all_enemy_damage,
            "all_enemy_received": result.all_enemy_received,
            "all_enemy_healed": result.all_enemy_healed,
            "all_enemy_healing_received": result.all_enemy_healing_received,
            "rdps_avg": result.rdps_avg,
        }

    @staticmethod
    def _make_battle_config(max_turns, enable_rdps=True, enable_rdps_tracking=False):
        cfg = BattleConfig()
        cfg.max_turns = max_turns
        cfg.enable_rdps = enable_rdps
        cfg.enable_rdps_tracking = enable_rdps_tracking
        return cfg

    def _display_results(self, results):
        self.start_btn.config(state="normal")
        self.log_btn.config(state="normal")
        self.progress_var.set("完成!")
        self._result_panel.clear()

        w = results
        total = w["total_runs"]
        if total == 0:
            return

        win_rate = w["wins"] / total * 100
        avg_turns = w["total_turns"] / total
        min_turns = min(w["turn_list"])
        max_turns = max(w["turn_list"])

        out = []
        out.append("=" * 60)
        out.append(f"  模拟统计 ({total} 场)")
        out.append("=" * 60)
        out.append(f"  胜率: {w['wins']}/{total} = {win_rate:.1f}%")
        out.append(f"  回合: 平均{avg_turns:.1f} | 最少{min_turns} | 最多{max_turns}")
        rate = w.get("rate", 0)
        elapsed = w.get("elapsed", 0)
        if rate > 0:
            out.append(f"  效率: {rate:.1f} 场/秒 | 耗时 {elapsed:.1f} 秒")
        out.append("=" * 60)

        # 统计数据（参考战术演习格式，不含计分）
        all_ally_damage = w.get("all_ally_damage", [])
        all_ally_received = w.get("all_ally_received", [])
        all_ally_healed = w.get("all_ally_healed", [])
        all_enemy_damage = w.get("all_enemy_damage", [])
        all_enemy_received = w.get("all_enemy_received", [])
        all_enemy_healed = w.get("all_enemy_healed", [])

        if all_ally_damage:
            def _mean(lst):
                return sum(lst) / len(lst) if lst else 0.0

            if total == 1:
                out.append("")
                out.append("─" * 60)
                out.append(f"  【统计明细】")
                out.append("")
                out.append(f"  【我方合计】")
                out.append(f"    造成伤害: {all_ally_damage[0]:,}")
                out.append(f"    受到伤害: {all_ally_received[0]:,}")
                out.append(f"    提供回复: {all_ally_healed[0]:,}")
                out.append("")
                out.append(f"  【敌方合计】")
                out.append(f"    造成伤害: {all_enemy_damage[0]:,}")
                out.append(f"    受到伤害: {all_enemy_received[0]:,}")
                out.append(f"    提供回复: {all_enemy_healed[0]:,}")
                out.append("─" * 60)
            else:
                out.append("")
                out.append("─" * 60)
                out.append(f"  【统计明细 ({total} 场平均值)】")
                out.append("")
                out.append(f"  【我方合计（场均）】")
                out.append(f"    造成伤害: {_mean(all_ally_damage):,.1f}")
                out.append(f"    受到伤害: {_mean(all_ally_received):,.1f}")
                out.append(f"    提供回复: {_mean(all_ally_healed):,.1f}")
                out.append("")
                out.append(f"  【敌方合计（场均）】")
                out.append(f"    造成伤害: {_mean(all_enemy_damage):,.1f}")
                out.append(f"    受到伤害: {_mean(all_enemy_received):,.1f}")
                out.append(f"    提供回复: {_mean(all_enemy_healed):,.1f}")
                out.append("─" * 60)

        rdps_avg = w.get("rdps_avg")
        if rdps_avg:
            out.append(_build_rdps_summary(rdps_avg))

        self._result_panel.set_summary("\n".join(out))

        # 角色明细表（Treeview）
        def _avg(lst):
            return sum(lst) / len(lst) if lst else 0

        tables = []
        # 我方角色
        ally_rows = []
        for cid in w["friends_chars"]:
            char = self.app.data_loader.get_character_by_id(cid)
            name = char.name if char else str(cid)
            dmg_list = w["char_dmg"].get(cid, [0])
            surv = w["char_survivals"].get(cid, 0)
            death = w["char_deaths"].get(cid, 0)
            sr = surv / (surv + death) * 100 if (surv + death) else 0
            ally_rows.append([name, f"{_avg(dmg_list):,.0f}", f"{max(dmg_list):,}", f"{sr:.1f}%"])
        if ally_rows:
            tables.append({"title": "我方角色", "columns": ["角色", "平均伤害", "最大伤害", "存活率"],
                           "rows": ally_rows, "col_widths": [135, 110, 110, 80],
                           "col_aligns": ["w", "e", "e", "e"]})

        # 敌方角色
        enemy_rows = []
        enemy_names = w.get("enemy_names", {})
        for cid in w["enemies_chars"]:
            char = self.app.data_loader.get_character_by_id(cid)
            name = char.name if char else enemy_names.get(cid, str(cid))
            dmg_list = w["char_dmg"].get(cid, [0])
            surv = w["char_survivals"].get(cid, 0)
            death = w["char_deaths"].get(cid, 0)
            sr = surv / (surv + death) * 100 if (surv + death) else 0
            enemy_rows.append([name, f"{_avg(dmg_list):,.0f}", f"{max(dmg_list):,}", f"{sr:.1f}%"])
        if enemy_rows:
            tables.append({"title": "敌方角色", "columns": ["角色", "平均伤害", "最大伤害", "存活率"],
                           "rows": enemy_rows, "col_widths": [135, 110, 110, 80],
                           "col_aligns": ["w", "e", "e", "e"]})

        if rdps_avg:
            tables.extend(_build_rdps_tables(rdps_avg))

        if tables:
            self._result_panel.set_tables(tables)

    def _display_error(self, msg):
        self.start_btn.config(state="normal")
        self.log_btn.config(state="normal")
        self.progress_var.set("错误!")
        self._result_panel.append_summary(f"\n❌ 模拟出错:\n{msg}\n")

    def _start_single_battle_with_log(self):
        sel = self._get_selection()
        if not sel["friends"] or not sel["enemies"]:
            messagebox.showwarning("编队不完整", "请至少为己方和敌方各选择1个角色")
            return

        self.start_btn.config(state="disabled")
        self.log_btn.config(state="disabled")
        self._result_panel.clear()
        self._result_panel.append_summary("正在单次模拟并生成日志...\n")

        thread = threading.Thread(target=self._run_single_with_log, args=(sel,), daemon=True)
        thread.start()

    def _run_single_with_log(self, sel):
        try:
            global_vals = self.app.global_tab.get_values()
            max_turns = global_vals["max_turns"]

            panel_config = self.app._build_panel_config_from_gui(global_vals)
            player_config = panel_config.get_player_config()
            lerp_data = self.app.data_loader.load_level_lerp_data()
            stat_calculator = StatCalculator(lerp_data, data_loader=self.app.data_loader)

            narrative = BattleNarrativeWriter()

            friend_positions = sel.get("friend_positions", sel.get("friends", []))
            enemy_positions = sel.get("enemy_positions", sel.get("enemies", []))

            bf = BattlefieldState()
            for i, cid in enumerate(friend_positions):
                if cid is not None:
                    u = self.app._create_unit(panel_config, player_config, stat_calculator,
                                              cid, Side.ALLY, GRID_ALLY_POSITIONS[i])
                    if u:
                        bf.add_unit(u)
            for i, cid in enumerate(enemy_positions):
                if cid is not None:
                    if isinstance(cid, dict):
                        u = self.app.circle_tab._create_circle_battle_enemy(cid)
                    else:
                        u = self.app._create_unit(panel_config, player_config, stat_calculator,
                                                  cid, Side.ENEMY, GRID_ENEMY_POSITIONS[i])
                    if u:
                        bf.add_unit(u)

            bf.memory_cards = self._build_memory_cards(sel.get("mems_friend", []))

            seed = int(time.time() * 1000000) % (2**31)
            random.seed(seed)

            controller = BattleFlowController(bf, data_loader=self.app.data_loader,
                                      config=self._make_battle_config(max_turns, global_vals.get("enable_rdps", True),
                                                                      enable_rdps_tracking=True),
                                      narrative=narrative)
            result = controller.execute_battle()

            log_dir = _BASE_PATH / "data" / "battle_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"battle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            narrative.write(str(log_path))

            winner_text = "胜利" if result['winner'] == 'FRIEND' else ("败北" if result['winner'] == 'ENEMY' else "超时")
            tracking_log = result.get("rdps_tracking_log") or []
            self.app.root.after(0, lambda: self._display_single_result(result, winner_text, str(log_path), tracking_log))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_single_result(self, result, winner_text, log_path, tracking_log=None):
        self.start_btn.config(state="normal")
        self.log_btn.config(state="normal")
        if tracking_log is not None:
            self._rdps_tracking_log = tracking_log
        self.progress_var.set("完成!")
        self._result_panel.clear()
        out = []
        out.append("=" * 60)
        out.append(f"  单次模拟结果: {winner_text}")
        out.append(f"  回合数: {result['total_turns']}")
        out.append(f"  日志文件: {log_path}")
        if tracking_log:
            out.append(f"  RDPS追踪日志: {len(tracking_log)} 行（可点击\"导出RDPS日志\"按钮导出）")
        out.append("=" * 60)

        score_data = result.get("score")
        tables = []
        if score_data:
            out.append("")
            out.append("─" * 60)
            out.append(f"  【统计明细】")
            out.append("")
            out.append(f"  【我方合计】")
            out.append(f"    造成伤害: {score_data.get('ally_total_damage_dealt', 0):,}")
            out.append(f"    受到伤害: {score_data.get('ally_total_damage_received', 0):,}")
            out.append(f"    提供回复: {score_data.get('ally_total_hp_healed', 0):,}")
            out.append("")
            out.append(f"  【敌方合计】")
            out.append(f"    造成伤害: {score_data.get('enemy_total_damage_dealt', 0):,}")
            out.append(f"    受到伤害: {score_data.get('enemy_total_damage_received', 0):,}")
            out.append(f"    提供回复: {score_data.get('enemy_total_hp_healed', 0):,}")
            out.append("─" * 60)

            unit_stats = score_data.get("unit_stats", {})
            ally_units = {uid: s for uid, s in unit_stats.items() if s.get("side") == "ally"}
            enemy_units = {uid: s for uid, s in unit_stats.items() if s.get("side") == "enemy"}

            cols = ["角色", "造成伤害", "受到伤害", "提供回复"]
            widths = [135, 120, 120, 120]
            aligns = ["w", "e", "e", "e"]

            if ally_units:
                rows = []
                for uid, s in ally_units.items():
                    name = s.get("name", uid)
                    rows.append([name, f"{s['damage_dealt']:,}", f"{s['damage_received']:,}", f"{s['hp_healed']:,}"])
                tables.append({"title": "我方角色明细", "columns": cols, "rows": rows,
                               "col_widths": widths, "col_aligns": aligns})

            if enemy_units:
                rows = []
                for uid, s in enemy_units.items():
                    name = s.get("name", uid)
                    rows.append([name, f"{s['damage_dealt']:,}", f"{s['damage_received']:,}", f"{s['hp_healed']:,}"])
                tables.append({"title": "敌方角色明细", "columns": cols, "rows": rows,
                               "col_widths": widths, "col_aligns": aligns})

        rdps_data = result.get("rdps")
        if rdps_data:
            out.append(_build_rdps_summary(rdps_data))
            tables.extend(_build_rdps_tables(rdps_data))

        self._result_panel.set_summary("\n".join(out))
        if tables:
            self._result_panel.set_tables(tables)

    # ─────────────────── 预设管理 ───────────────────

    def _refresh_presets(self):
        self.preset_listbox.delete(0, tk.END)
        PRESET_DIR.mkdir(parents=True, exist_ok=True)
        for f in sorted(PRESET_DIR.glob("*.json")):
            self.preset_listbox.insert(tk.END, f.stem)

    def _save_preset(self):
        name = self.preset_name_var.get().strip()
        if not name:
            messagebox.showwarning("名称", "请输入预设名称")
            return
        sel = self._get_selection()
        PRESET_DIR.mkdir(parents=True, exist_ok=True)
        path = PRESET_DIR / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sel, f, ensure_ascii=False, indent=2)
        self._refresh_presets()
        messagebox.showinfo("保存", f"预设 '{name}' 已保存")

    def _load_preset(self):
        sel = self.preset_listbox.curselection()
        if not sel:
            return
        name = self.preset_listbox.get(sel[0])
        path = PRESET_DIR / f"{name}.json"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        friend_positions = data.get("friend_positions")
        if friend_positions is not None:
            for i, cid in enumerate(friend_positions):
                if i < len(self.friend_slots):
                    if cid is not None:
                        self._set_slot_char(self.friend_slots[i], cid)
                    else:
                        self._clear_slot(self.friend_slots[i])
        else:
            for i, cid in enumerate(data.get("friends", [])):
                if i < len(self.friend_slots):
                    self._set_slot_char(self.friend_slots[i], cid)
            for i in range(len(data.get("friends", [])), len(self.friend_slots)):
                self._clear_slot(self.friend_slots[i])

        enemy_positions = data.get("enemy_positions")
        if enemy_positions is not None:
            for i, cid in enumerate(enemy_positions):
                if i < len(self.enemy_slots):
                    if isinstance(cid, dict):
                        self._set_slot_circle_enemy(self.enemy_slots[i], cid)
                    elif cid is not None:
                        self._set_slot_char(self.enemy_slots[i], cid)
                    else:
                        self._clear_slot(self.enemy_slots[i])
        else:
            for i, cid in enumerate(data.get("enemies", [])):
                if i < len(self.enemy_slots):
                    self._set_slot_char(self.enemy_slots[i], cid)
            for i in range(len(data.get("enemies", [])), len(self.enemy_slots)):
                self._clear_slot(self.enemy_slots[i])

        mem_friend_positions = data.get("mem_friend_positions")
        if mem_friend_positions is not None:
            for i, mem_entry in enumerate(mem_friend_positions):
                if i < len(self.mem_friend_slots):
                    mid = self._parse_memory_card_id(mem_entry) if mem_entry else None
                    if mid is not None:
                        self._set_mem_slot(i, mid, False)
                    else:
                        self._clear_mem_slot(i, False)
            for i in range(len(mem_friend_positions), len(self.mem_friend_slots)):
                self._clear_mem_slot(i, False)
        else:
            mems = data.get("mems_friend", [])
            for i, mem_entry in enumerate(mems):
                if i < len(self.mem_friend_slots):
                    mid = self._parse_memory_card_id(mem_entry) if mem_entry else None
                    if mid is not None:
                        self._set_mem_slot(i, mid, False)
                    else:
                        self._clear_mem_slot(i, False)
            for i in range(len(mems), len(self.mem_friend_slots)):
                self._clear_mem_slot(i, False)

        mem_enemy_positions = data.get("mem_enemy_positions")
        if mem_enemy_positions is not None:
            for i, mem_entry in enumerate(mem_enemy_positions):
                if i < len(self.mem_enemy_slots):
                    mid = self._parse_memory_card_id(mem_entry) if mem_entry else None
                    if mid is not None:
                        self._set_mem_slot(i, mid, True)
                    else:
                        self._clear_mem_slot(i, True)
            for i in range(len(mem_enemy_positions), len(self.mem_enemy_slots)):
                self._clear_mem_slot(i, True)
        else:
            mems = data.get("mems_enemy", [])
            for i, mem_entry in enumerate(mems):
                if i < len(self.mem_enemy_slots):
                    mid = self._parse_memory_card_id(mem_entry) if mem_entry else None
                    if mid is not None:
                        self._set_mem_slot(i, mid, True)
                    else:
                        self._clear_mem_slot(i, True)
            for i in range(len(mems), len(self.mem_enemy_slots)):
                self._clear_mem_slot(i, True)

    def _delete_preset(self):
        sel = self.preset_listbox.curselection()
        if not sel:
            return
        name = self.preset_listbox.get(sel[0])
        path = PRESET_DIR / f"{name}.json"
        if path.exists():
            os.remove(path)
            self._refresh_presets()
