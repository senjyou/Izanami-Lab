"""Reproducible optimizer-only benchmark; never changes combat implementation.

python -m src.optimizer.benchmark --output /tmp/optimizer-benchmark.json
Run before/after with the same fixture, seed list and interpreter. cProfile is
separate from throughput timing; the queue test measures a local feeder roundtrip,
not macOS GUI rendering. No user configuration is saved.
"""
import argparse
import contextlib
import copy
import cProfile
import hashlib
import importlib.util
import io
import json
import logging
import multiprocessing
import pickle
import platform
import pstats
import random
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

from src.combat_v2.scoring_tracker import ScoringTracker
from src.combat_v2.battle_logger import battle_logger
from src.optimizer import engine
from src.optimizer.model import configuration_key, validate_snapshot
from src.optimizer.search import BudgetedSearch, SearchSettings, mutate
from src.utils.batch_simulator import _silence_worker_battle_logging


def measure(fn, count=50):
    started = time.perf_counter()
    for _ in range(count):
        fn()
    return (time.perf_counter() - started) / count


def benchmark(root, fixture, battles=20):
    case = json.loads(fixture.read_text(encoding="utf-8"))
    state, constraints = case["state"], case["constraints"]
    _silence_worker_battle_logging()
    assert not battle_logger().isEnabledFor(logging.INFO)
    started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        evaluator = engine.TacticalEvaluator(root)
        evaluator.evaluate(state, 2026)  # Lazy loading is included in cold startup.
    cold = time.perf_counter() - started
    seeds = list(range(2026, 2026 + battles))
    scores, samples = [], []
    # Three passes over identical seeds; profiling is deliberately excluded.
    for _ in range(3):
        started = time.perf_counter()
        scores.append([evaluator.evaluate(state, seed) for seed in seeds])
        samples.append(time.perf_counter() - started)
    assert scores[0] == scores[1] == scores[2]
    parts = {"build": 0., "score_build": 0., "validate_in_build": 0.}
    score_holder = {}
    build, score_build, validate = evaluator.battlefield, ScoringTracker.build_result, engine.validate_snapshot

    def timed(name, fn):
        def call(*args, **kwargs):
            started = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                if name == "score_build":
                    score_holder["result"] = result
                return result
            finally:
                parts[name] += time.perf_counter() - started
        return call

    started = time.perf_counter()
    with patch.object(evaluator, "battlefield", timed("build", build)), \
         patch.object(ScoringTracker, "build_result", timed("score_build", score_build)), \
         patch.object(engine, "validate_snapshot", timed("validate_in_build", validate)):
        measured = [evaluator.evaluate(state, seed) for seed in seeds]
    duration = time.perf_counter() - started
    assert measured == scores[0]
    parts["flow_controller_rng_extract"] = duration - parts["build"] - parts["score_build"]
    replay_samples, replay_reports = [], []
    for _ in range(3):
        search = BudgetedSearch(evaluator, state, constraints,
                                SearchSettings(budget=max(200, battles)))
        search.search_start = copy.deepcopy(state)
        emitted = []
        search.progress = lambda result: emitted.append(len(pickle.dumps(result)))
        started = time.perf_counter()
        replay_scores = []
        for seed in seeds:
            replay_scores.append(search.estimate(state, [seed]))
            search.report("正在搜索")
        search.report("完成", final=True)
        replay_samples.append(time.perf_counter() - started)
        replay_reports.append(len(emitted))
        assert replay_scores == scores[0]
    rng = random.Random(2026)
    report_count = 50
    search.progress = lambda result: pickle.dumps(result)
    report_time = measure(lambda: search.report("正在搜索"), report_count)
    # Force construction to separate snapshot cost from throttling (V2).
    full_report = (measure(lambda: search.report("测量完整报告", force=True), 10)
                   if hasattr(search, "reports_emitted") else report_time)
    result = search.report("性能测量", final=True)
    cache_time = measure(lambda: search.estimate(state, seeds))
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    try:
        def roundtrip():
            queue.put(result)
            queue.get(timeout=10)
        ipc = measure(roundtrip, 20)
    finally:
        queue.close()
        queue.join_thread()
    profiler = cProfile.Profile()
    profiler.enable()
    evaluator.evaluate(state, seeds[0])
    profiler.disable()
    stats = pstats.Stats(profiler)
    hotspots = []
    for (filename, line, name), (cc, nc, tt, ct, _) in sorted(
            stats.stats.items(), key=lambda item: item[1][2], reverse=True)[:15]:
        hotspots.append(dict(file=filename, line=line, function=name, calls=nc,
                             self_seconds=tt, cumulative_seconds=ct))
    init_started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        engine.TacticalEvaluator(root)
    init_only = time.perf_counter() - init_started
    return {"environment": {"python": platform.python_version(), "platform": platform.platform()},
            "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "configuration_key": configuration_key(state), "seeds": seeds, "scores": scores[0],
            "cold_init_and_first_battle_seconds": cold, "init_only_seconds": init_only,
            "throughput": {"pass_seconds": samples, "battles_per_pass": battles,
                           "battles_per_second": battles / statistics.median(samples)},
            "fixed_replay_loop": {"pass_seconds": replay_samples, "reports_per_pass": replay_reports,
                                  "battles_per_pass": battles,
                                  "battles_per_second": battles / statistics.median(replay_samples),
                                  "note": "estimate + report + pickle, fixed inputs; excludes real Tk rendering and file autosave"},
            "components_seconds_per_battle": {k: v / battles for k, v in parts.items()},
            "per_operation_seconds": {"validation": measure(lambda: validate_snapshot(state)),
                                      "score_extract": measure(lambda: float(score_holder["result"].total_score), 10000),
                                      "candidate": measure(lambda: mutate(state, constraints, SearchSettings(), rng)),
                                      "configuration_key": measure(lambda: configuration_key(state)),
                                      "cache_lookup_seed_batch": cache_time,
                                      "deepcopy": measure(lambda: copy.deepcopy(result)),
                                      "report_call": report_time, "full_report": full_report,
                                      "pickle": measure(lambda: pickle.dumps(result)),
                                      "local_queue_roundtrip": ipc},
            "report_calls_measured": report_count, "hotspots_by_self_time": hotspots,
            "INFO_enabled": battle_logger().isEnabledFor(logging.INFO),
            "notes": "build includes validate_in_build; score_build is final aggregation only; "
                     "flow includes incremental scoring and RNG setup. Queue is not Tk rendering."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--fixture", type=Path, default=root / "tests/fixtures/tactical_optimizer_v1.json")
    parser.add_argument("--battles", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path,
                        help="Optional external directory containing model-before.py, engine-before.py, search-before.py")
    args = parser.parse_args()
    if args.battles < 1:
        parser.error("battles must be positive")
    if args.baseline:
        # External snapshot of trusted local code, only for reproducible A/B tests.
        modules = {}
        for name in ("model", "engine", "search"):
            module_name = "src.optimizer." + name
            spec = importlib.util.spec_from_file_location(module_name, args.baseline / (name + "-before.py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            modules[name] = module
        globals().update(engine=modules["engine"], BudgetedSearch=modules["search"].BudgetedSearch,
                         SearchSettings=modules["search"].SearchSettings, mutate=modules["search"].mutate,
                         configuration_key=modules["model"].configuration_key,
                         validate_snapshot=modules["model"].validate_snapshot)
    result = benchmark(root, args.fixture, args.battles)
    result["implementation"] = "external-before-snapshot" if args.baseline else "current-checkout"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["throughput"], indent=2))


if __name__ == "__main__":
    main()
