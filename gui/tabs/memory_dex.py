# -*- coding: utf-8 -*-
"""回忆图鉴视图（嵌在「角色与回忆」Tab 内，与角色参数页分段切换）。

为什么合并在角色参数 Tab 内
--------------------------
用户要为主界面 Notebook 预留标签位，因此图鉴不作为独立 Tab，而是与角色参数
共用一个 Tab（Tab 名「角色与回忆」），内部用分段切换切视图。

本页是**只读**浏览页（回忆卡没有可编辑参数：稀有度/效果都由数据决定），
职责是：卡面网格 + 稀有度筛选 + 搜索 + 详情（大图 / 剧情文本 / 结构化效果），
外加收藏星标（与角色参数页同一个 favorites.json）。

性能
----
164 张卡的合成（开图 + 缩放 + 叠卡框 + 叠徽章 + 轮廓裁切）单张约 5~20ms，
一次性画完会卡住界面，因此：
  * 首次切到本视图才填卡图（`on_shown()`，避免拖慢启动）；
  * 卡图按帧分批异步加载（每帧 4 张，与 MemoryPickerDialog 同一套做法）。
"""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

from gui.constants import (
    CHAR_TYPE_NAMES,
    ELEMENT_NAMES,
    MEM_RARITY_MAP,
    RARITY_DIR,
    ROLE_TYPE_NAMES,
)
from gui.widgets.favorite_star import star_photo as load_favorite_star
from gui.widgets.formation_card import (
    MEM_H,
    MEM_W,
    load_memory_card_image,
    purge_memory_card_cache,
)
from gui.widgets.grid_layout import cols_for_width, configure_uniform_columns, fit_card_size

_DEFAULT_COLS = 5        # 默认宽度下可容纳的列数（面板缩窄时自动减少）
_CARD_PAD = 3
_CARD_BORDER = 2
# 卡图尺寸随面板宽度自适应：一行正好铺满，且不小于/大于以下范围
_CARD_ASPECT = 300 / 168          # 胶片卡框宽/高（与 MEM_W:MEM_H 同比例）
_MIN_CARD_W, _MAX_CARD_W = 120, 220
_DETAIL_W, _DETAIL_H = 240, 134   # 详情大图（固定尺寸）

# highlight.party_position 是位置位掩码（与引擎 _POSITION_BITMASK_MAP 一致）：
# 1=左前 2=中前 4=右前 8=左后 16=中后 32=右后
_POS_BITS = [(1, "左前"), (2, "中前"), (4, "右前"), (8, "左后"), (16, "中后"), (32, "右后")]
_FRONT_MASK = 1 | 2 | 4
_BACK_MASK = 8 | 16 | 32


def format_position_mask(mask: int) -> str:
    """把位置位掩码渲染成可读文字（整排/整列时用简称，否则逐格列出）。"""
    if not mask:
        return "?"
    if mask & (_FRONT_MASK | _BACK_MASK) == (_FRONT_MASK | _BACK_MASK):
        return "任意位置"
    if mask == _FRONT_MASK:
        return "前排"
    if mask == _BACK_MASK:
        return "后排"
    if mask == (2 | 16):
        return "中列"
    names = [name for bit, name in _POS_BITS if mask & bit]
    return "/".join(names) if names else str(mask)


def _variant_name_for_base(loader, base_id: int, app) -> Optional[str]:
    """基底名查不到时的兜底：用该基底下一个角色变体的名字（同样来自随包数据）。

    打包版没有 split_data，character_team_mapping.json 里可能缺少数个较新的
    角色基底；这时宁可显示变体名（如「ドメスティックなリーダー」），也不能把
    解包出来的 ID 漏到界面上。
    """
    try:
        for char in (loader.load_characters() or {}).values():
            if getattr(char, "character_base_id", None) == base_id:
                return app.format_char_name(char)
    except Exception:
        pass
    return None


# 参与合并/渲染的条件字段（skill_master_id / is_targeting_friendly_party 单独处理）
_CONDITION_FIELDS = ("character_team_master_id", "character_base_master_id",
                     "character_master_id", "character_attribute",
                     "character_role", "character_type", "party_position")


