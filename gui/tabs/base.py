# -*- coding: utf-8 -*-
"""战斗 Tab 共用方法 Mixin。

从 gui_app.py 抽取 4 个战斗 Tab（TeamBattleTab / TacticalExerciseTab /
CircleBattleTab / CompositeTacticExerciseTab）的重复代码，差异通过钩子处理。

子类需保证 __init__ 中初始化以下属性：
    - self.app: 主 GUI 引用
    - self.friend_slots: List[Dict[str, Any]]
    - self.mem_friend_slots: List[Dict[str, Any]]
    - self._drag_source = None
    - self._drag_preview = None

钩子方法（子类可按需覆盖）：
    - _get_char_slots(is_enemy=False)
    - _get_mem_slots(is_enemy=False)
    - _slot_has_content(slot)
    - _after_slot_changed()
    - _on_post_display(slot, cid)
    - _swap_slots(src_slot, dst_slot, src_cid, dst_cid)
"""

import os
import tkinter as tk
from typing import Optional

from gui.constants import (
    _DARK_ACCENT,
    AVATAR_DIR,
    BANNER_DIR,
    MEMORY_CARD_DIR,
)
from gui.dialogs.char_picker import CharacterPickerDialog
from gui.dialogs.memory_picker import MemoryPickerDialog
from src.entities.memory_card import MemoryCard, MemoryHighlight


