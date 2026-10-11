# -*- coding: utf-8 -*-
"""编队卡片 / 回忆卡 / 角色方卡渲染。

用于各战斗 Tab 的己方/敌方编队槽位、回忆卡槽位（共用 BattleTabMixin），
以及角色参数页网格与选择角色弹窗的角色方卡。

素材来源 data/images/formations（取自游戏素材映射）：
    icon_frm_player_front/back  己方前排/后排卡框（蓝，含 FRONT/BACK 竖排文字）
    icon_frm_enemy_front/back   敌方前排/后排卡框（粉）
    icon_bg_empty_horizontal    空位背景（含左右 EMPTY 竖排文字）
    icon_frm_empty_plus         空位「+」标记
    icon_frm_locked_txt         锁定标记
    icon_frm_memory_sr/ssr/ur/lr      回忆卡横向胶片卡框（按稀有度）
    icon_frm_square_*/icon_frm_ur_plus_0  角色方卡卡框（正方形，按需拉伸）
稀有度徽章复用 data/images/rarities，属性图标复用 data/images/attributes，
定位图标复用 data/images/roles。

尺寸/位置均按参考图（180x86，即游戏卡框 300x144 的 0.6 倍）实测换算：
    属性图标    直径 ≈31px(参考) → 贴合卡片右上角（右边距≈1、上边距0）
    稀有度徽章  字形 ≈40x44(参考)，72x72 贴图换算后整图 ≈38px → 左上角 (1,36)，底部贴齐卡片
    等级文字    蓝色填充 + 白色描边（参考图逐像素结构实测）；数字块 ≈17px 高、≈13px/位宽，
                「Lv.」≈23x14px 位于数字正上方；数值为等宽数字

回忆卡按参考图（180x101，即胶片框 300x168 的 0.6 倍）：卡图铺满整框后叠加胶片框
（上下 24/168 为遮罩），稀有度徽章贴左下角。

角色方卡按参考图 参考图-角色卡图.png(112x144)：正方形卡框(188x188)拉伸到 7:9，
卡图铺满后叠加卡框，再叠加右上属性图标 + 其下定位图标、左下稀有度徽章、右下等级。
"""

from pathlib import Path
from typing import Dict, Optional, Tuple

import tkinter as tk

from gui.constants import (
    ATTR_ICON_DIR,
    ATTR_ICON_MAP,
    AVATAR_DIR,
    BANNER_DIR,
    CHAR_RARITY_MAP,
    FORMATION_DIR,
    MEM_RARITY_MAP,
    MEMORY_CARD_DIR,
    RARITY_DIR,
    ROLE_ICON_DIR,
    ROLE_ICON_MAP,
)

# 卡片显示尺寸（与游戏卡框 300x144 等比：154/74 = 2.081 = 300/144）
CARD_W, CARD_H = 154, 74

# ── 各元素尺寸（按卡片高度比例；源自参考图 180x86 实测）──
_ATTR_SIZE = round(CARD_H * 31 / 86)      # 属性图标直径
_RARITY_SIZE = round(CARD_H * 38 / 74)    # 稀有度徽章整图（72x72 画布）显示尺寸
_PLUS_SIZE = round(CARD_H * 0.62)         # 空位「+」标记整图尺寸
_ATTR_POS = (CARD_W - 1, 0)               # 属性图标锚点（anchor="ne"）
_RARITY_POS = (round(CARD_W * 1 / 154), round(CARD_H * 36 / 74))  # 稀有度锚点（anchor="nw"）

# 等级文字（右下角）——编队横卡样式（参考图 180x86 实测）
_FONT_FILE = Path(r"C:\Windows\Fonts\ariblk.ttf")   # Arial Black：最接近游戏内的粗体数字
_LV_TEXT = "Lv."

