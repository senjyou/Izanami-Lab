"""Find the working way to give ttk's clam checkbox a real checkmark.

`clam` draws the selected checkbutton indicator as a filled box containing a
glyph that reads as an "X" at 16 px, which is the opposite of what a checkbox
means. Switching the whole app to another theme is not an option: `gui/app.py`
tunes clam extensively (buttons, entries, treeview, spinbox), and those
configure calls target clam's element names.

So the indicator itself is replaced. This probe establishes which Tk call form
actually works and what it renders, instead of guessing at the API:

  A. element_create with a NEW name, then a custom layout that uses it.
  B. element_create overriding the built-in name directly.

The result is screenshotted so the glyph can be checked by eye.
"""
import os
import sys
import tkinter as tk
from tkinter import ttk

ROOT = r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation"


def make_images(bg, surface, border, accent, accent_fg, size=15):
    """Draw unchecked / checked indicator images with PIL.

    The checked state is a filled accent box with a white tick; the unchecked
    state is an outlined box. Both are drawn at the indicator's own size so they
    drop into the layout without scaling.
    """
    from PIL import Image, ImageDraw, ImageTk

    def box(fill, outline):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, size - 1, size - 1], fill=fill, outline=outline)
        return img

    off = box(surface, border)
    on = box(accent, accent)
    # A tick, drawn as two strokes. Coordinates are proportional to the box so
    # the glyph stays centred at any size.
    d = ImageDraw.Draw(on)
    w = max(2, size // 7)
    d.line([(size * 0.22, size * 0.52), (size * 0.42, size * 0.72)],
           fill=accent_fg, width=w)
    d.line([(size * 0.42, size * 0.72), (size * 0.78, size * 0.28)],
           fill=accent_fg, width=w)
    return ImageTk.PhotoImage(off), ImageTk.PhotoImage(on)


def main():
    root = tk.Tk()
    root.geometry("300x260+80+80")
    scheme = {"bg": "#eff1f5", "fg": "#4c4f69", "surface": "#e6e9ef",
              "border": "#bcc0cc", "accent": "#1e66f5", "accent_fg": "#ffffff"}
    root.configure(bg=scheme["bg"])
    style = ttk.Style()
    style.theme_use("clam")

    keep = []
    off, on = make_images(scheme["bg"], scheme["surface"], scheme["border"],
                          scheme["accent"], scheme["accent_fg"])
    keep.extend([off, on])
    print(f"  generated indicator images: {off.width()}x{off.height()}")

    # ---- Form A: new element name + custom layout -------------------------
    print()
    print("=== form A: new element name + custom layout ===")
    try:
        style.element_create("Tick.Checkbutton.indicator", "image",
                             off, ("selected", on),
                             border=2, sticky="")
        print("    element_create OK")
    except tk.TclError as exc:
        print(f"    element_create FAILED: {exc}")
        style = None

    if style is not None:
        try:
            style.layout("Tick.TCheckbutton", [
                ("Checkbutton.padding", {"sticky": "nswe", "children": [
                    ("Tick.Checkbutton.indicator", {"side": "left", "sticky": ""}),
                    ("Checkbutton.focus", {"side": "left", "sticky": "w",
                                           "children": [
                                               ("Checkbutton.label",
                                                {"sticky": "nswe"})]}),
                ]}),
            ])
            print("    layout OK")
            v1 = tk.BooleanVar(value=True)
            v2 = tk.BooleanVar(value=False)
            ttk.Checkbutton(root, text="已选（勾）", variable=v1,
                            style="Tick.TCheckbutton").pack(anchor="w", padx=10, pady=4)
            ttk.Checkbutton(root, text="未选（空框）", variable=v2,
                            style="Tick.TCheckbutton").pack(anchor="w", padx=10, pady=4)
        except tk.TclError as exc:
            print(f"    layout FAILED: {exc}")

    # ---- Form B: override the built-in element name -----------------------
    print()
    print("=== form B: override the built-in name directly ===")
    try:
        style.element_create("Checkbutton.indicator", "image",
                             off, ("selected", on), border=2, sticky="")
        print("    override OK (built-in name replaced)")
    except tk.TclError as exc:
        print(f"    override FAILED: {exc}")

    # Controls for comparison, using whatever is now in force.
    print()
    print("=== current default style for comparison ===")
    v3 = tk.BooleanVar(value=True)
    ttk.Checkbutton(root, text="默认样式 已选", variable=v3).pack(anchor="w", padx=10, pady=4)

    root.update_idletasks()
    root.update()
    root.lift()
    root.attributes("-topmost", True)
    import time
    time.sleep(0.5)
    root.update()

    try:
        from PIL import ImageGrab
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        shot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        shot = shot.resize((shot.width * 3, shot.height * 3), 0)
        out = os.path.join(ROOT, "_analysis", "checkmark_probe.png")
        shot.save(out)
        print()
        print(f"  saved: {out} ({shot.width}x{shot.height})")
    except Exception as exc:
        print(f"  grab failed: {type(exc).__name__}: {exc}")

    root.destroy()


if __name__ == "__main__":
    main()