class BattleTabMixin:
    """战斗 Tab 的共用方法 Mixin。

    本 Mixin 不继承 ttk.Frame，由子类自行声明继承链
    （例如 `class FooTab(BattleTabMixin, ttk.Frame)`）。
    所有方法均依赖子类实例属性 self.app / self.friend_slots 等。
    """

    # ─────────────────── 钩子方法（默认实现） ───────────────────

    def _get_char_slots(self, is_enemy: bool = False):
        """返回指定阵营的角色槽位列表。

        默认实现：单阵营 Tab 直接返回 self.friend_slots（忽略 is_enemy）。
        TeamBattleTab 覆盖为根据 is_enemy 返回 friend/enemy 槽位；
        CompositeTacticExerciseTab 覆盖为返回当前队伍的槽位。
        """
        return self.friend_slots

    def _get_mem_slots(self, is_enemy: bool = False):
        """返回指定阵营的回忆卡槽位列表。"""
        return self.mem_friend_slots

    def _slot_has_content(self, slot) -> bool:
        """判断槽位是否有内容（用于决定是否显示拖拽预览）。

        默认实现：仅检查 cid；TeamBattleTab 覆盖为同时检查 enemy_data。
        """
        return slot["cid"] is not None

    def _after_slot_changed(self):
        """槽位内容变更后的回调（例如刷新队伍列表显示）。

        默认实现：no-op。CompositeTacticExerciseTab 覆盖为调用 _refresh_team_list。
        """
        pass

    def _on_post_display(self, slot, cid):
        """_update_slot_display 完成绘制后的回调。

        默认实现：no-op。CompositeTacticExerciseTab 覆盖为在 banner 右上角
        绘制重复角色惩罚标识。
        """
        pass

    def _swap_slots(self, src_slot, dst_slot, src_cid, dst_cid):
        """交换两个槽位的内容。

        默认实现：调用 _set_slot_char / _clear_slot。
        CompositeTacticExerciseTab 覆盖为直接操作 cid 后再刷新显示
        （避免 _update_slot_display 触发重复惩罚误判）；
        TeamBattleTab 覆盖为同时处理 enemy_data 互斥交换。
        """
        if dst_cid is not None:
            self._set_slot_char(dst_slot, src_cid)
            self._set_slot_char(src_slot, dst_cid)
        else:
            self._set_slot_char(dst_slot, src_cid)
            self._clear_slot(src_slot)

    # ─────────────────── 完全相同的方法（直接抽取） ───────────────────

    def _on_drag_motion(self, event, slot_idx, is_enemy: bool = False):
        """拖拽移动（4 个 Tab 逐字相同）。"""
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return
        dx = abs(event.x_root - self._drag_start_x)
        dy = abs(event.y_root - self._drag_start_y)
        if dx < 5 and dy < 5:
            return
        self._drag_moved = True
        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.geometry(f"+{event.x_root + 15}+{event.y_root + 15}")

    def _set_clear_btn_visible(self, slot, visible: bool):
        """控制槽位清除按钮的显示/隐藏（4 个 Tab 逐字相同）。"""
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

    @staticmethod
    def _parse_memory_card_id(entry: str) -> Optional[int]:
        """从回忆卡条目字符串解析 card_id（3 个 Tab 相同，Composite 不需要）。"""
        if not entry:
            return None
        import re
        m = re.match(r'\[(\d+)\]', entry)
        if m:
            return int(m.group(1))
        return None

    # ─────────────────── 默认实现（子类可覆盖） ───────────────────

    def _build_slot(self, parent, slot_idx, is_enemy: bool = False):
        """构建单个编队槽位（横版头像 300:144 比例）。

        默认实现：与 TacticalExerciseTab / CircleBattleTab 一致；
        TeamBattleTab 覆盖以附加 enemy_data 字段。
        """
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
            widget.bind("<ButtonPress-1>", lambda e, s=slot_idx, ie=is_enemy: self._on_drag_start(e, s, ie))
            widget.bind("<B1-Motion>", lambda e, s=slot_idx, ie=is_enemy: self._on_drag_motion(e, s, ie))
            widget.bind("<ButtonRelease-1>", lambda e, s=slot_idx, ie=is_enemy: self._on_drag_release(e, s, ie))

        return {"cid": None, "frame": slot_frame, "avatar_label": avatar_canvas,
                "name_label": name_label, "clear_btn": None,
                "slot_idx": slot_idx, "is_enemy": is_enemy}

    def _build_mem_slot(self, parent, slot_idx, is_enemy: bool = False):
        """构建单个回忆卡槽位（缩略图 + 右上角覆盖清除按钮）。"""
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
        clear_btn.bind("<Button-1>", lambda e, idx=slot_idx, ie=is_enemy: self._clear_mem_slot(idx, ie))

        for widget in [slot_frame, card_canvas]:
            widget.bind("<Button-1>", lambda e, idx=slot_idx, ie=is_enemy: self._open_mem_picker(idx, ie))

        return {"mid": None, "frame": slot_frame, "canvas": card_canvas,
                "name_label": None, "clear_btn": clear_btn,
                "slot_idx": slot_idx, "is_enemy": is_enemy}

    def _on_drag_start(self, event, slot_idx, is_enemy: bool = False):
        """开始拖拽。"""
        source_slot = self._get_char_slots(is_enemy)[slot_idx]
        has_content = self._slot_has_content(source_slot)
        self._drag_source = {"slot_idx": slot_idx, "is_enemy": is_enemy,
                              "has_char": has_content}
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_moved = False

        if has_content:
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

    def _on_drag_release(self, event, slot_idx, is_enemy: bool = False):
        """释放拖拽。

        默认实现：同阵营拖拽，使用 _swap_slots 钩子完成内容交换。
        TeamBattleTab / CompositeTacticExerciseTab 通过覆盖钩子即可复用此实现。
        """
        if not hasattr(self, "_drag_source") or self._drag_source is None:
            return

        if hasattr(self, "_drag_preview") and self._drag_preview:
            self._drag_preview.destroy()
            self._drag_preview = None

        src = self._drag_source
        self._drag_source = None

        if not src["has_char"] or not self._drag_moved:
            self._open_char_picker(src["slot_idx"], src.get("is_enemy", False))
            return

        target_widget = self.winfo_containing(event.x_root, event.y_root)
        if target_widget is None:
            return

        # 查找目标槽位（默认搜索己方与敌方两套槽位）
        target_slot = None
        found_idx = None
        found_is_enemy = None
        widget = target_widget
        while widget is not None:
            for ie in (False, True):
                slots = self._get_char_slots(ie)
                for idx, slot in enumerate(slots):
                    if widget is slot["frame"]:
                        target_slot = slot
                        found_idx = idx
                        found_is_enemy = ie
                        break
                if target_slot:
                    break
            if target_slot:
                break
            widget = widget.master

        if target_slot is None:
            return

        # 默认实现只允许同阵营拖拽（TeamBattleTab 的跨阵营行为由覆盖 _swap_slots 实现，
        # 但同阵营限制保持原行为；如需跨阵营，子类应整体覆盖 _on_drag_release）
        src_is_enemy = src.get("is_enemy", False)
        if src_is_enemy != found_is_enemy:
            return

        src_slots = self._get_char_slots(src_is_enemy)
        src_slot = src_slots[src["slot_idx"]]
        src_cid = src_slot["cid"]
        dst_cid = target_slot["cid"]

        if src["slot_idx"] == found_idx:
            return

        self._swap_slots(src_slot, target_slot, src_cid, dst_cid)
        self._after_slot_changed()

    def _open_char_picker(self, slot_idx, is_enemy: bool = False):
        """打开角色选择弹窗。"""
        dialog = CharacterPickerDialog(self, self.app, title="选择角色", for_ally=not is_enemy)
        self.wait_window(dialog)
        if dialog.result is not None:
            slot = self._get_char_slots(is_enemy)[slot_idx]
            self._set_slot_char(slot, dialog.result)
            self._after_slot_changed()

    def _open_mem_picker(self, slot_idx, is_enemy: bool = False):
        """打开回忆卡选择弹窗。"""
        slots = self._get_mem_slots(is_enemy)
        exclude = set()
        for s in slots:
            if s["mid"] is not None:
                exclude.add(s["mid"])
        current_mid = slots[slot_idx]["mid"]
        exclude.discard(current_mid)

        dlg = MemoryPickerDialog(self, self.app, title="选择回忆卡", exclude_ids=exclude)
        self.wait_window(dlg)
        if dlg.result is not None:
            self._set_mem_slot(slot_idx, dlg.result, is_enemy)

    def _set_slot_char(self, slot, cid):
        """设置槽位角色。"""
        slot["cid"] = cid
        self._update_slot_display(slot, cid)

    def _clear_slot(self, slot):
        """清除槽位。"""
        slot["cid"] = None
        self._update_slot_display(slot, None)

    def _clear_slot_by_idx(self, slot_idx, is_enemy: bool = False):
        """通过索引清除槽位。"""
        self._clear_slot(self._get_char_slots(is_enemy)[slot_idx])
        self._after_slot_changed()

    def _update_slot_display(self, slot, cid):
        """更新槽位显示。

        默认实现：与 TacticalExerciseTab / CircleBattleTab 一致；
        TeamBattleTab 覆盖以处理 enemy_data 分支；
        CompositeTacticExerciseTab 通过 _on_post_display 钩子附加重复惩罚绘制。
        """
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

        self._on_post_display(slot, cid)

    def _load_slot_avatar(self, cid):
        """加载槽位横版头像。

        默认实现：与 TacticalExerciseTab / CircleBattleTab 一致
        （优先用 banner，回退从竖版头像中心裁剪）；
        TeamBattleTab 覆盖以使用不同的裁剪比例；
        CompositeTacticExerciseTab 覆盖为简单的 resize。
        """
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

    def _set_mem_slot(self, slot_idx, mid, is_enemy: bool = False):
        """设置回忆卡槽位内容。"""
        CARD_W, CARD_H = 120, 68
        s = self.app._get_scheme()
        slot = self._get_mem_slots(is_enemy)[slot_idx]
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

    def _clear_mem_slot(self, slot_idx, is_enemy: bool = False):
        """清空回忆卡槽位。"""
        s = self.app._get_scheme()
        slot = self._get_mem_slots(is_enemy)[slot_idx]
        slot["mid"] = None
        canvas = slot["canvas"]
        clear_btn = slot["clear_btn"]
        CARD_W, CARD_H = 120, 68

        canvas.delete("all")
        canvas._card_photo = None
        canvas.create_text(CARD_W // 2, CARD_H // 2, text="点击选择",
                           fill=s["border"], font=("Microsoft YaHei UI", 8))
        clear_btn.place_forget()

    def _build_memory_cards(self, mem_entries: list) -> list:
        """构建回忆卡对象列表。

        默认实现：接受 str 列表（通过 _parse_memory_card_id 解析）或 int 列表。
        CompositeTacticExerciseTab 直接传入 int 列表，无需 _parse_memory_card_id。
        """
        cards = []
        for entry in mem_entries:
            if isinstance(entry, str):
                card_id = self._parse_memory_card_id(entry)
            else:
                card_id = entry
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