# ── 角色方卡（7:9，用于角色参数页网格 / 选择角色弹窗）──
# 素材仅提供正方形卡框 icon_frm_square_*（188x188），按参考图 参考图-角色卡图.png(112x144)
# 需求拉伸到 7:9 使用；卡图铺满后叠加卡框，再叠加属性/定位小部件、稀有度徽章、等级。
SQ_W, SQ_H = 72, 92
_SQ_ATTR_SIZE = round(SQ_W * 30 / 112)      # 属性图标直径（右上）
_SQ_ATTR_POS = (round(SQ_W * 105 / 112), round(SQ_H * 6 / 144))   # anchor="ne"
_SQ_ROLE_SIZE = round(SQ_W * 22 / 112)      # 定位图标直径（属性图标下方）
_SQ_ROLE_POS = (round(SQ_W * 103 / 112), round(SQ_H * 63 / 144))  # anchor="se"（底边对齐）
_SQ_BADGE_SIZE = round(SQ_W * 36 / 112 * 72 / 64)   # 稀有度徽章整图（72x72 画布）
_SQ_BADGE_POS = (0, SQ_H)                   # anchor="sw"（贴齐左下角）
_SQ_FRAME_FILES = {                          # DefaultRarity 分组（见 图片素材映射.txt）
    1: "icon_frm_square_r_0.png",            # 1/2
    3: "icon_frm_square_sr_0.png",           # 3/4
    5: "icon_frm_square_ssr_0.png",          # 5/6
    7: "icon_frm_ur_plus_0.png",             # 7/8
    9: "icon_frm_square_lr_0.png",           # 9-14
}

# 等级文字配色（参考图采样：蓝色填充 + 白色描边）
_LEVEL_OUTLINE = (255, 255, 255)      # 白色描边
_LEVEL_FILL_TOP = (26, 161, 252)      # 填充蓝（上）
_LEVEL_FILL_BOTTOM = (0, 146, 250)    # 填充蓝（下）

# 等级样式：编队横卡（参考图 180x86）/ 角色方卡（参考图 112x144）
_LEVEL_STYLES = {
    "formation": {
        "num_h": round(CARD_H * 17 / 86), "label_h": round(CARD_H * 14 / 86),
        "digit_w": round(CARD_W * 13 / 180), "label_w": round(CARD_W * 23 / 180),
        "gap": round(CARD_H * 3 / 86), "inset": 2,
        "num_outline": 1.2, "label_outline": 1.0,
        "right_margin": 4, "bottom_margin": 4,
    },
    "square": {
        "num_h": round(SQ_H * 20 / 144), "label_h": round(SQ_H * 14 / 144),
        "digit_w": round(SQ_W * 44 / 3 / 112), "label_w": round(SQ_W * 24 / 112),
        "gap": round(SQ_H * 5 / 144), "inset": 2,
        "num_outline": 0.9, "label_outline": 0.8,
        "right_margin": 1, "bottom_margin": 0,
    },
}

_frame_files = {
    (False, False): "icon_frm_player_front.png",
    (False, True): "icon_frm_player_back.png",
    (True, False): "icon_frm_enemy_front.png",
    (True, True): "icon_frm_enemy_back.png",
}

# ── 回忆卡（横向胶片卡框，素材 300x168，中带 300x120 为卡图区）──
# 与参考图 回忆卡参考图.png(180x101) 等比：卡图铺满整框后再叠加胶片框（上下遮罩），
# 稀有度徽章贴左下角。
MEM_W, MEM_H = 120, 67
_MEM_BADGE_W_RATIO = 0.24   # 稀有度徽章整图宽 / 卡片宽（贴齐左下角）
_MEM_FRAME_FILES = {
    1: "icon_frm_memory_sr.png",
    2: "icon_frm_memory_ssr.png",
    3: "icon_frm_memory_ur.png",
    4: "icon_frm_memory_lr.png",
}

# PhotoImage 缓存（必须长期保持引用，否则会被 GC 回收导致图片消失）
_photo_cache: Dict[Tuple, tk.PhotoImage] = {}
_level_image_cache: Dict[str, tk.PhotoImage] = {}
_memory_cache: Dict[Tuple, tk.PhotoImage] = {}
_square_cache: Dict[Tuple, tk.PhotoImage] = {}
_silhouette_cache: Dict[Tuple, object] = {}


