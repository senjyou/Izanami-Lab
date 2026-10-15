"""Decode the party_position bitmask to confirm the slot semantics.

Observed values: 1,2,4,5,7,8,16,18,32,48,56
These look like bitmasks over slots. Decode against two hypotheses:
  (A) bit (n-1) = slot n, 6 slots  -> max 63
  (B) bits in two nibbles: low nibble = front row, high nibble = back row
"""
from collections import Counter
import json
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
mem = json.loads((ROOT / "data" / "memories.json").read_text(encoding="utf-8"))

vals = Counter()
examples = {}
for mid, card in mem.items():
    for h in card.get("highlights", []):
        pp = h.get("party_position")
        if pp not in (None, 0, "0"):
            vals[pp] += 1
            examples.setdefault(pp, (mid, card["name"], h.get("skill_master_id")))

print("=== party_position bitmask decode ===")
print(f"{'value':>6} {'bits':>8} {'slots(1-6)':>18} {'front?':>7} {'back?':>6}  count")
for v in sorted(vals):
    bits = format(v, "06b")[::-1]           # bit0 = slot1
    slots = [i + 1 for i in range(6) if v & (1 << i)]
    front = [s for s in slots if s <= 3]
    back = [s for s in slots if s > 3]
    print(f"{v:>6} {bits:>8} {str(slots):>18} {str(front):>7} {str(back):>6}  {vals[v]}")

print()
print("Hypothesis check:")
print("  value 1  -> slot 1 only            (single front slot)")
print("  value 7  -> 1+2+4  = slots 1,2,3   (ENTIRE FRONT ROW)")
print("  value 56 -> 8+16+32 = slots 4,5,6  (ENTIRE BACK ROW)")
print("  value 8  -> slot 4 only            (single back slot)")
print()
print("This matches 'bit (n-1) = ally slot n', 6 slots, mask up to 63.")

print()
print("=== sample cards per mask ===")
for v in sorted(vals):
    mid, name, skill = examples[v]
    slots = [i + 1 for i in range(6) if v & (1 << i)]
    print(f"  mask {v:>2} slots {str(slots):>16}  card {mid} ({name})  skill={skill}")