def group_highlights(highlights) -> List[Dict]:
    """把同一技能的 highlight 合并成一条展示项。

    为什么必须合并：`scripts/import_memory.py` 会把原始 highlight 的**位掩码**
    （属性/职能）拆成多条 highlight —— 引擎按单值比较 unit.role_type / element，
    存掩码会永不匹配（见该文件 `_ROLE_FLAG_TO_TYPE` 的注释，那里就点名了 30046）。
    拆分出来的条目携带**同一个 skill_master_id**，逐条展示就会看到「同一段效果
    文本重复出现」：30046 被拆成 物理/EN 两条、30035 被拆成 光/暗两条。

    合并语义：同一个技能对「各条条件的并集」生效，所以展示成一条是准确的。
    规则：
      * skill_master_id 相同、且 is_targeting_friendly_party 相同才合并
        （一条己方一条敌方时不能并进同一行）；
      * 普通字段取并集（去重、保持首次出现顺序）；
      * party_position 是位掩码，并集按位或；
      * 保持首次出现的顺序；skill_master_id 为空的条目各自单独成组。
    """
    groups: List[Dict] = []
    index: Dict[tuple, Dict] = {}
    for hl in highlights or []:
        skill_id = getattr(hl, "skill_master_id", None)
        friendly = getattr(hl, "is_targeting_friendly_party", True) is not False
        key = (skill_id, friendly, None if skill_id else id(hl))
        group = index.get(key)
        if group is None:
            group = {"skill_master_id": skill_id, "friendly": friendly,
                     "values": {f: [] for f in _CONDITION_FIELDS}, "position_mask": 0}
            index[key] = group
            groups.append(group)
        for field in _CONDITION_FIELDS:
            value = getattr(hl, field, None)
            if not value:
                continue
            if field == "party_position":
                group["position_mask"] |= int(value)
            elif value not in group["values"][field]:
                group["values"][field].append(value)
    return groups


def format_condition_group(group: Dict, app) -> str:
    """渲染一组（可能由多条 highlight 合并而来）的条件；不含任何解包 ID。"""
    loader = app.data_loader
    values = group.get("values") or {}
    parts: List[str] = []

    team_ids = values.get("character_team_master_id") or []
    if team_ids:
        teams = loader.load_character_teams() or {}
        parts.append("队伍「" + "/".join(teams.get(t) or "所属队伍" for t in team_ids) + "」")

    base_ids = values.get("character_base_master_id") or []
    if base_ids:
        names = []
        for base_id in base_ids:
            name = loader.get_character_base_name(base_id) or _variant_name_for_base(loader, base_id, app)
            names.append(name or "特定角色")
        parts.append("角色「" + "/".join(names) + "」")

    char_ids = values.get("character_master_id") or []
    if char_ids:
        names = []
        for char_id in char_ids:
            ch = loader.get_character_by_id(char_id)
            names.append(app.format_char_name(ch) if ch else "特定形态")
        parts.append("形态「" + "/".join(names) + "」")

    attrs = values.get("character_attribute") or []
    if attrs:
        parts.append("/".join(f"{ELEMENT_NAMES.get(a, a)}属性" for a in attrs))

    roles = values.get("character_role") or []
    if roles:
        parts.append("定位:" + "/".join(str(ROLE_TYPE_NAMES.get(r, r)) for r in roles))

    types = values.get("character_type") or []
    if types:
        parts.append("类型:" + "/".join(str(CHAR_TYPE_NAMES.get(t, t)) for t in types))

    if group.get("position_mask"):
        parts.append("位置:" + format_position_mask(group["position_mask"]))

    side = "己方" if group.get("friendly", True) else "敌方"
    if parts:
        return f"{side} · " + " · ".join(parts)
    return f"{side}全体（不限条件）"


def format_highlight_condition(hl, app) -> str:
    """单条 highlight 的条件行。

    「只输出名字、绝不输出解包 ID」的保证统一在 format_condition_group 里，
    图鉴展示与测试都走同一套逻辑。
    """
    return format_condition_group(group_highlights([hl])[0], app)