def _frame_silhouette(path: Path, size: Tuple[int, int]):
    """由卡框贴图求外轮廓遮罩（0/255），用于裁掉圆角外露出的头像。

    圆角框四角为透明且与框内中空区不相连，从四角泛洪即可得到「框外」区域。
    """
    key = (str(path), size)
    cached = _silhouette_cache.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import Image, ImageDraw
        alpha = Image.open(path).convert("RGBA").split()[3].copy()
        w, h = alpha.size
        for pt in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if alpha.getpixel(pt) < 128:
                ImageDraw.floodfill(alpha, pt, 128, thresh=0)
        sil = alpha.point(lambda v: 0 if v == 128 else 255).resize(size, Image.LANCZOS)
        _silhouette_cache[key] = sil
        return sil
    except Exception:
        return None


def _mask_by_silhouette(img, frame_path: Path, size: Tuple[int, int]) -> None:
    """按卡框外轮廓裁掉圆角外露出的内容（就地修改 img 的 alpha）。"""
    try:
        from PIL import ImageChops
        sil = _frame_silhouette(frame_path, size)
        if sil is None:
            return
        img.putalpha(ImageChops.multiply(img.split()[3], sil))
    except Exception:
        pass


def _load_photo(path: Path, size: Tuple[int, int],
                crop_ratio: Optional[float] = None) -> Optional[tk.PhotoImage]:
    """按尺寸加载图片为 PhotoImage（带缓存）。

    crop_ratio 非空时先把图片按该宽高比中心裁剪，再缩放到 size。
    """
    key = (str(path), size, crop_ratio)
    cached = _photo_cache.get(key)
    if cached is not None:
        return cached
    if not path.exists():
        return None
    try:
        from PIL import Image, ImageTk
        img = Image.open(path).convert("RGBA")
        if crop_ratio:
            w, h = img.size
            crop_h = int(w / crop_ratio)
            if 0 < crop_h <= h:
                top = (h - crop_h) // 2
                img = img.crop((0, top, w, top + crop_h))
        img = img.resize(size, Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        _photo_cache[key] = photo
        return photo
    except Exception:
        return None


def _frame_photo(filename: str) -> Optional[tk.PhotoImage]:
    return _load_photo(FORMATION_DIR / filename, (CARD_W, CARD_H))


def load_portrait(cid: Optional[int] = None, *,
                  path: Optional[Path] = None,
                  crop: bool = True) -> Optional[tk.PhotoImage]:
    """加载角色横版头像并缩放到卡片尺寸。

    cid 时优先 banner（横版），回退 avatars（竖版，按 crop 决定是否中心裁剪）；
    path 时直接使用该文件。crop=False 表示直接拉伸（不裁剪）。
    """
    if path is None:
        if cid is None:
            return None
        banner = BANNER_DIR / f"{cid}.png"
        src = banner if banner.exists() else AVATAR_DIR / f"{cid}.png"
    else:
        src = path
    ratio = (CARD_W / CARD_H) if crop else None
    return _load_photo(src, (CARD_W, CARD_H), ratio)


# ─────────────────── 等级文字（仿真游戏美术表现） ───────────────────

def _font_for_glyph_height(height_px: int):
    """选取使数字字形高度约为 height_px 的字体（Arial Black）。"""
    from PIL import ImageFont
    probe = ImageFont.truetype(str(_FONT_FILE), 100)
    bbox = probe.getbbox("0123456789")
    unit_h = max(1, bbox[3] - bbox[1])
    size = max(1, int(round(height_px * 100 / unit_h)))
    return ImageFont.truetype(str(_FONT_FILE), size)


def _render_text_block(text: str, target_h: int, outline_px: float,
                       target_w: Optional[int] = None):
    """渲染一段带描边+纵向渐变的文字块（1x 尺寸，透明背景）。

    target_w 非空时按该宽度等比外的目标宽度缩放（用于对齐游戏内字宽）。
    """
    from PIL import Image, ImageDraw, ImageFilter
    S = 6  # 超采样倍率
    glyph_h = max(2, target_h - 2 * outline_px)
    font = _font_for_glyph_height(int(round(glyph_h * S)))
    pad = int(round(outline_px * S)) + 2 * S
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0] + pad * 2
    h = bbox[3] - bbox[1] + pad * 2
    mask = Image.new("L", (max(w, 1), max(h, 1)), 0)
    ImageDraw.Draw(mask).text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=255)

    r = max(1, int(round(outline_px * S)))
    dil = mask.filter(ImageFilter.MaxFilter(2 * r + 1))

    # 纵向渐变填充
    grad = Image.new("RGB", (1, mask.height))
    for y in range(mask.height):
        t = y / max(1, mask.height - 1)
        grad.putpixel((0, y), tuple(
            int(_LEVEL_FILL_TOP[i] + (_LEVEL_FILL_BOTTOM[i] - _LEVEL_FILL_TOP[i]) * t) for i in range(3)))
    grad = grad.resize(mask.size)

    out = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    outline_layer = Image.new("RGBA", mask.size, _LEVEL_OUTLINE + (0,))
    outline_layer.putalpha(dil)
    out.alpha_composite(outline_layer)

    fill_layer = grad.convert("RGBA")
    fill_layer.putalpha(mask)
    out.alpha_composite(fill_layer)

    content = out.getbbox()
    if content:
        out = out.crop(content)
    if target_h > 0 and out.height > 0:
        new_w = target_w if target_w else int(round(out.width * target_h / out.height))
        out = out.resize((max(1, new_w), target_h), Image.LANCZOS)
    return out


