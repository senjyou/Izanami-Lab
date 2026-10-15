"""Background entry point for an optimization run.

Runs in a spawned process, so everything it touches must be picklable: the
request is plain data (no Tk objects, no open handles), and results travel back
through a queue as plain dicts.

The worker holds no Tk dependency by design; the GUI side lives in
``gui/optimizer_runner.py``.
"""

import logging
import time
import traceback
from pathlib import Path

from src.optimizer.engine import silence_worker_logging
from src.optimizer.parallel import BattlePool, resolve_workers
from src.optimizer.search import Search, SearchSettings


def optimizer_worker(request, stop_event, queue):
    """Run one search and stream progress back to the caller.

    ``request`` keys:
        base_path       repository root (for the data loader)
        user_data_dir   optional user data directory
        mode            "tactical" | "circle"
        state           the template snapshot to optimize
        constraints     {"memories": {id: "必选"/"候选"}, "positions": {...}}
        settings        plain dict accepted by SearchSettings
        circle          optional {season, stage, stage_data, enemy_state_overrides}
        workers         battle processes (0 = one per CPU, matching the official
                        batch simulator's default)
    """
    logger = logging.getLogger("izanami.optimizer")
    started = time.monotonic()
    pool = None
    try:
        silence_worker_logging()
        settings = SearchSettings(**request["settings"])

        def progress(info):
            # Coarse-grained progress only: the GUI polls, so flooding the queue
            # would just add overhead.
            queue.put({"type": "progress", "info": dict(info, elapsed=time.monotonic() - started)})

        # A battle pool runs the battles across every core. Without it a search is
        # single-process and feels far slower than a normal batch run, even though
        # each individual battle costs slightly less.
        pool = BattlePool(
            request["base_path"], request.get("user_data_dir"),
            mode=request.get("mode", "tactical"),
            circle_context=request.get("circle"),
            workers=request.get("workers", 0),
            progress=progress, stop=stop_event.is_set)

        search = Search(evaluator=None, settings=settings,
                        mode=request.get("mode", "tactical"),
                        stop=stop_event.is_set, progress=progress, pool=pool)
        result = search.run(request["state"], request.get("constraints") or {},
                            request["state"])
        payload = result.to_dict()
        payload["workers"] = resolve_workers(request.get("workers", 0),
                                              max(1, len(result.candidates)))
        queue.put({"type": "done", "result": payload})
    except Exception:
        queue.put({"type": "error", "message": traceback.format_exc()})
    finally:
        if pool is not None:
            pool.close()
        queue.put({"type": "exit"})


def prepare_user_dir(path):
    """Create the optimizer results directory, returning it as a Path."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