class MemoryDexView(ttk.Frame):
    """回忆图鉴：左侧卡面网格（稀有度筛选 + 搜索），右侧详情（含收藏星标）。

    搜索范围包含效果名/效果说明（图鉴最常见的用法是「哪张卡给攻击力」）。
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._current_rarity = 0        # 0=全部, 1=SR, 2=SSR, 3=UR, 4=LR
        self._filtered_ids: List[int] = []
        self._card_widgets: Dict[int, tk.Canvas] = {}
        self._selected_mid: Optional[int] = None
        self._wrap_labels: List[tk.Widget] = []
        self._grid_filled = False       # 首次显示前不填卡图（不拖慢启动）
        # 布局：由画布宽度算出 (列数, 卡图宽, 卡图高)，画布一有真实宽度就确定
        self._layout = None
        self._card_w, self._card_h = MEM_W, MEM_H
        self._cols = _DEFAULT_COLS
        self._rendered_size: Optional[Tuple[int, int]] = None
        self._resize_job = None
        self._build()

    # ─────────────────── 布局 ───────────────────

    def _build(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ── 左：筛选 + 网格 ──
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="回忆图鉴", font=("Microsoft YaHei UI", 10, "bold")).pack(pady=(5, 0))

        filter_frame = ttk.Frame(left)
        filter_frame.pack(fill="x", padx=5, pady=5)
        self._rarity_buttons: List[ttk.Label] = []
        ICON_SIZE = 20
        # 0=全部, 1=SR, 2=SSR, 3=UR, 4=LR（与选择弹窗的筛选一致）
        rarity_items = [(0, "全部", None)]
        for rid, (rname, ricon) in MEM_RARITY_MAP.items():
            rarity_items.append((rid, rname, ricon))
        for rid, rname, ricon in rarity_items:
            photo = self._load_rarity_icon(ricon, ICON_SIZE) if ricon else None
            if photo is not None:
                btn = ttk.Label(filter_frame, image=photo, cursor="hand2", style="Seg.TLabel")
                btn.image = photo
            else:
                btn = ttk.Label(filter_frame, text=rname, cursor="hand2", style="Seg.TLabel")
            btn.pack(side=tk.LEFT, padx=1)
            btn.bind("<Button-1>", lambda e, r=rid: self._apply_rarity(r))
            self._rarity_buttons.append(btn)
        self._update_rarity_highlight()

        search_row = ttk.Frame(left)
        search_row.pack(fill="x", padx=5)
        ttk.Label(search_row, text="搜索:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        # 还没填过卡图时不重绘（视图可能一直没被切到过）
        self._search_var.trace_add("write", lambda *a: self.refresh_grid())
        search_entry = ttk.Entry(search_row, textvariable=self._search_var)
        search_entry.pack(side=tk.LEFT, fill="x", expand=True, padx=4)

        grid_frame = ttk.Frame(left)
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._canvas = tk.Canvas(grid_frame, bg=self.app._get_scheme()["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(grid_frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid_inner = tk.Frame(self._canvas, bg=self.app._get_scheme()["surface"])
        self._canvas_window = self._canvas.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind("<Configure>",
                              lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        def _bind_mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", _bind_mw))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        # ── 右：详情 ──
        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        s = self.app._get_scheme()
        right_canvas = tk.Canvas(right, bg=s["bg"], highlightthickness=0)
        self._detail_canvas = right_canvas
        self._detail_width = 0
        right_scrollbar = ttk.Scrollbar(right, orient="vertical", command=right_canvas.yview)
        self.detail_frame = ttk.Frame(right_canvas)
        self.detail_frame.bind("<Configure>",
                               lambda e: right_canvas.configure(scrollregion=right_canvas.bbox("all")))
        self._detail_window = right_canvas.create_window((0, 0), window=self.detail_frame, anchor="nw")
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        right_canvas.pack(side="left", fill="both", expand=True)
        right_scrollbar.pack(side="right", fill="y")

        def _on_right_resize(event):
            right_canvas.itemconfig(self._detail_window, width=event.width)
            self._detail_width = event.width
            self._update_wraplength(event.width)

        right_canvas.bind("<Configure>", _on_right_resize)

        def _on_right_mousewheel(e):
            right_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        right_canvas.bind("<Enter>", lambda e: right_canvas.bind_all("<MouseWheel>", _on_right_mousewheel))
        right_canvas.bind("<Leave>", lambda e: right_canvas.unbind_all("<MouseWheel>"))

        self._show_placeholder()

    @staticmethod
    def _load_rarity_icon(filename: Optional[str], size: int):
        if not filename:
            return None
        try:
            photo = tk.PhotoImage(file=str(RARITY_DIR / filename))
            if photo.width() > size:
                factor = max(1, photo.width() // size)
                photo = photo.subsample(factor, factor)
            return photo
        except Exception:
            return None

    # ─────────────────── 外部接口 ───────────────────

    def on_shown(self):
        """切到本视图时调用：首次才真正填卡图（164 张合成不便宜）。

        刚 pack 时画布还没有真实宽度（winfo_width 仍是 1），这种情况交给
        第一次 <Configure> 去填（见 _on_canvas_resize）。
        """
        self._grid_filled = True
        if self._layout is not None:
            self._refresh_grid()

    def refresh_grid(self):
        """主题切换等外部原因触发的重绘（仅在已填过卡图时）。"""
        if self._grid_filled:
            self._refresh_grid()

    # ─────────────────── 网格 ───────────────────

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)
        layout = self._layout_for_width(event.width)
        if layout == self._layout:
            return
        self._layout = layout
        self._cols, self._card_w, self._card_h = layout
        if not self._grid_filled:
            return
        if not self._card_widgets:
            self._refresh_grid()            # 首次铺开
        else:
            self._schedule_grid_refresh()   # 拖动面板时等停下来再重建

    @staticmethod
    def _layout_for_width(avail: int):
        """由可用宽度算出 (列数, 卡图宽, 卡图高)：一行正好铺满。

        列数按「不小于 _MIN_CARD_W」估一个，再把列宽均分给卡图
        （uniform 列会吃掉全部可用宽度），这样右边不会留空、卡片也不会被压窄。
        """
        cols = cols_for_width(avail, _MIN_CARD_W, _CARD_PAD, _CARD_BORDER)
        card_w, card_h = fit_card_size(avail, cols, _CARD_PAD, _CARD_BORDER,
                                       _CARD_ASPECT, _MIN_CARD_W, _MAX_CARD_W)
        return cols, card_w, card_h

    def _schedule_grid_refresh(self):
        """拖动面板时不要每像素重建一次网格（卡图缓存会按尺寸膨胀）。"""
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(120, self._rebuild_after_resize)

    def _rebuild_after_resize(self):
        self._resize_job = None
        self._refresh_grid()

    def _apply_rarity(self, rarity_id: int):
        self._current_rarity = rarity_id
        self._update_rarity_highlight()
        if self._grid_filled:
            self._refresh_grid()
        self._canvas.yview_moveto(0)

    def _update_rarity_highlight(self):
        for i, btn in enumerate(self._rarity_buttons):
            btn.configure(style="SegActive.TLabel" if i == self._current_rarity else "Seg.TLabel")

    def _get_filtered_ids(self) -> List[int]:
        search_text = self._search_var.get().strip().lower()
        try:
            memories = self.app.data_loader.load_memories()
        except Exception:
            return []
        result = []
        for mid, mem in memories.items():
            if self._current_rarity and mem.rarity != self._current_rarity:
                continue
            if search_text and not self._matches_search(mid, mem, search_text):
                continue
            result.append(mid)
        result.sort()
        return result

    def _matches_search(self, mid: int, mem, search_text: str) -> bool:
        """搜索范围：卡ID / 卡名 / 卡面文本 / 效果名 / 效果说明。

        图鉴最常见的用法就是「哪张卡给攻击力」，所以效果文本也参与搜索。
        """
        if search_text in str(mid) or search_text in mem.name.lower():
            return True
        if search_text in (getattr(mem, "description", "") or "").lower():
            return True
        for hl in getattr(mem, "highlights", []) or []:
            sid = getattr(hl, "skill_master_id", None)
            if not sid:
                continue
            effect = self.app.data_loader.get_memory_effect(sid)
            if not effect:
                continue
            if search_text in str(effect.get("name", "")).lower():
                return True
            if search_text in str(effect.get("description", "")).lower():
                return True
        return False

    def _ensure_layout(self):
        """兜底：画布已有真实宽度但首个 <Configure> 还没到（或已被 withdraw）时补算布局。"""
        if self._layout is not None:
            return
        try:
            avail = self._canvas.winfo_width()
        except Exception:
            avail = 1
        if avail > 1:
            self._layout = self._layout_for_width(avail)
            self._cols, self._card_w, self._card_h = self._layout

    def _refresh_grid(self):
        self._ensure_layout()
        self._filtered_ids = self._get_filtered_ids()
        for child in self._grid_inner.winfo_children():
            child.destroy()
        self._card_widgets.clear()

        COLS = self._cols
        card_w, card_h = self._card_w, self._card_h
        s = self.app._get_scheme()
        self._canvas.configure(bg=s["bg"])
        self._grid_inner.configure(bg=s["surface"])

        # 卡图尺寸变了：丢掉上一尺寸的缓存（否则拖动面板会攒出几十种尺寸）
        if self._rendered_size is not None and self._rendered_size != (card_w, card_h):
            purge_memory_card_cache(self._rendered_size)
        self._rendered_size = (card_w, card_h)

        configure_uniform_columns(self._grid_inner, COLS)

        if not self._filtered_ids:
            tk.Label(self._grid_inner, text="没有符合条件的回忆卡", bg=s["surface"],
                     fg=s["border"], font=("Microsoft YaHei UI", 10)).grid(
                row=0, column=0, columnspan=max(1, COLS), pady=40)
            self._thumb_queue = []
            return

        for i, mid in enumerate(self._filtered_ids):
            row, col = divmod(i, COLS)
            card = tk.Frame(self._grid_inner, bg=s["surface"], bd=0,
                            highlightbackground=s["border"], highlightthickness=_CARD_BORDER,
                            cursor="hand2")
            card.grid(row=row, column=col, padx=_CARD_PAD, pady=_CARD_PAD, sticky="n")

            card_canvas = tk.Canvas(card, width=card_w, height=card_h, bg=s["surface"],
                                    highlightthickness=0)
            card_canvas.pack()
            card_canvas.create_text(card_w // 2, card_h // 2, text="...",
                                    fill=s["border"], font=("Microsoft YaHei UI", 9))
            card_canvas.bind("<Button-1>", lambda e, m=mid: self._on_card_click(m))
            card.bind("<Button-1>", lambda e, m=mid: self._on_card_click(m))

            # 卡名（与角色参数页网格同一排版：卡图下方两行；不显示解包 ID）。
            # wraplength 比卡图再窄一点：卡名的请求宽度绝不能超过卡图宽度，
            # 否则卡片框会被撑宽、超出列宽，卡图右侧又被裁掉。
            name = getattr(self.app.data_loader.get_memory(mid), "name", str(mid))
            if len(name) > 14:
                name = name[:13] + "…"
            name_label = tk.Label(card, text=name, bg=s["surface"], fg=s["fg"],
                                  font=("Microsoft YaHei UI", 8),
                                  wraplength=max(40, card_w - 14),
                                  height=2, justify="center")
            name_label.pack(fill="x")
            name_label.bind("<Button-1>", lambda e, m=mid: self._on_card_click(m))

            if mid == self._selected_mid:
                card.configure(highlightbackground=s["accent"])
            self._card_widgets[mid] = card_canvas

        self._thumb_queue = list(self._filtered_ids)
        self._load_thumbs_async()

    def _refresh_card_thumb(self, mid: int):
        """重画单张卡缩略图（收藏角标变化时用，避免整片网格重绘闪烁）。"""
        canvas = self._card_widgets.get(mid)
        if canvas is None:
            return
        try:
            if not canvas.winfo_exists():
                return
        except Exception:
            return
        mem = self.app.data_loader.get_memory(mid)
        rarity = getattr(mem, "rarity", 1) if mem else 1
        photo = load_memory_card_image(mid, rarity, (self._card_w, self._card_h),
                                       favorite=self.app.is_favorite_memory(mid))
        if photo is not None:
            canvas.delete("all")
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas._card_photo = photo

    def _load_thumbs_async(self):
        """每帧加载 4 张卡图，避免 164 张一次性合成卡住界面。"""
        queue = getattr(self, "_thumb_queue", None)
        if not queue:
            return
        for _ in range(4):
            if not queue:
                break
            self._refresh_card_thumb(queue.pop(0))
        if queue:
            self.after(10, self._load_thumbs_async)

    def _on_card_click(self, mid: int):
        s = self.app._get_scheme()
        prev = self._selected_mid
        if prev is not None and prev in self._card_widgets:
            try:
                self._card_widgets[prev].master.configure(highlightbackground=s["border"])
            except Exception:
                pass
        self._selected_mid = mid
        canvas = self._card_widgets.get(mid)
        if canvas is not None:
            try:
                canvas.master.configure(highlightbackground=s["accent"])
            except Exception:
                pass
        self._show_detail(mid)

    # ─────────────────── 详情 ───────────────────

    def _show_placeholder(self):
        for w in self.detail_frame.winfo_children():
            w.destroy()
        self._wrap_labels.clear()
        ttk.Label(self.detail_frame, text="选择左侧回忆卡查看卡面与效果",
                  font=("Microsoft YaHei UI", 10)).pack(pady=20)

    def _detail_wrap(self) -> int:
        """详情区文本换行宽度。

        Label 不会自动重排文字，必须在**建标签时**就按当前实际宽度给出
        wraplength —— 早期版本写死 400，于是明明还有横向宽度就提前换行了
        （<Configure> 只改已存在的标签，详情是之后才重建的）。
        """
        width = self._detail_width
        if width <= 1:
            try:
                width = self._detail_canvas.winfo_width()
            except Exception:
                width = 0
        if width <= 1:
            width = 640          # 还没布局时的兜底，_sync_wraplength 随后会纠正
        return max(200, width - 40)

    def _sync_wraplength(self):
        """布局落定后按真实宽度再校正一次（首次渲染时可能还没拿到宽度）。"""
        try:
            width = self._detail_canvas.winfo_width()
        except Exception:
            return
        if width > 1:
            self._detail_width = width
            self._update_wraplength(width)

    def _update_wraplength(self, canvas_width: int):
        """详情区宽度变化时同步换行宽度（Label 不会自动重排文字）。"""
        wrap = max(200, canvas_width - 40)
        for lbl in self._wrap_labels:
            try:
                lbl.configure(wraplength=wrap - getattr(lbl, "_wrap_inset", 0))
            except Exception:
                pass

    def _show_detail(self, mid: int):
        mem = self.app.data_loader.get_memory(mid)
        if not mem:
            self._show_placeholder()
            return
        for w in self.detail_frame.winfo_children():
            w.destroy()
        self._wrap_labels.clear()

        f = self.detail_frame
        ttk.Label(f, text="").pack()

        # 换行宽度按当前详情区实际宽度算（写死会提前换行；见 _detail_wrap）
        wrap = self._detail_wrap()

        # 卡面大图
        photo = load_memory_card_image(mid, getattr(mem, "rarity", 1), (_DETAIL_W, _DETAIL_H),
                                       favorite=self.app.is_favorite_memory(mid))
        if photo is not None:
            img_label = ttk.Label(f, image=photo)
            img_label.image = photo
            img_label.pack(pady=(0, 6))

        # 名称 + 收藏星标（与角色参数页同一个星标交互）
        name_row = ttk.Frame(f)
        name_row.pack(fill="x", padx=10)
        rarity_name = MEM_RARITY_MAP.get(getattr(mem, "rarity", 1), ("?",))[0]
        ttk.Label(name_row, text=mem.name, font=("Microsoft YaHei UI", 14, "bold"),
                  anchor="center").pack(side="left", fill="x", expand=True)
        self._build_favorite_toggle(name_row, mid, self.app.is_favorite_memory(mid))

        # 注意：不显示回忆卡 ID / 技能 ID（解包内容不进 GUI）
        ttk.Label(f, text=f"稀有度: {rarity_name}",
                  font=("Microsoft YaHei UI", 10)).pack(pady=(2, 6))

        # 剧情文本
        desc = getattr(mem, "description", "") or ""
        if desc:
            desc_frame = ttk.LabelFrame(f, text="卡面文本")
            desc_frame.pack(fill="x", padx=8, pady=4)
            lbl = ttk.Label(desc_frame, text=desc.replace("\\n", "\n"),
                            font=("Microsoft YaHei UI", 10), justify="left", wraplength=wrap)
            lbl.pack(anchor="w", padx=8, pady=6)
            self._wrap_labels.append(lbl)

        # 结构化效果：同一技能的多条 highlight（位掩码拆分的产物）合并成一条，
        # 否则会看到「同一段效果文本重复出现」（见 group_highlights 的说明）
        eff_frame = ttk.LabelFrame(f, text="效果")
        eff_frame.pack(fill="x", padx=8, pady=4)
        highlights = list(getattr(mem, "highlights", []) or [])
        groups = group_highlights(highlights)
        if not groups:
            ttk.Label(eff_frame, text="（无效果数据）", font=("Microsoft YaHei UI", 10)).pack(
                anchor="w", padx=8, pady=6)
        for i, group in enumerate(groups, start=1):
            block = ttk.Frame(eff_frame)
            block.pack(fill="x", padx=6, pady=(6, 2))
            sid = group.get("skill_master_id")
            effect = self.app.data_loader.get_memory_effect(sid) if sid else None
            cond_lbl = ttk.Label(block, text=f"{i}. 适用: {format_condition_group(group, self.app)}",
                                 font=("Microsoft YaHei UI", 10, "bold"), justify="left",
                                 wraplength=wrap)
            cond_lbl.pack(anchor="w")
            self._wrap_labels.append(cond_lbl)
            if effect:
                skill_lbl = ttk.Label(block, text=effect.get("name", ""),
                                      font=("Microsoft YaHei UI", 9), justify="left",
                                      wraplength=wrap)
                skill_lbl.pack(anchor="w")
                # 缩进 12px 的说明行：换行宽度相应减 12
                desc_lbl = ttk.Label(block, text=effect.get("description", ""),
                                     font=("Microsoft YaHei UI", 9), justify="left",
                                     wraplength=max(160, wrap - 12))
                desc_lbl._wrap_inset = 12
                desc_lbl.pack(anchor="w", padx=(12, 0))
                self._wrap_labels.extend([skill_lbl, desc_lbl])
            else:
                ttk.Label(block, text="（缺少效果数据）",
                          font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        ttk.Label(f, text="").pack(pady=(0, 8))

        # 首次渲染时详情画布可能还没量到宽度，布局落定后再校正一次换行宽度
        self.after_idle(self._sync_wraplength)

    def _build_favorite_toggle(self, parent, mid: int, is_favorite: bool):
        """收藏星标（与角色参数页同一套 ttk 样式，主题切换自动跟随）。"""
        photo = load_favorite_star(18, is_favorite)
        if photo is None:
            btn = ttk.Label(parent, text="★" if is_favorite else "☆", cursor="hand2",
                            style="Favorite.TLabel",
                            foreground="#ffb300" if is_favorite else self.app._get_scheme()["border"],
                            font=("Microsoft YaHei UI", 14))
        else:
            btn = ttk.Label(parent, image=photo, cursor="hand2", style="Favorite.TLabel")
            btn.image = photo
        btn.pack(side="right", padx=(5, 0))
        btn.bind("<Button-1>", lambda e, m=mid: self._toggle_favorite(m))
        text = "已收藏 - 点击取消收藏" if is_favorite else "点击收藏该回忆卡"
        self._create_tooltip(btn, text)

    def _toggle_favorite(self, mid: int):
        self.app.toggle_favorite_memory(mid)
        # 只重画这一张卡的角标 + 刷新详情（避免 164 张整片重绘的闪烁）
        self._refresh_card_thumb(mid)
        self._show_detail(mid)

    def _create_tooltip(self, widget, text):
        def _show(event):
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
            s = self.app._get_scheme()
            tk.Label(tooltip, text=text, bg=s["surface"], fg=s["fg"], relief="solid",
                     borderwidth=1, font=("Microsoft YaHei UI", 9), padx=4, pady=2).pack()
            widget._tooltip = tooltip

        def _hide(event):
            tooltip = getattr(widget, "_tooltip", None)
            if tooltip:
                tooltip.destroy()
                widget._tooltip = None

        widget.bind("<Enter>", _show)
        widget.bind("<Leave>", _hide)
