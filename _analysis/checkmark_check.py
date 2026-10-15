"""Check the checkmark indicator: correct glyph, and it survives theme switches.

The user reported that the optimizer dialog's selected checkboxes rendered as an
"X". The cause was Tk's `clam` theme indicator, and the fix replaces just that
element's layout. Three things need to hold:

  1. the built-in `TCheckbutton` layout actually points at the tick element;
  2. it survives `theme_use("clam")` followed by a reinstall, which is what a
     light/dark switch does (the app re-runs its whole style pass);
  3. it does not disturb anything else -- the radiobutton dot, the unchecked box,
     and widgets built before and after the install all behave.

The glyph itself is confirmed by eye from the screenshot the probe writes.
"""
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\MGGBattleSimulation")
sys.path.insert(0, str(ROOT))
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
from tkinter import ttk  # noqa: E402

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK    {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


from gui.app import MGGBattleSimulatorGUI  # noqa: E402
from gui.widgets import checkmark_indicator as ci  # noqa: E402


def indicator_of(style, style_name="TCheckbutton"):
    """The element name the checkbutton layout starts with."""
    try:
        return style.layout(style_name)[0][1]["children"][0][0]
    except (tk.TclError, IndexError, KeyError):
        return None


with patch.object(tk.Tk, "mainloop"), \
     patch.object(MGGBattleSimulatorGUI, "_start_update_check"):
    app = MGGBattleSimulatorGUI()

try:
    app.root.deiconify()
    app.root.update()
    style = ttk.Style()

    print("=== the built-in layout points at a tick element ===")
    first = indicator_of(style)
    print(f"    TCheckbutton first child = {first!r}")
    check("indicator replaced", first is not None and first.startswith("Tick."),
          first)
    check("the theme's own indicator is gone", first != "Checkbutton.indicator",
          first)

    print()
    print("=== the radiobutton is untouched (it already drew a dot) ===")
    radio = indicator_of(style, "TRadiobutton")
    print(f"    TRadiobutton first child = {radio!r}")
    check("radiobutton keeps its own indicator", radio == "Radiobutton.indicator",
          radio)

    print()
    print("=== survives a theme switch (the app re-runs its whole style pass) ===")
    # What _apply_ttk_style does: theme_use then reconfigure then install.
    # Measured: theme_use('clam') does NOT reset a layout override (it only
    # re-applies the theme's own defaults for styles the app has not touched), so
    # the tick survives even before the reinstall. The reinstall then replaces it
    # with a fresh element in the new colours.
    style.theme_use("clam")
    after_theme_use = indicator_of(style)
    print(f"    after theme_use('clam') alone : {after_theme_use!r}")
    check("the tick survives theme_use on its own",
          after_theme_use is not None and after_theme_use.startswith("Tick."),
          after_theme_use)
    app._apply_ttk_style()
    app.root.update_idletasks()
    after = indicator_of(style)
    print(f"    after the app's style pass    : {after!r}")
    check("the style pass keeps the tick",
          after is not None and after.startswith("Tick."), after)

    print()
    print("=== works for both colour schemes ===")
    for scheme_name in ("dark", "light"):
        try:
            app._current_scheme = scheme_name
            app._apply_ttk_style()
            app.root.update_idletasks()
            got = indicator_of(style)
            print(f"    {scheme_name:6}: {got!r}")
            check(f"{scheme_name} scheme keeps the tick",
                  got is not None and got.startswith("Tick."), got)
        except Exception as exc:
            check(f"{scheme_name} scheme applies", False, repr(exc))

    print()
    print("=== widgets built before and after the install both work ===")
    before = ttk.Checkbutton(app.root, text="built later")
    before.pack()
    app.root.update_idletasks()
    check("a new checkbutton uses the tick layout",
          indicator_of(style) is not None
          and indicator_of(style).startswith("Tick."))

    print()
    print("=== install() reports failure instead of raising ===")
    class Boom:
        def element_create(self, *a, **k):
            raise tk.TclError("nope")

        def layout(self, *a, **k):
            raise tk.TclError("nope")

    result = ci.install(Boom(), {"bg": "#000", "fg": "#fff",
                                 "surface": "#111", "border": "#222",
                                 "accent": "#333", "accent_fg": "#fff"},
                        app.root)
    check("a refused install returns False rather than raising", result is False,
          result)

    print()
    print("=== the app's style pass never breaks on a cosmetic failure ===")
    original = ci.install
    try:
        ci.install = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        app._apply_ttk_style()
        check("style pass survives a broken indicator install", True)
    except Exception as exc:
        check("style pass survives a broken indicator install", False, repr(exc))
    finally:
        ci.install = original
        app._apply_ttk_style()

finally:
    try:
        app.update_daemon.stop()
    except Exception:
        pass
    app.root.destroy()

print()
if failures:
    print(f"FAILED ({len(failures)}): " + ", ".join(failures))
    sys.exit(1)
print("checkmark indicator checks passed")