def _build_level_pil(text: str, style_key: str = "formation"):
    """生成「Lv.」+ 等级数字的组合图（PIL Image，右下对齐）。"""
    from PIL import Image
    st = _LEVEL_STYLES.get(style_key, _LEVEL_STYLES["formation"])
    num_w = st["digit_w"] * len(text)
    num = _render_text_block(text, st["num_h"], outline_px=st["num_outline"], target_w=num_w)
    if num is None:
        return None
    label = _render_text_block(_LV_TEXT, st["label_h"], outline_px=st["label_outline"],
                               target_w=st["label_w"])
    width = max(num.width, (label.width + st["inset"]) if label else 0)
    height = num.height + (st["gap"] + label.height if label else 0)
    img = Image.new("RGBA", (max(width, 1), max(height, 1)), (0, 0, 0, 0))
    if label is not None:
        img.alpha_composite(label, (width - st["inset"] - label.width, 0))
    img.alpha_composite(num, (width - num.width, img.height - num.height))
    return img


def load_level_image(text: str, style_key: str = "formation") -> Optional[tk.PhotoImage]:
    """生成「Lv.」+ 等级数字的组合图并缓存为 PhotoImage（右下对齐）。"""
    cache_key = f"{style_key}:{text}"
    cached = _level_image_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from PIL import ImageTk
        img = _build_level_pil(text, style_key)
        if img is None:
            return None
        photo = ImageTk.PhotoImage(img)
        _level_image_cache[cache_key] = photo
        return photo
    except Exception:
        return None


# ─────────────────── 卡片绘制 ───────────────────

