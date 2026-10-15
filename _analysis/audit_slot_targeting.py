"""Quantify slot-targeting in memory cards.

Confirms the user's correction: cards can buff the character in a designated
position. Measures how many cards/highlights are position-sensitive, and how
many are positional at all. No battles.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
mem = json.loads((ROOT / "data" / "memories.json").read_text(encoding="utf-8"))

total_cards = len(mem)
total_highlights = 0
by_party_position = Counter()
cards_with_pos = set()
cards_with_any_selector = set()
selector_fields = Counter()

SELECTOR_FIELDS = ("character_attribute", "character_base_master_id", "character_master_id",
                   "character_role", "character_team_master_id", "character_type",
                   "is_targeting_friendly_party", "party_position")

for mid, card in mem.items():
    for h in card.get("highlights", []):
        total_highlights += 1
        pp = h.get("party_position")
        if pp not in (None, 0, "0"):
            by_party_position[pp] += 1
            cards_with_pos.add(mid)
        for f in SELECTOR_FIELDS:
            if h.get(f) not in (None, 0, "0", False):
                selector_fields[f] += 1
                cards_with_any_selector.add(mid)

print("=== MEMORY CARD SLOT-TARGETING AUDIT ===")
print(f"total cards                    : {total_cards}")
print(f"total highlights               : {total_highlights}")
print(f"cards referencing party_position: {len(cards_with_pos)}"
      f"  ({len(cards_with_pos)/total_cards*100:.1f}% of cards)")
print(f"cards with ANY selector field   : {len(cards_with_any_selector)}"
      f"  ({len(cards_with_any_selector)/total_cards*100:.1f}%)")
print()
print("position values used (1-6 = slots, counting highlights):")
for k in sorted(by_party_position, key=lambda x: (str(type(x)), str(x))):
    print(f"   party_position={k!r:>6} : {by_party_position[k]} highlights")
print()
print("selector-field usage (highlights referencing each):")
for f in SELECTOR_FIELDS:
    print(f"   {f:32} {selector_fields.get(f,0)}")

# How many cards target a SPECIFIC slot vs rely on the generic highlight mechanism?
print()
print("=== interpretation ===")
if cards_with_pos:
    ex = sorted(cards_with_pos)[:8]
    print(f"example slot-targeting cards: {ex}")
    c = mem[ex[0]]
    print(f"  card {ex[0]} ({c['name']}):")
    for h in c["highlights"]:
        print("   ", json.dumps(h, ensure_ascii=False)[:220])
print()
print("=== cards with party_position=None (position-agnostic highlight) ===")
none_ct = sum(1 for mid, c in mem.items() for h in c.get("highlights", [])
              if h.get("party_position") in (None, 0, "0"))
print("highlights with no slot restriction:", none_ct, "/", total_highlights)
