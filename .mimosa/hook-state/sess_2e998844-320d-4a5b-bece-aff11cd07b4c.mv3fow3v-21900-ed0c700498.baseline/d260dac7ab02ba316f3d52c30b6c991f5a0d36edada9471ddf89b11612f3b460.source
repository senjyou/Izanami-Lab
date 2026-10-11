# -*- coding: utf-8 -*-
"""战斗结果表格面板（通用组件）。

从 gui_app.py 抽取，供 team/tactical/circle/composite 等 Tab 复用。
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from gui.constants import (
    _DARK_INPUT_BG,
    _DARK_FG,
    _DARK_SELECT_BG,
    _DARK_SELECT_FG,
)


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
