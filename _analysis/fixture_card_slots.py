"""Which slots do the FIXTURE's 6 cards target? And what do the selectors mean?

This explains why one position pair scored identically across 10 seeds:
if none of the equipped cards targets those slots, the swap is inert --
position relevance is CONDITIONAL on the memory set. That reframes the search.
"""
import json
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
mem = json.loads((ROOT / "data" / "memories.json").read_text(encoding="utf-8"))
eff = json.loads((ROOT / "data" / "memory_effects.json").read_text(encoding="utf-8"))

FIXTURE_CARDS = [10001, 10002, 10003, 10004, 10005, 10006]


def slots_of(mask):
    return [i + 1 for i in range(6) if mask & (1 << i)]


print("=== FIXTURE'S SIX CARDS ===")
for mid in FIXTURE_CARDS:
    card = mem.get(str(mid))
    if not card:
        print(f"  {mid}: NOT FOUND")
        continue
    print(f"\n  [{mid}] {card['name']}  (rarity {card['rarity']})")
    for h in card["highlights"]:
        pp = h.get("party_position")
        mask = pp if isinstance(pp, int) else 0
        sel = {k: v for k, v in h.items()
               if k in ("character_attribute", "character_role", "character_type",
                        "character_base_master_id", "character_master_id",
                        "character_team_master_id", "is_targeting_friendly_party")
               and v not in (None, 0, False)}
        sk = h.get("skill_master_id")
        desc = ""
        e = eff.get(str(sk))
        if e:
            desc = e.get("description", "")[:70]
        print(f"     mask={pp!r:>5} slots={str(slots_of(mask)):>14} selectors={sel}")
        print(f"        skill {sk}: {desc}")

print("\n=== UNION OF TARGETED SLOTS (fixture cards only) ===")
union = 0
for mid in FIXTURE_CARDS:
    card = mem.get(str(mid))
    if card:
        for h in card["highlights"]:
            pp = h.get("party_position")
            if isinstance(pp, int):
                union |= pp
print(f"  combined mask = {union}  -> slots {slots_of(union)}")
print(f"  slots NEVER referenced by these cards: "
      f"{[s for s in range(1,7) if not (union & (1 << (s-1)))]}")
print()
print("  => a swap involving only unreferenced slots must score identically.")
print("     That is why 'back-left <-> back-right' showed 10/10 identical scores:")
print("     it is a property of THIS memory set, NOT a general equivalence.")
