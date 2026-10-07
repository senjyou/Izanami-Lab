# -*- coding: utf-8 -*-
"""敌方详情弹窗：显示敌方各项属性和技能。

从 gui_app.py 抽取。
"""

import os
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any

from gui.constants import (
    ELEMENT_NAMES,
    CHAR_TYPE_NAMES,
    ROLE_TYPE_NAMES,
    RARITY_NAMES,
    ENEMY_IMAGE_DIR,
)
from gui.widgets.modal import _bind_modal_minimize_restore


class EnemyDetailDialog(tk.Toplevel):
    """敌方详情弹窗：显示敌方各项属性和技能（参考角色页角色信息显示）"""

    # 敌方位置名称映射
    POSITION_NAMES = {1: "左前", 2: "中前", 3: "右前", 4: "左后", 5: "中后", 6: "右后"}

    def __init__(self, parent, app, enemy_data: Dict[str, Any], title="敌方详情"):
        super().__init__(parent)
        self.app = app
        self.enemy_data = enemy_data
        self._avatar_photo = None  # 保持头像引用避免被GC回收

        self.title(title)
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(True, True)
        self.geometry("640x720")
        self.minsize(520, 600)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 居中于父窗口
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _build(self):
        s = self.app._get_scheme()
        self.configure(bg=s["bg"])

        # ── 可滚动内容容器 ──
        scroll_outer = tk.Frame(self, bg=s["bg"])
        scroll_outer.pack(fill="both", expand=True)
        self._scroll_canvas = tk.Canvas(scroll_outer, bg=s["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_outer, orient="vertical",
                                   command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._scroll_canvas.pack(side=tk.LEFT, fill="both", expand=True)

        # 内容载体
        content = tk.Frame(self._scroll_canvas, bg=s["bg"])
        self._scroll_canvas_window = self._scroll_canvas.create_window(
            (0, 0), window=content, anchor="nw")
        content.bind("<Configure>",
                      lambda e: self._scroll_canvas.configure(
                          scrollregion=self._scroll_canvas.bbox("all")))
        self._scroll_canvas.bind("<Configure>", self._on_scroll_canvas_resize)

        # 鼠标滚轮支持
        def _bind_mw(e):
            self._scroll_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _enter(e):
            self._scroll_canvas.bind_all("<MouseWheel>", _bind_mw)

        def _leave(e):
            self._scroll_canvas.unbind_all("<MouseWheel>")

        self._scroll_canvas.bind("<Enter>", _enter)
        self._scroll_canvas.bind("<Leave>", _leave)

        # ── 顶部：头像 + 基本信息 ──
        top_frame = tk.Frame(content, bg=s["bg"])
        top_frame.pack(fill="x", padx=10, pady=5)

        # 头像（原图300x144，缩放到250x120保持比例）
        AVATAR_W, AVATAR_H = 250, 120
        avatar_canvas = tk.Canvas(top_frame, width=AVATAR_W, height=AVATAR_H,
                                   bg=s["bg"], highlightthickness=0)
        avatar_canvas.pack(side=tk.LEFT, padx=(0, 10))

        photo = self._load_enemy_avatar(
            self.enemy_data.get("model_asset_id", ""), AVATAR_W, AVATAR_H)
        if photo:
            self._avatar_photo = photo
            avatar_canvas.create_image(AVATAR_W // 2, AVATAR_H // 2,
                                        image=photo, anchor="center")
        else:
            avatar_canvas.create_text(AVATAR_W // 2, AVATAR_H // 2, text="无头像",
                                       fill=s["border"],
                                       font=("Microsoft YaHei UI", 10))

        # 基本信息右侧
        info_frame = tk.Frame(top_frame, bg=s["bg"])
        info_frame.pack(side=tk.LEFT, fill="y")

        name = self.enemy_data.get("name", "???")
        level = self.enemy_data.get("level", 1)
        slot = self.enemy_data.get("slot", 1)
        pos_text = self.POSITION_NAMES.get(slot, f"位置{slot}")

        ttk.Label(info_frame, text=name,
                   font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        ttk.Label(info_frame, text=f"等级: {level}",
                   font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(5, 0))
        ttk.Label(info_frame, text=f"位置: {pos_text}",
                   font=("Microsoft YaHei UI", 10)).pack(anchor="w")

        # ── 中部：属性网格 ──
        stats_frame = ttk.LabelFrame(content, text="属性")
        stats_frame.pack(fill="x", padx=10, pady=5)

        hp = self.enemy_data.get("hp", 0)
        attack = self.enemy_data.get("attack", 0)
        defense = self.enemy_data.get("defense", 0)
        speed = self.enemy_data.get("speed", 0)
        crit = self.enemy_data.get("critical_rate", 0)
        attribute = ELEMENT_NAMES.get(self.enemy_data.get("attribute", 0), "未知")
        char_type = CHAR_TYPE_NAMES.get(self.enemy_data.get("type", 0), "未知")
        role_type = ROLE_TYPE_NAMES.get(self.enemy_data.get("role_type", 0), "未知")
        rarity = RARITY_NAMES.get(self.enemy_data.get("rarity", 0), "未知")
        ap = self.enemy_data.get("action_point", 0)
        pp = self.enemy_data.get("passive_point", 0)

        stats = [
            ("HP", str(hp)), ("ATK", str(attack)), ("DEF", str(defense)),
            ("SPD", str(speed)), ("暴击率", f"{crit * 100:.1f}%"), ("属性", attribute),
            ("类型", char_type), ("定位", role_type), ("稀有度", rarity),
            ("AP", str(ap)), ("PP", str(pp)),
        ]
        # 敌方ID仅在开发者模式下显示
        if self.app.is_developer_mode():
            stats.append(("敌方ID", str(self.enemy_data.get("enemy_id", ""))))

        for i, (label, value) in enumerate(stats):
            r, c = divmod(i, 4)
            cell = ttk.Frame(stats_frame)
            cell.grid(row=r, column=c, padx=8, pady=3, sticky="w")
            ttk.Label(cell, text=f"{label}:",
                       font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
            ttk.Label(cell, text=value,
                       font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT, padx=(3, 0))

        # ── 底部：技能列表 ──
        skill_frame = ttk.LabelFrame(content, text="技能")
        skill_frame.pack(fill="x", padx=10, pady=5)

        self._render_skills(skill_frame)

        # ── 关闭按钮 ──
        btn_frame = ttk.Frame(content)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="关闭", command=self._on_close, width=10).pack()

    def _on_scroll_canvas_resize(self, event):
        """滚动画布尺寸变化时，同步内容宽度"""
        self._scroll_canvas.itemconfig(self._scroll_canvas_window, width=event.width)

    def _load_enemy_avatar(self, model_asset_id: str, w: int, h: int):
        """加载敌方头像（按ModelAssetId命名，缩放到指定尺寸）"""
        if not model_asset_id:
            return None
        from PIL import Image
        avatar_path = ENEMY_IMAGE_DIR / f"{model_asset_id}.png"
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

    def _render_skills(self, parent):
        """渲染技能列表（参考CharacterParamsTab._render_skill_cards，只读版）"""
        s = self.app._get_scheme()
        skill_ids = self.enemy_data.get("skill_ids", [])
        raw_levels = self.enemy_data.get("skill_levels", {})

        if not skill_ids:
            ttk.Label(parent, text="(无技能)",
                       font=("Microsoft YaHei UI", 9)).pack(padx=5, pady=5)
            return

        skill_type_names = {1: "AS", 2: "PS", 3: "EX"}
        cost_unit = {1: "AP", 2: "PP", 3: "EP"}

        for sid in skill_ids:
            skill = self.app.data_loader.get_skill_by_id(sid)
            if skill is None:
                # 技能找不到，仅显示ID
                card = ttk.Frame(parent, relief="groove", borderwidth=1)
                card.pack(fill="x", padx=3, pady=2)
                ttk.Label(card, text=f"[未知] 技能ID: {sid}",
                           font=("Microsoft YaHei UI", 9, "bold")).pack(
                    anchor="w", padx=5, pady=3)
                continue

            # 从skill_levels获取技能等级（兼容string/int键），与战斗引擎逻辑一致
            level = int(raw_levels.get(str(sid), raw_levels.get(sid, 1)))

            card = ttk.Frame(parent, relief="groove", borderwidth=1)
            card.pack(fill="x", padx=3, pady=2)

            # 技能名称行
            info_frame = ttk.Frame(card)
            info_frame.pack(fill="x", padx=3, pady=(3, 0))

            stype = skill_type_names.get(skill.skill_type, str(skill.skill_type))
            ttk.Label(info_frame, text=f"[{stype}] {skill.name}",
                       font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT)

            # 消耗点数
            unit = cost_unit.get(skill.skill_type, "AP")
            ttk.Label(info_frame, text=f" | 消耗: {skill.resource_cost}{unit}",
                       font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(5, 0))

            # 冷却信息
            if skill.cooldown:
                if skill.cooldown_update_timing == 1:
                    cd_text = f" | 冷却: {skill.cooldown}回合"
                elif skill.cooldown_update_timing == 2:
                    cd_text = f" | 冷却: {skill.cooldown}行动"
                else:
                    cd_text = f" | 冷却: {skill.cooldown}无"
            else:
                cd_text = " | 冷却: 无"
            ttk.Label(info_frame, text=cd_text,
                       font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(5, 0))

            # 描述区域
            desc_text = self._format_skill_description(skill, level)
            desc_widget = tk.Text(card, wrap=tk.WORD,
                                   font=("Microsoft YaHei UI", 9),
                                   height=3, relief="flat", borderwidth=0,
                                   padx=5, pady=2,
                                   bg=s["input_bg"], fg=s["fg"],
                                   state="disabled")
            desc_widget.pack(fill="x", padx=5, pady=3)
            desc_widget.config(state="normal")
            desc_widget.insert("1.0", desc_text)
            desc_widget.config(state="disabled")

    def _format_skill_description(self, skill, level):
        """格式化技能描述，替换模板标签为实际数值"""
        template = skill.get_description_at_level(level)
        if not template:
            return "(无描述)"
        result = template
        for tag_name, tag in skill.template_tags.items():
            val = tag.get_value_at_level(level)
            if val == int(val):
                val_str = str(int(val))
            else:
                val_str = f"{val:.2f}".rstrip('0').rstrip('.')
            result = result.replace(f"{{{tag_name}}}", val_str)
        return result

    def _on_close(self):
        self.destroy()
