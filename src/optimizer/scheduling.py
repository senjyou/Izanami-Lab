"""Bounded combination planning and structural diversity, outside combat rules."""
import math

from src.optimizer.model import active_snapshot, initialize_character, validate_constraints, validate_snapshot


def members(state):
    return tuple(sorted(c for c in state["friend_positions"] if c is not None))


def _unrank(pool, count, rank):
    """Lexicographic combination unranking; never materializes all C(n,k) teams."""
    chosen, start = [], 0
    for remaining in range(count, 0, -1):
        for index in range(start, len(pool) - remaining + 1):
            block = math.comb(len(pool) - index - 1, remaining - 1)
            if rank < block:
                chosen.append(pool[index])
                start = index + 1
                break
            rank -= block
    return tuple(chosen)


def _rank(pool, chosen):
    rank, start = 0, 0
    for offset, value in enumerate(chosen):
        index = pool.index(value)
        remaining = len(chosen) - offset - 1
        for skipped in range(start, index):
            rank += math.comb(len(pool) - skipped - 1, remaining)
        start = index + 1
    return rank


def plan_combinations(state, constraints, enabled, capacity, rng):
    current = members(state)
    if not enabled:
        return 1, [current] if capacity else []
    required = sorted(int(c) for c, mark in constraints["characters"].items() if mark == "必选")
    pool = sorted(int(c) for c, mark in constraints["characters"].items() if mark == "候选")
    count = 5 - len(required)
    if count < 0 or len(pool) < count:
        raise ValueError("角色约束无法组成五名不同角色")
    total = math.comb(len(pool), count)
    capacity = min(total, max(0, capacity))
    if not capacity:
        return total, []
    initial = _rank(pool, tuple(c for c in current if c not in required))
    # Floyd sampling without replacement, O(capacity), also works for huge ints.
    ranks = set()
    for j in range(total - capacity, total - 1):
        picked = rng.randrange(j + 1)
        ranks.add(j if picked in ranks else picked)
    others = [rank + (rank >= initial) for rank in sorted(ranks)]
    rng.shuffle(others)
    order = [initial] + others
    return total, [tuple(sorted(required + list(_unrank(pool, count, rank)))) for rank in order]


def combination_start(base, team, constraints, loader=None, diagnostics=None, *, optimize_affixes=True):
    positions = list(base["friend_positions"])
    retained = set(members(base)).intersection(team)
    added = iter(c for c in team if c not in retained)
    for slot, cid in enumerate(positions):
        if cid is not None and cid not in retained:
            positions[slot] = next(added)
    # Fixed-combination walks need only five configs, even for huge input pools.
    out = active_snapshot(dict(base, friend_positions=positions))
    for cid in team:
        if not optimize_affixes and cid in members(base):
            continue
        initialize_character(out, cid, loader, diagnostics, operation="组合基础起点",
                             fifth_replacement=cid not in members(base), optimize_affixes=optimize_affixes)
    validate_snapshot(out, loader, affixes=optimize_affixes)
    validate_constraints(out, constraints, loader)
    return out


def structural_signature(state):
    return (members(state), tuple(state["friend_positions"]), tuple(sorted(state["memory_ids"])))


def _affix_features(state):
    return {(cid, mi, g.get("effect_type", 0), float(g.get("value", 0)))
            for cid in members(state)
            for mi, mod in enumerate(state["panel"].get("modules", {}).get(str(cid), []))
            for g in mod.get("gear_effects", [])}


def diverse_elites(archive, limit=8):
    """Keep global leader, team champions, layout/memory structures, then affix variety.

    Diversity chooses retention only; final winner always uses engine score.
    """
    ranked = sorted(archive.items(), key=lambda item: (-item[1][0], item[0]))
    if not ranked:
        return {}
    chosen = [ranked[0]]
    seen_teams = {members(chosen[0][1][1])}
    for entry in ranked[1:]:
        team = members(entry[1][1])
        if team not in seen_teams and len(chosen) < limit:
            chosen.append(entry)
            seen_teams.add(team)
    seen_structures = {structural_signature(entry[1][1]) for entry in chosen}
    for entry in ranked:
        structure = structural_signature(entry[1][1])
        if structure not in seen_structures and len(chosen) < limit:
            chosen.append(entry)
            seen_structures.add(structure)
    selected = {entry[0] for entry in chosen}
    features = {key: _affix_features(value[1]) for key, value in ranked}
    while len(chosen) < min(limit, len(ranked)):
        # Search score is a tie-breaker after minimum structural distance.
        entry = max((entry for entry in ranked if entry[0] not in selected),
                    key=lambda entry: (min(len(features[entry[0]] ^ features[key]) for key in selected),
                                       entry[1][0], entry[0]))
        chosen.append(entry)
        selected.add(entry[0])
    return dict(chosen)
