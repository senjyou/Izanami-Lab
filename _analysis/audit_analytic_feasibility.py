"""If 92% of memory effects are static battle_start stat changes, can we compute
their effect on the team WITHOUT running a battle?

This checks whether the engine exposes the stat pipeline so an analytic model is
feasible, and what the 8% dynamic residue looks like.
No battles.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
eff = json.loads((ROOT / "data" / "memory_effects.json").read_text(encoding="utf-8"))

STAT = {"StatusAttack", "StatusDefense", "StatusMaxHp", "StatusSpeed",
        "StatusCriticalChance", "DealtDamage", "ReceivedDamage", "ReceivedHealing",
        "CriticalBonusModification"}
DYNAMIC = {"Heal", "AcquireMark", "RecoverSkillCooldown", "StatusMaxAp"}

print("=== classify every memory effect skill ===")
pure_static, has_dynamic, other = [], [], []
for sid, e in eff.items():
    t = (e.get("trigger") or {}).get("type")
    types = set()
    for b in e.get("blocks", []):
        for ef in b.get("effects", []):
            types.add(ef.get("effect_type"))
    if t != "battle_start":
        other.append((sid, t, types))
        continue
    if types <= STAT:
        pure_static.append(sid)
    else:
        has_dynamic.append((sid, sorted(types - STAT)))

total = len(eff)
print(f"  pure battle_start STATIC stat effects : {len(pure_static):4} "
      f"({len(pure_static)/total*100:.0f}%)  <- analytic, 0 battles")
print(f"  battle_start but with dynamic parts   : {len(has_dynamic):4} "
      f"({len(has_dynamic)/total*100:.0f}%)")
print(f"  non-battle_start triggers             : {len(other):4} "
      f"({len(other)/total*100:.0f}%)")

print("\n  dynamic components inside battle_start skills:")
c = Counter()
for sid, extra in has_dynamic:
    for x in extra:
        c[x] += 1
for k, v in c.most_common():
    print(f"     {k:28} {v}")

print("\n  non-battle_start trigger breakdown:")
c2 = Counter(t for _, t, _ in other)
for k, v in c2.most_common():
    print(f"     {str(k):28} {v}")

print("\n=== what the static ones touch ===")
c3 = Counter()
for sid in pure_static:
    for b in eff[sid]["blocks"]:
        for ef in b["effects"]:
            c3[ef["effect_type"]] += 1
for k, v in c3.most_common():
    print(f"     {k:28} {v}")

print("\n=== are target selectors resolvable without combat? ===")
tgt = Counter()
for sid in pure_static:
    for b in eff[sid]["blocks"]:
        tgt[b.get("target_type")] += 1
for k, v in tgt.most_common():
    print(f"     {str(k):28} {v}")
print()
print("  highlight_targets => resolved from the card's highlight selector")
print("  (party_position mask / attribute / role / type / base_master_id),")
print("  all of which are static data. So targeting IS resolvable analytically.")
