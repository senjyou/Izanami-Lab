#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MGGBattleSimulation - GUI 配置面板
gui_app.py

功能:
  1. 全局参数设置（学园等级、装备数值、角色等级、默认稀有度/模块/好感度/技能）
  2. 角色参数设置（个人覆盖优先于全局默认）
  3. 编队及战斗（2x3 网格、预设管理、一键模拟+统计）
"""

import sys
import json
import os
import random
import time
import threading
import statistics
import unicodedata
from datetime import datetime
import tkinter as tk
import pywinstyles
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

from src.data.data_loader import DataLoader
from src.data.stat_calculator import StatCalculator
from src.config.panel_config import PanelConfig, ModuleConfig
from src.config.player_config import SchoolLevels
from src.entities_v2.unit_state import UnitState
from src.entities_v2.battlefield_state import BattlefieldState
from src.entities_v2.enums import Side, Position
from src.combat_v2.battle_flow_controller import BattleFlowController, BattleConfig
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController
from src.combat_v2.battle_narrative import BattleNarrativeWriter
from src.entities_v2.custom_dummy import (
    CustomDummyConfig, CustomASConfig, CustomPSConfig, CustomEffectConfig,
    EFFECT_TYPE_DISPLAY, EFFECT_DISPLAY_REVERSE, EFFECT_FIELD_FLAGS,
    STATUS_TYPE_DISPLAY, STATUS_DISPLAY_REVERSE,
    DURATION_TYPE_DISPLAY, DURATION_DISPLAY_REVERSE,
    EFFECT_CATEGORIES,
)
from src.entities.memory_card import MemoryCard, MemoryHighlight
from version import __version__, __repository__, __release_url__
from src.utils.update_daemon import UpdateDaemon, UpdateProgress
from src.utils.version_checker import UpdateType
from src.utils.cold_updater import ColdUpdater


# ── CJK 文本视觉宽度对齐工具 ──

def _str_visual_width(s: str) -> int:
    """计算字符串视觉宽度：CJK全角字符=2，ASCII半角=1"""
    w = 0
    for c in s:
        w += 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
    return w


def _cjk_ljust(s: str, width: int) -> str:
    """左对齐到指定视觉宽度"""
    return s + ' ' * max(0, width - _str_visual_width(s))


def _cjk_rjust(s: str, width: int) -> str:
    """右对齐到指定视觉宽度"""
    return ' ' * max(0, width - _str_visual_width(s)) + s


def _cjk_truncate(s: str, max_width: int, ellipsis: str = "…") -> str:
    """按视觉宽度截断字符串，超出时末尾添加省略号"""
    if _str_visual_width(s) <= max_width:
        return s
    result = []
    width = 0
    ellipsis_w = _str_visual_width(ellipsis)
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
        if width + cw > max_width - ellipsis_w:
            break
        result.append(c)
        width += cw
    return ''.join(result) + ellipsis


def _cjk_fit(s: str, width: int) -> str:
    """截断到指定视觉宽度后左对齐填充，保证输出宽度恒定"""
    return _cjk_ljust(_cjk_truncate(s, width), width)


# ── 路径辅助（PyInstaller 兼容） ──
def get_base_path():
    """获取应用根目录（打包后为 exe 所在目录，开发环境为脚本所在目录）"""
    if getattr(sys, 'frozen', False):
        # 打包模式：exe 同级目录（data/ 外置在 exe 旁边）
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_internal_path():
    """获取 PyInstaller 内部资源路径（icon 等）"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def get_user_data_path():
    """获取用户可写数据目录（配置、日志、预设等）"""
    path = Path(os.environ.get('APPDATA', Path.home() / '.config')) / 'Izanami Lab'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_user_config(src_name, dst_path):
    """如果用户配置不存在，从默认模板复制"""
    if not dst_path.exists():
        # 优先从外置 data 目录查找，回退到内部资源
        default_src = _BASE_PATH / "data" / src_name
        if not default_src.exists():
            default_src = get_internal_path() / "data" / src_name
        if default_src.exists():
            import shutil
            shutil.copy(default_src, dst_path)


_BASE_PATH = get_base_path()
_USER_DATA = get_user_data_path()

GRID_ALLY_POSITIONS = [
    Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT, Position.ALLY_RIGHT_FRONT,
    Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK, Position.ALLY_RIGHT_BACK,
]
GRID_ENEMY_POSITIONS = [
    Position.ENEMY_LEFT_FRONT, Position.ENEMY_CENTER_FRONT, Position.ENEMY_RIGHT_FRONT,
    Position.ENEMY_LEFT_BACK, Position.ENEMY_CENTER_BACK, Position.ENEMY_RIGHT_BACK,
]

# 战术演习：敌方站位映射（1-6 → Position）
ENEMY_SLOT_POSITION_MAP = {
    1: Position.ENEMY_LEFT_FRONT,
    2: Position.ENEMY_CENTER_FRONT,
    3: Position.ENEMY_RIGHT_FRONT,
    4: Position.ENEMY_LEFT_BACK,
    5: Position.ENEMY_CENTER_BACK,
    6: Position.ENEMY_RIGHT_BACK,
}

# 战术演习：用户模式下可选的敌方ID（经过debug验证可正常模拟的单位）
ALLOWED_ENEMY_IDS = {232315, 672105, 682205, 703405}

# 战术演习：敌方ID → 同名角色ID（用于获取头像）
ENEMY_AVATAR_MAP = {
    232315: 113301,   # フィー・ドレーゼ
    672105: 122301,   # ミリアム・ヘイワード
    682205: 123301,   # ハリエット・ミルズ
    703405: 144301,   # ナージャ・ヴォルコワ
    222211: 112301,   # 紫雲沙耶
    243406: 114301,   # アニス・ベネット
    251105: 128301,   # ノエル・アルエ
    261205: 130301,   # リリー・ラヴォア
    271305: 129301,   # リュシー・ムーグロフト
    293105: 119301,   # レイラ・ジェンキンス
    603305: 118302,   # シエナ・クラーク
    632306: 141301,   # カリナ・ジェンティーレ
    641105: 112302,   # 紫雲沙耶
    652405: 142301,   # 大賀真桜
    661305: 111302,   # 劉翠蘭
    93109: 100301,    # 桃園める
    101209: 110301,   # ユリア・バーンズ
}

SCHOOL_LABELS = [
    ("物理", "physical_level"), ("EN", "en_level"), ("敏捷", "agility_level"),
    ("火", "fire_level"), ("水", "water_level"), ("风", "wind_level"),
    ("土", "earth_level"), ("光", "light_level"), ("暗", "dark_level"),
]

GEAR_EFFECT_DISPLAY = {
    0: "无效果",
    7: "有利属性伤害(%)",
    1: "HP增加(%)",
    2: "攻击力增加(%)",
    3: "防御力增加(%)",
    4: "速度增加(%)",
    5: "暴击率增加(%)",
    6: "暴击伤害增加(%)",
}
GEAR_EFFECT_VALUES = [0, 7, 1, 2, 3, 4, 5, 6]
GEAR_EFFECT_OPTIONS_DISPLAY = [GEAR_EFFECT_DISPLAY[v] for v in GEAR_EFFECT_VALUES]
GEAR_EFFECT_REVERSE = {v: k for k, v in GEAR_EFFECT_DISPLAY.items()}

RARITY_NAMES = {
    1: "R", 2: "R+", 3: "SR", 4: "SR+",
    5: "SSR", 6: "SSR+", 7: "UR", 8: "UR+", 9: "LR",
    10: "LR+1", 11: "LR+2", 12: "LR+3", 13: "LR+4", 14: "LR+5",
}

ELEMENT_NAMES = {1: "火", 2: "水", 3: "风", 4: "土", 5: "光", 6: "暗"}
CHAR_TYPE_NAMES = {1: "物理", 2: "EN", 3: "敏捷"}
POSITION_TYPE_NAMES = {1: "前排", 2: "后排", 3: "灵活"}
ROLE_TYPE_NAMES = {1: "物理攻击手", 2: "EN攻击手", 3: "坦克", 4: "辅助", 5: "控制"}
TARGET_TYPE_NAMES = {1: "自身", 2: "自身+友方", 3: "敌方全体", 4: "友方全体", 5: "全场"}
TARGET_RANGE_NAMES = {1: "单体", 2: "双体", 3: "三体", 4: "四体", 5: "全体", 6: "横排", 7: "竖列"}
TARGET_PRIORITY_NAMES = {0: "最近优先(默认)", 1: "前排优先", 2: "后排优先", 3: "左列优先", 4: "中列优先", 5: "右列优先"}
COOLDOWN_TIMING_NAMES = {1: "回合后", 2: "行动后"}
SHIELD_TYPE_NAMES = {0: "无", 1: "物理盾", 2: "EN盾", 3: "全伤害盾"}
SHIELD_TYPE_REV = {v: k for k, v in SHIELD_TYPE_NAMES.items()}


def get_max_rarity_for(default_rarity: int) -> int:
    """根据默认稀有度计算最大稀有度上限"""
    if default_rarity <= 1:
        return 5
    elif default_rarity <= 3:
        return 7
    else:
        return 14

TRIGGER_TIMING_OPTIONS = [
    ("战斗开始", "BattleStart"),
    ("波次开始", "WaveStart"),
    ("波次结束", "WaveEnd"),
    ("回合开始", "TurnStart"),
    ("回合结束", "TurnEnd"),
    ("技能使用前", "BeforeSkillUse"),
    ("技能效果应用前", "BeforeSkillEffectsApply"),
    ("技能使用后", "AfterSkillUse"),
    ("被AS攻击前", "BeforeAsAttacked"),
    ("被任意攻击前", "BeforeAnyAttacked"),
    ("友方AS攻击前", "BeforeAllyAsAttack"),
    ("被攻击后", "AfterAsAttacked"),
    ("友方被攻击后", "AfterAllyAttacked"),
    ("单位死亡", "PawnDied"),
    ("获得Buff/Debuff", "PawnReceivedAura"),
    ("造成暴击", "PawnCausedCritical"),
    ("受到伤害", "PawnReceivedDamage"),
    ("受到治疗", "PawnReceivedHealing"),
    ("击杀敌人", "PawnKilled"),
    ("HP低于阈值", "HpBelow"),
    ("技能使用次数计数", "SkillUseCount"),
    ("敌军数量低于阈值", "UnitCountBelow"),
    ("战斗结束", "BattleEnd"),
]

PRESET_DIR = _USER_DATA / "presets"
TACTICAL_PRESET_DIR = _USER_DATA / "tactical_presets"
GLOBAL_CONFIG_PATH = _USER_DATA / "global_config.json"
CHAR_CONFIG_PATH = _USER_DATA / "char_config.json"
# 图片资源目录（统一存放在 data/images/ 下，从 base path 读取）
_IMAGE_BASE = _BASE_PATH / "data" / "images"
AVATAR_DIR = _IMAGE_BASE / "avatars"          # 角色竖版头像
BANNER_DIR = _IMAGE_BASE / "banners"          # 角色横版头像
MEMORY_CARD_DIR = _IMAGE_BASE / "memory_cards"  # 回忆卡图片
ATTR_ICON_DIR = _IMAGE_BASE / "attributes"    # 属性图标
RARITY_DIR = _IMAGE_BASE / "rarities"         # 稀有度图标
ENEMY_IMAGE_DIR = _IMAGE_BASE / "enemies"     # 敌方横版头像（ModelAssetId命名）

# 属性ID到图标文件名映射
ATTR_ICON_MAP = {
    0: "all", 1: "fire", 2: "water", 3: "wind", 4: "earth", 5: "light", 6: "dark",
}

# 稀有度ID到名称和图标文件名映射
# 回忆卡稀有度: 1=SR, 2=SSR, 3=UR, 4=LR
MEM_RARITY_MAP = {
    1: ("SR", "rarity_sr.png"),
    2: ("SSR", "rarity_ssr.png"),
    3: ("UR", "rarity_ur.png"),
    4: ("LR", "rarity_lr.png"),
}
# 角色稀有度: 1=R, 2=R+, 3=SR, 4=SR+, 5=SSR, 6=SSR+, 7=UR, 8=UR+, 9=LR, 10=LR+1, 11=LR+2, 12=LR+3, 13=LR+4, 14=LR+5
CHAR_RARITY_MAP = {
    1: ("R", "rarity_r.png"),
    2: ("R+", "rarity_r_plus.png"),
    3: ("SR", "rarity_sr.png"),
    4: ("SR+", "rarity_sr_plus.png"),
    5: ("SSR", "rarity_ssr.png"),
    6: ("SSR+", "rarity_ssr_plus.png"),
    7: ("UR", "rarity_ur.png"),
    8: ("UR+", "rarity_ur_plus.png"),
    9: ("LR", "rarity_lr.png"),
    10: ("LR+1", "rarity_lr_plus1.png"),
    11: ("LR+2", "rarity_lr_plus2.png"),
    12: ("LR+3", "rarity_lr_plus3.png"),
    13: ("LR+4", "rarity_lr_plus4.png"),
    14: ("LR+5", "rarity_lr_plus5.png"),
}

# ── 主题配色方案 ──
THEME_SCHEMES = {
    "dark": {
        "label": "深色",
        "bg": "#1e1e2e", "fg": "#cdd6f4", "surface": "#313244",
        "border": "#45475a", "accent": "#89b4fa", "input_bg": "#181825",
        "select_bg": "#45475a", "select_fg": "#cdd6f4",
        "accent_fg": "#1e1e2e", "header_color": "#1e1e2e",
        "header_text": "white", "border_color": "#45475a",
        "tab_active_bg": "#3e3e5e",
    },
    "light": {
        "label": "浅色",
        "bg": "#eff1f5", "fg": "#4c4f69", "surface": "#e6e9ef",
        "border": "#bcc0cc", "accent": "#1e66f5", "input_bg": "#ffffff",
        "select_bg": "#ccd0da", "select_fg": "#4c4f69",
        "accent_fg": "#ffffff", "header_color": "#dce0e8",
        "header_text": "#4c4f69", "border_color": "#bcc0cc",
        "tab_active_bg": "#ccd0da",
    },
}

THEME_OPTIONS = ["深色", "浅色", "跟随系统"]

UI_CONFIG_PATH = _USER_DATA / "ui_config.json"

# 默认主题常量（向后兼容，初始化时使用）
_DEFAULT_SCHEME = THEME_SCHEMES["dark"]
_DARK_BG = _DEFAULT_SCHEME["bg"]
_DARK_FG = _DEFAULT_SCHEME["fg"]
_DARK_SURFACE = _DEFAULT_SCHEME["surface"]
_DARK_BORDER = _DEFAULT_SCHEME["border"]
_DARK_ACCENT = _DEFAULT_SCHEME["accent"]
_DARK_INPUT_BG = _DEFAULT_SCHEME["input_bg"]
_DARK_SELECT_BG = _DEFAULT_SCHEME["select_bg"]
_DARK_SELECT_FG = _DEFAULT_SCHEME["select_fg"]


def get_module_type_ids(char_type):
    return [int(f"{char_type}1"), int(f"{char_type}2"), int(f"{char_type}3")]


# ─────────────────── 战斗结果表格面板（通用组件） ───────────────────

class ResultTablePanel(ttk.Frame):
    """战斗结果面板：上方摘要Text + 下方明细Treeview（Notebook分页）"""

    def __init__(self, parent, app, title="战斗结果", font=("Cascadia Mono", 10)):
        super().__init__(parent)
        self.app = app
        self._font = font
        self._title = title
        self._sort_reverse = False
        self._trees: list[ttk.Treeview] = []

        # 标题
        self._title_label = ttk.Label(self, text=title, font=("Microsoft YaHei UI", 10, "bold"))
        self._title_label.pack(pady=5)

        # 垂直 PanedWindow：上方摘要，下方表格
        self._paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self._paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ── 上方：摘要 Text ──
        s = app._get_scheme() if hasattr(app, '_get_scheme') else None
        text_bg = s["input_bg"] if s else _DARK_INPUT_BG
        text_fg = s["fg"] if s else _DARK_FG
        self._summary_text = scrolledtext.ScrolledText(
            self._paned, width=50, height=12, wrap=tk.WORD,
            font=font, bg=text_bg, fg=text_fg,
            insertbackground=text_fg,
            selectbackground=s["select_bg"] if s else _DARK_SELECT_BG,
            selectforeground=s["select_fg"] if s else _DARK_SELECT_FG)
        self._paned.add(self._summary_text, weight=1)

        # ── 下方：Notebook（表格容器） ──
        self._notebook = ttk.Notebook(self._paned)
        self._paned.add(self._notebook, weight=2)

        self.apply_theme()

    def clear(self):
        """清空摘要和表格"""
        self._summary_text.delete("1.0", tk.END)
        self._clear_tables()

    def _clear_tables(self):
        """仅清空表格（保留摘要文本）"""
        for tab_id in self._notebook.tabs():
            self._notebook.forget(tab_id)
        self._trees = []

    def set_summary(self, text: str):
        """设置摘要文本（覆盖式）"""
        self._summary_text.delete("1.0", tk.END)
        self._summary_text.insert(tk.END, text)

    def append_summary(self, text: str):
        """追加摘要文本"""
        self._summary_text.insert(tk.END, text)

    def set_table(self, title: str, columns: list, rows: list,
                  col_widths: list = None, col_aligns: list = None):
        """设置单个表格（覆盖式，不清空摘要）"""
        self._clear_tables()
        self._add_table(title, columns, rows, col_widths, col_aligns)

    def set_tables(self, tables: list):
        """设置多个表格（Notebook分页，不清空摘要）"""
        self._clear_tables()
        for t in tables:
            self._add_table(
                t.get("title", ""),
                t.get("columns", []),
                t.get("rows", []),
                t.get("col_widths"),
                t.get("col_aligns"))

    def _add_table(self, title: str, columns: list, rows: list,
                   col_widths: list = None, col_aligns: list = None):
        """添加一个表格到Notebook"""
        if not columns:
            return

        # 创建表格容器
        tab_frame = ttk.Frame(self._notebook)
        self._notebook.add(tab_frame, text=f"{title}({len(rows)})" if rows else title)

        # Treeview + 滚动条
        tree_frame = ttk.Frame(tab_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=8)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # 配置列
        for i, col in enumerate(columns):
            align = col_aligns[i] if col_aligns and i < len(col_aligns) else "w"
            width = col_widths[i] if col_widths and i < len(col_widths) else 100
            tree.heading(col, text=col, command=lambda c=col, t=tree: self._sort_by_column(t, c))
            tree.column(col, anchor=align, width=width, stretch=False)

        # 填充数据
        for row_idx, row in enumerate(rows):
            tag = "evenrow" if row_idx % 2 == 0 else "oddrow"
            tree.insert("", tk.END, values=row, tags=(tag,))

        self._trees.append(tree)
        self.apply_theme()

    def _sort_by_column(self, tree: ttk.Treeview, col: str):
        """点击列头排序（升序/降序切换）"""
        items = [(tree.set(k, col), k) for k in tree.get_children("")]
        try:
            items.sort(key=lambda x: float(x[0].replace(",", "").replace("%", "")),
                       reverse=self._sort_reverse)
        except (ValueError, AttributeError):
            items.sort(key=lambda x: x[0], reverse=self._sort_reverse)
        self._sort_reverse = not self._sort_reverse
        for i, (val, k) in enumerate(items):
            tree.move(k, "", i)

    def apply_theme(self):
        """应用当前主题"""
        s = self.app._get_scheme() if hasattr(self.app, '_get_scheme') else None
        if not s:
            return

        # 摘要 Text
        self._summary_text.config(bg=s["input_bg"], fg=s["fg"],
                                   insertbackground=s["fg"],
                                   selectbackground=s["select_bg"],
                                   selectforeground=s["select_fg"])

        # Treeview 交替行颜色
        for tree in self._trees:
            tree.tag_configure("evenrow", background=s["surface"])
            tree.tag_configure("oddrow", background=s["input_bg"])


# ────────────────────────────── 全局参数 Tab ──────────────────────────────

class GlobalParamsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()

    def _build(self):
        f = ttk.Frame(self)
        f.pack(fill=tk.BOTH, expand=True)
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)

        # ── 左栏：等级、学园、装备 ──
        left_col = ttk.Frame(f)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)

        # ── 角色等级 ──
        ttk.Label(left_col, text="角色等级", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 2))
        lf = ttk.LabelFrame(left_col, text="等级设置")
        lf.pack(fill="x", pady=2)
        ttk.Label(lf, text="角色等级:").grid(row=0, column=0, padx=5, pady=5)
        self.var_level = tk.IntVar(value=355)
        ttk.Spinbox(lf, from_=1, to=999, textvariable=self.var_level, width=8).grid(row=0, column=1, padx=5)

        # ── 学园等级 ──
        ttk.Label(left_col, text="学园等级", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        lf = ttk.LabelFrame(left_col, text="类型等级")
        lf.pack(fill="x", pady=2)
        self.vars_school = {}
        for i, (label, key) in enumerate(SCHOOL_LABELS):
            r, c = divmod(i, 3)
            ttk.Label(lf, text=label, width=6).grid(row=r, column=c * 2, padx=2, pady=2)
            v = tk.IntVar(value=getattr(SchoolLevels(), key))
            self.vars_school[key] = v
            ttk.Spinbox(lf, from_=0, to=999, textvariable=v, width=5).grid(row=r, column=c * 2 + 1, padx=2, pady=2)

        # ── 装备数值 ──
        ttk.Label(left_col, text="装备数值 (按角色类型填写 HP/ATK/DEF 总值)", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        lf = ttk.LabelFrame(left_col, text="装备加成 (同类型所有装备总加成)")
        lf.pack(fill="x", pady=2)
        headers = ["类型", "HP加成", "ATK加成", "DEF加成"]
        for j, h in enumerate(headers):
            ttk.Label(lf, text=h, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=j, padx=6, pady=3)
        self.equip_vars: Dict[int, Dict[str, tk.IntVar]] = {}
        equip_types = [(1, "物理"), (2, "EN"), (3, "敏捷")]
        for i, (ct, ct_name) in enumerate(equip_types, start=1):
            ttk.Label(lf, text=ct_name).grid(row=i, column=0, padx=6, pady=2)
            self.equip_vars[ct] = {}
            for j, key in enumerate(["hp", "attack", "defense"]):
                v = tk.IntVar(value=0)
                self.equip_vars[ct][key] = v
                ttk.Spinbox(lf, from_=0, to=999999, textvariable=v, width=9).grid(row=i, column=1 + j, padx=3, pady=2)

        # ── 右栏：角色默认参数、战斗设置、保存重置 ──
        right_col = ttk.Frame(f)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)

        # ── 角色默认参数 ──
        ttk.Label(right_col, text="角色默认参数 (一键套用至所有角色)", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 2))
        lf = ttk.LabelFrame(right_col, text="通用角色设置")
        lf.pack(fill="x", pady=2)

        ttk.Label(lf, text="稀有度:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.var_rarity = tk.IntVar(value=14)
        cb = ttk.Combobox(lf, textvariable=self.var_rarity, values=list(range(5, 15)), state="readonly", width=5)
        cb.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.rarity_name_label = ttk.Label(lf, text=RARITY_NAMES[14])
        self.rarity_name_label.grid(row=0, column=2, padx=5, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_rarity_change())
        # 备注：全局默认稀有度仍提供5-14全范围，角色参数页会根据角色类型限制上限

        ttk.Label(lf, text="好感度:").grid(row=0, column=3, padx=5, pady=5, sticky="e")
        self.var_affection = tk.IntVar(value=40)
        ttk.Spinbox(lf, from_=1, to=40, textvariable=self.var_affection, width=5).grid(row=0, column=4, padx=5)

        ttk.Label(lf, text="技能等级:").grid(row=0, column=5, padx=5, pady=5, sticky="e")
        self.var_skill_lv = tk.IntVar(value=15)
        self.skill_lv_spinbox = ttk.Spinbox(lf, from_=1, to=15, textvariable=self.var_skill_lv, width=5)
        self.skill_lv_spinbox.grid(row=0, column=6, padx=5)

        ttk.Label(lf, text="模块Tier:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.var_mod_tier = tk.IntVar(value=9)
        cb_tier = ttk.Combobox(lf, textvariable=self.var_mod_tier, values=list(range(1, 10)), state="readonly", width=5)
        cb_tier.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(lf, text="模块等级:").grid(row=1, column=3, padx=5, pady=5, sticky="e")
        self.var_mod_level = tk.IntVar(value=50)
        ttk.Spinbox(lf, from_=1, to=50, textvariable=self.var_mod_level, width=5).grid(row=1, column=4, padx=5)

        self._build_gear_defaults(lf)

        # ── 战斗设置 ──
        ttk.Label(right_col, text="战斗设置", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        lf = ttk.LabelFrame(right_col, text="模拟参数")
        lf.pack(fill="x", pady=2)

        ttk.Label(lf, text="默认模拟场数:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.var_runs = tk.IntVar(value=1)
        ttk.Spinbox(lf, from_=1, to=10000, textvariable=self.var_runs, width=8).grid(row=0, column=1, padx=5, sticky="w")

        ttk.Label(lf, text="最大回合数:").grid(row=0, column=2, padx=5, pady=5, sticky="e")
        self.var_max_turns = tk.IntVar(value=30)
        ttk.Spinbox(lf, from_=5, to=999, textvariable=self.var_max_turns, width=8).grid(row=0, column=3, padx=5, sticky="w")

        btn_frame = ttk.Frame(right_col)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="保存全局设置", command=self._save_global_config_with_feedback).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="重置全局设置", command=self._reset_global_config).pack(side=tk.LEFT, padx=5)

        self._load_global_config()

    def _on_rarity_change(self):
        r = self.var_rarity.get()
        self.rarity_name_label.config(text=RARITY_NAMES.get(r, ""))
        # 稀有度变化时联动技能等级上限：>=9(LR)为15，否则为10
        new_max = 15 if r >= 9 else 10
        self.skill_lv_spinbox.config(to=new_max)
        if self.var_skill_lv.get() > new_max:
            self.var_skill_lv.set(new_max)

    def _build_gear_defaults(self, parent):
        ttk.Label(parent, text="模块词条 (每角色共9槽，分3组对应3个模块，同组不可复选相同类型):", font=("Microsoft YaHei UI", 8)).grid(
            row=2, column=0, columnspan=7, sticky="w", padx=5, pady=(10, 2))

        self.gear_vars = []
        module_names = ["模块1 (HP)", "模块2 (攻击)", "模块3 (防御)"]
        gear_frame = ttk.Frame(parent)
        gear_frame.grid(row=3, column=0, columnspan=7, sticky="ew", padx=5, pady=2)

        for grp_idx in range(3):
            grp_frame = ttk.LabelFrame(gear_frame, text=module_names[grp_idx], style="Gear.TLabelframe")
            grp_frame.grid(row=0, column=grp_idx, padx=5, pady=3, sticky="n")

            for slot_idx in range(3):
                slot_frame = ttk.Frame(grp_frame)
                slot_frame.pack(pady=1, padx=3)

                et_var = tk.StringVar(value="无效果")
                cb = ttk.Combobox(slot_frame, textvariable=et_var, values=GEAR_EFFECT_OPTIONS_DISPLAY,
                                  state="readonly", width=16)
                cb.pack()

                slot_grp = grp_idx
                slot_idx_in_grp = slot_idx
                cb.bind("<<ComboboxSelected>>",
                        lambda e, g=slot_grp, s_idx=slot_idx_in_grp: self._validate_gear_group(g, s_idx))

                pct_frame = ttk.Frame(slot_frame)
                pct_frame.pack()
                v_var = tk.DoubleVar(value=0.0)
                ttk.Spinbox(pct_frame, from_=0, to=100, increment=0.5, textvariable=v_var, width=5).pack(side=tk.LEFT)
                ttk.Label(pct_frame, text="%", font=("Microsoft YaHei UI", 7)).pack(side=tk.LEFT)

                self.gear_vars.append({"et": et_var, "val": v_var, "group": grp_idx, "slot": slot_idx})

    def _validate_gear_group(self, group_idx, changed_slot_idx):
        group_slots = [(i, gv) for i, gv in enumerate(self.gear_vars) if gv["group"] == group_idx]
        used_types = {}
        for abs_idx, gv in group_slots:
            et_val = gv["et"].get()
            if et_val != "无效果":
                if et_val in used_types:
                    gv["et"].set("无效果")
                    gv["val"].set(0.0)
                    messagebox.showwarning("词条冲突",
                        f"模块{group_idx+1}中词条类型重复，已自动清除冲突槽位")
                else:
                    used_types[et_val] = abs_idx

    def _save_global_config(self):
        try:
            GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            values = self.get_values()
            with open(GLOBAL_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(values, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _save_global_config_with_feedback(self):
        self._save_global_config()
        # 传播全局等级到所有 override 且非 1 级的角色（链接等级系统语义）
        self.app._propagate_global_level_change(self.var_level.get())
        messagebox.showinfo("保存", "全局参数已保存")

    def _load_global_config(self):
        if not GLOBAL_CONFIG_PATH.exists():
            return
        try:
            with open(GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                values = json.load(f)
            self.var_level.set(values.get("character_level", 355))
            sl = values.get("school_levels", {})
            for key, v in self.vars_school.items():
                v.set(sl.get(key, 0))
            eq = values.get("equipment", {})
            for ct_str, vs in eq.items():
                ct = int(ct_str)
                if ct in self.equip_vars:
                    self.equip_vars[ct]["hp"].set(vs.get("hp", 0))
                    self.equip_vars[ct]["attack"].set(vs.get("attack", 0))
                    self.equip_vars[ct]["defense"].set(vs.get("defense", 0))
            self.var_rarity.set(values.get("default_rarity", 14))
            self.rarity_name_label.config(text=RARITY_NAMES.get(self.var_rarity.get(), ""))
            self.var_affection.set(values.get("default_affection", 40))
            # 联动技能等级上限
            r = self.var_rarity.get()
            skill_max = 15 if r >= 9 else 10
            self.skill_lv_spinbox.config(to=skill_max)
            raw_skill_lv = values.get("default_skill_level", 15)
            self.var_skill_lv.set(min(raw_skill_lv, skill_max))
            self.var_mod_tier.set(values.get("default_mod_tier", 9))
            self.var_mod_level.set(values.get("default_mod_level", 50))
            saved_gear = values.get("default_gear", [])
            saved_gear_map = {}
            for g in saved_gear:
                saved_gear_map[(g["group"], g["slot"])] = g
            for gv in self.gear_vars:
                sg = saved_gear_map.get((gv["group"], gv["slot"]), {})
                gv["et"].set(GEAR_EFFECT_DISPLAY.get(sg.get("effect_type", 0), "无效果"))
                gv["val"].set(sg.get("value", 0.0))
            self.var_runs.set(values.get("runs", 1))
            self.var_max_turns.set(values.get("max_turns", 30))
        except Exception as e:
            messagebox.showerror("加载配置失败", str(e))

    def _reset_global_config(self):
        self.var_level.set(355)
        for key, v in self.vars_school.items():
            v.set(getattr(SchoolLevels(), key))
        for ct in self.equip_vars:
            self.equip_vars[ct]["hp"].set(0)
            self.equip_vars[ct]["attack"].set(0)
            self.equip_vars[ct]["defense"].set(0)
        self.var_rarity.set(14)
        self.rarity_name_label.config(text=RARITY_NAMES[14])
        self.var_affection.set(40)
        self.skill_lv_spinbox.config(to=15)
        self.var_skill_lv.set(15)
        self.var_mod_tier.set(9)
        self.var_mod_level.set(50)
        for gv in self.gear_vars:
            gv["et"].set("无效果")
            gv["val"].set(0.0)
        self.var_runs.set(1)
        self.var_max_turns.set(30)
        messagebox.showinfo("重置", "全局参数已重置为默认值")
        self._save_global_config()
        # 重置后同样传播等级（355）到所有 override 且非 1 级的角色
        self.app._propagate_global_level_change(self.var_level.get())

    def _bind_mousewheel(self, canvas):
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_canvas(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_canvas(event):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_canvas)
        canvas.bind("<Leave>", _unbind_canvas)

    def get_values(self) -> Dict[str, Any]:
        return {
            "character_level": self.var_level.get(),
            "school_levels": {key: v.get() for key, v in self.vars_school.items()},
            "equipment": {ct: {"hp": vs["hp"].get(), "attack": vs["attack"].get(), "defense": vs["defense"].get()}
                          for ct, vs in self.equip_vars.items()},
            "default_rarity": self.var_rarity.get(),
            "default_affection": self.var_affection.get(),
            "default_skill_level": self.var_skill_lv.get(),
            "default_mod_tier": self.var_mod_tier.get(),
            "default_mod_level": self.var_mod_level.get(),
            "default_gear": [{"effect_type": GEAR_EFFECT_REVERSE[gv["et"].get()], "value": gv["val"].get(),
                              "group": gv["group"], "slot": gv["slot"]}
                             for gv in self.gear_vars if gv["et"].get() != "无效果"],
            "runs": self.var_runs.get(),
            "max_turns": self.var_max_turns.get(),
        }


# ────────────────────────────── 角色参数 Tab ──────────────────────────────

class CharacterParamsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.char_override_vars: Dict[int, Dict[str, Any]] = {}
        self._current_filter = 0  # 0=全部, 1-6=属性
        self._filtered_char_ids: List[int] = []
        self._attr_icons: Dict[int, tk.PhotoImage] = {}  # 缓存属性图标
        self._build()

    def _build(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="角色列表", font=("Microsoft YaHei UI", 10, "bold")).pack(pady=(5, 0))

        # ── 属性筛选栏 + 视图切换 ──
        filter_frame = ttk.Frame(left)
        filter_frame.pack(fill="x", padx=5, pady=5)

        self._filter_buttons: List[tk.Label] = []
        ICON_SIZE = 24
        s = self.app._get_scheme()
        for attr_id in range(7):  # 0=全部, 1-6=属性
            icon_path = ATTR_ICON_DIR / f"{ATTR_ICON_MAP[attr_id]}.png"
            try:
                photo = tk.PhotoImage(file=str(icon_path))
                if photo.width() > ICON_SIZE:
                    photo = photo.subsample(photo.width() // ICON_SIZE, photo.width() // ICON_SIZE)
                self._attr_icons[attr_id] = photo
            except Exception:
                photo = None

            btn = tk.Label(filter_frame, image=photo, cursor="hand2",
                           bd=0, highlightthickness=0, bg=s["surface"])
            btn.pack(side=tk.LEFT, padx=1)
            btn.image = photo
            btn.bind("<Button-1>", lambda e, aid=attr_id: self._apply_filter(aid))
            self._filter_buttons.append(btn)

        self._update_filter_highlight()

        # 视图切换按钮
        self._view_mode = "grid"
        self._list_btn = ttk.Button(filter_frame, text="列表", width=4,
                                     command=self._switch_to_list_view)
        self._list_btn.pack(side=tk.RIGHT, padx=1)
        self._grid_btn = ttk.Button(filter_frame, text="头像", width=4,
                                     command=self._switch_to_grid_view)
        self._grid_btn.pack(side=tk.RIGHT, padx=1)

        # ── 列表视图 ──
        self._list_frame = ttk.Frame(left)
        list_scrollbar = ttk.Scrollbar(self._list_frame)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.char_listbox = tk.Listbox(self._list_frame, yscrollcommand=list_scrollbar.set,
                                       exportselection=False,
                                       bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                       selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                       borderwidth=0, highlightthickness=0,
                                       font=("Microsoft YaHei UI", 11))
        self.char_listbox.pack(fill=tk.BOTH, expand=True)
        list_scrollbar.config(command=self.char_listbox.yview)
        self.char_listbox.bind("<<ListboxSelect>>", self._on_char_select)

        # ── 网格视图（默认显示） ──
        self._grid_frame = ttk.Frame(left)
        self._grid_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        self._grid_canvas = tk.Canvas(self._grid_frame, bg=self.app._get_scheme()["bg"], highlightthickness=0)
        self._grid_scrollbar = ttk.Scrollbar(self._grid_frame, orient="vertical",
                                              command=self._grid_canvas.yview)
        self._grid_canvas.configure(yscrollcommand=self._grid_scrollbar.set)
        self._grid_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._grid_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        s = self.app._get_scheme()
        self._grid_inner = tk.Frame(self._grid_canvas, bg=s["surface"])
        self._grid_canvas_window = self._grid_canvas.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind("<Configure>",
                              lambda e: self._grid_canvas.configure(scrollregion=self._grid_canvas.bbox("all")))
        self._grid_canvas.bind("<Configure>", self._on_grid_canvas_resize)

        def _bind_grid_mousewheel(e):
            self._grid_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _enter_grid(e):
            self._grid_canvas.bind_all("<MouseWheel>", _bind_grid_mousewheel)

        def _leave_grid(e):
            self._grid_canvas.unbind_all("<MouseWheel>")

        self._grid_canvas.bind("<Enter>", _enter_grid)
        self._grid_canvas.bind("<Leave>", _leave_grid)

        self._grid_cards: Dict[int, tk.Frame] = {}  # cid -> card frame
        self._selected_grid_cid: Optional[int] = None

        self._refresh_list()

        btn_frame = ttk.Frame(left)
        btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text="重置选中角色", command=self._reset_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_frame, text="全部重置", command=self._reset_all).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_frame, text="全部应用全局", command=self._apply_global_all).pack(side=tk.LEFT, padx=3)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        s = self.app._get_scheme()
        right_canvas = tk.Canvas(right, bg=s["bg"], highlightthickness=0)
        right_scrollbar = ttk.Scrollbar(right, orient="vertical", command=right_canvas.yview)
        self.detail_frame = ttk.Frame(right_canvas)
        self.detail_frame.bind("<Configure>",
                               lambda e: right_canvas.configure(scrollregion=right_canvas.bbox("all")))
        right_canvas.create_window((0, 0), window=self.detail_frame, anchor="nw")
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        right_canvas.pack(side="left", fill="both", expand=True)
        right_scrollbar.pack(side="right", fill="y")

        def _bind_right_width(event):
            right_canvas.itemconfig(1, width=event.width)

        right_canvas.bind("<Configure>", _bind_right_width)

        def _on_right_mousewheel(e):
            right_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _enter_right(e):
            right_canvas.bind_all("<MouseWheel>", _on_right_mousewheel)

        def _leave_right(e):
            right_canvas.unbind_all("<MouseWheel>")

        right_canvas.bind("<Enter>", _enter_right)
        right_canvas.bind("<Leave>", _leave_right)

        ttk.Label(self.detail_frame, text="选择左侧角色查看/编辑参数", font=("Microsoft YaHei UI", 10)).pack(pady=20)

    def _on_char_select(self, event):
        sel = self.char_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._filtered_char_ids):
            cid = self._filtered_char_ids[idx]
            self._show_detail(cid)

    def _on_grid_canvas_resize(self, event):
        """Canvas宽度变化时调整inner frame宽度"""
        self._grid_canvas.itemconfig(self._grid_canvas_window, width=event.width)

    def _refresh_list(self):
        """根据当前筛选条件刷新角色列表"""
        self._filtered_char_ids = []
        for cid in self.app.char_ids:
            char = self.app.data_loader.get_character_by_id(cid)
            if not char:
                continue
            if self._current_filter != 0 and char.attribute != self._current_filter:
                continue
            self._filtered_char_ids.append(cid)

        if self._view_mode == "list":
            self.char_listbox.delete(0, tk.END)
            for cid in self._filtered_char_ids:
                char = self.app.data_loader.get_character_by_id(cid)
                is_locked = self.app.char_config.get(cid, {}).get("locked", False)
                lock_mark = "🔒 " if is_locked else ""
                if self.app.is_developer_mode():
                    self.char_listbox.insert(tk.END, f"{lock_mark}[{cid}] {self.app.format_char_name(char)}")
                else:
                    self.char_listbox.insert(tk.END, f"{lock_mark}{self.app.format_char_name(char)}")
        else:
            self._refresh_grid_view()

    def _switch_to_list_view(self):
        """切换到列表视图"""
        self._view_mode = "list"
        self._grid_frame.pack_forget()
        self._list_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        self._refresh_list()

    def _switch_to_grid_view(self):
        """切换到网格视图"""
        self._view_mode = "grid"
        self._list_frame.pack_forget()
        self._grid_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        self._refresh_grid_view()

    def _load_avatar_thumbnail(self, cid):
        """加载角色头像缩略图（用于网格视图），返回 tk.PhotoImage 或 None"""
        from PIL import Image, ImageTk
        THUMB_W, THUMB_H = 70, 90
        avatar_path = AVATAR_DIR / f"{cid}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            pil_img = pil_img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
            return ImageTk.PhotoImage(pil_img)
        except Exception:
            return None

    def _refresh_grid_view(self):
        """刷新网格视图"""
        self._selected_grid_cid = None
        s = self.app._get_scheme()
        # 刷新容器背景色（画布与内容载体均使用整体背景色，保持一致）
        self._grid_canvas.config(bg=s["bg"])
        self._grid_inner.config(bg=s["bg"])
        for child in self._grid_inner.winfo_children():
            child.destroy()
        self._grid_cards.clear()

        COLS = 6
        PAD = 2
        THUMB_W, THUMB_H = 70, 90
        s = self.app._get_scheme()

        for i, cid in enumerate(self._filtered_char_ids):
            char = self.app.data_loader.get_character_by_id(cid)
            if not char:
                continue
            row, col = divmod(i, COLS)
            # 使用highlightthickness作为选中边框，bd固定为0避免点击时尺寸变化
            card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                            highlightbackground=s["border"], highlightthickness=2,
                            cursor="hand2")
            card.grid(row=row, column=col, padx=PAD, pady=PAD, sticky="ew")

            # 头像
            photo = self._load_avatar_thumbnail(cid)
            if photo:
                avatar_label = tk.Label(card, image=photo, bg=s["surface"], bd=0)
                avatar_label.image = photo
                avatar_label.pack()
            else:
                placeholder_text = f"[{cid}]" if self.app.is_developer_mode() else "???"
                placeholder = tk.Label(card, text=placeholder_text, bg=s["surface"], fg=s["border"],
                                       width=THUMB_W // 8, height=THUMB_H // 16,
                                       font=("Microsoft YaHei UI", 8))
                placeholder.pack()

            # 角色名（锁定角色显示🔒标识）
            name = self.app.format_char_name(char)
            is_locked = self.app.char_config.get(cid, {}).get("locked", False)
            if is_locked:
                name = "🔒" + name
            # 截断过长名字
            if len(name) > 12:
                name = name[:11] + "…"
            name_label = tk.Label(card, text=name, bg=s["surface"], fg=s["fg"],
                                  font=("Microsoft YaHei UI", 8), wraplength=THUMB_W + 10,
                                  height=2, justify="center")
            name_label.pack(pady=(2, 0))

            # 绑定点击事件
            for widget in [card] + list(card.winfo_children()):
                widget.bind("<Button-1>", lambda e, c=cid: self._on_grid_card_click(c))

            self._grid_cards[cid] = card

        # 每列均分权重，使每行内容居中
        for c in range(COLS):
            self._grid_inner.grid_columnconfigure(c, weight=1, uniform="col")

    def _on_grid_card_click(self, cid):
        """网格视图卡片点击"""
        s = self.app._get_scheme()
        accent = s["accent"]
        surface = s["surface"]
        # 仅恢复上一个选中卡片的边框，再高亮新卡片（避免遍历全部卡片）
        prev = self._selected_grid_cid
        if prev is not None and prev in self._grid_cards:
            self._grid_cards[prev].config(highlightbackground=surface)
        self._selected_grid_cid = cid
        if cid in self._grid_cards:
            self._grid_cards[cid].config(highlightbackground=accent)
        self._show_detail(cid)

    def _apply_filter(self, attr_id: int):
        """应用属性筛选"""
        self._current_filter = attr_id
        self._update_filter_highlight()
        self._refresh_list()
        # 切换筛选后回到页面顶部（网格视图和列表视图均处理）
        if self._view_mode == "grid":
            self._grid_canvas.yview_moveto(0)
        else:
            self.char_listbox.yview_moveto(0)
        # 清空右侧详情
        for w in self.detail_frame.winfo_children():
            w.destroy()
        ttk.Label(self.detail_frame, text="选择左侧角色查看/编辑参数",
                  font=("Microsoft YaHei UI", 10)).pack(pady=20)

    def _update_filter_highlight(self):
        """更新筛选按钮高亮状态"""
        for i, btn in enumerate(self._filter_buttons):
            btn.config(bd=2, relief="raised")
            if i == self._current_filter:
                btn.config(bd=2, relief="sunken")

    def _show_detail(self, cid):
        for w in self.detail_frame.winfo_children():
            w.destroy()

        char = self.app.data_loader.get_character_by_id(cid)
        if not char:
            return

        f = self.detail_frame

        # 标题上方留白
        ttk.Label(f, text="").pack()

        type_name = ["", "物理", "EN", "敏捷"][char.character_type] if char.character_type <= 3 else "?"
        attr_name = ["", "火", "水", "风", "土", "光", "暗"][char.attribute] if char.attribute <= 6 else "?"
        role_names = {0: "未设定", 1: "物理攻击手", 2: "EN攻击手", 3: "坦克", 4: "辅助", 5: "控制"}
        role_name = role_names.get(char.role_type, "?")
        pos_names = {0: "未设定", 1: "前排", 2: "后排", 3: "灵活"}
        pos_name = pos_names.get(char.position_type, "?")

        # ── 顶部区域：头像(左) + 基本信息+面板预览(右) ──
        top_frame = ttk.Frame(f)
        top_frame.pack(fill="x", padx=5, pady=5)

        # 头像（左上）
        self._build_avatar_preview(top_frame, cid)

        # 右侧区域：基本信息 + 面板预览（上下居中于头像高度）
        right_frame = ttk.Frame(top_frame)
        right_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        # 基本信息区域（上半部分，上下居中，紧凑行距）
        info_frame = ttk.Frame(right_frame)
        info_frame.grid(row=0, column=0, sticky="s")

        char_display_name = f"{self.app.format_char_name(char)} [{cid}]" if self.app.is_developer_mode() else self.app.format_char_name(char)
        name_row = ttk.Frame(info_frame)
        name_row.pack(fill="x", pady=(0, 2))
        ttk.Label(name_row, text=char_display_name,
                  font=("Microsoft YaHei UI", 14, "bold"), anchor="center").pack(side="left", fill="x", expand=True)

        # 锁定按钮
        is_locked = self.app.char_config.get(cid, {}).get("locked", False)
        lock_btn = ttk.Button(name_row, width=3,
                              text="🔒" if is_locked else "🔓",
                              command=lambda c=cid: self._toggle_lock(c))
        lock_btn.pack(side="right", padx=(5, 0))
        lock_tooltip = "已锁定 - 点击解锁" if is_locked else "未锁定 - 点击锁定"
        self._create_tooltip(lock_btn, lock_tooltip)
        ttk.Label(info_frame, text=f"类型: {type_name} | 属性: {attr_name} | 默认稀有度: {char.default_rarity}",
                  font=("Microsoft YaHei UI", 11), anchor="center").pack(fill="x", pady=1)
        ttk.Label(info_frame, text=f"定位: {role_name} | 位置适应性: {pos_name}",
                  font=("Microsoft YaHei UI", 11), anchor="center").pack(fill="x", pady=(1, 4))

        # 角色面板预览（下半部分，上下居中）
        self._build_preview_inline(right_frame, cid, char)

        # ── 预计算技能等级上限（必须在_build_skill_preview之前）──
        cfg = self.app.char_config.get(cid, {"override": False})
        init_rarity_for_skill = cfg.get("rarity", self.app.global_tab.var_rarity.get()) if cfg.get("override") else self.app.global_tab.var_rarity.get()
        max_rarity_for_skill = get_max_rarity_for(char.default_rarity)
        if init_rarity_for_skill > max_rarity_for_skill:
            init_rarity_for_skill = max_rarity_for_skill
        self._current_skill_max = 15 if init_rarity_for_skill >= 9 else 10

        # ── 技能效果预览 ──
        self._build_skill_preview(f, cid, char)

        # ── 参数配置（左侧基础参数1/3，右侧模块设置2/3）──
        cfg = self.app.char_config.get(cid, {"override": False})
        is_locked = self.app.char_config.get(cid, {}).get("locked", False)
        config_title = "参数配置 🔒 已锁定" if is_locked else "参数配置"
        config_frame = ttk.LabelFrame(f, text=config_title)
        config_frame.pack(fill="x", padx=5, pady=5)

        # 左侧：基础参数（1/3宽度，上下分割）
        basic_frame = ttk.Frame(config_frame)
        basic_frame.pack(side="left", fill="y", padx=10, pady=5)

        # 基础参数区上下分割：上方2/3内容，下方1/3按钮
        basic_frame.grid_rowconfigure(0, weight=2)
        basic_frame.grid_rowconfigure(1, weight=1)

        # 上方：原有内容（稀有度、好感度、技能等级）
        basic_content = ttk.Frame(basic_frame)
        basic_content.grid(row=0, column=0, sticky="nsew")

        ttk.Label(basic_content, text="基础参数", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(0, 5))

        init_level = cfg.get("level", self.app.global_tab.var_level.get()) if cfg.get("override") else self.app.global_tab.var_level.get()
        level_row = ttk.Frame(basic_content)
        level_row.pack(fill="x", pady=3)
        ttk.Label(level_row, text="角色等级:", width=8).pack(side="left")
        level_var = tk.IntVar(value=init_level)
        ttk.Spinbox(level_row, from_=1, to=999, textvariable=level_var, width=5).pack(side="left", padx=3)

        init_rarity = cfg.get("rarity", self.app.global_tab.var_rarity.get()) if cfg.get("override") else self.app.global_tab.var_rarity.get()
        max_rarity = get_max_rarity_for(char.default_rarity)
        min_rarity = char.default_rarity
        # 截断到 [min_rarity, max_rarity] 范围内
        if init_rarity > max_rarity:
            init_rarity = max_rarity
        elif init_rarity < min_rarity:
            init_rarity = min_rarity
        rarity_row = ttk.Frame(basic_content)
        rarity_row.pack(fill="x", pady=3)
        ttk.Label(rarity_row, text="稀有度:", width=8).pack(side="left")
        rarity_var = tk.IntVar(value=init_rarity)
        cb = ttk.Combobox(rarity_row, textvariable=rarity_var, values=list(range(min_rarity, max_rarity + 1)), state="readonly", width=5)
        cb.pack(side="left", padx=3)
        rarity_name_var = tk.StringVar(value=RARITY_NAMES.get(rarity_var.get(), ""))
        ttk.Label(rarity_row, textvariable=rarity_name_var, width=6).pack(side="left", padx=3)

        def _update_rarity_label(*a):
            rarity_name_var.set(RARITY_NAMES.get(rarity_var.get(), ""))
        rarity_var.trace_add("write", _update_rarity_label)

        init_aff = cfg.get("affection", self.app.global_tab.var_affection.get()) if cfg.get("override") else self.app.global_tab.var_affection.get()
        aff_row = ttk.Frame(basic_content)
        aff_row.pack(fill="x", pady=3)
        ttk.Label(aff_row, text="好感度:", width=8).pack(side="left")
        aff_var = tk.IntVar(value=init_aff)
        ttk.Spinbox(aff_row, from_=1, to=40, textvariable=aff_var, width=5).pack(side="left", padx=3)

        # 技能等级不再统一设置，改为在每个技能卡片中单独设置
        # _current_skill_max 已在 _build_skill_preview 之前预计算
        self._current_rarity_var = rarity_var

        def _update_skill_max_on_rarity_change(*a):
            """稀有度变化时动态调整所有技能等级Spinbox上限"""
            r = rarity_var.get()
            new_max = 15 if r >= 9 else 10
            self._current_skill_max = new_max
            # 更新所有技能等级Spinbox的上限
            if hasattr(self, '_skill_level_spinboxes'):
                for spinbox in self._skill_level_spinboxes:
                    try:
                        spinbox.config(to=new_max)
                    except Exception:
                        pass
            # 更新超出上限的等级值
            if hasattr(self, '_skill_level_vars'):
                for sid, lv_var in self._skill_level_vars.items():
                    try:
                        if lv_var.get() > new_max:
                            lv_var.set(new_max)
                    except Exception:
                        pass
        rarity_var.trace_add("write", _update_skill_max_on_rarity_change)

        # 下方：按钮区（两个按钮分两行）
        btn_frame = ttk.Frame(basic_frame)
        btn_frame.grid(row=1, column=0, sticky="nsew")

        ttk.Button(btn_frame, text="应用设置", command=lambda: self._apply_detail(cid, char, v)).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="重置为全局默认", command=lambda: self._reset_to_global(cid, char)).pack(fill="x", pady=2)

        # 右侧：模块设置（2/3宽度）
        mod_frame = ttk.Frame(config_frame)
        mod_frame.pack(side="left", fill="both", expand=True, padx=10, pady=5)

        # 标题行：模块设置 + 三个模块组同行
        title_row = ttk.Frame(mod_frame)
        title_row.pack(fill="x", pady=(0, 3))

        # 左1/4：Tier和等级竖排
        mod_left = ttk.Frame(title_row)
        mod_left.pack(side="left", fill="y", padx=(0, 10))

        ttk.Label(mod_left, text="模块设置", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(0, 3))

        tier_row = ttk.Frame(mod_left)
        tier_row.pack(fill="x", pady=2)
        ttk.Label(tier_row, text="Tier:", width=6).pack(side="left")
        init_tier = cfg.get("mod_tier", self.app.global_tab.var_mod_tier.get()) if cfg.get("override") else self.app.global_tab.var_mod_tier.get()
        mod_tier_var = tk.IntVar(value=init_tier)
        ttk.Combobox(tier_row, textvariable=mod_tier_var, values=list(range(1, 10)), state="readonly", width=5).pack(side="left", padx=3)

        lv_row = ttk.Frame(mod_left)
        lv_row.pack(fill="x", pady=2)
        ttk.Label(lv_row, text="等级:", width=6).pack(side="left")
        init_lv = cfg.get("mod_level", self.app.global_tab.var_mod_level.get()) if cfg.get("override") else self.app.global_tab.var_mod_level.get()
        mod_lv_var = tk.IntVar(value=init_lv)
        ttk.Spinbox(lv_row, from_=1, to=50, textvariable=mod_lv_var, width=5).pack(side="left", padx=3)

        # 右3/4：9个模块词条（与"模块设置"同行高度）
        mod_right = ttk.Frame(title_row)
        mod_right.pack(side="left", fill="both", expand=True)

        self._build_detail_gears_inline(mod_right, cid, cfg)

        v = {
            "level": level_var,
            "rarity": rarity_var, "affection": aff_var,
            "mod_tier": mod_tier_var, "mod_level": mod_lv_var,
        }
        self.char_override_vars[cid] = v

        self._refresh_preview(cid)

    def _build_preview(self, parent, cid, char):
        preview_frame = ttk.LabelFrame(parent, text="角色面板预览")
        preview_frame.pack(fill="x", padx=5, pady=5)

        self.preview_labels: Dict[str, ttk.Label] = {}
        rows_info = [
            ("角色等级", "level"), ("稀有度", "rarity"), ("好感度", "affection"),
            ("HP", "hp"), ("攻击力", "attack"), ("防御力", "defense"),
            ("暴击率(%)", "crit_rate"), ("暴伤(%)", "crit_dmg"), ("速度", "speed"),
            ("有利加成(%)", "adv_dmg"), ("AP", "ap"), ("PP", "pp"),
        ]
        for i, (label_text, key) in enumerate(rows_info):
            r, c = divmod(i, 4)
            inner = ttk.Frame(preview_frame)
            inner.grid(row=r, column=c, padx=8, pady=2, sticky="w")
            ttk.Label(inner, text=label_text + ":", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
            lbl = ttk.Label(inner, text="--", font=("Microsoft YaHei UI", 9, "bold"))
            lbl.pack(side=tk.LEFT, padx=(3, 0))
            self.preview_labels[key] = lbl

        self.preview_cid = cid
        self.preview_char = char

    def _build_preview_inline(self, parent, cid, char):
        """构建角色面板预览（内嵌于头像右侧，紧凑排版）"""
        preview_frame = ttk.Frame(parent)
        preview_frame.grid(row=1, column=0, sticky="n")

        self.preview_labels: Dict[str, ttk.Label] = {}
        rows_info = [
            ("等级", "level"), ("稀有度", "rarity"), ("好感度", "affection"),
            ("HP", "hp"), ("攻击力", "attack"), ("防御力", "defense"),
            ("暴击率%", "crit_rate"), ("暴伤%", "crit_dmg"), ("速度", "speed"),
            ("有利%", "adv_dmg"), ("AP", "ap"), ("PP", "pp"),
        ]
        for i, (label_text, key) in enumerate(rows_info):
            r, c = divmod(i, 4)
            inner = ttk.Frame(preview_frame)
            inner.grid(row=r, column=c, padx=6, pady=1, sticky="w")
            ttk.Label(inner, text=label_text + ":", font=("Microsoft YaHei UI", 11)).pack(side=tk.LEFT)
            lbl = ttk.Label(inner, text="--", font=("Microsoft YaHei UI", 11, "bold"))
            lbl.pack(side=tk.LEFT, padx=(2, 0))
            self.preview_labels[key] = lbl

        self.preview_cid = cid
        self.preview_char = char

    def _get_skill_level(self, cid):
        """获取角色的技能等级"""
        cfg = self.app.char_config.get(cid, {"override": False})
        if cfg.get("override"):
            return cfg.get("skill_level", self.app.global_tab.var_skill_lv.get())
        return self.app.global_tab.var_skill_lv.get()

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
                val_str = f"{val:.1f}"
            result = result.replace(f"{{{tag_name}}}", val_str)
        return result

    def _build_skill_preview(self, parent, cid, char):
        """构建技能效果预览区域"""
        skills = self.app.data_loader.get_character_skills(cid)
        if not skills:
            return

        frame = ttk.LabelFrame(parent, text="技能效果预览")
        frame.pack(fill="x", padx=5, pady=5)

        # 保存引用以便动态刷新
        self._skill_preview_frame = frame
        self._skill_preview_cid = cid
        self._skill_preview_char = char
        self._skill_preview_skills = skills

        # 构建每个技能的独立等级变量
        cfg = self.app.char_config.get(cid, {"override": False})
        skill_level_vars: Dict[int, tk.IntVar] = {}
        skill_max = getattr(self, '_current_skill_max', 15)
        global_skill_lv = self.app.global_tab.var_skill_lv.get()

        for skill in skills:
            # 读取已保存的各技能等级，向后兼容旧的统一skill_level
            saved_levels = cfg.get("skill_levels", {}) if cfg.get("override") else {}
            if saved_levels and str(skill.skill_id) in saved_levels:
                init_lv = saved_levels[str(skill.skill_id)]
            elif saved_levels and skill.skill_id in saved_levels:
                init_lv = saved_levels[skill.skill_id]
            elif cfg.get("override") and "skill_level" in cfg:
                # 向后兼容：旧配置使用统一skill_level
                init_lv = min(cfg["skill_level"], skill_max)
            else:
                init_lv = min(global_skill_lv, skill_max)
            skill_level_vars[skill.skill_id] = tk.IntVar(value=init_lv)

        self._skill_level_vars = skill_level_vars

        self._render_skill_cards(frame, skills)

    def _render_skill_cards(self, frame, skills):
        """渲染技能卡片到指定frame"""
        CARD_HEIGHT = 40
        skill_max = getattr(self, '_current_skill_max', 15)
        self._skill_desc_widgets = {}
        self._skill_level_spinboxes = []

        for skill in skills:
            card_frame = ttk.Frame(frame, relief="groove", borderwidth=1)
            card_frame.pack(fill="x", padx=3, pady=2)

            # 技能名称和属性信息
            info_frame = ttk.Frame(card_frame)
            info_frame.pack(fill="x", padx=3, pady=(3, 0))

            skill_type_names = {1: "AS", 2: "PS", 3: "EX"}
            stype = skill_type_names.get(skill.skill_type, str(skill.skill_type))
            ttk.Label(info_frame, text=f"[{stype}] {skill.name}",
                      font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")

            # 等级Spinbox（每个技能独立）
            lv_var = self._skill_level_vars.get(skill.skill_id)
            if lv_var:
                lv_frame = ttk.Frame(info_frame)
                lv_frame.pack(side="left", padx=(8, 0))
                ttk.Label(lv_frame, text="Lv.", font=("Microsoft YaHei UI", 8)).pack(side="left")
                lv_spinbox = ttk.Spinbox(lv_frame, from_=1, to=skill_max, textvariable=lv_var, width=3,
                                         font=("Microsoft YaHei UI", 8))
                lv_spinbox.pack(side="left", padx=1)
                self._skill_level_spinboxes.append(lv_spinbox)
                # 等级变化时刷新该技能的描述
                lv_var.trace_add("write", lambda *a, sid=skill.skill_id: self._refresh_single_skill_desc(sid))

            # 消耗点数（AS→AP, PS→PP, EX→EP）
            cost_unit = {1: "AP", 2: "PP", 3: "EP"}.get(skill.skill_type, "AP")
            ttk.Label(info_frame, text=f" | 消耗: {skill.resource_cost}{cost_unit}",
                      font=("Microsoft YaHei UI", 8)).pack(side="left", padx=(5, 0))

            # 冷却信息（1=技能结束→行动, 2=行动结束→回合）
            if skill.cooldown:
                if skill.cooldown_update_timing == 1:
                    cd_text = f" | 冷却: {skill.cooldown}回合"
                elif skill.cooldown_update_timing == 2:
                    cd_text = f" | 冷却: {skill.cooldown}行动"
                else:
                    cd_text = f" | 冷却: {skill.cooldown}无"
            else:
                cd_text = " | 冷却: 无"
            ttk.Label(info_frame, text=cd_text, font=("Microsoft YaHei UI", 8)).pack(side="left", padx=(5, 0))

            # 描述区域（带滚动条）
            lv_var = self._skill_level_vars.get(skill.skill_id)
            skill_lv = lv_var.get() if lv_var else 1
            desc_text = self._format_skill_description(skill, skill_lv)
            desc_outer = ttk.Frame(card_frame, height=CARD_HEIGHT)
            desc_outer.pack(fill="x", padx=5, pady=3)
            desc_outer.pack_propagate(False)

            s = self.app._get_scheme()
            desc_text_widget = tk.Text(desc_outer, wrap=tk.WORD, font=("Microsoft YaHei UI", 9),
                                       state="disabled", relief="flat",
                                       borderwidth=0, padx=2, pady=2,
                                       bg=s["input_bg"], fg=s["fg"],
                                       insertbackground=s["fg"],
                                       selectbackground=s["select_bg"],
                                       selectforeground=s["select_fg"])
            desc_scrollbar = ttk.Scrollbar(desc_outer, orient="vertical",
                                           command=desc_text_widget.yview)
            desc_text_widget.configure(yscrollcommand=desc_scrollbar.set)

            desc_scrollbar.pack(side="right", fill="y")
            desc_text_widget.pack(side="left", fill="both", expand=True)

            desc_text_widget.config(state="normal")
            desc_text_widget.insert("1.0", desc_text)
            desc_text_widget.config(state="disabled")

            # 保存desc widget引用以便单独刷新
            if not hasattr(self, '_skill_desc_widgets'):
                self._skill_desc_widgets = {}
            self._skill_desc_widgets[skill.skill_id] = desc_text_widget

    def _refresh_single_skill_desc(self, skill_id):
        """单个技能等级变化时刷新该技能的描述"""
        if not hasattr(self, '_skill_desc_widgets') or not hasattr(self, '_skill_preview_skills'):
            return
        desc_widget = self._skill_desc_widgets.get(skill_id)
        if not desc_widget or not desc_widget.winfo_exists():
            return
        # 找到对应的skill对象
        skill = None
        for s in self._skill_preview_skills:
            if s.skill_id == skill_id:
                skill = s
                break
        if not skill:
            return
        lv_var = self._skill_level_vars.get(skill_id)
        try:
            skill_lv = lv_var.get() if lv_var else 1
        except (tk.TclError, ValueError):
            return
        desc_text = self._format_skill_description(skill, skill_lv)
        desc_widget.config(state="normal")
        desc_widget.delete("1.0", tk.END)
        desc_widget.insert("1.0", desc_text)
        desc_widget.config(state="disabled")

    def _load_avatar_image(self, cid):
        """加载角色头像并等比例缩放至目标尺寸，返回 tk.PhotoImage 或 None"""
        AVATAR_W = 141
        AVATAR_H = 180
        avatar_path = AVATAR_DIR / f"{cid}.png"
        if not avatar_path.exists():
            return None
        try:
            img = tk.PhotoImage(file=str(avatar_path))
            # 等比例缩放：计算缩放因子
            orig_w = img.width()
            orig_h = img.height()
            if orig_w > 0 and orig_h > 0:
                scale_x = AVATAR_W / orig_w
                scale_y = AVATAR_H / orig_h
                scale = min(scale_x, scale_y)
                if scale < 1.0:
                    # 缩小：使用subsample（整数近似）
                    factor = max(1, int(1.0 / scale))
                    img = img.subsample(factor, factor)
                elif scale > 1.0:
                    # 放大：使用zoom（整数近似）
                    factor = max(1, int(scale))
                    img = img.zoom(factor, factor)
                # 如果缩放后仍偏大，再次subsample微调
                if img.width() > AVATAR_W or img.height() > AVATAR_H:
                    factor2 = max(1, max(img.width() // AVATAR_W, img.height() // AVATAR_H))
                    img = img.subsample(factor2, factor2)
            return img
        except Exception:
            return None

    def _build_avatar_preview(self, parent, cid):
        """构建角色头像预览区域（7:9 比例），作为顶部左侧内嵌组件"""
        AVATAR_W = 140   # 宽度: 7 * 20
        AVATAR_H = 180   # 高度: 9 * 20
        s = self.app._get_scheme()

        # 头像画布（直接pack到parent的左侧）
        self._avatar_canvas = tk.Canvas(parent, width=AVATAR_W, height=AVATAR_H,
                                        bg=s["surface"], highlightthickness=1,
                                        highlightbackground=s["border"])
        self._avatar_canvas._is_avatar = True
        self._avatar_canvas.pack(side="left", padx=(0, 10))

        # 加载头像或显示占位
        avatar_img = self._load_avatar_image(cid)
        if avatar_img:
            self._avatar_canvas.create_image(AVATAR_W // 2, AVATAR_H // 2,
                                             image=avatar_img, anchor="center")
            # 保持引用防止被GC回收
            self._avatar_canvas._photo_ref = avatar_img
        else:
            self._avatar_canvas.create_text(AVATAR_W // 2, AVATAR_H // 2,
                                            text=f"{cid}",
                                            font=("Microsoft YaHei UI", 8), fill=_DARK_BORDER,
                                            justify="center")

    def _build_detail_gears_inline(self, parent, cid, cfg):
        """构建模块词条（内联版本，使用pack布局）"""
        saved_gears = cfg.get("gear", []) if cfg.get("override") else self.app.global_tab.get_values()["default_gear"]
        saved_map = {}
        for g in saved_gears:
            saved_map[(g.get("group", 0), g.get("slot", 0))] = g

        self.detail_gear_vars = []
        module_names = ["模块1 (HP)", "模块2 (攻击)", "模块3 (防御)"]
        gear_frame = ttk.Frame(parent)
        gear_frame.pack(fill="x")

        for grp_idx in range(3):
            grp_frame = ttk.LabelFrame(gear_frame, text=module_names[grp_idx], style="Gear.TLabelframe")
            grp_frame.pack(side="left", padx=3, pady=0, fill="y")

            for slot_idx in range(3):
                slot_frame = ttk.Frame(grp_frame)
                slot_frame.pack(pady=1, padx=3)

                saved = saved_map.get((grp_idx, slot_idx), {})
                init_et = GEAR_EFFECT_DISPLAY.get(saved.get("effect_type", 0), "无效果")
                init_val = saved.get("value", 0.0)

                et_var = tk.StringVar(value=init_et)
                cb = ttk.Combobox(slot_frame, textvariable=et_var, values=GEAR_EFFECT_OPTIONS_DISPLAY,
                                  state="readonly", width=14)
                cb.pack()

                g_idx = grp_idx
                s_idx = slot_idx
                cb.bind("<<ComboboxSelected>>",
                        lambda e, g=g_idx, s=s_idx: self._validate_detail_gear_group(g, s))

                pct_frame = ttk.Frame(slot_frame)
                pct_frame.pack()
                v_var = tk.DoubleVar(value=init_val)
                ttk.Spinbox(pct_frame, from_=0, to=100, increment=0.5, textvariable=v_var, width=5).pack(side=tk.LEFT)
                ttk.Label(pct_frame, text="%", font=("Microsoft YaHei UI", 7)).pack(side=tk.LEFT)

                self.detail_gear_vars.append(
                    {"et": et_var, "val": v_var, "group": grp_idx, "slot": slot_idx})

    def _build_detail_gears(self, parent, cid, cfg):
        ttk.Label(parent, text="模块词条 (每角色共9槽，分3组，同组不可复选相同类型):", font=("Microsoft YaHei UI", 8)).grid(
            row=1, column=0, columnspan=6, sticky="w", padx=5, pady=(10, 2))

        saved_gears = cfg.get("gear", []) if cfg.get("override") else self.app.global_tab.get_values()["default_gear"]
        saved_map = {}
        for g in saved_gears:
            saved_map[(g.get("group", 0), g.get("slot", 0))] = g

        self.detail_gear_vars = []
        module_names = ["模块1 (HP)", "模块2 (攻击)", "模块3 (防御)"]
        gear_frame = ttk.Frame(parent)
        gear_frame.grid(row=2, column=0, columnspan=6, sticky="ew", padx=5, pady=2)

        for grp_idx in range(3):
            grp_frame = ttk.LabelFrame(gear_frame, text=module_names[grp_idx], style="Gear.TLabelframe")
            grp_frame.grid(row=0, column=grp_idx, padx=5, pady=3, sticky="n")

            for slot_idx in range(3):
                slot_frame = ttk.Frame(grp_frame)
                slot_frame.pack(pady=1, padx=3)

                saved = saved_map.get((grp_idx, slot_idx), {})
                init_et = GEAR_EFFECT_DISPLAY.get(saved.get("effect_type", 0), "无效果")
                init_val = saved.get("value", 0.0)

                et_var = tk.StringVar(value=init_et)
                cb = ttk.Combobox(slot_frame, textvariable=et_var, values=GEAR_EFFECT_OPTIONS_DISPLAY,
                                  state="readonly", width=16)
                cb.pack()

                g_idx = grp_idx
                s_idx = slot_idx
                cb.bind("<<ComboboxSelected>>",
                        lambda e, g=g_idx, s=s_idx: self._validate_detail_gear_group(g, s))

                pct_frame = ttk.Frame(slot_frame)
                pct_frame.pack()
                v_var = tk.DoubleVar(value=init_val)
                ttk.Spinbox(pct_frame, from_=0, to=100, increment=0.5, textvariable=v_var, width=5).pack(side=tk.LEFT)
                ttk.Label(pct_frame, text="%", font=("Microsoft YaHei UI", 7)).pack(side=tk.LEFT)

                self.detail_gear_vars.append(
                    {"et": et_var, "val": v_var, "group": grp_idx, "slot": slot_idx})

    def _validate_detail_gear_group(self, group_idx, changed_slot):
        group_slots = [gv for gv in self.detail_gear_vars if gv["group"] == group_idx]
        used_types = {}
        for gv in group_slots:
            et_val = gv["et"].get()
            if et_val != "无效果":
                if et_val in used_types:
                    gv["et"].set("无效果")
                    gv["val"].set(0.0)
                    messagebox.showwarning("词条冲突",
                        f"模块{group_idx+1}中词条类型重复，已自动清除冲突槽位")
                else:
                    used_types[et_val] = True

    def _get_detail_gears(self) -> list:
        return [{"effect_type": GEAR_EFFECT_REVERSE[gv["et"].get()], "value": gv["val"].get(),
                 "group": gv["group"], "slot": gv["slot"]}
                for gv in self.detail_gear_vars if gv["et"].get() != "无效果"]

    def _apply_detail(self, cid, char, v):
        config = self.app.char_config.setdefault(cid, {"override": False})
        config["override"] = True
        config["level"] = v["level"].get()
        config["rarity"] = v["rarity"].get()
        config["affection"] = v["affection"].get()
        # 保存每个技能的独立等级
        skill_levels = {}
        if hasattr(self, '_skill_level_vars'):
            for sid, lv_var in self._skill_level_vars.items():
                try:
                    skill_levels[sid] = lv_var.get()
                except Exception:
                    pass
        config["skill_levels"] = skill_levels
        # 向后兼容：同时保存统一skill_level（取所有技能中的最大值）
        if skill_levels:
            config["skill_level"] = max(skill_levels.values())
        config["mod_tier"] = v["mod_tier"].get()
        config["mod_level"] = v["mod_level"].get()
        config["gear"] = self._get_detail_gears()
        self._refresh_preview(cid)
        self.app._save_char_config()

    def _reset_to_global(self, cid, char):
        if self.app.char_config.get(cid, {}).get("locked"):
            messagebox.showwarning("操作被阻止", f"角色 [{self._get_char_display_name(cid)}] 已锁定，无法重置。\n请先解锁后再操作。")
            return
        # 保留锁定状态
        was_locked = self.app.char_config.get(cid, {}).get("locked", False)
        self.app.char_config[cid] = {"override": False}
        if was_locked:
            self.app.char_config[cid]["locked"] = True
        self._show_detail(cid)
        self.app._save_char_config()

    def _refresh_preview(self, cid):
        try:
            from src.data.stat_calculator import StatCalculator
            from src.config.panel_config import PanelConfig, ModuleConfig
            from src.config.player_config import SchoolLevels

            gv = self.app.global_tab.get_values()
            cfg = self.app.char_config.get(cid, {"override": False})
            char = self.app.data_loader.get_character_by_id(cid)

            panel = PanelConfig(
                character_level=gv["character_level"],
                school_levels=SchoolLevels(**gv["school_levels"]),
                equipment_enabled=True,
                equipment_bonuses=gv["equipment"],
            )

            if cfg.get("override"):
                panel.rarities[cid] = cfg.get("rarity", char.default_rarity)
                panel.affection_levels[cid] = cfg.get("affection", 40)
                panel.character_levels[cid] = cfg.get("level", gv["character_level"])
            else:
                panel.rarities[cid] = gv["default_rarity"]
                panel.affection_levels[cid] = gv["default_affection"]

            # 根据角色default_rarity限制稀有度上限
            max_rarity = get_max_rarity_for(char.default_rarity)
            panel.rarities[cid] = min(panel.rarities[cid], max_rarity)

            # 技能等级上限：稀有度>=9(LR)为15，否则为10
            skill_max = 15 if panel.rarities[cid] >= 9 else 10

            skill_ids = self.app.data_loader.load_character_skills().get(cid, [])
            if cfg.get("override"):
                saved_levels = cfg.get("skill_levels", {})
                if saved_levels:
                    # 使用各技能独立等级
                    panel.skill_levels[cid] = {}
                    for sid in skill_ids:
                        lv = saved_levels.get(sid, saved_levels.get(str(sid), None))
                        if lv is not None:
                            panel.skill_levels[cid][sid] = min(lv, skill_max)
                        else:
                            # 向后兼容：旧配置使用统一skill_level
                            raw_skill_lv = cfg.get("skill_level", 15)
                            panel.skill_levels[cid][sid] = min(raw_skill_lv, skill_max)
                else:
                    # 向后兼容：旧配置使用统一skill_level
                    raw_skill_lv = cfg.get("skill_level", 15)
                    panel.skill_levels[cid] = {sid: min(raw_skill_lv, skill_max) for sid in skill_ids}
            else:
                raw_skill_lv = gv["default_skill_level"]
                panel.skill_levels[cid] = {sid: min(raw_skill_lv, skill_max) for sid in skill_ids}

            tid = get_module_type_ids(char.character_type)
            if cfg.get("override"):
                gear_list = cfg.get("gear", [])
                panel.modules[cid] = [ModuleConfig(
                    module_id=mid,
                    tier=cfg.get("mod_tier", 9),
                    level=cfg.get("mod_level", 50),
                    gear_effects=[g for g in gear_list if g.get("group", 0) == grp_idx],
                ) for grp_idx, mid in enumerate(tid)]
            else:
                panel.modules[cid] = [ModuleConfig(
                    module_id=mid,
                    tier=gv["default_mod_tier"],
                    level=gv["default_mod_level"],
                    gear_effects=[g for g in gv["default_gear"] if g.get("group", 0) == grp_idx],
                ) for grp_idx, mid in enumerate(tid)]

            lerp_data = self.app.data_loader.load_level_lerp_data()
            sc = StatCalculator(lerp_data, data_loader=self.app.data_loader)
            player_config = panel.get_player_config()
            cc = panel.get_character_config(cid, char.default_rarity)
            stats = sc.calculate_stats(cc, player_config)

            r_name = RARITY_NAMES.get(panel.rarities[cid], "")
            effective_level = panel.character_levels.get(cid, gv["character_level"])
            self.preview_labels["level"].config(text=str(effective_level))
            self.preview_labels["rarity"].config(text=f"{panel.rarities[cid]} ({r_name})")
            self.preview_labels["affection"].config(text=str(panel.affection_levels[cid]))
            self.preview_labels["hp"].config(text=str(int(stats.hp)))
            self.preview_labels["attack"].config(text=str(int(stats.attack)))
            self.preview_labels["defense"].config(text=str(int(stats.defense)))
            self.preview_labels["crit_rate"].config(text=f"{(stats.critical_rate * 100):.2f}")
            self.preview_labels["crit_dmg"].config(text=f"{(stats.critical_damage * 100):.2f}")
            self.preview_labels["speed"].config(text=str(int(stats.speed)))
            self.preview_labels["adv_dmg"].config(text=f"{(stats.advantage_damage * 100):.2f}")
            self.preview_labels["ap"].config(text=str(stats.initial_ap))
            self.preview_labels["pp"].config(text=str(stats.initial_pp))

        except Exception as e:
            import traceback
            traceback.print_exc()
            for lbl in self.preview_labels.values():
                lbl.config(text="ERR")

    def _reset_selected(self):
        sel = self.char_listbox.curselection()
        if not sel:
            return
        cid = self._filtered_char_ids[sel[0]]
        if self.app.char_config.get(cid, {}).get("locked"):
            messagebox.showwarning("操作被阻止", f"角色 [{self._get_char_display_name(cid)}] 已锁定，无法重置。\n请先解锁后再操作。")
            return
        if not messagebox.askyesno("确认重置",
                f"确定要重置角色 [{self._get_char_display_name(cid)}] 的配置吗？\n\n"
                "该操作将清除该角色的所有自定义参数\n"
                "（稀有度、好感度、技能等级、模块等级、模块词条等），\n"
                "恢复为全局默认参数。此操作不可撤销。",
                icon="warning"):
            return
        if cid in self.char_override_vars:
            del self.char_override_vars[cid]
        # 保留锁定状态
        was_locked = self.app.char_config.get(cid, {}).get("locked", False)
        self.app.char_config[cid] = {"override": False}
        if was_locked:
            self.app.char_config[cid]["locked"] = True
        self._show_detail(cid)
        self.app._save_char_config()

    def _reset_all(self):
        locked_cids = [cid for cid in self.app.char_ids if self.app.char_config.get(cid, {}).get("locked")]
        if locked_cids:
            locked_names = "、".join(self._get_char_display_name(cid) for cid in locked_cids[:5])
            if len(locked_cids) > 5:
                locked_names += f" 等{len(locked_cids)}个角色"
            suffix = f"\n\n以下角色已锁定，将不会被重置：\n{locked_names}"
        else:
            suffix = ""
        if not messagebox.askyesno("确认全部重置",
                f"确定要重置所有角色的配置吗？\n\n"
                "该操作将清除所有角色的自定义参数\n"
                "（稀有度、好感度、技能等级、模块等级、模块词条等），\n"
                "恢复为全局默认参数。此操作不可撤销。" + suffix,
                icon="warning"):
            return
        for cid in self.app.char_ids:
            if self.app.char_config.get(cid, {}).get("locked"):
                continue
            if cid in self.char_override_vars:
                del self.char_override_vars[cid]
            self.app.char_config[cid] = {"override": False}
        messagebox.showinfo("重置", "所有未锁定角色已恢复为全局默认参数")
        if self._filtered_char_ids:
            self._show_detail(self._filtered_char_ids[0])
        self._refresh_list()
        self.app._save_char_config()

    def _apply_global_all(self):
        locked_cids = [cid for cid in self.app.char_ids if self.app.char_config.get(cid, {}).get("locked")]
        if locked_cids:
            locked_names = "、".join(self._get_char_display_name(cid) for cid in locked_cids[:5])
            if len(locked_cids) > 5:
                locked_names += f" 等{len(locked_cids)}个角色"
            suffix = f"\n\n以下角色已锁定，将不会被应用全局参数：\n{locked_names}"
        else:
            suffix = ""
        if not messagebox.askyesno("确认全部应用全局",
                f"确定要将所有角色应用全局默认参数吗？\n\n"
                "该操作将清除所有角色的自定义参数\n"
                "（稀有度、好感度、技能等级、模块等级、模块词条等），\n"
                "统一使用全局默认参数。此操作不可撤销。" + suffix,
                icon="warning"):
            return
        for cid in self.app.char_ids:
            if self.app.char_config.get(cid, {}).get("locked"):
                continue
            if cid in self.char_override_vars:
                del self.char_override_vars[cid]
            self.app.char_config[cid] = {"override": False}
        messagebox.showinfo("应用", "所有未锁定角色已应用全局默认参数")
        if self._filtered_char_ids:
            self._show_detail(self._filtered_char_ids[0])
        self._refresh_list()
        self.app._save_char_config()

    def _get_char_display_name(self, cid):
        """获取角色的显示名称"""
        char = self.app.data_loader.get_character_by_id(cid)
        if char:
            return self.app.format_char_name(char)
        return str(cid)

    def _toggle_lock(self, cid):
        """切换角色的锁定状态"""
        cfg = self.app.char_config.setdefault(cid, {"override": False})
        new_locked = not cfg.get("locked", False)
        cfg["locked"] = new_locked
        self.app._save_char_config()
        # 刷新详情页以更新锁定按钮状态
        self._show_detail(cid)
        # 刷新列表/网格视图以更新锁定标识
        self._refresh_list()

    def _create_tooltip(self, widget, text):
        """为控件创建简单的悬浮提示"""
        def _show(event):
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
            s = self.app._get_scheme()
            label = tk.Label(tooltip, text=text, bg=s["surface"], fg=s["fg"],
                             relief="solid", borderwidth=1,
                             font=("Microsoft YaHei UI", 9), padx=4, pady=2)
            label.pack()
            widget._tooltip = tooltip

        def _hide(event):
            tooltip = getattr(widget, '_tooltip', None)
            if tooltip:
                tooltip.destroy()
                widget._tooltip = None

        widget.bind("<Enter>", _show)
        widget.bind("<Leave>", _hide)

    def get_char_config(self, cid) -> Dict[str, Any]:
        cfg = self.app.char_config.get(cid, {"override": False})
        if not cfg.get("override"):
            return {"override": False}
        return {
            "override": True,
            "level": cfg.get("level", self.app.global_tab.var_level.get()),
            "rarity": cfg.get("rarity", 14),
            "affection": cfg.get("affection", 40),
            "skill_level": cfg.get("skill_level", 15),
            "skill_levels": cfg.get("skill_levels", {}),
            "mod_tier": cfg.get("mod_tier", 9),
            "mod_level": cfg.get("mod_level", 50),
            "gear": cfg.get("gear", []),
        }


# ────────────────────────────── 自定义木桩 Tab ──────────────────────────────


class CustomDummyTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._dummy_index = 0
        self._registered_ids: List[int] = []
        self._as_rows: List[Dict[str, Any]] = []
        self._ps_rows: List[Dict[str, Any]] = []
        self._build()

    def _build(self):
        f = ttk.Frame(self)
        f.pack(fill=tk.BOTH, expand=True)

        row = 0

        ttk.Label(f, text="自定义木桩管理", font=("Microsoft YaHei UI", 12, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 5), padx=10)
        row += 1

        reg_lf = ttk.LabelFrame(f, text="已注册木桩")
        reg_lf.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=2)
        self._dummy_listbox = tk.Listbox(reg_lf, height=4,
                                         bg=_DARK_INPUT_BG, fg=_DARK_FG,
                                         selectbackground=_DARK_ACCENT, selectforeground="#1e1e2e",
                                         borderwidth=0, highlightthickness=0,
                                         font=("Microsoft YaHei UI", 9))
        self._dummy_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._dummy_listbox.bind("<<ListboxSelect>>", self._on_select_dummy)
        btn_f = ttk.Frame(reg_lf)
        btn_f.pack(side=tk.RIGHT, padx=5, pady=5)
        ttk.Button(btn_f, text="编辑", command=self._edit_selected).pack(fill="x", pady=2)
        ttk.Button(btn_f, text="删除", command=self._delete_selected).pack(fill="x", pady=2)
        ttk.Button(btn_f, text="清空", command=self._clear_all).pack(fill="x", pady=2)
        row += 1

        ttk.Label(f, text="木桩属性编辑", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 5), padx=10)
        row += 1

        basic_lf = ttk.LabelFrame(f, text="基础属性")
        basic_lf.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=2)

        self._var_name = tk.StringVar(value="木桩")
        self._var_element = tk.StringVar(value=ELEMENT_NAMES[1])
        self._var_char_type = tk.StringVar(value=CHAR_TYPE_NAMES[1])
        self._var_position_type = tk.StringVar(value=POSITION_TYPE_NAMES[3])
        self._var_role_type = tk.StringVar(value=ROLE_TYPE_NAMES[1])
        self._var_hp = tk.IntVar(value=10000)
        self._var_atk = tk.IntVar(value=1000)
        self._var_def = tk.IntVar(value=500)
        self._var_crit_rate = tk.DoubleVar(value=0.15)
        self._var_crit_dmg = tk.DoubleVar(value=1.5)
        self._var_spd = tk.IntVar(value=500)
        self._var_adv_dmg = tk.DoubleVar(value=0.0)
        self._var_ap = tk.IntVar(value=5)
        self._var_pp = tk.IntVar(value=5)
        self._var_shield_type = tk.StringVar(value="无")
        self._var_shield_value = tk.IntVar(value=0)

        r = 0
        # 第一列：名称、属性、类型、定位、位置、永久盾类型
        ttk.Label(basic_lf, text="名称:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_name, width=20).grid(row=r, column=1, padx=5, sticky="w")
        # 第二列：HP、ATK、DEF、暴击率、速度、永久盾值
        ttk.Label(basic_lf, text="HP:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_hp, width=10).grid(row=r, column=3, padx=5, sticky="w")
        # 第三列：暴击伤害、有利加成、AP、PP
        ttk.Label(basic_lf, text="暴击伤害:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_crit_dmg, width=10).grid(row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="属性:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_elem = ttk.Combobox(basic_lf, textvariable=self._var_element,
                                values=list(ELEMENT_NAMES.values()), state="readonly", width=8)
        cb_elem.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="ATK:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_atk, width=10).grid(row=r, column=3, padx=5, sticky="w")
        ttk.Label(basic_lf, text="有利加成:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_adv_dmg, width=10).grid(row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="类型:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_ctype = ttk.Combobox(basic_lf, textvariable=self._var_char_type,
                                 values=list(CHAR_TYPE_NAMES.values()), state="readonly", width=8)
        cb_ctype.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="DEF:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_def, width=10).grid(row=r, column=3, padx=5, sticky="w")
        ttk.Label(basic_lf, text="AP:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_ap, width=10).grid(row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="定位:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_role = ttk.Combobox(basic_lf, textvariable=self._var_role_type,
                                values=list(ROLE_TYPE_NAMES.values()), state="readonly", width=8)
        cb_role.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="暴击率:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_crit_rate, width=10).grid(row=r, column=3, padx=5, sticky="w")
        ttk.Label(basic_lf, text="PP:").grid(row=r, column=4, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_pp, width=10).grid(row=r, column=5, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="位置:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_position = ttk.Combobox(basic_lf, textvariable=self._var_position_type,
                                     values=list(POSITION_TYPE_NAMES.values()), state="readonly", width=8)
        cb_position.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="速度:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_spd, width=10).grid(row=r, column=3, padx=5, sticky="w")
        r += 1

        ttk.Label(basic_lf, text="永久盾类型:").grid(row=r, column=0, padx=5, pady=3, sticky="e")
        cb_shield = ttk.Combobox(basic_lf, textvariable=self._var_shield_type,
                                  values=list(SHIELD_TYPE_NAMES.values()), state="readonly", width=10)
        cb_shield.grid(row=r, column=1, padx=5, sticky="w")
        ttk.Label(basic_lf, text="永久盾值:").grid(row=r, column=2, padx=5, pady=3, sticky="e")
        ttk.Entry(basic_lf, textvariable=self._var_shield_value, width=10).grid(row=r, column=3, padx=5, sticky="w")
        r += 1

        row += 1

        self._as_frame = ttk.LabelFrame(f, text="AS技能 (0~4个)")
        self._as_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
        self._as_container = ttk.Frame(self._as_frame)
        self._as_container.pack(fill="x", padx=5, pady=5)
        ttk.Button(self._as_frame, text="+ 添加AS技能", command=self._add_as_row).pack(anchor="w", padx=5, pady=(0, 5))
        row += 1

        self._ps_frame = ttk.LabelFrame(f, text="PS技能 (0~4个)")
        self._ps_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
        self._ps_container = ttk.Frame(self._ps_frame)
        self._ps_container.pack(fill="x", padx=5, pady=5)
        ttk.Button(self._ps_frame, text="+ 添加PS技能", command=self._add_ps_row).pack(anchor="w", padx=5, pady=(0, 5))
        row += 1

        btn_row = ttk.Frame(f)
        btn_row.grid(row=row, column=0, columnspan=2, pady=10, padx=10, sticky="w")
        ttk.Button(btn_row, text="注册/更新木桩", command=self._register_dummy, width=18).pack(side=tk.LEFT, padx=5)
        row += 1

        self._refresh_list()

    def _add_as_row(self) -> Optional[Dict[str, Any]]:
        if len(self._as_rows) >= 4:
            messagebox.showwarning("上限", "最多添加4个AS技能")
            return None
        row_data = self._make_skill_row(self._as_container, self._as_rows, is_ps=False)
        if row_data:
            self._as_rows.append(row_data)
        return row_data

    def _add_ps_row(self) -> Optional[Dict[str, Any]]:
        if len(self._ps_rows) >= 4:
            messagebox.showwarning("上限", "最多添加4个PS技能")
            return None
        row_data = self._make_skill_row(self._ps_container, self._ps_rows, is_ps=True)
        if row_data:
            self._ps_rows.append(row_data)
        return row_data

    def _make_skill_row(self, parent: ttk.Frame, rows: list, is_ps: bool = False) -> Optional[Dict[str, Any]]:
        idx = len(rows)
        prefix = "PS" if is_ps else "AS"
        frame = ttk.LabelFrame(parent, text=f"{prefix}[{idx + 1}]")
        frame.pack(fill="x", pady=2)

        row_data: Dict[str, Any] = {"frame": frame, "effects": []}

        # ── 第一行：名称 + 消耗 + 冷却 + 删除 ──
        vars_row = ttk.Frame(frame)
        vars_row.pack(fill="x", padx=3, pady=2)

        ttk.Label(vars_row, text="名称:").pack(side=tk.LEFT)
        row_data["name"] = tk.StringVar(value=f"自定义{prefix}")
        ttk.Entry(vars_row, textvariable=row_data["name"], width=12).pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(vars_row, text="消耗:").pack(side=tk.LEFT)
        row_data["resource_cost"] = tk.IntVar(value=1)
        ttk.Entry(vars_row, textvariable=row_data["resource_cost"], width=4).pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(vars_row, text="冷却:").pack(side=tk.LEFT)
        row_data["cooldown"] = tk.IntVar(value=0)
        ttk.Entry(vars_row, textvariable=row_data["cooldown"], width=4).pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(vars_row, text="冷却计时:").pack(side=tk.LEFT)
        row_data["cooldown_timing"] = tk.StringVar(value=COOLDOWN_TIMING_NAMES[1])
        ttk.Combobox(vars_row, textvariable=row_data["cooldown_timing"],
                      values=list(COOLDOWN_TIMING_NAMES.values()), state="readonly", width=8).pack(
            side=tk.LEFT, padx=(2, 8))

        ttk.Button(vars_row, text="✕", width=2,
                   command=lambda: (frame.destroy(), rows.remove(row_data))).pack(side=tk.RIGHT, padx=3)

        # ── 第二行：目标设置 ──
        target_row = ttk.Frame(frame)
        target_row.pack(fill="x", padx=3, pady=2)

        ttk.Label(target_row, text="目标类型:").pack(side=tk.LEFT)
        row_data["target_type"] = tk.StringVar(value=TARGET_TYPE_NAMES[3])
        ttk.Combobox(target_row, textvariable=row_data["target_type"],
                      values=list(TARGET_TYPE_NAMES.values()), state="readonly", width=10).pack(
            side=tk.LEFT, padx=(2, 8))

        ttk.Label(target_row, text="范围:").pack(side=tk.LEFT)
        row_data["target_range"] = tk.StringVar(value=TARGET_RANGE_NAMES[1])
        ttk.Combobox(target_row, textvariable=row_data["target_range"],
                      values=list(TARGET_RANGE_NAMES.values()), state="readonly", width=8).pack(
            side=tk.LEFT, padx=(2, 8))

        ttk.Label(target_row, text="优先级:").pack(side=tk.LEFT)
        row_data["target_priority"] = tk.StringVar(value=TARGET_PRIORITY_NAMES[0])
        ttk.Combobox(target_row, textvariable=row_data["target_priority"],
                      values=list(TARGET_PRIORITY_NAMES.values()), state="readonly", width=10).pack(
            side=tk.LEFT, padx=(2, 8))

        # ── PS触发时机 ──
        if is_ps:
            ps_extra = ttk.Frame(frame)
            ps_extra.pack(fill="x", padx=3, pady=2)
            ttk.Label(ps_extra, text="触发时机:").pack(side=tk.LEFT)
            row_data["trigger_timing"] = tk.StringVar(value=TRIGGER_TIMING_OPTIONS[0][0])
            cb = ttk.Combobox(ps_extra, textvariable=row_data["trigger_timing"],
                              values=[t[0] for t in TRIGGER_TIMING_OPTIONS], state="readonly", width=16)
            cb.pack(side=tk.LEFT, padx=(2, 8))

        # ── 效果列表区域 ──
        effects_lf = ttk.LabelFrame(frame, text="效果列表")
        effects_lf.pack(fill="x", padx=3, pady=2)
        row_data["effects_container"] = effects_lf
        row_data["effects_frame"] = ttk.Frame(effects_lf)
        row_data["effects_frame"].pack(fill="x", padx=2, pady=2)

        ttk.Button(effects_lf, text="+ 添加效果", width=10,
                   command=lambda: self._add_effect_row(row_data)).pack(anchor="w", padx=5, pady=(0, 3))

        # 默认添加一个伤害效果
        self._add_effect_row(row_data)

        return row_data

    def _add_effect_row(self, skill_row_data: Dict[str, Any]):
        """向技能行添加一个效果配置行"""
        effects_list = skill_row_data["effects"]
        effects_frame = skill_row_data["effects_frame"]
        idx = len(effects_list)

        ef_frame = ttk.Frame(effects_frame, relief="groove", borderwidth=1)
        ef_frame.pack(fill="x", pady=1, padx=2)

        ef_data: Dict[str, Any] = {"frame": ef_frame}

        # 第一行：效果类型 + 数值 + 段数 + 删除
        row1 = ttk.Frame(ef_frame)
        row1.pack(fill="x", padx=2, pady=1)

        ttk.Label(row1, text="类型:").pack(side=tk.LEFT)
        # 构建分类显示的效果选项列表
        effect_options = []
        for cat, types in EFFECT_CATEGORIES.items():
            for t in types:
                effect_options.append(f"[{cat}] {EFFECT_TYPE_DISPLAY[t]}")
        ef_data["effect_type_display"] = tk.StringVar(value=f"[伤害] {EFFECT_TYPE_DISPLAY['damage']}")
        cb_type = ttk.Combobox(row1, textvariable=ef_data["effect_type_display"],
                                values=effect_options, state="readonly", width=16)
        cb_type.pack(side=tk.LEFT, padx=(2, 4))

        # 数值
        ef_data["value_label"] = ttk.Label(row1, text="威力%:")
        ef_data["value_label"].pack(side=tk.LEFT)
        ef_data["value"] = tk.DoubleVar(value=100.0)
        ef_data["value_entry"] = ttk.Entry(row1, textvariable=ef_data["value"], width=6)
        ef_data["value_entry"].pack(side=tk.LEFT, padx=(2, 4))

        # 段数（仅damage显示）
        ef_data["hit_count_label"] = ttk.Label(row1, text="段数:")
        ef_data["hit_count_label"].pack(side=tk.LEFT)
        ef_data["hit_count"] = tk.IntVar(value=1)
        ef_data["hit_count_entry"] = ttk.Entry(row1, textvariable=ef_data["hit_count"], width=3)
        ef_data["hit_count_entry"].pack(side=tk.LEFT, padx=(2, 4))

        # 删除按钮
        ttk.Button(row1, text="✕", width=2,
                   command=lambda: (ef_frame.destroy(), effects_list.remove(ef_data))).pack(side=tk.RIGHT, padx=2)

        # 第二行：持续时间 + 持续类型 + 状态名（动态显示）
        row2 = ttk.Frame(ef_frame)
        row2.pack(fill="x", padx=2, pady=1)

        ef_data["duration_label"] = ttk.Label(row2, text="持续:")
        ef_data["duration_label"].pack(side=tk.LEFT)
        ef_data["duration"] = tk.IntVar(value=2)
        ef_data["duration_entry"] = ttk.Entry(row2, textvariable=ef_data["duration"], width=3)
        ef_data["duration_entry"].pack(side=tk.LEFT, padx=(2, 4))

        ef_data["duration_type_label"] = ttk.Label(row2, text="计时:")
        ef_data["duration_type_label"].pack(side=tk.LEFT)
        ef_data["duration_type_display"] = tk.StringVar(value=DURATION_TYPE_DISPLAY["turn"])
        ef_data["duration_type_cb"] = ttk.Combobox(row2, textvariable=ef_data["duration_type_display"],
                                                     values=list(DURATION_TYPE_DISPLAY.values()),
                                                     state="readonly", width=5)
        ef_data["duration_type_cb"].pack(side=tk.LEFT, padx=(2, 4))

        ef_data["status_label"] = ttk.Label(row2, text="状态:")
        ef_data["status_label"].pack(side=tk.LEFT)
        ef_data["status_name_display"] = tk.StringVar(value=STATUS_TYPE_DISPLAY["stun"])
        ef_data["status_cb"] = ttk.Combobox(row2, textvariable=ef_data["status_name_display"],
                                              values=list(STATUS_TYPE_DISPLAY.values()),
                                              state="readonly", width=6)
        ef_data["status_cb"].pack(side=tk.LEFT, padx=(2, 4))

        # 效果类型变化时更新字段可见性
        def _on_type_change(*args):
            display_val = ef_data["effect_type_display"].get()
            # 从显示名提取效果类型key
            effect_key = None
            for k, v in EFFECT_TYPE_DISPLAY.items():
                if display_val.endswith(v):
                    effect_key = k
                    break
            if not effect_key:
                return
            flags = EFFECT_FIELD_FLAGS.get(effect_key, {})

            # 数值字段
            if flags.get("value", False):
                ef_data["value_label"].pack(side=tk.LEFT)
                ef_data["value_entry"].pack(side=tk.LEFT, padx=(2, 4))
                # 更新数值标签
                if effect_key == "damage":
                    ef_data["value_label"].config(text="威力%:")
                elif effect_key in ("add_ap", "remove_ap"):
                    ef_data["value_label"].config(text="数值:")
                elif effect_key == "add_ep":
                    ef_data["value_label"].config(text="EP值:")
                elif effect_key == "shield":
                    ef_data["value_label"].config(text="盾值:")
                elif effect_key == "hp_ratio_damage":
                    ef_data["value_label"].config(text="HP%:")
                else:
                    ef_data["value_label"].config(text="数值%:")
            else:
                ef_data["value_label"].pack_forget()
                ef_data["value_entry"].pack_forget()

            # 段数字段
            if flags.get("hit_count", False):
                ef_data["hit_count_label"].pack(side=tk.LEFT)
                ef_data["hit_count_entry"].pack(side=tk.LEFT, padx=(2, 4))
            else:
                ef_data["hit_count_label"].pack_forget()
                ef_data["hit_count_entry"].pack_forget()

            # 持续时间字段
            if flags.get("duration", False):
                ef_data["duration_label"].pack(side=tk.LEFT)
                ef_data["duration_entry"].pack(side=tk.LEFT, padx=(2, 4))
            else:
                ef_data["duration_label"].pack_forget()
                ef_data["duration_entry"].pack_forget()

            # 持续类型字段
            if flags.get("duration_type", False):
                ef_data["duration_type_label"].pack(side=tk.LEFT)
                ef_data["duration_type_cb"].pack(side=tk.LEFT, padx=(2, 4))
                # 状态异常默认用action计时
                if effect_key == "add_status":
                    ef_data["duration_type_display"].set(DURATION_TYPE_DISPLAY["action"])
            else:
                ef_data["duration_type_label"].pack_forget()
                ef_data["duration_type_cb"].pack_forget()

            # 状态名字段
            if flags.get("status_name", False):
                ef_data["status_label"].pack(side=tk.LEFT)
                ef_data["status_cb"].pack(side=tk.LEFT, padx=(2, 4))
            else:
                ef_data["status_label"].pack_forget()
                ef_data["status_cb"].pack_forget()

        ef_data["effect_type_display"].trace_add("write", _on_type_change)
        # 初始化可见性
        _on_type_change()

        effects_list.append(ef_data)

    def _register_dummy(self):
        cfg = self._build_config_from_gui()
        char_id = self.app.data_loader.register_custom_dummy(cfg, self._dummy_index)
        self._refresh_list()
        self._dummy_index += 1
        self.app.team_tab._refresh_char_options()
        messagebox.showinfo("注册成功", f"木桩 [{char_id}] {cfg.name} 已注册，可在编队Tab中选择")

    def _build_config_from_gui(self) -> CustomDummyConfig:
        elem_rev = {v: k for k, v in ELEMENT_NAMES.items()}
        ctype_rev = {v: k for k, v in CHAR_TYPE_NAMES.items()}
        ptype_rev = {v: k for k, v in POSITION_TYPE_NAMES.items()}
        rtype_rev = {v: k for k, v in ROLE_TYPE_NAMES.items()}
        ttype_rev = {v: k for k, v in TARGET_TYPE_NAMES.items()}
        trange_rev = {v: k for k, v in TARGET_RANGE_NAMES.items()}
        tprio_rev = {v: k for k, v in TARGET_PRIORITY_NAMES.items()}
        cdtiming_rev = {v: k for k, v in COOLDOWN_TIMING_NAMES.items()}
        trig_rev = {t[0]: t[1] for t in TRIGGER_TIMING_OPTIONS}

        def _parse_effect_type(display_val: str) -> str:
            """从显示名解析效果类型key"""
            for k, v in EFFECT_TYPE_DISPLAY.items():
                if display_val.endswith(v):
                    return k
            return "damage"

        def _build_effects(effects_list: list) -> List[CustomEffectConfig]:
            result = []
            for ef_data in effects_list:
                effect_key = _parse_effect_type(ef_data["effect_type_display"].get())
                try:
                    val = ef_data["value"].get()
                except (tk.TclError, ValueError):
                    val = 100.0
                try:
                    hc = ef_data["hit_count"].get()
                except (tk.TclError, ValueError):
                    hc = 1
                try:
                    dur = ef_data["duration"].get()
                except (tk.TclError, ValueError):
                    dur = 2
                dur_type_disp = ef_data["duration_type_display"].get()
                dur_type = DURATION_DISPLAY_REVERSE.get(dur_type_disp, "turn")
                status_disp = ef_data["status_name_display"].get()
                status_key = STATUS_DISPLAY_REVERSE.get(status_disp, "stun")
                result.append(CustomEffectConfig(
                    effect_type=effect_key,
                    value=val,
                    hit_count=hc,
                    duration=dur,
                    duration_type=dur_type,
                    status_name=status_key,
                ))
            return result

        as_skills = []
        for row in self._as_rows:
            effects = _build_effects(row.get("effects", []))
            as_skills.append(CustomASConfig(
                name=row["name"].get(),
                effects=effects,
                cooldown=row["cooldown"].get(),
                cooldown_update_timing=cdtiming_rev.get(row["cooldown_timing"].get(), 1),
                target_type=ttype_rev.get(row["target_type"].get(), 3),
                target_range=trange_rev.get(row["target_range"].get(), 1),
                target_priority=tprio_rev.get(row["target_priority"].get(), 0),
                resource_cost=row["resource_cost"].get(),
            ))

        ps_skills = []
        for row in self._ps_rows:
            effects = _build_effects(row.get("effects", []))
            ps_skills.append(CustomPSConfig(
                name=row["name"].get(),
                effects=effects,
                cooldown=row["cooldown"].get(),
                cooldown_update_timing=cdtiming_rev.get(row["cooldown_timing"].get(), 1),
                target_type=ttype_rev.get(row["target_type"].get(), 3),
                target_range=trange_rev.get(row["target_range"].get(), 1),
                target_priority=tprio_rev.get(row["target_priority"].get(), 0),
                resource_cost=row["resource_cost"].get(),
                trigger_timing=trig_rev.get(row["trigger_timing"].get(), "BeforeAsAttacked"),
            ))

        return CustomDummyConfig(
            name=self._var_name.get(),
            element=elem_rev.get(self._var_element.get(), 1),
            character_type=ctype_rev.get(self._var_char_type.get(), 1),
            position_type=ptype_rev.get(self._var_position_type.get(), 3),
            role_type=rtype_rev.get(self._var_role_type.get(), 1),
            hp=self._var_hp.get(),
            attack=self._var_atk.get(),
            defense=self._var_def.get(),
            crit_rate=self._var_crit_rate.get(),
            crit_damage=self._var_crit_dmg.get(),
            speed=self._var_spd.get(),
            advantage_damage=self._var_adv_dmg.get(),
            ap=self._var_ap.get(),
            pp=self._var_pp.get(),
            permanent_shield_type=SHIELD_TYPE_REV.get(self._var_shield_type.get(), 0),
            permanent_shield_value=self._var_shield_value.get(),
            as_skills=as_skills,
            ps_skills=ps_skills,
        )

    def _load_config_to_gui(self, cfg: CustomDummyConfig, dummy_index: int):
        self._dummy_index = dummy_index
        self._var_name.set(cfg.name)
        self._var_element.set(ELEMENT_NAMES.get(cfg.element, ELEMENT_NAMES[1]))
        self._var_char_type.set(CHAR_TYPE_NAMES.get(cfg.character_type, CHAR_TYPE_NAMES[1]))
        self._var_position_type.set(POSITION_TYPE_NAMES.get(cfg.position_type, POSITION_TYPE_NAMES[3]))
        self._var_role_type.set(ROLE_TYPE_NAMES.get(cfg.role_type, ROLE_TYPE_NAMES[1]))
        self._var_hp.set(cfg.hp)
        self._var_atk.set(cfg.attack)
        self._var_def.set(cfg.defense)
        self._var_crit_rate.set(cfg.crit_rate)
        self._var_crit_dmg.set(cfg.crit_damage)
        self._var_spd.set(cfg.speed)
        self._var_adv_dmg.set(cfg.advantage_damage)
        self._var_ap.set(cfg.ap)
        self._var_pp.set(cfg.pp)
        self._var_shield_type.set(SHIELD_TYPE_NAMES.get(cfg.permanent_shield_type, "无"))
        self._var_shield_value.set(cfg.permanent_shield_value)

        self._clear_skill_rows()
        for as_cfg in cfg.as_skills:
            row = self._add_as_row()
            if row:
                row["name"].set(as_cfg.name)
                row["cooldown"].set(as_cfg.cooldown)
                row["cooldown_timing"].set(COOLDOWN_TIMING_NAMES.get(as_cfg.cooldown_update_timing, COOLDOWN_TIMING_NAMES[1]))
                row["target_type"].set(TARGET_TYPE_NAMES.get(as_cfg.target_type, TARGET_TYPE_NAMES[3]))
                row["target_range"].set(TARGET_RANGE_NAMES.get(as_cfg.target_range, TARGET_RANGE_NAMES[1]))
                row["target_priority"].set(TARGET_PRIORITY_NAMES.get(as_cfg.target_priority, TARGET_PRIORITY_NAMES[0]))
                row["resource_cost"].set(as_cfg.resource_cost)
                # 加载效果列表
                self._load_effects_to_row(row, as_cfg.get_effects())
        for ps_cfg in cfg.ps_skills:
            row = self._add_ps_row()
            if row:
                row["name"].set(ps_cfg.name)
                row["cooldown"].set(ps_cfg.cooldown)
                row["cooldown_timing"].set(COOLDOWN_TIMING_NAMES.get(ps_cfg.cooldown_update_timing, COOLDOWN_TIMING_NAMES[1]))
                row["target_type"].set(TARGET_TYPE_NAMES.get(ps_cfg.target_type, TARGET_TYPE_NAMES[3]))
                row["target_range"].set(TARGET_RANGE_NAMES.get(ps_cfg.target_range, TARGET_RANGE_NAMES[1]))
                row["target_priority"].set(TARGET_PRIORITY_NAMES.get(ps_cfg.target_priority, TARGET_PRIORITY_NAMES[0]))
                row["resource_cost"].set(ps_cfg.resource_cost)
                trig_display = next((t[0] for t in TRIGGER_TIMING_OPTIONS if t[1] == ps_cfg.trigger_timing), "被攻击前")
                row["trigger_timing"].set(trig_display)
                # 加载效果列表
                self._load_effects_to_row(row, ps_cfg.get_effects())

    def _load_effects_to_row(self, row: Dict[str, Any], effects: List[CustomEffectConfig]):
        """将效果配置列表加载到技能行的效果区域"""
        # 清除默认效果
        for ef_data in row["effects"]:
            ef_data["frame"].destroy()
        row["effects"].clear()

        # 添加配置的效果
        for efg in effects:
            self._add_effect_row(row)
            ef_data = row["effects"][-1]
            # 设置效果类型
            display_name = EFFECT_TYPE_DISPLAY.get(efg.effect_type, "伤害")
            cat_name = next((cat for cat, types in EFFECT_CATEGORIES.items() if efg.effect_type in types), "伤害")
            ef_data["effect_type_display"].set(f"[{cat_name}] {display_name}")
            ef_data["value"].set(efg.value)
            ef_data["hit_count"].set(efg.hit_count)
            ef_data["duration"].set(efg.duration)
            ef_data["duration_type_display"].set(DURATION_TYPE_DISPLAY.get(efg.duration_type, DURATION_TYPE_DISPLAY["turn"]))
            ef_data["status_name_display"].set(STATUS_TYPE_DISPLAY.get(efg.status_name, STATUS_TYPE_DISPLAY["stun"]))

    def _clear_skill_rows(self):
        for row in self._as_rows:
            row["frame"].destroy()
        self._as_rows.clear()
        for row in self._ps_rows:
            row["frame"].destroy()
        self._ps_rows.clear()

    def _refresh_list(self):
        self._dummy_listbox.delete(0, tk.END)
        self._registered_ids.clear()
        dummies = self.app.data_loader.get_all_custom_dummies()
        for cid, char_data in dummies.items():
            self._dummy_listbox.insert(tk.END, f"[{cid}] {char_data.name}")
            self._registered_ids.append(cid)

    def _on_select_dummy(self, event):
        sel = self._dummy_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        cid = self._registered_ids[idx]
        cfg = self.app.data_loader.get_custom_dummy_config(cid)
        if cfg:
            dummy_idx = abs(cid) - 1
            self._load_config_to_gui(cfg, dummy_idx)

    def _edit_selected(self):
        sel = self._dummy_listbox.curselection()
        if not sel:
            messagebox.showwarning("未选择", "请先在列表中选中一个木桩")
            return
        idx = sel[0]
        cid = self._registered_ids[idx]
        old_cfg = self.app.data_loader.get_custom_dummy_config(cid)
        if not old_cfg:
            return

        new_cfg = self._build_config_from_gui()
        saved_configs = []
        for old_id in self._registered_ids:
            saved = self.app.data_loader.get_custom_dummy_config(old_id)
            saved_configs.append((old_id, saved))

        self.app.data_loader.clear_custom_dummies()
        for (old_id, saved) in saved_configs:
            if saved is None:
                continue
            target_cfg = new_cfg if old_id == cid else saved
            self.app.data_loader.register_custom_dummy(target_cfg, abs(old_id) - 1)
        self._registered_ids = self.app.data_loader.get_custom_dummy_ids()
        self._refresh_list()
        self.app.team_tab._refresh_char_options()
        messagebox.showinfo("更新成功", f"木桩 [{cid}] 已更新")

    def _delete_selected(self):
        sel = self._dummy_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        cid = self._registered_ids[idx]

        saved_configs = []
        for old_id in self._registered_ids:
            saved = self.app.data_loader.get_custom_dummy_config(old_id)
            saved_configs.append(saved)

        self.app.data_loader.clear_custom_dummies()
        new_index = 0
        for i, saved in enumerate(saved_configs):
            if i == idx:
                continue
            if saved is None:
                continue
            self.app.data_loader.register_custom_dummy(saved, new_index)
            new_index += 1
        self._registered_ids = self.app.data_loader.get_custom_dummy_ids()
        self._refresh_list()
        self.app.team_tab._refresh_char_options()

    def _clear_all(self):
        self.app.data_loader.clear_custom_dummies()
        self._registered_ids.clear()
        self._clear_skill_rows()
        self._refresh_list()
        self.app.team_tab._refresh_char_options()
        self._dummy_index = 0


# ────────────────────────────── 回忆卡选择弹窗 ──────────────────────────────

def _bind_modal_minimize_restore(dialog, parent):
    """为模态弹窗绑定父窗口最小化/恢复处理。

    修复bug：打开弹窗后最小化主界面（如Win+D显示桌面），再从任务栏恢复时
    无法恢复、无法关闭程序。根因：grab_set锁在不可见的弹窗上，Windows无法
    激活被grab锁定的主窗口，导致整个应用输入被锁死。
    方案：主窗口最小化时grab_release解锁；恢复时deiconify弹窗并重新grab_set。
    """
    top = parent.winfo_toplevel()

    def _on_top_unmap(event):
        # 主窗口被最小化/隐藏时，释放grab避免锁死整个应用
        if event.widget is not top:
            return
        try:
            if dialog.winfo_exists():
                dialog.grab_release()
        except Exception:
            pass

    def _on_top_map(event):
        # 主窗口恢复显示时，恢复弹窗并重新建立模态grab
        if event.widget is not top:
            return

        def _restore():
            try:
                if not dialog.winfo_exists():
                    return
                # 处理iconic和withdrawn两种隐藏状态
                state = str(dialog.state())
                if state in ('iconic', 'withdrawn'):
                    dialog.deiconify()
                dialog.lift()
                dialog.focus_force()
                dialog.grab_set()
            except Exception:
                pass

        # 延迟执行，确保窗口管理器状态已稳定
        try:
            top.after(50, _restore)
        except Exception:
            pass

    map_id = top.bind("<Map>", _on_top_map, "+")
    unmap_id = top.bind("<Unmap>", _on_top_unmap, "+")

    def _cleanup(event=None):
        try:
            top.unbind("<Map>", map_id)
            top.unbind("<Unmap>", unmap_id)
        except Exception:
            pass

    dialog.bind("<Destroy>", _cleanup, "+")


class MemoryPickerDialog(tk.Toplevel):
    """回忆卡可视化选择弹窗：16:9横版卡片网格 + 稀有度筛选 + 搜索"""

    def __init__(self, parent, app, title="选择回忆卡", exclude_ids=None):
        super().__init__(parent)
        self.app = app
        self.result: Optional[int] = None  # 选中的回忆卡ID
        self._exclude_ids: set = set(exclude_ids or [])
        self._current_rarity = 0  # 0=全部
        self._filtered_ids: List[int] = []
        self._thumb_cache: Dict[int, tk.PhotoImage] = {}

        self.title(title)
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(True, True)
        self.geometry("680x620")
        self.minsize(500, 400)

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

        # ── 顶部：搜索框 + 稀有度筛选 ──
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", padx=10, pady=5)

        # 搜索框
        search_frame = ttk.Frame(top_frame)
        search_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(search_frame, text="搜索:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._refresh_grid())
        search_entry = ttk.Entry(search_frame, textvariable=self._search_var, width=25)
        search_entry.pack(side=tk.LEFT, padx=5, fill="x", expand=True)
        search_entry.bind("<Return>", lambda e: self._refresh_grid())

        # 稀有度筛选按钮（使用图标）
        filter_frame = ttk.Frame(top_frame)
        filter_frame.pack(fill="x")
        self._rarity_buttons: List[tk.Label] = []
        # 0=全部, 1=SR, 2=SSR, 3=UR, 4=LR
        rarity_btn_data = [(0, "全部", None)]
        for rid, (rname, ricon) in MEM_RARITY_MAP.items():
            rarity_btn_data.append((rid, rname, ricon))
        ICON_SIZE = 20
        for rid, rname, ricon in rarity_btn_data:
            if ricon:
                icon_path = RARITY_DIR / ricon
                try:
                    photo = tk.PhotoImage(file=str(icon_path))
                    if photo.width() > ICON_SIZE:
                        photo = photo.subsample(photo.width() // ICON_SIZE, photo.width() // ICON_SIZE)
                except Exception:
                    photo = None
            else:
                photo = None
            if photo:
                btn = tk.Label(filter_frame, image=photo, cursor="hand2", bd=1, relief="raised",
                               bg=s["surface"], padx=2, pady=1)
                btn.image = photo
            else:
                btn = tk.Label(filter_frame, text=rname, cursor="hand2", bd=1, relief="raised",
                               bg=s["surface"], fg=s["fg"], font=("Microsoft YaHei UI", 9),
                               padx=6, pady=2)
            btn.pack(side=tk.LEFT, padx=2)
            btn.bind("<Button-1>", lambda e, r=rid: self._apply_rarity_filter(r))
            self._rarity_buttons.append(btn)
        self._update_rarity_highlight()

        # ── 中部：网格视图 ──
        grid_frame = ttk.Frame(self)
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self._canvas = tk.Canvas(grid_frame, bg=s["bg"], highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(grid_frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid_inner = tk.Frame(self._canvas, bg=s["surface"])
        self._canvas_window = self._canvas.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind("<Configure>",
                              lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        def _bind_mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _enter(e):
            self._canvas.bind_all("<MouseWheel>", _bind_mw)

        def _leave(e):
            self._canvas.unbind_all("<MouseWheel>")

        self._canvas.bind("<Enter>", _enter)
        self._canvas.bind("<Leave>", _leave)

        # ── 底部：取消按钮 ──
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="取消", command=self._on_close, width=10).pack()

        self._refresh_grid()

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _apply_rarity_filter(self, rarity_id):
        self._current_rarity = rarity_id
        self._update_rarity_highlight()
        self._refresh_grid()
        # 切换筛选后滚动到顶部
        self._canvas.yview_moveto(0)

    def _update_rarity_highlight(self):
        s = self.app._get_scheme()
        for i, btn in enumerate(self._rarity_buttons):
            if i == self._current_rarity:
                btn.config(relief="sunken", bg=s["accent"], fg="#1e1e2e")
            else:
                btn.config(relief="raised", bg=s["surface"], fg=s["fg"])

    def _get_filtered_ids(self):
        """获取过滤后的回忆卡ID列表"""
        search_text = self._search_var.get().strip().lower()
        result = []
        try:
            memories = self.app.data_loader.load_memories()
        except Exception as e:
            print(f"[MemoryPicker] 加载回忆卡数据失败: {e}")
            return result
        for mid, mem in memories.items():
            if mid in self._exclude_ids:
                continue
            if self._current_rarity != 0 and mem.rarity != self._current_rarity:
                continue
            if search_text:
                if search_text not in str(mid) and search_text not in mem.name.lower():
                    continue
            result.append(mid)
        result.sort()
        return result

    def _load_card_thumb(self, mid):
        """加载回忆卡缩略图（已预缩放为160x90，直接加载）"""
        if mid in self._thumb_cache:
            return self._thumb_cache[mid]
        card_path = MEMORY_CARD_DIR / f"{mid}.png"
        if not card_path.exists():
            return None
        try:
            photo = tk.PhotoImage(file=str(card_path))
            self._thumb_cache[mid] = photo
            return photo
        except Exception:
            return None

    def _refresh_grid(self):
        """刷新网格视图（先显示占位符，再异步加载缩略图）"""
        self._filtered_ids = self._get_filtered_ids()
        for child in self._grid_inner.winfo_children():
            child.destroy()

        COLS = 4
        PAD = 3
        s = self.app._get_scheme()
        self._card_widgets = {}  # mid -> (canvas, info_frame)

        # 用于智能截断的字体度量
        import tkinter.font as tkfont
        name_font = tkfont.Font(family="Microsoft YaHei UI", size=8)
        THUMB_W = 160
        # 名称可用宽度 = 卡片宽度 - 稀有度图标(~16px) - 边距
        MAX_NAME_WIDTH = THUMB_W - 20

        try:
            for i, mid in enumerate(self._filtered_ids):
                mem = self.app.data_loader.get_memory(mid)
                if not mem:
                    continue
                row, col = divmod(i, COLS)
                card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                                highlightbackground=s["border"], highlightthickness=2,
                                cursor="hand2")
                card.grid(row=row, column=col, padx=PAD, pady=PAD)

                # 占位符画布（先不加载图片）
                THUMB_W, THUMB_H = 160, 90
                card_canvas = tk.Canvas(card, width=THUMB_W, height=THUMB_H,
                                        bg=s["surface"], highlightthickness=0)
                card_canvas.pack()
                card_canvas.create_text(THUMB_W // 2, THUMB_H // 2, text="...",
                                        fill=s["border"], font=("Microsoft YaHei UI", 9))

                # 稀有度图标 + 名称
                info_frame = tk.Frame(card, bg=s["surface"])
                info_frame.pack(fill="x", pady=(2, 0))
                rname, ricon = MEM_RARITY_MAP.get(mem.rarity, (f"?{mem.rarity}", None))
                if ricon:
                    icon_path = RARITY_DIR / ricon
                    try:
                        rphoto = tk.PhotoImage(file=str(icon_path))
                        RARITY_ICON_SIZE = 14
                        if rphoto.width() > RARITY_ICON_SIZE:
                            rphoto = rphoto.subsample(rphoto.width() // RARITY_ICON_SIZE, rphoto.width() // RARITY_ICON_SIZE)
                        rlabel = tk.Label(info_frame, image=rphoto, bg=s["surface"], bd=0)
                        rlabel.image = rphoto
                        rlabel.pack(side=tk.LEFT, padx=(0, 2))
                    except Exception:
                        tk.Label(info_frame, text=f"[{rname}]", bg=s["surface"], fg=s["fg"],
                                 font=("Microsoft YaHei UI", 7)).pack(side=tk.LEFT)
                # 智能截断：仅在像素宽度超出时才加省略号
                name = mem.name
                if name_font.measure(name) > MAX_NAME_WIDTH:
                    truncated = name
                    while truncated and name_font.measure(truncated + "…") > MAX_NAME_WIDTH:
                        truncated = truncated[:-1]
                    name = (truncated + "…") if truncated else "…"
                name_label = tk.Label(info_frame, text=name, bg=s["surface"], fg=s["fg"],
                                      font=("Microsoft YaHei UI", 8), anchor="center")
                name_label.pack(side=tk.LEFT, fill="x", expand=True)

                for widget in [card] + list(card.winfo_children()) + list(info_frame.winfo_children()):
                    widget.bind("<Button-1>", lambda e, m=mid: self._on_select(m))

                self._card_widgets[mid] = card_canvas
        except Exception as e:
            print(f"[MemoryPicker] _refresh_grid error: {e}")
            import traceback
            traceback.print_exc()

        # 每列均分权重，使每行内容居中
        for c in range(COLS):
            self._grid_inner.grid_columnconfigure(c, weight=1, uniform="col")

        # 异步加载缩略图（每帧加载几张，避免卡顿）
        self._thumb_load_queue = list(self._filtered_ids)
        self._load_thumbs_async()

    def _load_thumbs_async(self):
        """异步逐批加载缩略图，每帧加载4张"""
        if not hasattr(self, '_thumb_load_queue') or not self._thumb_load_queue:
            return
        BATCH = 4
        s = self.app._get_scheme()
        THUMB_W, THUMB_H = 160, 90
        for _ in range(BATCH):
            if not self._thumb_load_queue:
                break
            mid = self._thumb_load_queue.pop(0)
            if mid not in self._card_widgets:
                continue
            card_canvas = self._card_widgets[mid]
            photo = self._load_card_thumb(mid)
            if photo:
                card_canvas.delete("all")
                card_canvas.create_image(THUMB_W // 2, THUMB_H // 2, image=photo, anchor="center")
                card_canvas._card_photo = photo
        if self._thumb_load_queue:
            self.after(10, self._load_thumbs_async)

    def _on_select(self, mid):
        self.result = mid
        self.destroy()

    def _on_close(self):
        self.result = None
        self.destroy()


# ────────────────────────────── 敌方选择弹窗 ──────────────────────────────

class EnemyPickerDialog(tk.Toplevel):
    """敌方选择二级弹窗：头像网格选择"""

    def __init__(self, parent, app, title="选择敌方单位"):
        super().__init__(parent)
        self.app = app
        self.result: Optional[int] = None  # 选中的敌方ID
        self._thumb_cache: Dict[int, tk.PhotoImage] = {}

        self.title(title)
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(True, True)
        self.geometry("440x400")
        self.minsize(300, 300)

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

        # 标题
        ttk.Label(self, text="选择敌方单位", font=("Microsoft YaHei UI", 11, "bold")).pack(pady=(10, 5))

        # 网格视图
        grid_frame = tk.Frame(self, bg=s["bg"])
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self._canvas = tk.Canvas(grid_frame, bg=s["bg"], highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(grid_frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid_inner = tk.Frame(self._canvas, bg=s["surface"])
        self._canvas_window = self._canvas.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind("<Configure>",
                              lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        def _bind_mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _enter(e):
            self._canvas.bind_all("<MouseWheel>", _bind_mw)

        def _leave(e):
            self._canvas.unbind_all("<MouseWheel>")

        self._canvas.bind("<Enter>", _enter)
        self._canvas.bind("<Leave>", _leave)

        # 底部取消按钮
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="取消", command=self._on_close, width=10).pack()

        self._refresh_grid()

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _load_thumb(self, cid):
        """加载缩略图（缓存）"""
        if cid in self._thumb_cache:
            return self._thumb_cache[cid]
        from PIL import Image, ImageTk
        THUMB_W, THUMB_H = 70, 90
        avatar_path = AVATAR_DIR / f"{cid}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            pil_img = pil_img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
            photo = ImageTk.PhotoImage(pil_img)
            self._thumb_cache[cid] = photo
            return photo
        except Exception:
            return None

    def _refresh_grid(self):
        """刷新网格视图"""
        s = self.app._get_scheme()
        for child in self._grid_inner.winfo_children():
            child.destroy()

        dev_mode = self.app.is_developer_mode()
        enemies = []
        for eid, data in sorted(self._enemy_data().items(), key=lambda x: x[1]["character_name"]):
            if not dev_mode and eid not in ALLOWED_ENEMY_IDS:
                continue
            enemies.append((eid, data))

        COLS = 4
        PAD = 4
        THUMB_W, THUMB_H = 70, 90

        for i, (eid, data) in enumerate(enemies):
            row, col = divmod(i, COLS)
            card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                           highlightbackground=s["border"], highlightthickness=2,
                           cursor="hand2")
            card.grid(row=row, column=col, padx=PAD, pady=PAD)

            # 头像
            avatar_cid = ENEMY_AVATAR_MAP.get(eid)
            photo = None
            if avatar_cid:
                photo = self._load_thumb(avatar_cid)
            if photo:
                avatar_label = tk.Label(card, image=photo, bg=s["surface"], bd=0)
                avatar_label.image = photo
                avatar_label.pack()
            else:
                placeholder_text = f"[{eid}]" if dev_mode else "???"
                placeholder = tk.Label(card, text=placeholder_text, bg=s["surface"], fg=s["border"],
                                       width=THUMB_W // 8, height=THUMB_H // 16,
                                       font=("Microsoft YaHei UI", 8))
                placeholder.pack()

            # 名称
            pos_name = ["", "左前", "中前", "右前", "左后", "中后", "右后"][data.get("position", 2)]
            if dev_mode:
                name_text = f"[{eid}] {data['character_name']}"
            else:
                name_text = f"{data['character_name']}"
            name_label = tk.Label(card, text=name_text, bg=s["surface"], fg=s["fg"],
                                  font=("Microsoft YaHei UI", 8), wraplength=THUMB_W + 10,
                                  height=2, justify="center")
            name_label.pack(pady=(2, 0))

            # 站位
            pos_label = tk.Label(card, text=f"({pos_name})", bg=s["surface"], fg=s["border"],
                                  font=("Microsoft YaHei UI", 7))
            pos_label.pack()

            # 绑定点击事件
            for widget in [card] + list(card.winfo_children()):
                widget.bind("<Button-1>", lambda e, eid=eid: self._on_select(eid))

        # 每列均分权重
        for c in range(COLS):
            self._grid_inner.grid_columnconfigure(c, weight=1, uniform="col")

    def _enemy_data(self):
        """获取敌方数据"""
        return self.app.data_loader.get_tactical_exercise_enemies()

    def _on_select(self, eid):
        self.result = eid
        self.destroy()

    def _on_close(self):
        self.result = None
        self.destroy()


# ────────────────────────────── 角色选择弹窗 ──────────────────────────────

class CharacterPickerDialog(tk.Toplevel):
    """角色选择二级弹窗：头像网格 + 属性筛选 + 搜索"""

    def __init__(self, parent, app, title="选择角色"):
        super().__init__(parent)
        self.app = app
        self.result: Optional[int] = None  # 选中的角色ID
        self._current_filter = 0
        self._filtered_ids: List[int] = []
        self._thumb_cache: Dict[int, tk.PhotoImage] = {}

        self.title(title)
        self.transient(parent)
        self.grab_set()
        _bind_modal_minimize_restore(self, parent)
        self.resizable(True, True)
        self.geometry("520x620")
        self.minsize(400, 400)

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

        # ── 顶部：搜索框 + 属性筛选 ──
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", padx=10, pady=5)

        # 搜索框
        search_frame = ttk.Frame(top_frame)
        search_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(search_frame, text="搜索:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._refresh_grid())
        search_entry = ttk.Entry(search_frame, textvariable=self._search_var, width=20)
        search_entry.pack(side=tk.LEFT, padx=5, fill="x", expand=True)
        search_entry.bind("<Return>", lambda e: self._refresh_grid())

        # 属性筛选
        filter_frame = ttk.Frame(top_frame)
        filter_frame.pack(fill="x")
        self._filter_buttons: List[tk.Label] = []
        ICON_SIZE = 24
        s = self.app._get_scheme()
        for attr_id in range(7):
            icon_path = ATTR_ICON_DIR / f"{ATTR_ICON_MAP[attr_id]}.png"
            try:
                photo = tk.PhotoImage(file=str(icon_path))
                if photo.width() > ICON_SIZE:
                    photo = photo.subsample(photo.width() // ICON_SIZE, photo.width() // ICON_SIZE)
            except Exception:
                photo = None

            btn = tk.Label(filter_frame, image=photo, cursor="hand2", bd=0, highlightthickness=0, bg=s["surface"])
            btn.pack(side=tk.LEFT, padx=1)
            btn.image = photo
            btn.bind("<Button-1>", lambda e, aid=attr_id: self._apply_filter(aid))
            self._filter_buttons.append(btn)

        self._update_filter_highlight()

        # ── 中部：网格视图 ──
        grid_frame = ttk.Frame(self)
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self._canvas = tk.Canvas(grid_frame, bg=s["bg"], highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(grid_frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid_inner = tk.Frame(self._canvas, bg=s["surface"])
        self._canvas_window = self._canvas.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind("<Configure>",
                              lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        def _bind_mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _enter(e):
            self._canvas.bind_all("<MouseWheel>", _bind_mw)

        def _leave(e):
            self._canvas.unbind_all("<MouseWheel>")

        self._canvas.bind("<Enter>", _enter)
        self._canvas.bind("<Leave>", _leave)

        # ── 底部：取消按钮 ──
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="取消", command=self._on_close, width=10).pack()

        self._refresh_grid()

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _apply_filter(self, attr_id):
        self._current_filter = attr_id
        self._update_filter_highlight()
        self._refresh_grid()
        # 切换筛选后滚动到顶部
        self._canvas.yview_moveto(0)

    def _update_filter_highlight(self):
        s = self.app._get_scheme()
        for i, btn in enumerate(self._filter_buttons):
            if i == self._current_filter:
                btn.config(bd=2, relief="sunken", bg=s["accent"])
            else:
                btn.config(bd=0, relief="raised", bg=s["surface"])

    def _get_filtered_ids(self):
        """获取过滤后的角色ID列表（包含自定义木桩）"""
        search_text = self._search_var.get().strip().lower()
        result = []
        for cid in self.app.char_ids:
            char = self.app.data_loader.get_character_by_id(cid)
            if not char:
                continue
            if self._current_filter != 0 and char.attribute != self._current_filter:
                continue
            if search_text:
                char_name = self.app.format_char_name(char).lower()
                if search_text not in str(cid) and search_text not in char_name:
                    continue
            result.append(cid)
        # 追加自定义木桩（属性筛选为"全部"或木桩属性匹配时显示）
        for cid, char_data in self.app.data_loader.get_all_custom_dummies().items():
            if self._current_filter != 0 and char_data.attribute != self._current_filter:
                continue
            if search_text:
                dummy_name = char_data.name.lower()
                if search_text not in str(cid) and search_text not in dummy_name:
                    continue
            result.append(cid)
        return result

    def _load_thumb(self, cid):
        """加载缩略图（缓存）"""
        if cid in self._thumb_cache:
            return self._thumb_cache[cid]
        from PIL import Image, ImageTk
        THUMB_W, THUMB_H = 70, 90
        avatar_path = AVATAR_DIR / f"{cid}.png"
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            pil_img = pil_img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
            photo = ImageTk.PhotoImage(pil_img)
            self._thumb_cache[cid] = photo
            return photo
        except Exception:
            return None

    def _refresh_grid(self):
        """刷新网格视图"""
        self._filtered_ids = self._get_filtered_ids()
        for child in self._grid_inner.winfo_children():
            child.destroy()

        COLS = 6
        PAD = 2
        s = self.app._get_scheme()

        for i, cid in enumerate(self._filtered_ids):
            char = self.app.data_loader.get_character_by_id(cid)
            if not char:
                continue
            row, col = divmod(i, COLS)
            card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                            highlightbackground=s["border"], highlightthickness=2,
                            cursor="hand2")
            card.grid(row=row, column=col, padx=PAD, pady=PAD)

            photo = self._load_thumb(cid)
            if photo:
                avatar_label = tk.Label(card, image=photo, bg=s["surface"], bd=0)
                avatar_label.image = photo
                avatar_label.pack()
            else:
                # 木桩等无头像角色显示名称占位
                is_dummy = cid < 0
                if is_dummy:
                    placeholder_text = "木桩"
                elif self.app.is_developer_mode():
                    placeholder_text = f"[{cid}]"
                else:
                    placeholder_text = "???"
                placeholder = tk.Label(card, text=placeholder_text, bg=s["surface"], fg=s["border"],
                                       width=10, height=6, font=("Microsoft YaHei UI", 8))
                placeholder.pack()

            name = self.app.format_char_name(char)
            if len(name) > 12:
                name = name[:11] + "…"
            # 木桩名称前加标记
            if cid < 0:
                name = "▣ " + name
            name_label = tk.Label(card, text=name, bg=s["surface"], fg=s["fg"],
                                  font=("Microsoft YaHei UI", 8), wraplength=90,
                                  height=2, justify="center")
            name_label.pack(pady=(2, 0))

            for widget in [card] + list(card.winfo_children()):
                widget.bind("<Button-1>", lambda e, c=cid: self._on_select(c))

        # 每列均分权重，使每行内容居中
        for c in range(COLS):
            self._grid_inner.grid_columnconfigure(c, weight=1, uniform="col")

    def _on_select(self, cid):
        self.result = cid
        self.destroy()

    def _on_close(self):
        self.result = None
        self.destroy()


# ────────────────────────────── 编队与战斗 Tab ──────────────────────────────


class TeamBattleTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.friend_slots: List[Dict[str, Any]] = []  # {cid, frame, avatar_label, name_label, clear_btn}
        self.enemy_slots: List[Dict[str, Any]] = []
        self.mem_options = ["(空)"] + self._build_memory_options()
        self._build_char_options()
        self._build()

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

    def _build_mem_slot(self, parent, slot_idx, is_enemy):
        """构建单个回忆卡槽位（缩略图 + 右上角覆盖清除按钮，无文字）"""
        CARD_W, CARD_H = 120, 68  # 16:9 缩略图（1.5倍原尺寸）
        s = self.app._get_scheme()

        slot_frame = tk.Frame(parent, bg=s["bg"], bd=0, relief="flat",
                              highlightbackground=s["border"], highlightthickness=1,
                              cursor="hand2")

        # 缩略图画布
        card_canvas = tk.Canvas(slot_frame, width=CARD_W, height=CARD_H,
                                bg=s["bg"], highlightthickness=0)
        card_canvas.pack(padx=2, pady=2)
        card_canvas._card_photo = None
        # 初始占位文字
        card_canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                fill=s["border"], font=("Microsoft YaHei UI", 8))

        # 右上角覆盖清除按钮（默认隐藏，选中后显示）
        clear_btn = tk.Label(slot_frame, text="\u00d7", fg="white", bg="#cc3333",
                              font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2",
                              padx=3, pady=0, bd=0)
        clear_btn.bind("<Button-1>", lambda e, idx=slot_idx, ie=is_enemy: self._clear_mem_slot(idx, ie))

        # 点击打开选择弹窗（clear_btn 单独绑定清除，不在此列）
        for widget in [slot_frame, card_canvas]:
            widget.bind("<Button-1>", lambda e, idx=slot_idx, ie=is_enemy: self._open_mem_picker(idx, ie))

        return {"mid": None, "frame": slot_frame, "canvas": card_canvas,
                "name_label": None, "clear_btn": clear_btn,
                "slot_idx": slot_idx, "is_enemy": is_enemy}

    def _open_mem_picker(self, slot_idx, is_enemy):
        """打开回忆卡选择弹窗"""
        slots = self.mem_enemy_slots if is_enemy else self.mem_friend_slots
        # 已选的回忆卡ID排除（避免重复选择）
        exclude = set()
        for s in slots:
            if s["mid"] is not None:
                exclude.add(s["mid"])
        # 当前槽位的不排除（允许换选）
        current_mid = slots[slot_idx]["mid"]
        exclude.discard(current_mid)

        dlg = MemoryPickerDialog(self, self.app, title="选择回忆卡", exclude_ids=exclude)
        self.wait_window(dlg)
        if dlg.result is not None:
            self._set_mem_slot(slot_idx, is_enemy, dlg.result)

    def _set_mem_slot(self, slot_idx, is_enemy, mid):
        """设置回忆卡槽位内容"""
        CARD_W, CARD_H = 120, 68
        s = self.app._get_scheme()
        slots = self.mem_enemy_slots if is_enemy else self.mem_friend_slots
        slot = slots[slot_idx]
        slot["mid"] = mid
        canvas = slot["canvas"]
        clear_btn = slot["clear_btn"]

        # 加载缩略图（用PIL缩放到120x68）
        card_path = MEMORY_CARD_DIR / f"{mid}.png"
        if card_path.exists():
            try:
                from PIL import Image, ImageTk
                pil_img = Image.open(card_path)
                pil_img = pil_img.resize((CARD_W, CARD_H), Image.LANCZOS)
                photo = ImageTk.PhotoImage(pil_img)
                canvas.delete("all")
                canvas.create_image(CARD_W // 2, CARD_H // 2, image=photo, anchor="center")
                canvas._card_photo = photo
            except Exception:
                canvas.delete("all")
                canvas.create_text(CARD_W // 2, CARD_H // 2, text=f"[{mid}]",
                                   fill=s["fg"], font=("Microsoft YaHei UI", 8))
        else:
            canvas.delete("all")
            canvas.create_text(CARD_W // 2, CARD_H // 2, text=f"[{mid}]",
                               fill=s["fg"], font=("Microsoft YaHei UI", 8))

        # 显示右上角覆盖清除按钮
        clear_btn.place(relx=1.0, x=-3, y=3, anchor="ne", in_=canvas)
        clear_btn.lift()

    def _clear_mem_slot(self, slot_idx, is_enemy):
        """清空回忆卡槽位"""
        s = self.app._get_scheme()
        slots = self.mem_enemy_slots if is_enemy else self.mem_friend_slots
        slot = slots[slot_idx]
        slot["mid"] = None
        canvas = slot["canvas"]
        clear_btn = slot["clear_btn"]
        CARD_W, CARD_H = 120, 68

        canvas.delete("all")
        canvas._card_photo = None
        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                           fill=s["border"], font=("Microsoft YaHei UI", 8))
        clear_btn.place_forget()

    def _build_slot(self, parent, slot_idx, is_enemy):
        """构建单个编队槽位（横版头像 300:144 比例，画布填满内框）"""
        BANNER_W, BANNER_H = 154, 76  # 填满外框内可用空间（164-10pad × 剩余高度）
        s = self.app._get_scheme()

        slot_frame = tk.Frame(parent, bg=s["bg"])

        # 横版头像区域（使用Canvas实现像素精确显示）
        avatar_canvas = tk.Canvas(slot_frame, width=BANNER_W, height=BANNER_H,
                                   bg=s["bg"], highlightthickness=0,
                                   cursor="hand2")
        avatar_canvas.pack()
        avatar_canvas._banner_photo = None

        # 角色名（两行显示空间，确保完整显示，初始不pack，选中角色后显示）
        name_label = tk.Label(slot_frame, text="", bg=s["bg"], fg=s["fg"],
                               font=("Microsoft YaHei UI", 8), wraplength=BANNER_W,
                               justify="center", height=2)

        # 拖拽绑定（点击后未移动则打开选择弹窗，移动则拖拽）
        for widget in [slot_frame, avatar_canvas, name_label]:
            widget.bind("<ButtonPress-1>", lambda e, s=slot_idx, ie=is_enemy: self._on_drag_start(e, s, ie))
            widget.bind("<B1-Motion>", lambda e, s=slot_idx, ie=is_enemy: self._on_drag_motion(e, s, ie))
            widget.bind("<ButtonRelease-1>", lambda e, s=slot_idx, ie=is_enemy: self._on_drag_release(e, s, ie))

        return {"cid": None, "enemy_data": None, "frame": slot_frame, "avatar_label": avatar_canvas,
                "name_label": name_label, "clear_btn": None,
                "slot_idx": slot_idx, "is_enemy": is_enemy}

    def _on_drag_start(self, event, slot_idx, is_enemy):
        """开始拖拽"""
        slots = self.enemy_slots if is_enemy else self.friend_slots
        source_slot = slots[slot_idx]
        has_content = source_slot["cid"] is not None or source_slot.get("enemy_data") is not None
        self._drag_source = {"slot_idx": slot_idx, "is_enemy": is_enemy,
                              "has_char": has_content}
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_moved = False

        if has_content:
            # 创建拖拽预览窗口
            preview = tk.Toplevel(self)
            preview.overrideredirect(True)
            preview.attributes("-topmost", True)
            preview.attributes("-alpha", 0.7)
            preview_label = tk.Label(preview, text="拖拽中...", bg=_DARK_ACCENT, fg="#1e1e2e",
                                      font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=5)
            preview_label.pack()
            self._drag_preview = preview
        else:
            self._drag_preview = None

    def _on_drag_motion(self, event, slot_idx, is_enemy):
        """拖拽移动"""
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return
        dx = abs(event.x_root - self._drag_start_x)
        dy = abs(event.y_root - self._drag_start_y)
        if dx < 5 and dy < 5:
            return
        self._drag_moved = True
        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.geometry(f"+{event.x_root + 15}+{event.y_root + 15}")

    def _on_drag_release(self, event, slot_idx, is_enemy):
        """释放拖拽"""
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return

        # 清理预览
        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.destroy()
            self._drag_preview = None

        src = self._drag_source
        self._drag_source = None

        if not src["has_char"] or not self._drag_moved:
            # 空槽位点击或没移动 → 打开选择弹窗
            self._open_char_picker(src["slot_idx"], src["is_enemy"])
            return

        # 查找目标槽位
        target_widget = self.winfo_containing(event.x_root, event.y_root)
        if target_widget is None:
            return

        # 向上查找槽位frame
        target_slot = None
        found_slots = None
        found_is_enemy = None
        found_idx = None
        widget = target_widget
        while widget is not None:
            for slots_list, ie in [(self.friend_slots, False), (self.enemy_slots, True)]:
                for idx, slot in enumerate(slots_list):
                    if widget is slot["frame"]:
                        target_slot = slot
                        found_slots = slots_list
                        found_is_enemy = ie
                        found_idx = idx
                        break
                if target_slot:
                    break
            if target_slot:
                break
            widget = widget.master

        if target_slot is None:
            return

        # 只能同阵营拖拽
        if src["is_enemy"] != found_is_enemy:
            return

        src_slots = self.enemy_slots if src["is_enemy"] else self.friend_slots
        src_slot = src_slots[src["slot_idx"]]
        src_cid = src_slot["cid"]
        src_ed = src_slot.get("enemy_data")
        dst_cid = target_slot["cid"]
        dst_ed = target_slot.get("enemy_data")

        if src["slot_idx"] == found_idx:
            return

        # 互换 (同时交换 cid 和 enemy_data, 二者互斥)
        if src_ed is not None:
            self._set_slot_circle_enemy(target_slot, src_ed)
        else:
            self._set_slot_char(target_slot, src_cid)
        if dst_ed is not None:
            self._set_slot_circle_enemy(src_slot, dst_ed)
        elif dst_cid is not None:
            self._set_slot_char(src_slot, dst_cid)
        else:
            self._clear_slot(src_slot)

    def _open_char_picker(self, slot_idx, is_enemy):
        """打开角色选择弹窗"""
        dialog = CharacterPickerDialog(self, self.app, title="选择角色")
        self.wait_window(dialog)
        if dialog.result is not None:
            slots = self.enemy_slots if is_enemy else self.friend_slots
            slot = slots[slot_idx]
            self._set_slot_char(slot, dialog.result)

    def _clear_slot_by_idx(self, slot_idx, is_enemy):
        """通过索引清除槽位"""
        slots = self.enemy_slots if is_enemy else self.friend_slots
        self._clear_slot(slots[slot_idx])

    def _set_slot_char(self, slot, cid):
        """设置槽位角色"""
        slot["cid"] = cid
        slot["enemy_data"] = None
        self._update_slot_display(slot, cid)

    def _set_slot_circle_enemy(self, slot, enemy_data):
        """设置槽位为对抗压制战敌方"""
        slot["cid"] = None
        slot["enemy_data"] = enemy_data
        self._update_slot_display(slot, None)

    def _clear_slot(self, slot):
        """清除槽位"""
        slot["cid"] = None
        slot["enemy_data"] = None
        self._update_slot_display(slot, None)

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

    def _set_clear_btn_visible(self, slot, visible):
        """控制槽位清除按钮的显示/隐藏"""
        clear_btn = slot.get("clear_btn")
        if clear_btn is None:
            return
        if visible:
            try:
                clear_btn.grid()
            except Exception:
                pass
        else:
            try:
                clear_btn.grid_remove()
            except Exception:
                pass

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
        self.progress_var = tk.StringVar(value="")
        ttk.Label(ctrl_frame, textvariable=self.progress_var).pack(side=tk.LEFT, padx=10)

        # ── 结果输出 ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self._result_panel = ResultTablePanel(right_frame, self.app, title="模拟结果")
        self._result_panel.pack(fill=tk.BOTH, expand=True)

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

    @staticmethod
    def _parse_memory_card_id(entry: str) -> Optional[int]:
        if not entry:
            return None
        import re
        m = re.match(r'\[(\d+)\]', entry)
        if m:
            return int(m.group(1))
        return None

    def _build_memory_cards(self, mem_entries: list) -> list:
        cards = []
        for entry in mem_entries:
            card_id = self._parse_memory_card_id(entry)
            if card_id is None:
                continue
            memory_data = self.app.data_loader.get_memory(card_id)
            if not memory_data:
                continue
            highlights = [
                MemoryHighlight(
                    character_attribute=hl.character_attribute,
                    character_base_master_id=hl.character_base_master_id,
                    character_master_id=hl.character_master_id,
                    character_role=hl.character_role,
                    character_team_master_id=hl.character_team_master_id,
                    character_type=hl.character_type,
                    is_targeting_friendly_party=hl.is_targeting_friendly_party,
                    party_position=hl.party_position,
                    skill_master_id=hl.skill_master_id,
                )
                for hl in memory_data.highlights
            ]
            cards.append(MemoryCard(
                card_id=card_id,
                name=memory_data.name,
                description=memory_data.description,
                rarity=memory_data.rarity,
                highlights=highlights,
            ))
        return cards

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
        }

    @staticmethod
    def _make_battle_config(max_turns):
        cfg = BattleConfig()
        cfg.max_turns = max_turns
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
                                      config=self._make_battle_config(max_turns),
                                      narrative=narrative)
            result = controller.execute_battle()

            log_dir = _BASE_PATH / "data" / "battle_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"battle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            narrative.write(str(log_path))

            winner_text = "胜利" if result['winner'] == 'FRIEND' else ("败北" if result['winner'] == 'ENEMY' else "超时")
            self.app.root.after(0, lambda: self._display_single_result(result, winner_text, str(log_path)))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_single_result(self, result, winner_text, log_path):
        self.start_btn.config(state="normal")
        self.log_btn.config(state="normal")
        self.progress_var.set("完成!")
        self._result_panel.clear()
        out = []
        out.append("=" * 60)
        out.append(f"  单次模拟结果: {winner_text}")
        out.append(f"  回合数: {result['total_turns']}")
        out.append(f"  日志文件: {log_path}")
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

        self._result_panel.set_summary("\n".join(out))
        if tables:
            self._result_panel.set_tables(tables)

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
                        self._set_mem_slot(i, False, mid)
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
                        self._set_mem_slot(i, False, mid)
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
                        self._set_mem_slot(i, True, mid)
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
                        self._set_mem_slot(i, True, mid)
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


# ────────────────────────────── 逐步暴击 Tab ──────────────────────────────


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
        # Canvas 引用（用于滚动）
        self._left_canvas = None
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

            self._interactive_controller = controller
            self._interactive_narrative = narrative

            result = controller.execute_battle()

            # 清除覆盖
            controller.damage_service.clear_crit_override()
            controller.skill_service.clear_branch_override()

            return result

        self._simulator.start_interactive_battle(battle_func)
        self._start_polling()

    def _save_sequence(self):
        """保存当前暴击序列到文件"""
        if not self._simulator:
            return

        seq_str = self._simulator.generate_sequence_string()
        if not seq_str:
            messagebox.showinfo("保存序列", "当前没有决策记录")
            return

        # 弹出输入框让用户命名
        from tkinter import simpledialog
        name = simpledialog.askstring("保存序列", "请输入序列名称:", parent=self)
        if not name:
            return

        # 保存到文件
        seq_dir = _BASE_PATH / "data" / "crit_sequences"
        seq_dir.mkdir(parents=True, exist_ok=True)
        seq_path = seq_dir / f"{name}.txt"

        # 同时保存编队信息（如果有）
        save_data = {
            "sequence": seq_str,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "decision_count": len(self._simulator.get_decision_points()),
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
        messagebox.showinfo("保存序列", f"序列已保存到: {name}\n序列: {seq_str}")

    def _load_sequence(self):
        """从文件加载暴击序列"""
        seq_dir = _BASE_PATH / "data" / "crit_sequences"
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

        info = f"已加载序列: {selected_file.stem}\n序列: {seq_str}"
        if "friends" in data:
            info += f"\n己方: {data['friends']}"
        self._append_output(info + "\n")
        messagebox.showinfo("加载序列", info)

    def _delete_sequence(self):
        """删除已保存的暴击序列"""
        seq_dir = _BASE_PATH / "data" / "crit_sequences"
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

            result = controller.execute_battle()

            # 清除覆盖
            controller.damage_service.clear_crit_override()
            controller.skill_service.clear_branch_override()

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

        self.crit_btn.config(state="normal")
        self.no_crit_btn.config(state="normal")
        self.stop_btn.config(state="normal")
        self.undo_btn.config(state="disabled")  # 预填阶段禁用回退
        self.save_seq_btn.config(state="disabled")
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

            self._interactive_controller = controller
            self._interactive_narrative = narrative

            result = controller.execute_battle()

            # 清除覆盖
            controller.damage_service.clear_crit_override()
            controller.skill_service.clear_branch_override()

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
                    info_text = (
                        f"[#{bp.index:03d}] {bp.caster_name} - {bp.skill_name} (ID:{bp.skill_id})\n"
                        f"  分组: group={bp.group_id}"
                    )
                    self.branch_decision_label.config(text=info_text)
                    self._show_branch_candidates(bp)
                    self._append_output(f"\n[#{bp.index:03d}] 分支决策: {bp.caster_name} - {bp.skill_name} "
                                        f"(group={bp.group_id}, {len(bp.candidates)}个候选)\n", scroll=False)
                    # 禁用暴击按钮，强制用户先完成分支选择
                    self.crit_btn.config(state="disabled")
                    self.no_crit_btn.config(state="disabled")

                elif event_type == "branch_prefill_step":
                    # 预填分支选择已执行
                    bp = data
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

    def _append_output(self, text: str, scroll: bool = True):
        """向输出区域追加文本"""
        self.output_text.config(state="normal")
        self.output_text.insert(tk.END, text)
        if scroll:
            self.output_text.see(tk.END)
        self.output_text.config(state="disabled")


# ────────────────────────────── 战术演习 Tab ──────────────────────────────


class TacticalExerciseTab(ttk.Frame):
    """战术演习模式 - 单体敌方无限复活，阶段递增"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._enemy_data: Dict[int, Dict] = self.app.data_loader.get_tactical_exercise_enemies()
        self.friend_slots: List[Dict[str, Any]] = []
        self.mem_friend_slots: List[Dict[str, Any]] = []
        self._drag_source = None
        self._drag_preview = None
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

    # ── 己方可视化编队方法 ──

    def _build_slot(self, parent, slot_idx):
        """构建单个编队槽位（横版头像 300:144 比例）"""
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

        for widget in [slot_frame, avatar_canvas, name_label]:
            widget.bind("<ButtonPress-1>", lambda e, s=slot_idx: self._on_drag_start(e, s))
            widget.bind("<B1-Motion>", lambda e, s=slot_idx: self._on_drag_motion(e, s))
            widget.bind("<ButtonRelease-1>", lambda e, s=slot_idx: self._on_drag_release(e, s))

        return {"cid": None, "frame": slot_frame, "avatar_label": avatar_canvas,
                "name_label": name_label, "clear_btn": None,
                "slot_idx": slot_idx}

    def _build_mem_slot(self, parent, slot_idx):
        """构建单个回忆卡槽位（缩略图 + 右上角覆盖清除按钮，无文字）"""
        CARD_W, CARD_H = 120, 68  # 16:9 缩略图（1.5倍原尺寸）
        s = self.app._get_scheme()

        slot_frame = tk.Frame(parent, bg=s["bg"], bd=0, relief="flat",
                              highlightbackground=s["border"], highlightthickness=1,
                              cursor="hand2")

        # 缩略图画布
        card_canvas = tk.Canvas(slot_frame, width=CARD_W, height=CARD_H,
                                bg=s["bg"], highlightthickness=0)
        card_canvas.pack(padx=2, pady=2)
        card_canvas._card_photo = None
        # 初始占位文字
        card_canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                fill=s["border"], font=("Microsoft YaHei UI", 8))

        # 右上角覆盖清除按钮（默认隐藏，选中后显示）
        clear_btn = tk.Label(slot_frame, text="\u00d7", fg="white", bg="#cc3333",
                              font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2",
                              padx=3, pady=0, bd=0)
        clear_btn.bind("<Button-1>", lambda e, idx=slot_idx: self._clear_mem_slot(idx))

        # 点击打开选择弹窗（clear_btn 单独绑定清除，不在此列）
        for widget in [slot_frame, card_canvas]:
            widget.bind("<Button-1>", lambda e, idx=slot_idx: self._open_mem_picker(idx))

        return {"mid": None, "frame": slot_frame, "canvas": card_canvas,
                "name_label": None, "clear_btn": clear_btn,
                "slot_idx": slot_idx}

    def _on_drag_start(self, event, slot_idx):
        source_slot = self.friend_slots[slot_idx]
        self._drag_source = {"slot_idx": slot_idx,
                              "has_char": source_slot["cid"] is not None}
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_moved = False

        if source_slot["cid"] is not None:
            preview = tk.Toplevel(self)
            preview.overrideredirect(True)
            preview.attributes("-topmost", True)
            preview.attributes("-alpha", 0.7)
            preview_label = tk.Label(preview, text="拖拽中...", bg=_DARK_ACCENT, fg="#1e1e2e",
                                      font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=5)
            preview_label.pack()
            self._drag_preview = preview
        else:
            self._drag_preview = None

    def _on_drag_motion(self, event, slot_idx):
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return
        dx = abs(event.x_root - self._drag_start_x)
        dy = abs(event.y_root - self._drag_start_y)
        if dx < 5 and dy < 5:
            return
        self._drag_moved = True
        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.geometry(f"+{event.x_root + 15}+{event.y_root + 15}")

    def _on_drag_release(self, event, slot_idx):
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return

        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.destroy()
            self._drag_preview = None

        src = self._drag_source
        self._drag_source = None

        if not src["has_char"] or not self._drag_moved:
            self._open_char_picker(src["slot_idx"])
            return

        target_widget = self.winfo_containing(event.x_root, event.y_root)
        if target_widget is None:
            return

        target_slot = None
        found_idx = None
        widget = target_widget
        while widget is not None:
            for idx, slot in enumerate(self.friend_slots):
                if widget is slot["frame"]:
                    target_slot = slot
                    found_idx = idx
                    break
            if target_slot:
                break
            widget = widget.master

        if target_slot is None:
            return

        src_slot = self.friend_slots[src["slot_idx"]]
        src_cid = src_slot["cid"]
        dst_cid = target_slot["cid"]

        if src["slot_idx"] == found_idx:
            return

        if dst_cid is not None:
            self._set_slot_char(target_slot, src_cid)
            self._set_slot_char(src_slot, dst_cid)
        else:
            self._set_slot_char(target_slot, src_cid)
            self._clear_slot(src_slot)

    def _open_char_picker(self, slot_idx):
        dialog = CharacterPickerDialog(self, self.app, title="选择角色")
        self.wait_window(dialog)
        if dialog.result is not None:
            slot = self.friend_slots[slot_idx]
            self._set_slot_char(slot, dialog.result)

    def _open_mem_picker(self, slot_idx):
        exclude = set()
        for s in self.mem_friend_slots:
            if s["mid"] is not None:
                exclude.add(s["mid"])
        current_mid = self.mem_friend_slots[slot_idx]["mid"]
        exclude.discard(current_mid)

        dlg = MemoryPickerDialog(self, self.app, title="选择回忆卡", exclude_ids=exclude)
        self.wait_window(dlg)
        if dlg.result is not None:
            self._set_mem_slot(slot_idx, dlg.result)

    def _set_slot_char(self, slot, cid):
        slot["cid"] = cid
        self._update_slot_display(slot, cid)

    def _clear_slot(self, slot):
        slot["cid"] = None
        self._update_slot_display(slot, None)

    def _clear_slot_by_idx(self, slot_idx):
        self._clear_slot(self.friend_slots[slot_idx])

    def _update_slot_display(self, slot, cid):
        canvas = slot["avatar_label"]
        name_label = slot["name_label"]
        s = self.app._get_scheme()
        BANNER_W, BANNER_H = 154, 76

        canvas.delete("all")
        canvas.config(bg=s["bg"])
        canvas._banner_photo = None

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
            name_label.pack(pady=(1, 0))
            self._set_clear_btn_visible(slot, True)

    def _set_clear_btn_visible(self, slot, visible):
        clear_btn = slot.get("clear_btn")
        if clear_btn is None:
            return
        if visible:
            try:
                clear_btn.grid()
            except Exception:
                pass
        else:
            try:
                clear_btn.grid_remove()
            except Exception:
                pass

    def _load_slot_avatar(self, cid):
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
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            w, h = pil_img.size
            crop_h = int(w * BANNER_H / BANNER_W)
            if crop_h > h:
                crop_h = h
            top = (h - crop_h) // 2
            pil_img = pil_img.crop((0, top, w, top + crop_h))
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

    def _set_mem_slot(self, slot_idx, mid):
        CARD_W, CARD_H = 120, 68
        s = self.app._get_scheme()
        slot = self.mem_friend_slots[slot_idx]
        slot["mid"] = mid
        canvas = slot["canvas"]
        clear_btn = slot["clear_btn"]

        card_path = MEMORY_CARD_DIR / f"{mid}.png"
        if card_path.exists():
            try:
                from PIL import Image, ImageTk
                pil_img = Image.open(card_path)
                pil_img = pil_img.resize((CARD_W, CARD_H), Image.LANCZOS)
                photo = ImageTk.PhotoImage(pil_img)
                canvas.delete("all")
                canvas.create_image(CARD_W // 2, CARD_H // 2, image=photo, anchor="center")
                canvas._card_photo = photo
            except Exception:
                canvas.delete("all")
                canvas.create_text(CARD_W // 2, CARD_H // 2, text=f"[{mid}]",
                                   fill=s["fg"], font=("Microsoft YaHei UI", 8))
        else:
            canvas.delete("all")
            canvas.create_text(CARD_W // 2, CARD_H // 2, text=f"[{mid}]",
                               fill=s["fg"], font=("Microsoft YaHei UI", 8))

        # 显示右上角覆盖清除按钮
        clear_btn.place(relx=1.0, x=-3, y=3, anchor="ne", in_=canvas)
        clear_btn.lift()

    def _clear_mem_slot(self, slot_idx):
        s = self.app._get_scheme()
        slot = self.mem_friend_slots[slot_idx]
        slot["mid"] = None
        canvas = slot["canvas"]
        clear_btn = slot["clear_btn"]
        CARD_W, CARD_H = 120, 68

        canvas.delete("all")
        canvas._card_photo = None
        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                           fill=s["border"], font=("Microsoft YaHei UI", 8))
        clear_btn.place_forget()

    @staticmethod
    def _parse_memory_card_id(entry: str) -> Optional[int]:
        if not entry:
            return None
        import re
        m = re.match(r'\[(\d+)\]', entry)
        if m:
            return int(m.group(1))
        return None

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

            self.app.root.after(0, lambda: self._display_single_result(
                winner_text, stages, turns, str(log_path), score_data))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_single_result(self, winner_text, stages, turns, log_path, score_data=None):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        self._progress_var.set("完成!")
        self._result_panel.clear()
        out = []
        out.append("=" * 60)
        out.append(f"  战术演习结果: {winner_text}")
        out.append(f"  清除阶段数: {stages}")
        out.append(f"  总回合数: {turns}")
        out.append(f"  日志文件: {log_path}")
        out.append("=" * 60)

        tables = []
        if score_data:
            self._append_score_display(out, score_data, tables)

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
            # 角色明细用 Treeview 表格呈现
            columns = ["角色", "造成伤害", "受到伤害", "提供回复"]
            col_widths = [135, 120, 120, 120]
            col_aligns = ["w", "e", "e", "e"]

            if ally_units:
                ally_rows = []
                for uid, s in ally_units.items():
                    name = s.get("name", uid)[:18]
                    ally_rows.append([name,
                                      f"{s.get('damage_dealt', 0):,}",
                                      f"{s.get('damage_received', 0):,}",
                                      f"{s.get('hp_healed', 0):,}"])
                tables.append({"title": "我方角色明细", "columns": columns,
                               "rows": ally_rows, "col_widths": col_widths,
                               "col_aligns": col_aligns})

            if enemy_units:
                enemy_rows = []
                for uid, s in enemy_units.items():
                    name = s.get("name", uid)[:18]
                    enemy_rows.append([name,
                                       f"{s.get('damage_dealt', 0):,}",
                                       f"{s.get('damage_received', 0):,}",
                                       f"{s.get('hp_healed', 0):,}"])
                tables.append({"title": "敌方角色明细", "columns": columns,
                               "rows": enemy_rows, "col_widths": col_widths,
                               "col_aligns": col_aligns})
        else:
            # 回退：以文本形式输出角色明细
            if ally_units:
                out.append(f"  【我方角色明细】")
                out.append(f"    {_cjk_fit('角色', 20)} {'造成伤害':>12} {'受到伤害':>12} {'提供回复':>12}")
                for uid, s in ally_units.items():
                    name = s.get("name", uid)[:18]
                    out.append(f"    {_cjk_fit(name, 20)} {s['damage_dealt']:>12,} {s['damage_received']:>12,} {s['hp_healed']:>12,}")

            if enemy_units:
                out.append(f"")
                out.append(f"  【敌方角色明细】")
                out.append(f"    {_cjk_fit('角色', 20)} {'造成伤害':>12} {'受到伤害':>12} {'提供回复':>12}")
                for uid, s in enemy_units.items():
                    name = s.get("name", uid)[:18]
                    out.append(f"    {_cjk_fit(name, 20)} {s['damage_dealt']:>12,} {s['damage_received']:>12,} {s['hp_healed']:>12,}")

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

        # 角色明细表格（场均）：聚合 all_unit_stats
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
                                           "damage_dealt": 0, "damage_received": 0, "hp_healed": 0}
                        target[uid]["damage_dealt"] += s.get("damage_dealt", 0)
                        target[uid]["damage_received"] += s.get("damage_received", 0)
                        target[uid]["hp_healed"] += s.get("hp_healed", 0)

                columns = ["角色", "造成伤害", "受到伤害", "提供回复"]
                col_widths = [135, 120, 120, 120]
                col_aligns = ["w", "e", "e", "e"]

                if ally_agg:
                    ally_rows = []
                    for uid, s in ally_agg.items():
                        ally_rows.append([s["name"][:18],
                                          f"{s['damage_dealt'] / n:,.1f}",
                                          f"{s['damage_received'] / n:,.1f}",
                                          f"{s['hp_healed'] / n:,.1f}"])
                    tables.append({"title": "我方角色明细(场均)", "columns": columns,
                                   "rows": ally_rows, "col_widths": col_widths,
                                   "col_aligns": col_aligns})

                if enemy_agg:
                    enemy_rows = []
                    for uid, s in enemy_agg.items():
                        enemy_rows.append([s["name"][:18],
                                           f"{s['damage_dealt'] / n:,.1f}",
                                           f"{s['damage_received'] / n:,.1f}",
                                           f"{s['hp_healed'] / n:,.1f}"])
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


# ────────────────────────────── 对抗压制战 ──────────────────────────────

CIRCLE_PRESET_DIR = _USER_DATA / "circle_presets"
COMPOSITE_PRESET_DIR = _USER_DATA / "composite_presets"


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
                val_str = f"{val:.1f}"
            result = result.replace(f"{{{tag_name}}}", val_str)
        return result

    def _on_close(self):
        self.destroy()


class CircleBattleTab(ttk.Frame):
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

    # ── 己方可视化编队方法（参考TacticalExerciseTab） ──

    def _build_slot(self, parent, slot_idx):
        """构建单个编队槽位（横版头像 300:144 比例）"""
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

        for widget in [slot_frame, avatar_canvas, name_label]:
            widget.bind("<ButtonPress-1>", lambda e, s=slot_idx: self._on_drag_start(e, s))
            widget.bind("<B1-Motion>", lambda e, s=slot_idx: self._on_drag_motion(e, s))
            widget.bind("<ButtonRelease-1>", lambda e, s=slot_idx: self._on_drag_release(e, s))

        return {"cid": None, "frame": slot_frame, "avatar_label": avatar_canvas,
                "name_label": name_label, "clear_btn": None,
                "slot_idx": slot_idx}

    def _build_mem_slot(self, parent, slot_idx):
        """构建单个回忆卡槽位"""
        CARD_W, CARD_H = 120, 68
        s = self.app._get_scheme()

        slot_frame = tk.Frame(parent, bg=s["bg"], bd=0, relief="flat",
                              highlightbackground=s["border"], highlightthickness=1,
                              cursor="hand2")

        card_canvas = tk.Canvas(slot_frame, width=CARD_W, height=CARD_H,
                                bg=s["bg"], highlightthickness=0)
        card_canvas.pack(padx=2, pady=2)
        card_canvas._card_photo = None
        card_canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                fill=s["border"], font=("Microsoft YaHei UI", 8))

        clear_btn = tk.Label(slot_frame, text="\u00d7", fg="white", bg="#cc3333",
                              font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2",
                              padx=3, pady=0, bd=0)
        clear_btn.bind("<Button-1>", lambda e, idx=slot_idx: self._clear_mem_slot(idx))

        for widget in [slot_frame, card_canvas]:
            widget.bind("<Button-1>", lambda e, idx=slot_idx: self._open_mem_picker(idx))

        return {"mid": None, "frame": slot_frame, "canvas": card_canvas,
                "name_label": None, "clear_btn": clear_btn,
                "slot_idx": slot_idx}

    def _on_drag_start(self, event, slot_idx):
        source_slot = self.friend_slots[slot_idx]
        self._drag_source = {"slot_idx": slot_idx,
                              "has_char": source_slot["cid"] is not None}
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_moved = False

        if source_slot["cid"] is not None:
            preview = tk.Toplevel(self)
            preview.overrideredirect(True)
            preview.attributes("-topmost", True)
            preview.attributes("-alpha", 0.7)
            preview_label = tk.Label(preview, text="拖拽中...", bg=_DARK_ACCENT, fg="#1e1e2e",
                                      font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=5)
            preview_label.pack()
            self._drag_preview = preview
        else:
            self._drag_preview = None

    def _on_drag_motion(self, event, slot_idx):
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return
        dx = abs(event.x_root - self._drag_start_x)
        dy = abs(event.y_root - self._drag_start_y)
        if dx < 5 and dy < 5:
            return
        self._drag_moved = True
        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.geometry(f"+{event.x_root + 15}+{event.y_root + 15}")

    def _on_drag_release(self, event, slot_idx):
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return

        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.destroy()
            self._drag_preview = None

        src = self._drag_source
        self._drag_source = None

        if not src["has_char"] or not self._drag_moved:
            self._open_char_picker(src["slot_idx"])
            return

        target_widget = self.winfo_containing(event.x_root, event.y_root)
        if target_widget is None:
            return

        target_slot = None
        found_idx = None
        widget = target_widget
        while widget is not None:
            for idx, slot in enumerate(self.friend_slots):
                if widget is slot["frame"]:
                    target_slot = slot
                    found_idx = idx
                    break
            if target_slot:
                break
            widget = widget.master

        if target_slot is None:
            return

        src_slot = self.friend_slots[src["slot_idx"]]
        src_cid = src_slot["cid"]
        dst_cid = target_slot["cid"]

        if src["slot_idx"] == found_idx:
            return

        if dst_cid is not None:
            self._set_slot_char(target_slot, src_cid)
            self._set_slot_char(src_slot, dst_cid)
        else:
            self._set_slot_char(target_slot, src_cid)
            self._clear_slot(src_slot)

    def _open_char_picker(self, slot_idx):
        dialog = CharacterPickerDialog(self, self.app, title="选择角色")
        self.wait_window(dialog)
        if dialog.result is not None:
            self._set_slot_char(self.friend_slots[slot_idx], dialog.result)

    def _open_mem_picker(self, slot_idx):
        exclude = set()
        for s in self.mem_friend_slots:
            if s["mid"] is not None:
                exclude.add(s["mid"])
        current_mid = self.mem_friend_slots[slot_idx]["mid"]
        exclude.discard(current_mid)

        dlg = MemoryPickerDialog(self, self.app, title="选择回忆卡", exclude_ids=exclude)
        self.wait_window(dlg)
        if dlg.result is not None:
            self._set_mem_slot(slot_idx, dlg.result)

    def _set_slot_char(self, slot, cid):
        slot["cid"] = cid
        self._update_slot_display(slot, cid)

    def _clear_slot(self, slot):
        slot["cid"] = None
        self._update_slot_display(slot, None)

    def _clear_slot_by_idx(self, slot_idx):
        self._clear_slot(self.friend_slots[slot_idx])

    def _update_slot_display(self, slot, cid):
        canvas = slot["avatar_label"]
        name_label = slot["name_label"]
        s = self.app._get_scheme()
        BANNER_W, BANNER_H = 154, 76

        canvas.delete("all")
        canvas.config(bg=s["bg"])
        canvas._banner_photo = None

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
            name_label.pack(pady=(1, 0))
            self._set_clear_btn_visible(slot, True)

    def _set_clear_btn_visible(self, slot, visible):
        clear_btn = slot.get("clear_btn")
        if clear_btn is None:
            return
        if visible:
            try:
                clear_btn.grid()
            except Exception:
                pass
        else:
            try:
                clear_btn.grid_remove()
            except Exception:
                pass

    def _load_slot_avatar(self, cid):
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
        if not avatar_path.exists():
            return None
        try:
            pil_img = Image.open(avatar_path)
            w, h = pil_img.size
            crop_h = int(w * BANNER_H / BANNER_W)
            if crop_h > h:
                crop_h = h
            top = (h - crop_h) // 2
            pil_img = pil_img.crop((0, top, w, top + crop_h))
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

    def _set_mem_slot(self, slot_idx, mid):
        CARD_W, CARD_H = 120, 68
        s = self.app._get_scheme()
        slot = self.mem_friend_slots[slot_idx]
        slot["mid"] = mid
        canvas = slot["canvas"]
        clear_btn = slot["clear_btn"]

        card_path = MEMORY_CARD_DIR / f"{mid}.png"
        if card_path.exists():
            try:
                from PIL import Image, ImageTk
                pil_img = Image.open(card_path)
                pil_img = pil_img.resize((CARD_W, CARD_H), Image.LANCZOS)
                photo = ImageTk.PhotoImage(pil_img)
                canvas.delete("all")
                canvas.create_image(CARD_W // 2, CARD_H // 2, image=photo, anchor="center")
                canvas._card_photo = photo
            except Exception:
                canvas.delete("all")
                canvas.create_text(CARD_W // 2, CARD_H // 2, text=f"[{mid}]",
                                   fill=s["fg"], font=("Microsoft YaHei UI", 8))
        else:
            canvas.delete("all")
            canvas.create_text(CARD_W // 2, CARD_H // 2, text=f"[{mid}]",
                               fill=s["fg"], font=("Microsoft YaHei UI", 8))

        clear_btn.place(relx=1.0, x=-3, y=3, anchor="ne", in_=canvas)
        clear_btn.lift()

    def _clear_mem_slot(self, slot_idx):
        s = self.app._get_scheme()
        slot = self.mem_friend_slots[slot_idx]
        slot["mid"] = None
        canvas = slot["canvas"]
        clear_btn = slot["clear_btn"]
        CARD_W, CARD_H = 120, 68

        canvas.delete("all")
        canvas._card_photo = None
        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                           fill=s["border"], font=("Microsoft YaHei UI", 8))
        clear_btn.place_forget()

    @staticmethod
    def _parse_memory_card_id(entry: str) -> Optional[int]:
        if not entry:
            return None
        import re
        m = re.match(r'\[(\d+)\]', entry)
        if m:
            return int(m.group(1))
        return None

    def _build_memory_cards(self, mem_entries: list) -> list:
        cards = []
        for entry in mem_entries:
            card_id = self._parse_memory_card_id(entry)
            if card_id is None:
                continue
            memory_data = self.app.data_loader.get_memory(card_id)
            if not memory_data:
                continue
            highlights = [
                MemoryHighlight(
                    character_attribute=hl.character_attribute,
                    character_base_master_id=hl.character_base_master_id,
                    character_master_id=hl.character_master_id,
                    character_role=hl.character_role,
                    character_team_master_id=hl.character_team_master_id,
                    character_type=hl.character_type,
                    is_targeting_friendly_party=hl.is_targeting_friendly_party,
                    party_position=hl.party_position,
                    skill_master_id=hl.skill_master_id,
                )
                for hl in memory_data.highlights
            ]
            cards.append(MemoryCard(
                card_id=card_id,
                name=memory_data.name,
                description=memory_data.description,
                rarity=memory_data.rarity,
                highlights=highlights,
            ))
        return cards

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

            self.app.root.after(0, lambda: self._display_single_result(
                winner_text, turns, str(log_path), score_data, sel, stage_data))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_single_result(self, winner_text, turns, log_path, score_data, sel, stage_data):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
        self._progress_var.set("完成!")
        self._result_panel.clear()
        out = []
        out.append("=" * 60)
        out.append(f"  对抗压制战 第{sel['season']}赛季 阶段{sel['stage']}: {winner_text}")
        out.append(f"  总回合数: {turns}")
        out.append(f"  日志文件: {log_path}")
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


# ────────────────────────────── 复合战术演习 ──────────────────────────────


class CompositeTacticExerciseTab(ttk.Frame):
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

    # ── 角色槽位 ──

    def _build_slot(self, parent, slot_idx):
        """构建单个编队槽位"""
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
            widget.bind("<ButtonPress-1>", lambda e, s=slot_idx: self._on_drag_start(e, s))
            widget.bind("<B1-Motion>", lambda e, s=slot_idx: self._on_drag_motion(e, s))
            widget.bind("<ButtonRelease-1>", lambda e, s=slot_idx: self._on_drag_release(e, s))

        return {"cid": None, "frame": slot_frame, "avatar_label": avatar_canvas,
                "name_label": name_label, "clear_btn": None, "slot_idx": slot_idx}

    def _build_mem_slot(self, parent, slot_idx):
        """构建单个回忆卡槽位"""
        CARD_W, CARD_H = 120, 68
        s = self.app._get_scheme()

        slot_frame = tk.Frame(parent, bg=s["bg"], bd=0, relief="flat",
                              highlightbackground=s["border"], highlightthickness=1, cursor="hand2")
        card_canvas = tk.Canvas(slot_frame, width=CARD_W, height=CARD_H,
                                bg=s["bg"], highlightthickness=0)
        card_canvas.pack(padx=2, pady=2)
        card_canvas._card_photo = None
        card_canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                fill=s["border"], font=("Microsoft YaHei UI", 8))

        clear_btn = tk.Label(slot_frame, text="\u00d7", fg="white", bg="#cc3333",
                              font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2",
                              padx=3, pady=0, bd=0)
        clear_btn.bind("<Button-1>", lambda e, idx=slot_idx: self._clear_mem_slot(idx))

        for widget in [slot_frame, card_canvas]:
            widget.bind("<Button-1>", lambda e, idx=slot_idx: self._open_mem_picker(idx))

        return {"mid": None, "frame": slot_frame, "canvas": card_canvas,
                "name_label": None, "clear_btn": clear_btn, "slot_idx": slot_idx}

    def _on_drag_start(self, event, slot_idx):
        team_idx = self._current_team_index
        source_slot = self._teams_slots[team_idx][slot_idx]
        self._drag_source = {"team_idx": team_idx, "slot_idx": slot_idx,
                              "has_char": source_slot["cid"] is not None}
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_moved = False

        if source_slot["cid"] is not None:
            preview = tk.Toplevel(self)
            preview.overrideredirect(True)
            preview.attributes("-topmost", True)
            preview.attributes("-alpha", 0.7)
            preview_label = tk.Label(preview, text="拖拽中...", bg=_DARK_ACCENT, fg="#1e1e2e",
                                      font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=5)
            preview_label.pack()
            self._drag_preview = preview
        else:
            self._drag_preview = None

    def _on_drag_motion(self, event, slot_idx):
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return
        dx = abs(event.x_root - self._drag_start_x)
        dy = abs(event.y_root - self._drag_start_y)
        if dx < 5 and dy < 5:
            return
        self._drag_moved = True
        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.geometry(f"+{event.x_root + 15}+{event.y_root + 15}")

    def _on_drag_release(self, event, slot_idx):
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return

        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.destroy()
            self._drag_preview = None

        src = self._drag_source
        self._drag_source = None

        if not src["has_char"] or not self._drag_moved:
            self._open_char_picker(src["slot_idx"])
            return

        target_widget = self.winfo_containing(event.x_root, event.y_root)
        if target_widget is None:
            return

        team_idx = self._current_team_index
        target_slot = None
        found_idx = None
        widget = target_widget
        while widget is not None:
            for i, slot in enumerate(self._teams_slots[team_idx]):
                if widget is slot["frame"]:
                    target_slot = slot
                    found_idx = i
                    break
            if target_slot:
                break
            widget = widget.master

        if target_slot is None:
            return

        src_slot = self._teams_slots[team_idx][src["slot_idx"]]
        src_cid = src_slot["cid"]
        dst_cid = target_slot["cid"]

        if src["slot_idx"] == found_idx:
            return

        if dst_cid is not None:
            # 先交换数据，避免_update_slot_display时重复惩罚误判
            target_slot["cid"] = src_cid
            src_slot["cid"] = dst_cid
            self._update_slot_display(target_slot, src_cid)
            self._update_slot_display(src_slot, dst_cid)
        else:
            # 先移动数据
            target_slot["cid"] = src_cid
            src_slot["cid"] = None
            self._update_slot_display(target_slot, src_cid)
            self._update_slot_display(src_slot, None)
        self._refresh_team_list()

    def _open_char_picker(self, slot_idx):
        dialog = CharacterPickerDialog(self, self.app, title="选择角色")
        self.wait_window(dialog)
        if dialog.result is not None:
            team_idx = self._current_team_index
            self._set_slot_char(self._teams_slots[team_idx][slot_idx], dialog.result)
            self._refresh_team_list()

    def _open_mem_picker(self, slot_idx):
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

    def _set_slot_char(self, slot, cid):
        slot["cid"] = cid
        self._update_slot_display(slot, cid)

    def _clear_slot(self, slot):
        slot["cid"] = None
        self._update_slot_display(slot, None)

    def _clear_slot_by_idx(self, slot_idx):
        team_idx = self._current_team_index
        self._clear_slot(self._teams_slots[team_idx][slot_idx])
        self._refresh_team_list()

    def _update_slot_display(self, slot, cid):
        canvas = slot["avatar_label"]
        name_label = slot["name_label"]
        s = self.app._get_scheme()
        BANNER_W, BANNER_H = 154, 76

        canvas.delete("all")
        canvas.config(bg=s["bg"])
        canvas._banner_photo = None

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
            name_label.pack(pady=(1, 0))
            self._set_clear_btn_visible(slot, True)

            # 重复角色惩罚：在banner右上角绘制↓50%/↓99%标识
            penalty = self._get_duplicate_penalty(cid)
            if penalty:
                pval = "↓99%" if "99" in penalty else "↓50%"
                px, py = BANNER_W - 26, 11
                canvas.create_rectangle(px - 20, py - 8, px + 20, py + 8,
                                        fill="#cc3333", outline="white", width=1)
                canvas.create_text(px, py, text=pval, fill="white",
                                   font=("Microsoft YaHei UI", 7, "bold"))

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

    def _set_clear_btn_visible(self, slot, visible):
        clear_btn = slot.get("clear_btn")
        if clear_btn is None:
            return
        if visible:
            try:
                clear_btn.grid()
            except Exception:
                pass
        else:
            try:
                clear_btn.grid_remove()
            except Exception:
                pass

    def _load_slot_avatar(self, cid):
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

    # ── 回忆卡槽位 ──

    def _set_mem_slot(self, slot_idx, mid):
        team_idx = self._current_team_index
        slot = self._teams_mem_slots[team_idx][slot_idx]
        slot["mid"] = mid
        self._update_mem_slot_display(slot, mid)

    def _clear_mem_slot(self, slot_idx):
        team_idx = self._current_team_index
        slot = self._teams_mem_slots[team_idx][slot_idx]
        slot["mid"] = None
        self._update_mem_slot_display(slot, None)

    def _update_mem_slot_display(self, slot, mid):
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

    def _build_memory_cards(self, mem_ids: list) -> list:
        """构建回忆卡对象列表"""
        cards = []
        for mid in mem_ids:
            if mid is None:
                continue
            memory_data = self.app.data_loader.get_memory(mid)
            if not memory_data:
                continue
            highlights = [
                MemoryHighlight(
                    character_attribute=hl.character_attribute,
                    character_base_master_id=hl.character_base_master_id,
                    character_master_id=hl.character_master_id,
                    character_role=hl.character_role,
                    character_team_master_id=hl.character_team_master_id,
                    character_type=hl.character_type,
                    is_targeting_friendly_party=hl.is_targeting_friendly_party,
                    party_position=hl.party_position,
                    skill_master_id=hl.skill_master_id,
                )
                for hl in memory_data.highlights
            ]
            cards.append(MemoryCard(
                card_id=mid,
                name=memory_data.name,
                description=memory_data.description,
                rarity=memory_data.rarity,
                highlights=highlights,
            ))
        return cards

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

            self.app.root.after(0, lambda: self._display_single_result(result, str(log_path)))
        except Exception as e:
            import traceback
            err_msg = str(e) + "\n" + traceback.format_exc()
            self.app.root.after(0, lambda msg=err_msg: self._display_error(msg))

    def _display_single_result(self, result, log_path):
        self._start_btn.config(state="normal")
        self._log_btn.config(state="normal")
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


# ────────────────────────────── 主 GUI ──────────────────────────────

class MGGBattleSimulatorGUI:
    def format_char_name(self, char) -> str:
        base_name = None
        if hasattr(char, 'character_base_id') and char.character_base_id:
            base_name = self.data_loader.get_character_base_name(char.character_base_id)
        if base_name:
            return f"【{char.name}】{base_name}"
        return char.name

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Izanami Lab v{__version__}")
        self.root.geometry("1400x960")
        # 设置窗口图标
        _icon_path = get_internal_path() / "icon.ico"
        if not _icon_path.exists():
            _icon_path = _BASE_PATH / "icon.ico"
        if _icon_path.exists():
            self.root.iconbitmap(str(_icon_path))

        # 更新守护进程
        self.update_daemon = UpdateDaemon(
            app_data_dir=str(_BASE_PATH),
            user_data_dir=str(_USER_DATA),
            repository=__repository__,
            current_version=__version__,
            release_url=__release_url__,
            data_loader=None,  # DataLoader 尚未创建，后续设置
        )
        self.update_daemon.set_progress_callback(self._on_update_progress)
        self.update_daemon.set_refresh_callback(self._on_data_refresh)

        # 首次运行：从默认模板复制用户配置
        _ensure_user_config("global_config.default.json", GLOBAL_CONFIG_PATH)
        _ensure_user_config("char_config.default.json", CHAR_CONFIG_PATH)
        _ensure_user_config("ui_config.default.json", UI_CONFIG_PATH)
        PRESET_DIR.mkdir(parents=True, exist_ok=True)
        TACTICAL_PRESET_DIR.mkdir(parents=True, exist_ok=True)

        # 加载外观配置
        self._ui_config = self._load_ui_config()
        self._current_scheme = self._resolve_scheme(self._ui_config.get("theme", "深色"))

        self.root.configure(bg=self._get_scheme()["bg"])
        self._apply_window_style()
        self._apply_ttk_style()

        self.data_loader = DataLoader(base_path=str(_BASE_PATH), user_data_dir=str(_USER_DATA))
        self.data_loader.load_all()
        self.data_loader.load_custom_dummies()

        # 设置 UpdateDaemon 的 DataLoader 引用
        self.update_daemon._patch_engine._data_loader = self.data_loader

        chars_data = self.data_loader.load_characters()
        self.char_ids = sorted([int(k) for k in chars_data.keys()])
        self.char_config = {cid: {"override": False} for cid in self.char_ids}
        self._load_char_config()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.global_tab = GlobalParamsTab(self.notebook, self)
        self.char_tab = CharacterParamsTab(self.notebook, self)
        self.dummy_tab = CustomDummyTab(self.notebook, self)
        self.team_tab = TeamBattleTab(self.notebook, self)
        self.step_crit_tab = StepCritTab(self.notebook, self)
        self.tactical_tab = TacticalExerciseTab(self.notebook, self)
        self.circle_tab = CircleBattleTab(self.notebook, self)
        self.composite_tab = CompositeTacticExerciseTab(self.notebook, self)

        self.notebook.add(self.global_tab, text="全局参数")
        self.notebook.add(self.char_tab, text="角色参数")
        self.notebook.add(self.dummy_tab, text="自定义木桩")
        self.notebook.add(self.team_tab, text="编队与战斗")
        self.notebook.add(self.step_crit_tab, text="逐步暴击")
        self.notebook.add(self.tactical_tab, text="战术演习")
        self.notebook.add(self.circle_tab, text="对抗压制战")
        self.notebook.add(self.composite_tab, text="复合战术演习")

        # 主题下拉框（置于 Notebook 标签行右侧）
        self._theme_var = tk.StringVar(value=self._ui_config.get("theme", "深色"))
        self._theme_combo = ttk.Combobox(self.root, textvariable=self._theme_var,
                                         values=THEME_OPTIONS, state="readonly", width=10)
        self._theme_combo.bind("<<ComboboxSelected>>", self._on_theme_change)
        self._theme_combo.place(relx=1.0, y=5, anchor="ne", x=-10)

        # 检查更新按钮
        self._update_btn = ttk.Button(self.root, text="检查更新", command=self._check_updates_ui)
        self._update_btn.place(relx=1.0, y=5, anchor="ne", x=-110)

        # 启动时刷新原生组件颜色（确保浅色主题等非默认主题生效）
        self._refresh_native_widgets()

        # 启动时异步检查更新
        self._start_update_check()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    @staticmethod
    def _is_system_dark():
        """检测 Windows 系统是否为深色模式"""
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        except Exception:
            return True

    def _resolve_scheme(self, theme_name):
        """将用户选择的主题名解析为配色方案 key"""
        if theme_name == "浅色":
            return "light"
        elif theme_name == "跟随系统":
            return "dark" if self._is_system_dark() else "light"
        else:
            return "dark"

    def _get_scheme(self):
        """获取当前配色方案"""
        return THEME_SCHEMES.get(self._current_scheme, THEME_SCHEMES["dark"])

    def is_developer_mode(self):
        """是否为开发者模式"""
        return self._ui_config.get("developer_mode", False)

    def _on_theme_change(self, event=None):
        """主题下拉框切换回调"""
        theme_name = self._theme_var.get()
        self._current_scheme = self._resolve_scheme(theme_name)
        self._apply_window_style()
        self._apply_ttk_style()
        self._refresh_native_widgets()
        # 刷新各Tab中动态颜色的原生tk组件
        self._refresh_tab_themed_widgets()
        self._save_ui_config()
        # 清除 Combobox 选中高亮
        self._theme_combo.selection_clear()
        self._theme_combo.select_clear()

    def _refresh_tab_themed_widgets(self):
        """主题切换后刷新各Tab中使用动态配色的组件"""
        s = self._get_scheme()
        # 角色参数Tab：刷新网格视图（如果在头像模式）
        if hasattr(self, 'char_tab') and getattr(self.char_tab, '_view_mode', None) == "grid":
            self.char_tab._refresh_grid_view()
        # 角色参数Tab：刷新属性筛选图标背景色
        if hasattr(self, 'char_tab'):
            for btn in getattr(self.char_tab, '_filter_buttons', []):
                try:
                    btn.config(bg=s["surface"])
                except Exception:
                    pass
        # 编队与战斗Tab：刷新所有槽位显示和框架背景
        if hasattr(self, 'team_tab'):
            for slot in self.team_tab.friend_slots + self.team_tab.enemy_slots:
                self.team_tab._update_slot_display(slot, slot["cid"])
            # 刷新编队框架容器背景（包括外层容器）
            for frame_name in ['_enemy_main', '_ally_main', '_enemy_form_frame', '_ally_form_frame', '_enemy_mem_frame', '_ally_mem_frame']:
                frame = getattr(self.team_tab, frame_name, None)
                if frame:
                    try:
                        frame.config(bg=s["bg"])
                    except Exception:
                        pass
            # 刷新编队框架背景（外层frame + 内层slot_frame）
            for slot in self.team_tab.friend_slots + self.team_tab.enemy_slots:
                try:
                    slot["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["frame"].config(bg=s["bg"])
                    slot["avatar_label"].config(bg=s["bg"])
                    slot["name_label"].config(bg=s["bg"], fg=s["fg"])
                    slot["clear_btn"].config(bg=s["bg"], fg=s["border"])
                except Exception:
                    pass
            # 刷新回忆卡槽位背景
            for slot in self.team_tab.mem_friend_slots + self.team_tab.mem_enemy_slots:
                try:
                    slot["frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["canvas"].config(bg=s["bg"])
                    # clear_btn 保持红底白字，不随主题变化
                    # 空槽位重绘占位文字（颜色随主题变化）
                    if slot["mid"] is None:
                        canvas = slot["canvas"]
                        CARD_W, CARD_H = 120, 68
                        canvas.delete("all")
                        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                           fill=s["border"], font=("Microsoft YaHei UI", 8))
                except Exception:
                    pass
        # 战术演习Tab：刷新所有槽位显示和框架背景
        if hasattr(self, 'tactical_tab'):
            for slot in self.tactical_tab.friend_slots:
                self.tactical_tab._update_slot_display(slot, slot["cid"])
            # 刷新编队框架容器背景（包括外层容器）
            for frame_name in ['_ally_main', '_ally_form_frame', '_ally_mem_frame']:
                frame = getattr(self.tactical_tab, frame_name, None)
                if frame:
                    try:
                        frame.config(bg=s["bg"])
                    except Exception:
                        pass
            # 刷新编队框架背景（外层frame + 内层slot_frame）
            for slot in self.tactical_tab.friend_slots:
                try:
                    slot["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["frame"].config(bg=s["bg"])
                    slot["avatar_label"].config(bg=s["bg"])
                    slot["name_label"].config(bg=s["bg"], fg=s["fg"])
                    slot["clear_btn"].config(bg=s["bg"], fg=s["border"])
                except Exception:
                    pass
            # 刷新回忆卡槽位背景
            for slot in self.tactical_tab.mem_friend_slots:
                try:
                    slot["frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["canvas"].config(bg=s["bg"])
                    # clear_btn 保持红底白字，不随主题变化
                    # 空槽位重绘占位文字（颜色随主题变化）
                    if slot["mid"] is None:
                        canvas = slot["canvas"]
                        CARD_W, CARD_H = 120, 68
                        canvas.delete("all")
                        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                           fill=s["border"], font=("Microsoft YaHei UI", 8))
                except Exception:
                    pass
        # 对抗压制战Tab：刷新所有槽位显示和框架背景
        if hasattr(self, 'circle_tab'):
            for slot in self.circle_tab.friend_slots:
                self.circle_tab._update_slot_display(slot, slot["cid"])
            for frame_name in ['_ally_main', '_ally_form_frame', '_ally_mem_frame']:
                frame = getattr(self.circle_tab, frame_name, None)
                if frame:
                    try:
                        frame.config(bg=s["bg"])
                    except Exception:
                        pass
            for slot in self.circle_tab.friend_slots:
                try:
                    slot["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["frame"].config(bg=s["bg"])
                    slot["avatar_label"].config(bg=s["bg"])
                    slot["name_label"].config(bg=s["bg"], fg=s["fg"])
                    slot["clear_btn"].config(bg=s["bg"], fg=s["border"])
                except Exception:
                    pass
            for slot in self.circle_tab.mem_friend_slots:
                try:
                    slot["frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["canvas"].config(bg=s["bg"])
                    if slot["mid"] is None:
                        canvas = slot["canvas"]
                        CARD_W, CARD_H = 120, 68
                        canvas.delete("all")
                        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                           fill=s["border"], font=("Microsoft YaHei UI", 8))
                except Exception:
                    pass
            # 敌方网格：刷新背景与槽位显示（含空位文字颜色）
            enemy_grid = getattr(self.circle_tab, '_enemy_grid_frame', None)
            if enemy_grid:
                try:
                    enemy_grid.config(bg=s["bg"])
                except Exception:
                    pass
            for i, widget in enumerate(getattr(self.circle_tab, '_enemy_grid_widgets', [])):
                try:
                    widget["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    widget["frame"].config(bg=s["bg"])
                    enemy_data = self.circle_tab._enemy_slots[i] if i < len(self.circle_tab._enemy_slots) else None
                    self.circle_tab._update_enemy_slot_display(widget, enemy_data)
                except Exception:
                    pass
        # 复合战术演习Tab：刷新当前队伍槽位显示和框架背景
        if hasattr(self, 'composite_tab'):
            ct = self.composite_tab
            # 只刷新当前队伍的显示（共享GUI组件，遍历所有队伍会导致覆盖）
            team_idx = ct._current_team_index
            for slot in ct._teams_slots[team_idx]:
                ct._update_slot_display(slot, slot["cid"])
            for slot in ct._teams_mem_slots[team_idx]:
                ct._update_mem_slot_display(slot, slot["mid"])
            # 刷新队伍管理区域所有 tk.Frame 容器背景
            for frame_name in ['_team_list_frame', '_team_detail_frame', '_order_btn_frame',
                               '_ally_main', '_ally_form_frame', '_ally_mem_frame']:
                frame = getattr(ct, frame_name, None)
                if frame:
                    try:
                        frame.config(bg=s["bg"])
                    except Exception:
                        pass
            # 刷新角色槽位框架背景（所有队伍共享GUI组件，只需刷新一套）
            for slot in ct._teams_slots[team_idx]:
                try:
                    slot["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["frame"].config(bg=s["bg"])
                    slot["avatar_label"].config(bg=s["bg"])
                    slot["name_label"].config(bg=s["bg"], fg=s["fg"])
                    slot["clear_btn"].config(bg=s["bg"], fg=s["border"])
                except Exception:
                    pass
            # 刷新回忆卡槽位背景
            for slot in ct._teams_mem_slots[team_idx]:
                try:
                    slot["frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    slot["canvas"].config(bg=s["bg"])
                    if slot["mid"] is None:
                        canvas = slot["canvas"]
                        CARD_W, CARD_H = 120, 68
                        canvas.delete("all")
                        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                                           fill=s["border"], font=("Microsoft YaHei UI", 8))
                except Exception:
                    pass
            # 敌方网格：刷新背景与槽位显示
            enemy_grid = getattr(ct, '_enemy_grid_frame', None)
            if enemy_grid:
                try:
                    enemy_grid.config(bg=s["bg"])
                except Exception:
                    pass
            for i, widget in enumerate(getattr(ct, '_enemy_grid_widgets', [])):
                try:
                    widget["outer_frame"].config(bg=s["bg"], highlightbackground=s["border"])
                    widget["frame"].config(bg=s["bg"])
                    enemy_data = ct._enemy_slots[i] if i < len(ct._enemy_slots) else None
                    ct._update_enemy_slot_display(widget, enemy_data)
                except Exception:
                    pass
        # 战斗结果面板：刷新各Tab的ResultTablePanel主题（Text+Treeview配色）
        for tab_attr in ('team_tab', 'tactical_tab', 'circle_tab', 'composite_tab'):
            tab = getattr(self, tab_attr, None)
            if tab is not None and hasattr(tab, '_result_panel'):
                try:
                    tab._result_panel.apply_theme()
                except Exception:
                    pass

    def _start_update_check(self):
        """启动时启动更新守护进程"""
        self.update_daemon.start()

    def _check_updates_ui(self):
        """手动检查更新按钮回调"""
        self._update_btn.config(state="disabled", text="检查中...")
        def check():
            result = self.update_daemon.check_now()
            # 仅在无更新时恢复按钮（有更新时由进度回调管理按钮状态）
            if result is None:
                self.root.after(0, lambda: self._update_btn.config(state="normal", text="检查更新"))
                self.root.after(0, lambda: messagebox.showinfo("检查更新", f"当前已是最新版本 v{__version__}"))
            elif result.status == "COLD_UPDATE_REQUIRED":
                self.root.after(0, lambda: self._update_btn.config(state="normal", text="检查更新"))
                self.root.after(0, lambda: self._show_cold_update_dialog(result))
            else:
                # 有热/温更新，进度回调会管理按钮状态
                self.root.after(0, lambda: self._update_btn.config(state="normal"))
        threading.Thread(target=check, daemon=True).start()

    def _on_update_progress(self, progress: UpdateProgress):
        """更新进度回调（在后台线程中调用，需通过 root.after 回到主线程）"""
        self.root.after(0, lambda: self._handle_update_progress(progress))

    def _handle_update_progress(self, progress: UpdateProgress):
        """在主线程中处理更新进度"""
        status_text = {
            "IDLE": "检查更新",
            "CHECKING": "正在检查更新...",
            "READY": f"发现更新 v{progress.target_version}",
            "DOWNLOADING": f"正在更新 v{progress.target_version} ({progress.completed_files}/{progress.total_files})",
            "VERIFYING": "正在校验文件...",
            "APPLYING": "正在应用更新...",
            "COMPLETED": f"已更新至 v{progress.target_version}",
            "FAILED": f"更新失败",
            "ROLLING_BACK": "正在回滚...",
            "COLD_UPDATE_REQUIRED": f"发现新版本 v{progress.target_version}",
            "COLD_UPDATE_DOWNLOADED": f"更新已就绪 v{progress.target_version}",
        }.get(progress.status, "检查更新")

        self._update_btn.config(text=status_text[:20])

        # 冷更新下载进度（区别于热更新 DOWNLOADING）
        if progress.status == "DOWNLOADING" and progress.update_type == UpdateType.COLD:
            if progress.total_bytes and progress.total_bytes > 0:
                dl_mb = progress.downloaded_bytes // 1024 // 1024
                total_mb = progress.total_bytes // 1024 // 1024
                pct = progress.downloaded_bytes * 100 // progress.total_bytes
                self._update_btn.config(text=f"冷更新 {pct}% ({dl_mb}/{total_mb}MB)")
            else:
                self._update_btn.config(text="冷更新下载中...")
            return  # 冷更新不进入后续 COMPLETED/FAILED 判断

        if progress.status == "COMPLETED":
            warm_count = len(progress.warm_files) if progress.warm_files else 0
            hot_count = len(progress.hot_files) if progress.hot_files else 0
            msg = f"已成功更新至 v{progress.target_version}\n\n"
            if hot_count > 0:
                msg += f"数据更新: {hot_count} 个文件（已即时生效）\n"
            if warm_count > 0:
                msg += f"代码更新: {warm_count} 个文件（重启后生效）\n"
            if warm_count > 0:
                msg += "\n建议重启应用以完成更新。"
            messagebox.showinfo("更新完成", msg)
            self._update_btn.config(text="检查更新")

        elif progress.status == "FAILED":
            messagebox.showwarning("更新失败", progress.error_message or "未知错误")
            self._update_btn.config(text="检查更新")

        elif progress.status == "COLD_UPDATE_REQUIRED":
            self._show_cold_update_dialog(progress)

        elif progress.status == "COLD_UPDATE_DOWNLOADED":
            self._show_cold_update_ready_dialog(progress)

    def _show_cold_update_dialog(self, progress: UpdateProgress):
        """显示冷更新（完整包下载）对话框"""
        message = (
            f"检测到新版本 v{progress.target_version}（当前版本 v{progress.current_version}）\n\n"
            f"此更新包含重大变更，需要下载完整安装包。\n\n"
            f"是否前往下载更新？"
        )
        result = messagebox.askyesno("发现更新", message)
        if result:
            import webbrowser
            webbrowser.open(f"https://github.com/{__repository__}/releases")

    def _show_cold_update_ready_dialog(self, progress: UpdateProgress):
        """冷更新下载校验完成，询问用户是否立即重启应用"""
        message = (
            f"更新 v{progress.target_version} 已下载完成并通过校验。\n\n"
            f"是否立即重启应用以应用更新？\n"
            f"（选择「否」可继续使用当前版本，但需重新检查更新才能再次下载）"
        )
        result = messagebox.askyesno("冷更新已就绪", message)
        if result:
            # 用户确认，启动 updater.bat + os._exit(0)
            if not ColdUpdater.apply_pending():
                messagebox.showerror(
                    "更新失败",
                    "无法启动更新程序，请稍后重试或前往 GitHub 手动下载。",
                )
                self._update_btn.config(state="normal", text="检查更新")
        else:
            # 用户选择稍后，恢复按钮供下次检查
            self._update_btn.config(state="normal", text="检查更新")

    def _on_data_refresh(self, updated_files: list):
        """数据刷新回调（热更新后通知 UI 刷新）"""
        # 通知各 Tab 刷新数据
        if hasattr(self, 'char_tab'):
            # 清除角色相关缓存，触发重新加载
            pass  # 各 Tab 在下次访问时会自动从 DataLoader 重新加载

    def _apply_window_style(self):
        """应用 Windows 窗口样式"""
        s = self._get_scheme()
        try:
            is_dark = self._current_scheme == "dark"
            pywinstyles.apply_style(self.root, "dark" if is_dark else "normal")
            pywinstyles.change_header_color(self.root, color=s["header_color"])
            pywinstyles.change_title_color(self.root, color=s["header_text"])
            pywinstyles.change_border_color(self.root, color=s["border_color"])
        except Exception:
            pass

    def _apply_ttk_style(self):
        """配置 ttk 主题样式（根据当前配色方案）"""
        s = self._get_scheme()
        self.root.configure(bg=s["bg"])

        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=s["bg"], foreground=s["fg"],
                        fieldbackground=s["input_bg"], bordercolor=s["border"],
                        darkcolor=s["bg"], lightcolor=s["bg"],
                        troughcolor=s["surface"], focuscolor=s["accent"],
                        selectbackground=s["select_bg"], selectforeground=s["select_fg"],
                        insertcolor=s["fg"], font=("Microsoft YaHei UI", 9))
        style.map(".", background=[("active", s["surface"])])

        style.configure("TFrame", background=s["bg"])
        style.configure("TLabel", background=s["bg"], foreground=s["fg"])
        style.configure("TButton", background=s["surface"], foreground=s["fg"],
                        padding=6, relief="flat", borderwidth=0)
        style.map("TButton",
                  background=[("active", s["accent"]), ("pressed", s["accent"])],
                  foreground=[("active", s["accent_fg"])])
        style.configure("Accent.TButton", background=s["accent"], foreground=s["accent_fg"],
                        padding=8, font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Accent.TButton",
                  background=[("active", s["accent"]), ("pressed", s["accent"])])

        style.configure("TNotebook", background=s["bg"], borderwidth=0, relief="flat")
        style.configure("TNotebook.Tab",
                        background=s["surface"], foreground=s["fg"],
                        padding=[18, 8], font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", s["bg"]), ("active", s["tab_active_bg"])],
                  foreground=[("selected", s["accent"]), ("active", s["accent"])])

        style.configure("TLabelframe", background=s["bg"], foreground=s["fg"],
                        bordercolor=s["border"], relief="groove")
        style.configure("TLabelframe.Label", background=s["bg"], foreground=s["accent"],
                        font=("Microsoft YaHei UI", 10, "bold"))

        # 模块词条 LabelFrame 使用主文字色（非蓝色）
        style.configure("Gear.TLabelframe.Label", background=s["bg"], foreground=s["fg"],
                        font=("Microsoft YaHei UI", 9, "bold"))

        style.configure("TCombobox", fieldbackground=s["input_bg"], background=s["surface"],
                        foreground=s["fg"], selectbackground=s["select_bg"],
                        selectforeground=s["fg"], bordercolor=s["border"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", s["input_bg"])],
                  selectbackground=[("readonly", s["select_bg"])])

        style.configure("TSpinbox", fieldbackground=s["input_bg"], background=s["surface"],
                        foreground=s["fg"], bordercolor=s["border"],
                        arrowcolor=s["fg"])
        style.map("TSpinbox",
                  fieldbackground=[("readonly", s["input_bg"])])

        style.configure("TEntry", fieldbackground=s["input_bg"], foreground=s["fg"],
                        bordercolor=s["border"], insertcolor=s["fg"])

        style.configure("TCheckbutton", background=s["bg"], foreground=s["fg"],
                        indicatorcolor=s["surface"], indicatorforeground=s["fg"])
        style.map("TCheckbutton",
                  background=[("active", s["bg"])],
                  indicatorcolor=[("selected", s["accent"])])

        style.configure("TRadiobutton", background=s["bg"], foreground=s["fg"],
                        indicatorcolor=s["surface"], indicatorforeground=s["fg"])
        style.map("TRadiobutton",
                  background=[("active", s["bg"])],
                  indicatorcolor=[("selected", s["accent"])])

        style.configure("Treeview", background=s["surface"], foreground=s["fg"],
                        fieldbackground=s["surface"], borderwidth=0,
                        rowheight=28, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background=s["border"], foreground=s["fg"],
                        font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Treeview",
                  background=[("selected", s["accent"])],
                  foreground=[("selected", s["accent_fg"])])

        style.configure("TSeparator", background=s["border"])

        style.configure("TScale", background=s["bg"], troughcolor=s["surface"])

        style.configure("Horizontal.TScrollbar", background=s["surface"],
                        troughcolor=s["bg"], bordercolor=s["bg"],
                        arrowcolor=s["fg"])
        style.configure("Vertical.TScrollbar", background=s["surface"],
                        troughcolor=s["bg"], bordercolor=s["bg"],
                        arrowcolor=s["fg"])
        style.map("Horizontal.TScrollbar", background=[("active", s["border"])])
        style.map("Vertical.TScrollbar", background=[("active", s["border"])])

        style.configure("TProgressbar", background=s["accent"], troughcolor=s["surface"])

    def _refresh_native_widgets(self):
        """刷新所有原生 tk 组件的颜色（主题切换后调用）"""
        s = self._get_scheme()

        # 递归刷新所有原生 tk 组件
        def _refresh_widget(widget):
            try:
                wclass = widget.winfo_class()
                if wclass == "Canvas":
                    if getattr(widget, '_is_avatar', False):
                        widget.configure(bg=s["surface"], highlightbackground=s["border"])
                    else:
                        widget.configure(bg=s["bg"], highlightthickness=0)
                elif wclass == "Listbox":
                    widget.configure(bg=s["input_bg"], fg=s["fg"],
                                     selectbackground=s["accent"],
                                     selectforeground=s["accent_fg"])
                elif wclass == "Text":
                    widget.configure(bg=s["input_bg"], fg=s["fg"],
                                     insertbackground=s["fg"],
                                     selectbackground=s["select_bg"],
                                     selectforeground=s["select_fg"])
                    # 刷新已有文字的颜色（tag 和默认文字）
                    try:
                        for tag_name in widget.tag_names():
                            widget.tag_configure(tag_name, foreground=s["fg"])
                    except Exception:
                        pass
            except Exception:
                pass
            for child in widget.winfo_children():
                _refresh_widget(child)

        _refresh_widget(self.root)

    def _load_ui_config(self):
        """加载外观配置"""
        if UI_CONFIG_PATH.exists():
            try:
                with open(UI_CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg.setdefault("developer_mode", False)
                return cfg
            except Exception:
                pass
        return {"theme": "深色", "developer_mode": False}

    def _save_ui_config(self):
        """保存外观配置"""
        try:
            UI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            config = {
                "theme": self._theme_var.get(),
                "developer_mode": self._ui_config.get("developer_mode", False),
            }
            with open(UI_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self):
        self.update_daemon.stop()
        self._save_char_config()
        self.data_loader.save_custom_dummies()
        self.root.destroy()

    def _save_char_config(self):
        try:
            CHAR_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            serializable = {}
            for cid, cfg in self.char_config.items():
                serializable[str(cid)] = cfg
            with open(CHAR_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to save char_config: %s", e)

    def _load_char_config(self):
        if not CHAR_CONFIG_PATH.exists():
            return
        try:
            with open(CHAR_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for cid_str, cfg in data.items():
                cid = int(cid_str)
                self.char_config[cid] = cfg
        except Exception:
            pass

    def _propagate_global_level_change(self, new_level: int):
        """全局等级变化时，同步更新所有 override 且非 1 级的角色等级。

        游戏的「链接等级系统」语义：
        - level == 1：角色锁定在 1 级（不加入链接系统），保持不变
        - level != 1：角色加入链接系统，跟随全局等级
        """
        changed_cids = []
        for cid, cfg in self.char_config.items():
            if not cfg.get("override"):
                continue
            saved_level = cfg.get("level")
            if saved_level is None or saved_level == 1:
                continue
            if saved_level != new_level:
                cfg["level"] = new_level
                changed_cids.append(cid)
        if changed_cids:
            self._save_char_config()
            # 若当前角色参数页正在显示受影响角色，刷新详情以同步 Spinbox 与预览
            char_tab = getattr(self, "char_tab", None)
            if char_tab is not None:
                current_cid = getattr(char_tab, "preview_cid", None)
                if current_cid in changed_cids:
                    char_tab._show_detail(current_cid)

    def _build_panel_config_from_gui(self, global_vals: Dict) -> PanelConfig:
        panel = PanelConfig(
            character_level=global_vals["character_level"],
            school_levels=SchoolLevels(**global_vals["school_levels"]),
            equipment_enabled=True,
            equipment_bonuses=global_vals["equipment"],
        )

        default_rarity = global_vals["default_rarity"]
        default_affection = global_vals["default_affection"]
        default_skill_lv = global_vals["default_skill_level"]
        default_mod_tier = global_vals["default_mod_tier"]
        default_mod_level = global_vals["default_mod_level"]
        default_gear = global_vals["default_gear"]

        for cid in self.char_ids:
            if cid < 0:
                continue
            char = self.data_loader.get_character_by_id(cid)
            if not char:
                continue

            cc = self.char_tab.get_char_config(cid)
            if cc.get("override"):
                panel.rarities[cid] = cc["rarity"]
                panel.affection_levels[cid] = cc["affection"]
                panel.character_levels[cid] = cc["level"]
                tid = get_module_type_ids(char.character_type)
                panel.modules[cid] = [
                    ModuleConfig(module_id=mid, tier=cc["mod_tier"], level=cc["mod_level"],
                                 gear_effects=[g for g in cc["gear"] if g.get("group", 0) == grp_idx])
                    for grp_idx, mid in enumerate(tid)
                ]
                skill_ids = self.data_loader.load_character_skills().get(cid, [])
                saved_levels = cc.get("skill_levels", {})
                if saved_levels:
                    panel.skill_levels[cid] = {
                        sid: saved_levels.get(sid, saved_levels.get(str(sid), cc.get("skill_level", 15)))
                        for sid in skill_ids
                    }
                else:
                    panel.skill_levels[cid] = {sid: cc.get("skill_level", 15) for sid in skill_ids}
            else:
                panel.rarities[cid] = default_rarity
                panel.affection_levels[cid] = default_affection
                tid = get_module_type_ids(char.character_type)
                panel.modules[cid] = [
                    ModuleConfig(module_id=mid, tier=default_mod_tier,
                                 level=default_mod_level,
                                 gear_effects=[g for g in default_gear if g.get("group", 0) == grp_idx])
                    for grp_idx, mid in enumerate(tid)
                ]
                skill_ids = self.data_loader.load_character_skills().get(cid, [])
                panel.skill_levels[cid] = {sid: default_skill_lv for sid in skill_ids}

        return panel

    def _compute_max_extra_point(self, skill_ids: list) -> int:
        for sid in skill_ids:
            sk = self.data_loader.get_skill_by_id(sid)
            if sk and sk.skill_type == 3:
                return sk.resource_cost
        return 0  # 无EX技能的单位无EP条

    def _create_unit(self, panel_config, player_config, stat_calculator,
                     char_id, side, pos):
        char = self.data_loader.get_character_by_id(char_id)
        if not char:
            return None

        pt = getattr(char, 'position_type', 0)

        if char_id < 0:
            dummy_cfg = self.data_loader.get_custom_dummy_config(char_id)
            if not dummy_cfg:
                return None
            skill_ids = self.data_loader._custom_character_skills.get(char_id, [])
            max_extra_point = self._compute_max_extra_point(skill_ids)
            side_prefix = "D" if side == Side.ALLY else "E"
            hp = dummy_cfg.hp
            atk = dummy_cfg.attack
            defense = dummy_cfg.defense
            phys_shield = dummy_cfg.permanent_shield_value if dummy_cfg.permanent_shield_type == 1 else 0
            en_shld = dummy_cfg.permanent_shield_value if dummy_cfg.permanent_shield_type == 2 else 0
            all_shield = dummy_cfg.permanent_shield_value if dummy_cfg.permanent_shield_type == 3 else 0
            return UnitState(
                unit_id=f"{side_prefix}_{char_id}",
                name=char.name,
                side=side,
                position=pos,
                character_id=char_id,
                level=1,
                element=char.attribute,
                character_type=char.character_type,
                max_hp=hp,
                current_hp=hp,
                attack=atk,
                defense=defense,
                speed=dummy_cfg.speed,
                crit_rate=dummy_cfg.crit_rate,
                crit_damage=dummy_cfg.crit_damage - 1.5,
                advantage_damage=dummy_cfg.advantage_damage,
                initial_active_point=dummy_cfg.ap,
                initial_passive_point=dummy_cfg.pp,
                max_extra_point=max_extra_point,
                current_ap=dummy_cfg.ap,
                current_pp=dummy_cfg.pp,
                current_ep=0,
                shield=all_shield,
                physical_shield=phys_shield,
                en_shield=en_shld,
                skills=skill_ids,
                skill_levels={sid: 15 for sid in skill_ids},
                skill_cooldowns={},
                role_type=getattr(char, 'role_type', 0),
                position_type=pt,
            )

        char_config = panel_config.get_character_config(char_id, char.default_rarity)
        stats = stat_calculator.calculate_stats(char_config, player_config)
        skills = self.data_loader.load_character_skills().get(char_id, [])
        max_extra_point = self._compute_max_extra_point(skills)
        side_prefix = "F" if side == Side.ALLY else "E"
        hp = stats.hp
        atk = stats.attack
        defense = stats.defense
        return UnitState(
            unit_id=f"{side_prefix}_{char_id}",
            name=char.name,
            side=side,
            position=pos,
            character_id=char_id,
            level=char_config.level,
            element=char.attribute,
            character_type=char.character_type,
            max_hp=hp,
            current_hp=hp,
            attack=atk,
            defense=defense,
            speed=stats.speed,
            crit_rate=stats.critical_rate,
            crit_damage=stats.critical_damage - 1.5,
            advantage_damage=stats.advantage_damage - 1.25,
            initial_active_point=stats.initial_ap,
            initial_passive_point=stats.initial_pp,
            max_extra_point=max_extra_point,
            current_ap=stats.initial_ap,
            current_pp=stats.initial_pp,
            current_ep=0,
            skills=skills,
            skill_levels=char_config.skill_levels,
            skill_cooldowns={},
            role_type=getattr(char, 'role_type', 0),
            position_type=pt,
        )


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    MGGBattleSimulatorGUI()