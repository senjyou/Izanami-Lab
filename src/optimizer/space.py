"""Candidate enumeration: which position/memory layouts to evaluate.

Two axes are searched, independently or together:

* **positions** -- every legal arrangement of the five characters plus the empty
  slot across the six slots, filtered by per-character hard constraints.
* **memories** -- every legal set of six distinct shared memories, given which
  ones are pinned as required.

The spaces are enumerated lazily and never materialised in full when large: the
memory space is indexed combinatorially (rank/unrank) so C(n, k) does not have to
be built, and the search samples from it without replacement.

Position order matters and is NOT deduplicated: memories can target a specific
slot (the data carries a per-card slot bitmask), so two arrangements that differ
only by which character stands in which same-row slot can genuinely score
differently. That is why the space is the full 6! = 720 rather than a
row-collapsed set.
"""

import copy
import itertools
import math
import random

from src.optimizer.snapshot import SnapshotError

SLOT_COUNT = 6
ALLY_COUNT = 5
MEMORY_COUNT = 6

# Slot labels, index 0 == slot 1. Front row is 1-3, back row 4-6.
SLOT_LABELS = ("1 左前", "2 中前", "3 右前", "4 左后", "5 中后", "6 右后")
FRONT_SLOTS = (1, 2, 3)
BACK_SLOTS = (4, 5, 6)

# Position rule kinds accepted from a saved constraint.
RULE_KINDS = ("any", "front", "back", "fixed", "keep")
RULE_LABELS = ("不限", "必须前排", "必须后排", "保持当前位置", *SLOT_LABELS)


def _allowed_slots(rule, current_index):
    """Return the 0-based slot indices a character with this rule may occupy."""
    kind = (rule or {}).get("kind", "any")
    if kind not in RULE_KINDS:
        raise SnapshotError(f"未知的站位约束类型：{kind!r}")
    if kind in ("fixed", "keep"):
        slot = rule.get("position", current_index + 1)
        if kind == "keep" and not rule.get("position"):
            slot = current_index + 1
        if not isinstance(slot, int) or isinstance(slot, bool) \
                or not 1 <= slot <= SLOT_COUNT:
            raise SnapshotError(f"固定站位必须是 1-{SLOT_COUNT} 的整数")
        return {slot - 1}
    if kind == "front":
        return {s - 1 for s in FRONT_SLOTS}
    if kind == "back":
        return {s - 1 for s in BACK_SLOTS}
    return set(range(SLOT_COUNT))


def legal_positions(state, position_rules=None):
    """Enumerate legal slot arrangements as tuples of length 6.

    The current arrangement, when legal, is yielded first so that the baseline is
    always evaluated and can act as a fallback champion.
    """
    positions = list(state["friend_positions"])
    characters = sorted(c for c in positions if c is not None)
    if len(characters) != ALLY_COUNT:
        raise SnapshotError(f"位置枚举需要恰好 {ALLY_COUNT} 名角色")

    current = tuple(positions)
    rules = {}
    for raw_id, rule in (position_rules or {}).items():
        try:
            cid = int(raw_id)
        except (TypeError, ValueError):
            raise SnapshotError(f"站位约束角色编号无效：{raw_id!r}") from None
        if cid not in characters:
            raise SnapshotError(f"站位约束角色 {cid} 不在上场阵容中")
        if cid in rules:
            raise SnapshotError(f"角色 {cid} 存在重复的站位约束")
        rules[cid] = rule

    allowed = {}
    for cid in characters:
        current_index = positions.index(cid)
        allowed[cid] = _allowed_slots(rules.get(cid), current_index)

    out = []
    for arrangement in itertools.permutations(characters + [None]):
        if all(arrangement.index(cid) in slots for cid, slots in allowed.items()):
            out.append(arrangement)
    if not out:
        detail = "；".join(f"{cid}: {rules[cid]}" for cid in rules) or "无约束"
        raise SnapshotError(f"站位约束互相冲突，没有合法排列（{detail}）")

    if current in out:
        out.remove(current)
        out.insert(0, current)
    return out


