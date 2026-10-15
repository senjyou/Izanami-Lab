"""Replication v3 -- non-fatal, per-pair diagnostics, always writes results.

v1 was invalid (missing write-back line in the swap helper: it copied the list,
swapped the copy, and returned the unmodified state). v2 died on the first pair
whose scores happened to be identical. v3 records per-pair status and continues,
and dumps the states for any pair that yields no score difference so the cause
is visible rather than assumed.

Budget: 11 pairs x 10 seeds x 2 configs = 220 battles; each pair is its own case
(20 battles), within the project's 100-per-case convention.
"""
import json
import logging
import math
import statistics
import sys
import tempfile
from itertools import combinations
from pathlib import Path

logging.disable(logging.CRITICAL)

ROOT = Path(r"F:\MGG\muv_luv_girlsgardenx_cl\Izanami-Lab-MacOS-integration-full-enhancements-v1112")
sys.path.insert(0, str(ROOT))

from src.optimizer.engine import TacticalEvaluator  # noqa: E402

HERE = Path(__file__).parent
SEEDS = list(range(8026, 8026 + 10))
BASE = json.loads((ROOT / "tests" / "fixtures" / "tactical_optimizer_v1.json").read_text(encoding="utf-8"))["state"]


def swap_positions(state, i, j):
    s = json.loads(json.dumps(state))
    p = list(s["friend_positions"])
    p[i], p[j] = p[j], p[i]
    s["friend_positions"] = p          # REQUIRED write-back
    return s


def swap_memory(state, index, replacement):
    s = json.loads(json.dumps(state))
    m = sorted(s["memory_ids"])
    m[index] = replacement
    if len(set(m)) != 6:
        return None
    s["memory_ids"] = sorted(m)
    return s


POSITION_PAIRS = [
    ("front-left <-> back-left", 0, 3),
    ("front-left <-> back-right", 0, 5),
    ("center-front <-> center-back", 1, 4),
    ("right-front <-> back-left", 2, 3),
    ("front-left <-> center-front", 0, 1),
    ("back-left <-> back-right", 3, 5),
    ("center-front <-> back-right", 1, 5),
    ("right-front <-> center-back", 2, 4),
]
MEMORY_PAIRS = [("mem slot0 swap", 0, 10010),
                ("mem slot2 swap", 2, 10012),
                ("mem slot3 swap", 3, 10013)]


def run_pair(label, a_state, b_state, kind, notes):
    same = (a_state == b_state)
    rec = dict(label=label, kind=kind, states_equal=same, status="ok")
    if same:
        rec["status"] = "INVALID_states_identical"
        notes.append(f"{label}: states identical after swap -- harness error")
        return rec
    ev = TacticalEvaluator(str(ROOT), tempfile.mkdtemp(prefix="izanami_v3_"))
    a = [ev.evaluate(a_state, s) for s in SEEDS]
    b = [ev.evaluate(b_state, s) for s in SEEDS]
    differing = sum(1 for x, y in zip(a, b) if x != y)
    rec.update(differing=differing, a=a, b=b)
    if differing == 0:
        rec["status"] = "no_score_difference"
        notes.append(f"{label}: 10/10 seeds identical -> "
                     f"A_pos={a_state['friend_positions']} B_pos={b_state['friend_positions']}")
        return rec
    d = [x - y for x, y in zip(a, b)]
    ma, mb = statistics.mean(a), statistics.mean(b)
    sda, sdb, sdd = statistics.stdev(a), statistics.stdev(b), statistics.stdev(d)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
    r = cov / (sda * sdb) if sda > 0 and sdb > 0 else 0.0
    verdicts = []
    for idx in combinations(range(len(a)), 4):
        m4a = statistics.mean(a[i] for i in idx)
        m4b = statistics.mean(b[i] for i in idx)
        verdicts.append(m4b >= m4a * 0.97)
    rec.update(mean_a=ma, mean_b=mb, sda_pct=sda / ma * 100, sdb_pct=sdb / mb * 100,
               paired_sd_pct=sdd / ma * 100, corr=r, mean_diff_pct=(ma - mb) / ma * 100,
               four_seed_pass_rate=sum(verdicts) / len(verdicts))
    return rec


notes = []
results = []
for label, i, j in POSITION_PAIRS:
    results.append(run_pair(label, BASE, swap_positions(BASE, i, j), "position", notes))
for label, idx, repl in MEMORY_PAIRS:
    st = swap_memory(BASE, idx, repl)
    if st is not None:
        results.append(run_pair(label, BASE, st, "memory", notes))

(HERE / "replication_data.json").write_text(
    json.dumps(dict(seeds=SEEDS, results=results, notes=notes), indent=1), encoding="utf-8")


def summarise(kind):
    rows = [r for r in results if r["kind"] == kind and r["status"] == "ok"]
    bad = [r for r in results if r["kind"] == kind and r["status"] != "ok"]
    out = [f"=== {kind.upper()} ==="]
    for r in rows:
        out.append(f"  {r['label']:32} d={r['differing']:2}/10 "
                   f"rawSD={r['sda_pct']:5.2f}% pairedSD={r['paired_sd_pct']:5.2f}% "
                   f"r={r['corr']:+.3f} pass4={r['four_seed_pass_rate']*100:5.1f}%")
    for r in bad:
        out.append(f"  {r['label']:32} [{r['status']}]")
    if rows:
        sdds = [r["paired_sd_pct"] for r in rows]
        rs = [r["corr"] for r in rows]
        zs = [math.atanh(max(-.999, min(.999, x))) for x in rs]
        zbar = statistics.mean(zs)
        se = (statistics.stdev(zs) / math.sqrt(len(zs))) if len(zs) > 1 else float("nan")
        out.append(f"  -> usable pairs={len(rows)}  pooled pairedSD="
                   f"{statistics.mean(sdds):.2f}%  mean rawSD="
                   f"{statistics.mean([r['sda_pct'] for r in rows]):.2f}%")
        out.append(f"  -> pooled Fisher r={math.tanh(zbar):+.3f} "
                   f"95%CI[{math.tanh(zbar-1.96*se):+.3f},{math.tanh(zbar+1.96*se):+.3f}]")
    out.append("")
    return out


text = summarise("position") + summarise("memory") + ["=== NOTES ==="] + notes
(HERE / "replication_summary.txt").write_text("\n".join(text), encoding="utf-8")
print("\n".join(text))