def render_character_card(canvas: tk.Canvas, portrait: Optional[tk.PhotoImage], *,
                          is_enemy: bool = False, is_back: bool = False,
                          rarity: Optional[int] = None,
                          attribute: Optional[int] = None,
                          level: Optional[int] = None) -> None:
    """绘制已编队卡片：头像 + 卡框 + 稀有度徽章 + 属性图标 + 等级。"""
    canvas.delete("all")
    if portrait is not None:
        canvas.create_image(CARD_W // 2, CARD_H // 2, image=portrait, anchor="center")

    frame = _frame_photo(_frame_files[(bool(is_enemy), bool(is_back))])
    if frame is not None:
        canvas.create_image(CARD_W // 2, CARD_H // 2, image=frame, anchor="center")

    if rarity:
        info = CHAR_RARITY_MAP.get(rarity)
        if info:
            badge = _load_photo(RARITY_DIR / info[1], (_RARITY_SIZE, _RARITY_SIZE))
            if badge is not None:
                canvas.create_image(_RARITY_POS[0], _RARITY_POS[1], image=badge, anchor="nw")

    if attribute:
        attr_file = ATTR_ICON_MAP.get(attribute, "all")
        icon = _load_photo(ATTR_ICON_DIR / f"{attr_file}.png", (_ATTR_SIZE, _ATTR_SIZE))
        if icon is not None:
            canvas.create_image(_ATTR_POS[0], _ATTR_POS[1], image=icon, anchor="ne")

    if level is not None:
        level_img = load_level_image(str(level))
        if level_img is not None:
            st = _LEVEL_STYLES["formation"]
            canvas.create_image(CARD_W - st["right_margin"], CARD_H - st["bottom_margin"],
                                image=level_img, anchor="se")


def render_empty_card(canvas: tk.Canvas, locked: bool = False) -> None:
    """绘制空位卡片；locked=True 时叠加锁定标记（仅视觉，不限制编队）。"""
    canvas.delete("all")
    bg = _frame_photo("icon_bg_empty_horizontal.png")
    if bg is not None:
        canvas.create_image(CARD_W // 2, CARD_H // 2, image=bg, anchor="center")

    if locked:
        mark = _frame_photo("icon_frm_locked_txt.png")
        if mark is not None:
            canvas.create_image(CARD_W // 2, CARD_H // 2, image=mark, anchor="center")
    else:
        plus = _load_photo(FORMATION_DIR / "icon_frm_empty_plus.png", (_PLUS_SIZE, _PLUS_SIZE))
        if plus is not None:
            canvas.create_image(CARD_W // 2, CARD_H // 2, image=plus, anchor="center")


# ─────────────────── 回忆卡绘制 ───────────────────

def _load_pil(path: Path, size: Tuple[int, int]):
    """按尺寸加载为 PIL RGBA 图像（用于合成）。"""
    if not path.exists():
        return None
    try:
        from PIL import Image
        return Image.open(path).convert("RGBA").resize(size, Image.LANCZOS)
    except Exception:
        return None


def load_memory_card_image(mid: int, rarity: int,
                           size: Tuple[int, int] = (MEM_W, MEM_H)) -> Optional[tk.PhotoImage]:
    """合成回忆卡图：卡图铺满 + 胶片卡框 + 左下角稀有度徽章（按「卡ID+稀有度+尺寸」缓存）。"""
    w, h = size
    key = (mid, rarity, w, h)
    cached = _memory_cache.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import Image, ImageTk
        art = _load_pil(MEMORY_CARD_DIR / f"{mid}.png", (w, h))
        if art is None:
            return None
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.alpha_composite(art, (0, 0))

        frame_file = _MEM_FRAME_FILES.get(rarity, _MEM_FRAME_FILES[1])
        frame_path = FORMATION_DIR / frame_file
        frame = _load_pil(frame_path, (w, h))
        if frame is not None:
            img.alpha_composite(frame, (0, 0))

        info = MEM_RARITY_MAP.get(rarity, MEM_RARITY_MAP[1])
        badge_size = max(1, round(w * _MEM_BADGE_W_RATIO))
        badge = _load_pil(RARITY_DIR / info[1], (badge_size, badge_size))
        if badge is not None:
            img.alpha_composite(badge, (0, h - badge.height))

        _mask_by_silhouette(img, frame_path, (w, h))

        photo = ImageTk.PhotoImage(img)
        _memory_cache[key] = photo
        return photo
    except Exception:
        return None


def render_memory_card(canvas: tk.Canvas, mid: int, rarity: int) -> bool:
    """绘制回忆卡（卡图+胶片框+稀有度徽章）；无卡图时返回 False。"""
    photo = load_memory_card_image(mid, rarity)
    if photo is None:
        return False
    canvas.create_image(0, 0, image=photo, anchor="nw")
    return True


def render_memory_empty(canvas: tk.Canvas, scheme: Dict[str, str]) -> None:
    """绘制回忆卡空位占位（带边框 + 「点击选择」）。"""
    canvas.delete("all")
    canvas.create_rectangle(1, 1, MEM_W - 1, MEM_H - 1,
                            fill=scheme["bg"], outline=scheme["border"])
    canvas.create_text(MEM_W // 2, MEM_H // 2, text="点击选择",
                       fill=scheme["border"], font=("Microsoft YaHei UI", 8))


# ─────────────────── 角色方卡（角色参数页网格 / 选择角色弹窗） ───────────────────

def _square_frame_file(rarity: int) -> str:
    """按 DefaultRarity 选取方卡框（见 图片素材映射.txt）。"""
    if rarity >= 9:
        return _SQ_FRAME_FILES[9]
    if rarity >= 7:
        return _SQ_FRAME_FILES[7]
    if rarity >= 5:
        return _SQ_FRAME_FILES[5]
    if rarity >= 3:
        return _SQ_FRAME_FILES[3]
    return _SQ_FRAME_FILES[1]


def load_square_card_image(cid: int, rarity: int, attribute: int,
                           role: int, level: int) -> Optional[tk.PhotoImage]:
    """合成角色方卡（7:9）：头像 + 拉伸卡框 + 属性/定位小部件 + 稀有度徽章 + 等级（缓存）。

    返回 None 表示该角色没有头像素材（如自定义木桩），调用方回退占位文本。
    """
    key = (cid, rarity, attribute, role, level)
    cached = _square_cache.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import Image, ImageTk
        art = _load_pil(AVATAR_DIR / f"{cid}.png", (SQ_W, SQ_H))
        if art is None:
            return None
        img = Image.new("RGBA", (SQ_W, SQ_H), (0, 0, 0, 0))
        img.alpha_composite(art, (0, 0))

        frame_path = FORMATION_DIR / _square_frame_file(rarity)
        frame = _load_pil(frame_path, (SQ_W, SQ_H))
        if frame is not None:
            img.alpha_composite(frame, (0, 0))

        info = CHAR_RARITY_MAP.get(rarity)
        if info:
            badge = _load_pil(RARITY_DIR / info[1], (_SQ_BADGE_SIZE, _SQ_BADGE_SIZE))
            if badge is not None:
                img.alpha_composite(badge, (_SQ_BADGE_POS[0], _SQ_BADGE_POS[1] - badge.height))

        attr = _load_pil(ATTR_ICON_DIR / f"{ATTR_ICON_MAP.get(attribute, 'all')}.png",
                         (_SQ_ATTR_SIZE, _SQ_ATTR_SIZE))
        if attr is not None:
            img.alpha_composite(attr, (_SQ_ATTR_POS[0] - attr.width, _SQ_ATTR_POS[1]))

        role_file = ROLE_ICON_MAP.get(role)
        if role_file:
            role_img = _load_pil(ROLE_ICON_DIR / role_file, (_SQ_ROLE_SIZE, _SQ_ROLE_SIZE))
            if role_img is not None:
                img.alpha_composite(role_img, (_SQ_ROLE_POS[0] - role_img.width,
                                               _SQ_ROLE_POS[1] - role_img.height))

        lv = _build_level_pil(str(level), "square")
        if lv is not None:
            st = _LEVEL_STYLES["square"]
            img.alpha_composite(lv, (SQ_W - st["right_margin"] - lv.width,
                                     SQ_H - st["bottom_margin"] - lv.height))

        # 按卡框外轮廓裁掉圆角外露出的头像/徽章
        _mask_by_silhouette(img, frame_path, (SQ_W, SQ_H))

        photo = ImageTk.PhotoImage(img)
        _square_cache[key] = photo
        return photo
    except Exception:
        return None