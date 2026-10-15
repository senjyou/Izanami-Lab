"""Two questions that decide the alternative approach:

Q1. How much of the memory effect is DETERMINISTIC (battle_start static buffs we
    could compute analytically, with zero battles) vs dynamic/random?
Q2. What do the highlight SELECTORS mean -- can we *construct* good positions
    from card metadata instead of searching 720 permutations?
No battles.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
mem = json.loads((ROOT / "data" / "memories.json").read_text(encoding="utf-8"))
eff = json.loads((ROOT / "data" / "memory_effects.json").read_text(encoding="utf-8"))

# ---------- Q1: trigger / effect type distribution ----------
triggers = Counter()
effects = Counter()
static_triggers = {"battle_start", "turn_start", "always"}
dynamic = Counter()
n_skills = 0
for sid, e in eff.items():
    n_skills += 1
    t = (e.get("trigger") or {}).get("type")
    triggers[t] += 1
    for b in e.get("blocks", []):
        for ef in b.get("effects", []):
            effects[ef.get("effect_type")] += 1

print("=== Q1: memory effect structure ===")
print(f"memory effect skills: {n_skills}")
print("\ntrigger types:")
for t, c in triggers.most_common():
    tag = "  <- deterministic-at-start" if t in static_triggers else ""
    print(f"   {str(t):22} {c:4}{tag}")

print("\ntop effect types:")
for t, c in effects.most_common(18):
    print(f"   {str(t):26} {c:4}")

# ---------- Q2: selector semantics ----------
print("\n=== Q2: highlight selector usage ===")
sel = Counter()
role_vals = Counter()
type_vals = Counter()
attr_vals = Counter()
base_id_vals = Counter()
for mid, card in mem.items():
    for h in card["highlights"]:
        for f in ("character_role", "character_type", "character_attribute",
                  "character_base_master_id", "character_team_master_id",
                  "character_master_id", "party_position"):
            v = h.get(f)
            if v not in (None, 0, "0", False):
                sel[f] += 1
        if h.get("character_role") not in (None, 0):
            role_vals[h["character_role"]] += 1
        if h.get("character_type") not in (None, 0):
            type_vals[h["character_type"]] += 1
        if h.get("character_attribute") not in (None, 0):
            attr_vals[h["character_attribute"]] += 1
        if h.get("character_base_master_id") not in (None, 0):
            base_id_vals[h["character_base_master_id"]] += 1

for f, c in sel.most_common():
    print(f"   {f:28} {c:4}")

print("\ncharacter_role values :", dict(role_vals))
print("character_type values :", dict(type_vals))
print("character_attribute   :", dict(attr_vals))
print(f"character_base_master_id: {len(base_id_vals)} distinct ids, "
      f"top: {base_id_vals.most_common(6)}")

# ---------- how many cards are FULLY deterministic at battle_start? ----------
print("\n=== cards whose EVERY effect triggers at battle_start (analytic-only) ===")
fully_static = []
for mid, card in mem.items():
    sids = [h.get("skill_master_id") for h in card["highlights"]]
    ts = [(eff.get(str(s)) or {}).get("trigger", {}).get("type") for s in sids]
    ts = [t for t in ts if t is not None]
    if ts and all(t in static_triggers for t in ts):
        fully_static.append(mid)
print(f"{len(fully_static)} / {len(mem)} cards "
      f"({len(fully_static)/len(mem)*100:.0f}%)")
