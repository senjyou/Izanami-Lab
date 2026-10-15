"""Parallel battle evaluation: a spawn pool of battle workers.

Why this exists
---------------
A single battle costs ~250 ms, and that cost is the engine's own combat loop -
building the battlefield is 0.1% of it, so there is nothing to optimize away
inside a battle. The only lever is running many battles at once. The official
batch simulator already does this (`max(1, os.cpu_count())` workers); the
optimizer originally ran everything in one process, which is why it felt far
slower than a normal batch run despite costing slightly LESS per battle.

Shape of the work
-----------------
One task is (candidate state, list of seeds), not a single battle. The state is
~2.3 KB and pickles in 0.02 ms, so sending it once per candidate rather than once
per battle keeps IPC at about 0.01% of the cost of the battles it triggers. A
worker then fights several battles for the same line-up back to back.

Determinism
-----------
Each battle is explicitly seeded and depends on nothing else, so results do not
vary with the number of workers or the order tasks finish in. ``evaluate_jobs``
returns results in submission order, which keeps the search reproducible.
"""

import multiprocessing as mp
import os

from src.optimizer.engine import Evaluator

# One process per logical CPU, matching the official batch simulator's default so
# that an optimization run feels like a normal batch run.
DEFAULT_WORKERS = max(1, os.cpu_count() or 1)

# Tasks are tiny (one state plus one seed), so a worker should take several at a
# time to amortize the round trip. A battle costs ~250 ms, so a chunk of 4 still
# leaves the pool responsive to a stop request.
MIN_CHUNK = 4

# Report progress every N battles: often enough to feel live, rarely enough that
# queue traffic stays negligible.
_PROGRESS_EVERY = 8


def resolve_workers(requested, job_count):
    """Turn a user's worker choice into a real process count.

    ``0`` means automatic. The count is capped by the amount of work available, so
    a four-candidate search does not spawn sixteen processes.
    """
    if requested in (None, 0):
        wanted = DEFAULT_WORKERS
    else:
        wanted = max(1, int(requested))
    return max(1, min(wanted, max(1, job_count)))


def _chunk_size(job_count, workers):
    """Pick a chunk size that keeps every worker busy without coarse tailing."""
    if job_count <= workers:
        return 1
    return max(MIN_CHUNK, job_count // (workers * 4))


# --------------------------------------------------------------------------- #
# Worker process side
# --------------------------------------------------------------------------- #

_EVALUATOR = None


def _worker_init(base_path, user_data_dir, mode, circle_context):
    """Build one evaluator per worker process.

    Called once per worker, so the data tables are loaded once per process rather
    than once per battle. This is what makes the pool worth its startup cost.
    """
    global _EVALUATOR
    from src.optimizer.engine import silence_worker_logging
    silence_worker_logging()
    _EVALUATOR = Evaluator(base_path, user_data_dir, mode=mode,
                           circle_context=circle_context)


def _run_task(task):
    """Fight one battle. ``task`` is (state, seed)."""
    state, seed = task
    evaluator = _EVALUATOR
    if evaluator is None:                       # defensive: initializer skipped
        raise RuntimeError("战斗进程未初始化")
    return evaluator.evaluate(state, seed)


# --------------------------------------------------------------------------- #
# Parent side
# --------------------------------------------------------------------------- #

class BattlePool:
    """A spawn pool of battle workers, reused across all phases of one search.

    The pool is started once and kept for the whole run: pool startup costs about
    one battle's worth of time, so restarting it per phase would waste that.
    """

    def __init__(self, base_path, user_data_dir=None, mode="tactical",
                 circle_context=None, workers=0, progress=None, stop=None):
        self.base_path = str(base_path)
        self.user_data_dir = str(user_data_dir) if user_data_dir else None
        self.mode = mode
        self.circle_context = circle_context
        self.workers = workers
        self.progress = progress or (lambda info: None)
        self.stop = stop or (lambda: False)
        self._pool = None
        self.battles = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        """Shut the pool down without leaving orphaned processes."""
        if self._pool is not None:
            try:
                self._pool.terminate()
                self._pool.join()
            except Exception:
                pass
            self._pool = None

    # ------------------------------------------------------------------ run
    def evaluate_battles(self, tasks, phase="战斗"):
        """Fight ``tasks`` (a list of ``(state, seed)``) across the pool.

        Dispatch is per battle, not per candidate. Grouping a candidate's whole
        seed cohort into one task would pin that cohort to a single worker, so a
        search with few candidates and many seeds each would run serially however
        many workers were configured. A state pickles in ~0.02 ms against a
        ~250 ms fight, so per-battle dispatch is effectively free.

        Results come back in submission order whatever order they finish in, so a
        search produces identical output at any worker count. ``imap`` (rather
        than ``map``) also lets a stop request take effect between battles.
        """
        if not tasks:
            return []
        workers = resolve_workers(self.workers, len(tasks))
        if self._pool is None:
            context = mp.get_context("spawn")
            self._pool = context.Pool(
                processes=workers,
                initializer=_worker_init,
                initargs=(self.base_path, self.user_data_dir, self.mode,
                          self.circle_context),
            )

        chunk = _chunk_size(len(tasks), workers)
        scores = []
        for done, score in enumerate(
                self._pool.imap(_run_task, tasks, chunksize=chunk), start=1):
            scores.append(float(score))
            self.battles += 1
            if done % _PROGRESS_EVERY == 0 or done == len(tasks):
                self.progress(dict(phase=phase, done=done, total=len(tasks),
                                   battles=self.battles))
            if self.stop():
                break
        # A short list means the tail was never fought; the caller treats absent
        # scores as "not evaluated" rather than as zero.
        return scores

    # Kept for callers that want to hand a whole cohort to one worker (e.g. a
    # small verification run); the search itself uses evaluate_battles.
    def evaluate_jobs(self, jobs, phase="战斗"):
        """Fight every seed of each ``(state, seeds)`` job, in parallel."""
        tasks = []
        spans = []
        for state, seeds in jobs:
            spans.append((len(tasks), len(tasks) + len(seeds)))
            tasks.extend((state, seed) for seed in seeds)
        flat = self.evaluate_battles(tasks, phase=phase)
        out = []
        for start, end in spans:
            if end > len(flat):
                out.append(None)             # stopped before this job finished
            else:
                out.append(flat[start:end])
        return out
