"""Proxy-correlation experiment: can an ANALYTIC model rank configurations?

Design
------
For N sampled (position, memory) configurations we compute, for the SAME battle:
  * a STATIC STAT VECTOR taken right after memory effects are applied and BEFORE
    turn 1 begins  (this is exactly what an analytic layer could predict)
  * the REAL final score

Then we measure how well stat-derived proxies rank configurations against the
real score. If the correlation is high, an analytic pre-filter can replace most
battles. If it is low, the analytic layer can only prune.

Implementation detail: the controller applies memory effects inside
execute_battle() at line 190, so we cannot read stats before calling it. Instead
we run the battle but capture the stat vector at the earliest observable moment
by hooking the controller's start, then still let it finish to get the score.
"""
import itertools
import json
import logging
import math
import random
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.combat_v2.battle_flow_controller import BattleConfig  # noqa: E402
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController  # noqa: E402
from src.optimizer.engine import TacticalEvaluator  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]
HP = Path(__file__).parent

STAT_KEYS = ("max_hp", "attack", "defense", "speed", "critical_rate",
             "critical_damage", "favorable_damage")

# Candidate memory cards: mix of position-targeted and party-wide.
CARD_POOL = [10001, 10002, 10003, 10004, 10005, 10006, 10007, 10010, 10011, 10012]


def capture_stats_and_score(evaluator, state, seed):
    """Run one real battle; also capture ally stats right after memory setup."""
    saved = random.getstate()
    captured = {}
    try:
        random.seed(seed)
        bf, dl = evaluator.battlefield(state)
        controller = TacticalExerciseController(
            bf, BattleConfig(max_turns=5, enable_rdps=False), data_loader=dl)

        # Wrap the memory-application step so we can snapshot immediately after it,
        # which is the earliest point where an analytic model could be validated.
        original = controller._apply_memory_card_effects

        def hooked():
            original()
            for u in bf.friend_team:
                captured[u.name] = {k: float(getattr(u, k, 0.0)) for k in STAT_KEYS}
        controller._apply_memory_card_effects = hooked

        result = controller.execute_battle()
        score = float(result["score"]["total_score"])
        return score, captured
    finally:
        random.setstate(saved)


def proxies(stats):
    """Candidate analytic proxies over the 5 allies (post-memory stat vectors)."""
    if not stats:
        return {}
    vals = list(stats.values())
    out = {}
    out["sum_attack"] = sum(v["attack"] for v in vals)
    out["sum_atk_plus_spd"] = sum(v["attack"] + v["speed"] * 100 for v in vals)
    out["sum_atk_spd_cd"] = sum(v["attack"] * (1 + (v["critical_rate"] / 100) * (v["critical_damage"] / 100))
                                for v in vals)
    out["sum_hp_atk"] = sum(v["max_hp"] / 10 + v["attack"] for v in vals)
    out["sum_all_offense"] = sum(v["attack"] + v["favorable_damage"] * 500
                                 + v["critical_damage"] * 100 for v in vals)
    out["sum_atk_def_spd"] = sum(v["attack"] + v["defense"] + v["speed"] * 50 for v in vals)
    return out


def spearman(xs, ys):
    """Rank correlation, ties averaged."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def pearson(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den else 0.0


# ---------------- build the sample set ----------------
evaluator = TacticalEvaluator(str(ROOT), None)
SEEDS = [9001, 9002]                      # 2 seeds per config to reduce seed noise
rng = random.Random(4242)

configs = []
# vary positions AND memory sets so both mechanisms are exercised
pos_perms = [
    [100301, 101301, 102301, 103301, 104301, None],
    [103301, 101301, 102301, 100301, 104301, None],
    [100301, 102301, 101301, 104301, 103301, None],
    [104301, 101301, 102301, 103301, 100301, None],
    [100301, 101301, 104301, 103301, 102301, None],
    [102301, 101301, 100301, 103301, 104301, None],
]
mem_sets = [sorted(BASE["memory_ids"])]
for _ in range(11):
    cards = sorted(rng.sample(CARD_POOL, 6))
    if cards not in mem_sets:
        mem_sets.append(cards)

for p in pos_perms:
    for m in mem_sets[:2]:
        configs.append(dict(BASE, friend_positions=list(p), memory_ids=list(m)))
for m in mem_sets:
    configs.append(dict(BASE, memory_ids=list(m)))
# dedupe
seen, uniq = set(), []
for c in configs:
    k = (tuple(c["friend_positions"]), tuple(c["memory_ids"]))
    if k not in seen:
        seen.add(k)
        uniq.append(c)
configs = uniq[:20]                        # cap: 20 configs x 2 seeds = 40 battles

print(f"configs={len(configs)}  seeds/config={len(SEEDS)}  "
      f"total battles={len(configs)*len(SEEDS)}")
print()

rows = []
for i, cfg in enumerate(configs):
    scores, stat_sets = [], []
    for s in SEEDS:
        sc, st = capture_stats_and_score(evaluator, cfg, s)
        scores.append(sc)
        stat_sets.append(st)
    mean_score = statistics.mean(scores)
    # average the stat vectors across seeds (memory effects are deterministic,
    # so they should be identical; differences would reveal dynamic components)
    names = sorted(stat_sets[0]) if stat_sets[0] else []
    avg_stats = {n: {k: statistics.mean(st[n][k] for st in stat_sets) for k in STAT_KEYS}
                 for n in names}
    stable = all(stat_sets[0][n] == stat_sets[j][n]
                 for j in range(1, len(stat_sets)) for n in names) if names else None
    pr = proxies(avg_stats)
    rows.append(dict(idx=i, score=mean_score, proxies=pr, stats_stable=stable,
                     positions=cfg["friend_positions"], memories=cfg["memory_ids"]))
    print(f"  cfg {i:2}  score={mean_score:>14,.0f}  stats_stable={stable}")

print()
print("=== proxy vs real score (rank correlation over configs) ===")
ys = [r["score"] for r in rows]
names = sorted(rows[0]["proxies"])
results = []
for pname in names:
    xs = [r["proxies"][pname] for r in rows]
    sp = spearman(xs, ys)
    pe = pearson(xs, ys)
    results.append((pname, sp, pe))
for pname, sp, pe in sorted(results, key=lambda t: -abs(t[1])):
    print(f"  {pname:22} spearman={sp:+.3f}  pearson={pe:+.3f}")

best = max(results, key=lambda t: abs(t[1]))
print()
print(f"best proxy: {best[0]}  spearman={best[1]:+.3f}")

# how well does the best proxy pick the true top-k?
xs = [r["proxies"][best[0]] for r in rows]
by_proxy = [i for i, _ in sorted(enumerate(xs), key=lambda t: -t[1])]
by_true = [i for i, _ in sorted(enumerate(ys), key=lambda t: -t[1])]
for k in (3, 5):
    overlap = len(set(by_proxy[:k]) & set(by_true[:k]))
    print(f"  top-{k} overlap (proxy vs truth): {overlap}/{k}")

(HP / "proxy_experiment.json").write_text(json.dumps(
    dict(rows=[{k: v for k, v in r.items()} for r in rows],
         results=results, seeds=SEEDS), indent=1), encoding="utf-8")
print(f"\nwrote {HP/'proxy_experiment.json'}")
