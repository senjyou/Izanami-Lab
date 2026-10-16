# -*- coding: utf-8 -*-
"""收藏星标：PIL 绘制的 5 角星（实心/空心）+ 卡片角标叠加。

素材库里没有现成的收藏星标（data/images 下只有属性/稀有度/定位/卡框），
因此这里自己画：金色纵向渐变填充 + 深色描边 + 1px 投影。做法与
formation_card 里的等级文字同一套 —— 4x 超采样后缩回目标尺寸，否则 1px
描边在 20px 尺度上会糊成一团。

两种形态：
    filled=True   已收藏：金色实心星（角色卡左上角的角标、详情页高亮态）
    filled=False  未收藏：空心星（仅详情页的可点击开关使用）

投影是必需的：卡图本身有亮色（浅色衣服/天空），没有投影的金色星在
亮底上会糊掉；空心星更依赖投影才能在浅色主题的面板底色上显形。
"""

import math
from typing import Dict, List, Tuple

# ── 配色（渐变填充 + 描边 + 投影）──
_FILL_TOP = (255, 240, 150)
_FILL_BOTTOM = (255, 165, 0)
_OUTLINE = (122, 74, 0)
_HOLLOW = (150, 156, 178)          # 空心星描边：深浅主题底色上都可辨
_SHADOW = (0, 0, 0, 120)

# 超采样倍率：1px 描边直接在 20px 上画会有锯齿
_SUPERSAMPLE = 4

# PhotoImage / PIL Image 缓存（PhotoImage 必须长期持有引用，否则会被 GC 回收）
_pil_cache: Dict[Tuple[int, bool], object] = {}
_photo_cache: Dict[Tuple[int, bool], object] = {}


def _star_points(cx: float, cy: float, r_out: float, r_in: float,
                 points: int = 5, rotation: float = -90.0) -> List[Tuple[float, float]]:
    """5 角星顶点：外顶点/内顶点交替（rotation=-90 表示尖角朝上）。"""
    pts = []
    for i in range(points * 2):
        angle = math.radians(rotation + i * 180.0 / points)
        radius = r_out if i % 2 == 0 else r_in
        pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return pts


def star_image(size: int, filled: bool = True):
    """生成星标 PIL 图（RGBA，size x size）；PIL 不可用时返回 None。"""
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageFilter
    except Exception:
        return None

    size = max(7, int(size))
    key = (size, bool(filled))
    cached = _pil_cache.get(key)
    if cached is not None:
        return cached

    s = _SUPERSAMPLE
    big = size * s
    # 留白要容纳描边 + 向下 1px 的投影，否则星角会被裁掉
    pad = max(s + 1.0, big * 0.09)
    r_out = big / 2.0 - pad
    r_in = r_out * 0.42
    pts = _star_points(big / 2.0, big / 2.0, r_out, r_in)

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)

    # 描边：对星形遮罩做膨胀，宽度按目标尺寸等比（1x 下约 1~1.2px）
    stroke_w = max(1, int(round(s * max(1.0, size * 0.055))))
    stroke = mask.filter(ImageFilter.MaxFilter(2 * stroke_w + 1))
    # 只保留边界环带（膨胀结果 - 原遮罩）：空心星用它作描边，
    # 若直接用 stroke，星形内部也会被填成实心（那不是空心星）。
    band = ImageChops.subtract(stroke, mask)

    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    # 投影（先画，整体下移 1 个最终像素）：实心星投整星轮廓，空心星投描边环带
    shadow_layer = Image.new("RGBA", (big, big), _SHADOW)
    shadow_layer.putalpha(stroke if filled else band)
    img.alpha_composite(shadow_layer, (0, s))

    # 描边层：实心星用整星轮廓打底（渐变填充再叠上去，露出的边缘即为描边），
    # 空心星仅画环带
    outline_color = _OUTLINE if filled else _HOLLOW
    outline_layer = Image.new("RGBA", (big, big), outline_color + (255,))
    outline_layer.putalpha(stroke if filled else band)
    img.alpha_composite(outline_layer)

    if filled:
        # 纵向渐变填充
        grad = Image.new("RGB", (1, big))
        for y in range(big):
            t = y / max(1, big - 1)
            grad.putpixel((0, y), tuple(
                int(_FILL_TOP[i] + (_FILL_BOTTOM[i] - _FILL_TOP[i]) * t) for i in range(3)))
        fill_layer = grad.resize((big, big)).convert("RGBA")
        fill_layer.putalpha(mask)
        img.alpha_composite(fill_layer)

    final = img.resize((size, size), Image.LANCZOS)
    _pil_cache[key] = final
    return final


def star_photo(size: int, filled: bool = True):
    """生成星标 PhotoImage（供 tk.Label/tk.Canvas 使用）；无 Tk 或 PIL 时返回 None。"""
    key = (max(7, int(size)), bool(filled))
    cached = _photo_cache.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import ImageTk
        img = star_image(key[0], key[1])
        if img is None:
            return None
        photo = ImageTk.PhotoImage(img)
    except Exception:
        return None
    _photo_cache[key] = photo
    return photo


def compose_star(img, size: int, xy: Tuple[int, int], filled: bool = True) -> bool:
    """把星标就地叠加到 PIL 图上（xy 为左上角）。返回是否叠加成功。"""
    star = star_image(size, filled)
    if star is None:
        return False
    try:
        img.alpha_composite(star, (int(xy[0]), int(xy[1])))
        return True
    except Exception:
        return False
