# -*- coding: utf-8 -*-
"""GUI 常量：路径、图片目录、稀有度映射、主题方案、站位映射、白名单。

从 gui_app.py 抽取，供 gui 包内各模块复用。
"""

from pathlib import Path

from src.entities_v2.enums import Position

from .utils import get_base_path, get_user_data_path


# ─────────────────── 基础路径 ───────────────────

_BASE_PATH = get_base_path()
_USER_DATA = get_user_data_path()


# ─────────────────── 站位映射 ───────────────────

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


# ─────────────────── 战术演习敌方白名单 ───────────────────

# 用户模式下可选的敌方ID（经过debug验证可正常模拟的单位）
ALLOWED_ENEMY_IDS = {232315, 672105, 682205, 703405, 201405, 163205, 713405, 722305, 652105, 152205, 161418, 242305}

# 当期敌方数量（取JSON文件最后添加的N个为当期敌方，其余为往期）
CURRENT_EXERCISE_ENEMY_COUNT = 4

# 敌方ID → 同名角色ID（用于获取头像）
ENEMY_AVATAR_MAP = {
    232315: 113301,   # フィー・ドレーゼ
    672105: 122301,   # ミリアム・ヘイワード
    682205: 123301,   # ハリエット・ミルズ
    703405: 144301,   # ナージャ・ヴォルコワ
    201405: 109302,   # 夕凪舞亜
    163205: 105302,   # 生駒葵（火属性变体）
    161418: 105301,   # 生駒葵（土属性变体，厳格な規律の守護者）
    713405: 145301,   # エレーナ・パステルコワ
    722305: 146301,   # タチアナ・ドロズドヴァ
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
    652105: 142302,   # 大賀真桜（真夏の風紀委員長）
    661305: 111302,   # 劉翠蘭
    93109: 100301,    # 桃園める
    101209: 110301,   # ユリア・バーンズ
    152205: 131302,   # 姜小花（砂浜の策謀家）
    242305: 114302,   # 惨禍：アニス・ベネット（渚のスイートデビル）
}


# ─────────────────── 己方角色白名单数据源 ───────────────────

SUPPORTED_CHARACTERS_PATH = _BASE_PATH / "SUPPORTED_CHARACTERS.md"


# ─────────────────── 学园/装备/稀有度/属性映射 ───────────────────

SCHOOL_LABELS = [
    ("物理", "physical_level"), ("EN", "en_level"), ("敏捷", "agility_level"),
    ("火", "fire_level"), ("水", "water_level"), ("风", "wind_level"),
    ("土", "earth_level"), ("光", "light_level"), ("暗", "dark_level"),
]

GEAR_EFFECT_DISPLAY = {
    0: "无效果",
    7: "有利属性伤害",
    1: "HP增加",
    2: "攻击力增加",
    3: "防御力增加",
    4: "速度增加",
    5: "暴击率增加",
    6: "暴击伤害增加",
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


# ─────────────────── 触发器时序选项 ───────────────────

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


# ─────────────────── 预设/配置路径 ───────────────────

PRESET_DIR = _USER_DATA / "presets"
TACTICAL_PRESET_DIR = _USER_DATA / "tactical_presets"
CIRCLE_PRESET_DIR = _USER_DATA / "circle_presets"
COMPOSITE_PRESET_DIR = _USER_DATA / "composite_presets"
GLOBAL_CONFIG_PATH = _USER_DATA / "global_config.json"
CHAR_CONFIG_PATH = _USER_DATA / "char_config.json"
CRIT_SEQUENCE_DIR = _USER_DATA / "crit_sequences"
UI_CONFIG_PATH = _USER_DATA / "ui_config.json"


# ─────────────────── 图片资源目录 ───────────────────

_IMAGE_BASE = _BASE_PATH / "data" / "images"
AVATAR_DIR = _IMAGE_BASE / "avatars"          # 角色竖版头像
BANNER_DIR = _IMAGE_BASE / "banners"          # 角色横版头像
MEMORY_CARD_DIR = _IMAGE_BASE / "memory_cards"  # 回忆卡图片
ATTR_ICON_DIR = _IMAGE_BASE / "attributes"    # 属性图标
RARITY_DIR = _IMAGE_BASE / "rarities"         # 稀有度图标
ENEMY_IMAGE_DIR = _IMAGE_BASE / "enemies"     # 敌方横版头像（ModelAssetId命名）


# ─────────────────── 图标映射 ───────────────────

# 属性ID到图标文件名映射
ATTR_ICON_MAP = {
    0: "all", 1: "fire", 2: "water", 3: "wind", 4: "earth", 5: "light", 6: "dark",
}

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


# ─────────────────── 主题配色方案 ───────────────────

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