# --------------------------------------------------------------------------- #
# Memory space
# --------------------------------------------------------------------------- #

def memory_space(state, constraints):
    """Return (required_ids, candidate_pool, combinations_total).

    A shared memory's effect does not depend on which slot holds it, so the space
    is combinations of a SET, not permutations.
    """
    marks = (constraints or {}).get("memories", {})
    required = sorted({int(mid) for mid, mark in marks.items() if mark == "必选"})
    pool = sorted({int(mid) for mid, mark in marks.items() if mark == "候选"})
    pool = [mid for mid in pool if mid not in required]
    need = MEMORY_COUNT - len(required)
    if need < 0:
        raise SnapshotError(f"必选回忆不能超过 {MEMORY_COUNT} 张")
    if len(pool) < need:
        raise SnapshotError(
            f"候选回忆不足：需要 {need} 张，只有 {len(pool)} 张")
    return required, pool, math.comb(len(pool), need)


def unrank_combination(pool, k, rank):
    """Return the ``rank``-th k-combination of ``pool`` (lexicographic)."""
    result = []
    start = 0
    for remaining in range(k, 0, -1):
        for index in range(start, len(pool)):
            count = math.comb(len(pool) - index - 1, remaining - 1)
            if rank < count:
                result.append(pool[index])
                start = index + 1
                break
            rank -= count
    return tuple(result)


def rank_combination(pool, chosen):
    """Inverse of :func:`unrank_combination`."""
    index_of = {value: i for i, value in enumerate(pool)}
    rank = 0
    start = 0
    chosen = sorted(chosen)
    for position, value in enumerate(chosen):
        i = index_of[value]
        for j in range(start, i):
            rank += math.comb(len(pool) - j - 1, len(chosen) - position - 1)
        start = i + 1
    return rank


class MemorySpace:
    """Sampling helper over legal memory sets, without materialising them."""

    def __init__(self, state, constraints):
        self.required, self.pool, self.total = memory_space(state, constraints)
        self.need = MEMORY_COUNT - len(self.required)
        current = sorted(m for m in state["memory_ids"]
                         if m not in set(self.required))
        # The current set may be incomplete (e.g. a required card was added
        # later); fall back to rank 0 so there is always a starting point.
        try:
            self.initial_rank = rank_combination(self.pool, current) \
                if len(current) == self.need else 0
        except (ValueError, KeyError):
            self.initial_rank = 0

    def at(self, rank):
        """Return the sorted memory id tuple at ``rank``."""
        return tuple(sorted(set(self.required)
                            | set(unrank_combination(self.pool, self.need, rank))))

    def sample_ranks(self, capacity, rng):
        """Return up to ``capacity`` ranks, current set first, without repeats."""
        capacity = min(self.total, max(0, capacity))
        if not capacity:
            return []
        if capacity >= self.total:
            return list(range(self.total))
        picks = {self.initial_rank}
        # Floyd-style sampling: no replacement, no allocation of the full space.
        for j in range(self.total - capacity, self.total):
            candidate = rng.randrange(j + 1)
            picks.add(j if candidate in picks else candidate)
        picks.discard(self.initial_rank)
        rest = list(picks)
        rng.shuffle(rest)
        return [self.initial_rank] + rest[:capacity - 1]

    def ranks(self, capacity, rng):
        """Alias kept for readability at call sites."""
        return self.sample_ranks(capacity, rng)


# --------------------------------------------------------------------------- #
# Candidate generation
# --------------------------------------------------------------------------- #

def derive(template, positions, memories):
    """Return a new snapshot with the given position/memory assignment.

    Only the two searched fields differ, so the rest of the template (panel,
    enemy, schema) is shared by reference-free copy.
    """
    out = dict(template)
    out["friend_positions"] = list(positions)
    out["memory_ids"] = sorted(memories)
    return out


