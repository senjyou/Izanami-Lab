# -*- coding: utf-8 -*-
"""网格列宽工具：Tk uniform 列的历史残留坑 + 按可用宽度算卡片尺寸。

坑：`grid_columnconfigure(c, weight=1, uniform="col")` 一旦设过，这一列就永久
属于那个 uniform 组。如果上一次布局排了 5 列、这一次只需要 4 列，组里仍然有
5 个成员 —— 4 列只占可用宽度的 4/5，右侧留下大片空白；更糟的是列宽会小于
卡片的请求宽度，Tk 会把卡片（连同卡图）压窄，图片右侧直接被裁掉
（回忆图鉴网格就是这样被裁的：画布 106px 却画着 120px 的卡图）。

因此每次重排都要先清掉历史列设置，再按当前列数重建 uniform 组。
"""

import tkinter as tk
from typing import Tuple

# 需要清理的历史列数上限（各网格实际列数远小于此值，多清几列无副作用）
_MAX_TRACKED_COLS = 24


def configure_uniform_columns(container, cols: int, max_cols: int = _MAX_TRACKED_COLS) -> None:
    """按 cols 配置等宽列，并清掉更早布局留下的列设置（见模块 docstring）。"""
    for c in range(max_cols):
        try:
            container.grid_columnconfigure(c, weight=0, uniform="")
        except tk.TclError:
            break
    for c in range(cols):
        container.grid_columnconfigure(c, weight=1, uniform="col")


def fit_card_size(avail: int, cols: int, pad: int, border: int,
                  aspect: float, min_w: int, max_w: int) -> Tuple[int, int]:
    """按可用宽度算出让「一行正好铺满」的卡图尺寸（宽, 高）。

    列宽 = avail/cols（uniform 列会均分全部可用宽度），卡片连同
    左右各 pad 的外间距与 border 的描边必须落在这个列宽内，因此：
        卡图宽 = 列宽 - 2*pad - 2*border
    aspect = 卡框宽/高，用于按比例求卡图高。min_w/max_w 为兜底范围，
    防止面板极窄/极宽时把卡图压得看不清或拉得过大。
    """
    avail = max(1, int(avail))
    cols = max(1, int(cols))
    cell = avail // cols
    card_w = cell - 2 * pad - 2 * border
    card_w = max(int(min_w), min(int(max_w), card_w))
    card_h = max(16, int(round(card_w / aspect)))
    return card_w, card_h


def cols_for_width(avail: int, card_w: int, pad: int, border: int) -> int:
    """在给定「期望卡图宽」下，一行最多能放下几列。"""
    per = max(1, int(card_w) + 2 * pad + 2 * border)
    return max(1, max(1, int(avail)) // per)
