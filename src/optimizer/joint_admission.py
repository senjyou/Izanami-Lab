"""First-look eligibility only; later quick review treats every candidate equally."""
import math


def tied_score(a, b):
    """Representation-level tolerance only, without display rounding/absolute floor."""
    return abs(a-b) <= 8 * max(math.ulp(a), math.ulp(b))


def target_count(total, percent):
    return min(total, max(3, math.ceil(total * percent / 100)))


def select(entries, percent, expected_positions):
    """Entries contain only completed base cohorts from the retained joint space."""
    ranked = sorted(entries, key=lambda key: (-entries[key][0], key))
    count = target_count(len(ranked), percent)
    positions = {key: tuple(entries[key][1]['friend_positions']) for key in ranked}
    groups = {}
    for key in ranked:
        groups.setdefault(positions[key], []).append(key)
    if set(map(tuple, expected_positions)) != set(groups):
        raise ValueError('联合基础覆盖站位不完整，不能使用部分覆盖产生复评代表')
    selected = ranked[:count]
    cutoff = entries[selected[-1]][0] if selected else None
    ties = [key for key in ranked[count:] if tied_score(entries[key][0], cutoff)]
    selected.extend(ties)
    global_positions = {positions[key] for key in ranked[:count]}
    covered = {positions[key] for key in selected}
    representatives = []
    for position, keys in sorted(groups.items(), key=lambda item: tuple(-1 if x is None else x for x in item[0])):
        if position not in covered:
            # Sorted by true mean then key: exact within-position ties choose
            # the smallest key, never add the whole within-position tied group.
            representatives.append(keys[0]); covered.add(position)
    selected.extend(representatives)
    ranks = {key: i+1 for i, key in enumerate(ranked)}
    tie_keys=set(ties)
    additions = [dict(configuration_key=key, positions=list(positions[key]),
        basic_mean=entries[key][0], basic_global_rank=ranks[key],
        reason='全局边界真实同分保护' if key in tie_keys else '站位最佳代表保护')
        for key in [*ties, *representatives]]
    return selected, dict(version=1, basic_joint_total=len(entries), global_target_count=count,
        boundary_mean=cutoff, boundary_tie_added_count=len(ties),
        position_representative_added_count=len(representatives),
        global_top_k_position_count=len(global_positions),
        protected_candidate_total=len(selected), review_position_count=len(covered),
        extra_protected_configurations=additions,
        baseline_extra_added=False, baseline_control_added=False,
        first_eight_completed=False, guarantee='仅保证完整首轮8种子资格；后续晋级与普通候选相同')


def estimate_candidates(total, positions, percent):
    """Typical disjoint representatives; separately report all-tied worst case."""
    target = target_count(total, percent)
    return min(total, target + max(0, positions-1))