class CandidatePlan:
    """A concrete, reproducible sampling plan over the candidate space.

    The whole point is to spread a limited battle budget ACROSS the space. Taking
    the first N candidates in enumeration order would only ever examine
    arrangements that happen to sit near the current one alphabetically, so most
    of the space would never be looked at. This instead picks uniform, distinct
    (position, memory) pairs, always including the untouched baseline.
    """

    def __init__(self, template, constraints, settings, rng):
        self.template = template
        self.settings = settings
        self.change_positions = getattr(settings, "change_positions", True)
        self.change_memories = getattr(settings, "change_memories", True)

        if self.change_positions:
            self.positions = legal_positions(
                template, (constraints or {}).get("positions"))
        else:
            self.positions = [tuple(template["friend_positions"])]

        if self.change_memories:
            self.memory = MemorySpace(template, constraints)
            self.memory_total = self.memory.total
        else:
            self.memory = None
            self.memory_total = 1

        self.position_total = len(self.positions)
        self.total = self.position_total * self.memory_total
        # legal_positions puts the current arrangement first, so that index is 0.
        self.baseline_index = 0 * self.memory_total + (
            self.memory.initial_rank if self.memory else 0)
        self.rng = rng

    def memory_at(self, rank):
        return self.memory.at(rank) if self.memory else \
            tuple(sorted(self.template["memory_ids"]))

    def state_at(self, index):
        """Return (state, arrangement, memory_set) for a linear index."""
        if not 0 <= index < self.total:
            raise IndexError(index)
        position_index, memory_rank = divmod(index, self.memory_total)
        arrangement = self.positions[position_index]
        memory_set = self.memory_at(memory_rank)
        return (derive(self.template, arrangement, memory_set),
                arrangement, memory_set)

    def indices(self, count):
        """Return up to ``count`` distinct linear indices, baseline first.

        When the space is small enough to cover entirely, every index is
        returned in enumeration order (so the baseline still leads). Otherwise
        uniformly spaced distinct indices are drawn, which keeps the budget
        spread over the whole space instead of one alphabetical corner.
        """
        count = max(1, min(int(count), self.total))
        if count >= self.total:
            ordered = [self.baseline_index] + [
                i for i in range(self.total) if i != self.baseline_index]
            return ordered
        pool = range(self.total)
        # random.sample over a range avoids materialising the space.
        picked = self.rng.sample(pool, count)
        if self.baseline_index in picked:
            picked.remove(self.baseline_index)
        else:
            picked = picked[:count - 1]
        return [self.baseline_index] + sorted(picked)

    def iter_states(self, count):
        for index in self.indices(count):
            yield self.state_at(index)


def space_plan(template, constraints, settings, rng=None):
    """Build a :class:`CandidatePlan` for these settings."""
    return CandidatePlan(template, constraints, settings,
                         rng or random.Random(getattr(settings, "seed", 0)))


def candidates(template, constraints, settings, count=None, rng=None):
    """Yield (state, arrangement, memory_set) triples to evaluate.

    ``count`` limits how many are produced; when omitted the whole space is
    walked in enumeration order (only sensible for small spaces).
    """
    plan = space_plan(template, constraints, settings, rng)
    total = plan.total if count is None else max(1, min(int(count), plan.total))
    yield from plan.iter_states(total)


def space_size(template, constraints, settings):
    """Return (position_count, memory_count, combined_count) for display."""
    change_positions = getattr(settings, "change_positions", True)
    change_memories = getattr(settings, "change_memories", True)
    if change_positions:
        position_count = len(legal_positions(
            template, (constraints or {}).get("positions")))
    else:
        position_count = 1
    if change_memories:
        _, _, memory_count = memory_space(template, constraints)
    else:
        memory_count = 1
    return position_count, memory_count, position_count * memory_count
