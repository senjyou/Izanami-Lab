"""Does the memory system target specific position slots?

The user's correction: some memory cards buff the character standing in a
designated slot. If so, "same-row swap" is NOT equivalent -- it changes which
character receives which bonus. That also means the optimizer's bare
preselection (which evaluates positions with ZERO memories) is structurally
blind to the very mechanism that makes positions matter.

This inspects the game data to quantify how common slot-targeted effects are.
No battles.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")

mem_path = ROOT / "data" / "memories.json"
eff_path = ROOT / "data" / "memory_effects.json"

mem = json.loads(mem_path.read_text(encoding="utf-8"))
eff = json.loads(eff_path.read_text(encoding="utf-8"))

print("=== memories.json ===")
print("type:", type(mem).__name__, "count:", len(mem))
sample_key = next(iter(mem))
print("sample key:", sample_key)
print("sample entry keys:", sorted(mem[sample_key].keys())[:20])
print()
s = mem[sample_key]
for k in ("name", "rarity", "description"):
    if k in s:
        print(f"  {k}: {str(s[k])[:120]}")
if "highlights" in s:
    print("  highlights count:", len(s["highlights"]))
    print("  highlight[0]:", json.dumps(s["highlights"][0], ensure_ascii=False)[:400])

print()
print("=== memory_effects.json ===")
print("type:", type(eff).__name__, "count:", len(eff))
ek = next(iter(eff))
print("sample key:", ek)
print("sample entry:", json.dumps(eff[ek], ensure_ascii=False)[:600])
