"""Render the preview strip to an image, so the result can be inspected visually.

Tk cannot screenshot itself, so the strip is drawn into an offscreen window and
each card's composed image is re-rendered with PIL directly at thumbnail size.
That mirrors what the widgets do, and produces a file that can be opened.

Output: _analysis/preview_sample.png
"""
import logging
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)
os.environ["APPDATA"] = str(ROOT / "_analysis" / "_gui_check_appdata")

import importlib.util  # noqa: E402


def _stub(name, **attrs):
    if importlib.util.find_spec(name) is not None:
        return
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


class _FakeSession:
    def __init__(self, *a, **k):
        self.headers = {}
        self.trust_env = True

    def mount(self, *a, **k):
        return None

    def get(self, *a, **k):
        raise RuntimeError("stubbed")


_stub("pywinstyles", apply_style=lambda *a, **k: None,
      change_header_color=lambda *a, **k: None,
      change_title_color=lambda *a, **k: None,
      change_border_color=lambda *a, **k: None)
_stub("requests", Session=_FakeSession, Response=type("R", (), {}),
      exceptions=types.SimpleNamespace(RequestException=Exception,
                                       Timeout=Exception, ConnectionError=Exception),
      get=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stubbed")))

import tkinter as tk  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from gui.app import MGGBattleSimulatorGUI  # noqa: E402

CHAR = [100303, None, 132301, 117302, 104302, 113301]
MEM = [30007, 30029, 30031, 30034, 30038, 30039]
CHAR2 = [100303, None, 145301, 112302, 111301, 132301]
MEM2 = [30038, 30039, 30031, 30007, 30029, 30034]

with patch.object(tk.Tk, "mainloop"), \
     patch.object(MGGBattleSimulatorGUI, "_start_update_check"):
    app = MGGBattleSimulatorGUI()

try:
    for tab_id in app.notebook.tabs():
        if app.notebook.tab(tab_id, "text") == "战术演习":
            app.notebook.select(tab_id)
            break
    app.root.deiconify()
    app.root.update()
    import time
    time.sleep(0.3)
    app.root.update()

    from gui.optimizer_preview import (
        CHAR_SUBSAMPLE, MEM_SUBSAMPLE, MEM_THUMB_H, MEM_THUMB_W,
        THUMB_H, THUMB_W)
    from gui.widgets.formation_card import (
        CARD_H, CARD_W, MEM_H, MEM_W, render_character_card,
        render_empty_card, render_memory_card, render_memory_empty,
        load_portrait)

    scheme = app._get_scheme()
    PAD = 6

    def card_image(cid):
        """Compose one character card the way the widget does, then shrink it."""
        canvas = tk.Canvas(app.root, width=CARD_W, height=CARD_H,
                           bg=scheme["bg"], highlightthickness=0)
        if cid is None:
            render_empty_card(canvas)
        else:
            character = app.data_loader.get_character_by_id(cid)
            portrait = load_portrait(cid)
            if portrait is not None:
                app.root._keep = portrait
            render_character_card(
                canvas, portrait,
                rarity=getattr(character, "rarity", None),
                attribute=getattr(character, "attribute", None),
                level=app.global_tab.get_values().get("character_level"))
        canvas.update_idletasks()
        # Pull every image item out of the canvas via Tk's own image command.
        w, h = canvas.winfo_reqwidth(), canvas.winfo_reqheight()
        out = Image.new("RGB", (w, h), scheme["bg"])
        for item in canvas.find_all():
            if canvas.type(item) != "image":
                continue
            name = canvas.itemcget(item, "image")
            x, y = canvas.coords(item)
            small = tk.PhotoImage(master=canvas)
            small.tk.call(small, "copy", name, "-subsample",
                          CHAR_SUBSAMPLE, CHAR_SUBSAMPLE)
            app.root._keep = small
            # Recover the pixels through PIL by re-loading the source art at this
            # size: the composed frame is reproducible from the same assets.
        canvas.destroy()
        return out

    def memory_image(mid):
        canvas = tk.Canvas(app.root, width=MEM_W, height=MEM_H, bg=scheme["bg"],
                           highlightthickness=0)
        if mid is None:
            render_memory_empty(canvas, scheme)
        else:
            memory = app.data_loader.get_memory(mid)
            render_memory_card(canvas, mid, getattr(memory, "rarity", 1) or 1)
        canvas.destroy()
        return Image.new("RGB", (MEM_W, MEM_H), scheme["bg"])

    # Compose the sheet directly from the source assets at thumbnail size, which
    # is what the subsample produces.
    def load_scaled(path, size):
        if not path.exists():
            return None
        return Image.open(path).convert("RGBA").resize(size, Image.LANCZOS)

    from gui.constants import (AVATAR_DIR, BANNER_DIR, FORMATION_DIR,
                               MEMORY_CARD_DIR, RARITY_DIR, ATTR_ICON_DIR)
    from gui.widgets.formation_card import (
        _frame_files, _MEM_FRAME_FILES, ATTR_ICON_MAP, CHAR_RARITY_MAP,
        MEM_RARITY_MAP)

    def compose_char(cid):
        size = (THUMB_W, THUMB_H)
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        if cid is None:
            art = load_scaled(FORMATION_DIR / "icon_bg_empty_horizontal.png", size)
            if art:
                img.alpha_composite(art, (0, 0))
            return img
        banner = BANNER_DIR / f"{cid}.png"
        src = banner if banner.exists() else AVATAR_DIR / f"{cid}.png"
        portrait = load_scaled(src, size)
        if portrait:
            img.alpha_composite(portrait, (0, 0))
        frame = load_scaled(FORMATION_DIR / _frame_files[(False, False)], size)
        if frame:
            img.alpha_composite(frame, (0, 0))
        character = app.data_loader.get_character_by_id(cid)
        rarity = getattr(character, "rarity", None)
        info = CHAR_RARITY_MAP.get(rarity) if rarity else None
        if info:
            badge_size = max(1, round(CARD_H * 38 / 74 / CHAR_SUBSAMPLE))
            badge = load_scaled(RARITY_DIR / info[1], (badge_size, badge_size))
            if badge:
                img.alpha_composite(badge, (round(CARD_W / 154 / CHAR_SUBSAMPLE), 0))
        attribute = getattr(character, "attribute", None)
        if attribute:
            a_size = max(1, round(CARD_H * 31 / 86 / CHAR_SUBSAMPLE))
            attr = load_scaled(
                ATTR_ICON_DIR / f"{ATTR_ICON_MAP.get(attribute, 'all')}.png",
                (a_size, a_size))
            if attr:
                img.alpha_composite(attr, (THUMB_W - attr.width, 0))
        return img

    def compose_mem(mid):
        size = (MEM_THUMB_W, MEM_THUMB_H)
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        memory = app.data_loader.get_memory(mid)
        rarity = getattr(memory, "rarity", 1) or 1
        art = load_scaled(MEMORY_CARD_DIR / f"{mid}.png", size)
        if art:
            img.alpha_composite(art, (0, 0))
        frame = load_scaled(
            FORMATION_DIR / _MEM_FRAME_FILES.get(rarity, _MEM_FRAME_FILES[1]), size)
        if frame:
            img.alpha_composite(frame, (0, 0))
        info = MEM_RARITY_MAP.get(rarity, MEM_RARITY_MAP[1])
        badge_size = max(1, round(MEM_THUMB_W * 0.24))
        badge = load_scaled(RARITY_DIR / info[1], (badge_size, badge_size))
        if badge:
            img.alpha_composite(badge, (0, MEM_THUMB_H - badge.height))
        return img

    print("composing sample sheet...")
    rows = [
        ("最优阵容预览                                    1 / 10   [◀ 上一页] [下一页 ▶]", None, None),
        ("#1  均值 117,675,272   波动 0.2%   较当前 +9,094,130 (+8.38%)", CHAR, MEM),
        ("#2  均值 117,563,002   波动 0.7%", CHAR2, MEM2),
        ("#3  均值 116,169,260   波动 0.6%", CHAR, MEM),
    ]

    row_h = THUMB_H + MEM_THUMB_H + 30
    sheet_w = 6 * (THUMB_W + 2) + PAD * 2
    sheet_h = row_h * len(rows) + 28
    sheet = Image.new("RGB", (sheet_w, sheet_h), scheme["bg"])
    draw = ImageDraw.Draw(sheet)

    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
        title_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
    except Exception:
        font = title_font = ImageFont.load_default()

    draw.text((PAD, 6), "最优阵容预览", fill=scheme["fg"], font=title_font)
    y = 26
    for label, chars, mems in rows:
        draw.text((PAD, y), label, fill=scheme["fg"], font=font)
        y += 16
        if not chars:                       # header / pager row only
            y += 6
            continue
        x = PAD
        for cid in chars:
            card = compose_char(cid)
            sheet.paste(card, (x, y), card)
            x += THUMB_W + 2
        y += THUMB_H + 2
        x = PAD
        for mid in mems:
            card = compose_mem(mid)
            sheet.paste(card, (x, y), card)
            x += MEM_THUMB_W + 2
        y += MEM_THUMB_H + 12

    out = ROOT / "_analysis" / "preview_sample.png"
    sheet.save(out)
    print(f"saved: {out}")
    print(f"size : {sheet.width}x{sheet.height}")

finally:
    try:
        app.update_daemon.stop()
    except Exception:
        pass
    app.root.destroy()
