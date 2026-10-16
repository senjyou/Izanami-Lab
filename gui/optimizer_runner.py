# -*- coding: utf-8 -*-
"""GUI side of an optimization run: spawn, poll, report.

The runner owns no strategy. It launches :func:`src.optimizer.worker.optimizer_worker`
in a spawned process, polls the queue from the Tk thread, and writes progress and
results into the tab's EXISTING result panel. That keeps the optimizer from
adding a tab, a panel, or a second progress widget to the application.

Cancelling is cooperative: the stop event is a shared flag the worker checks
between battles, so a stop never corrupts a partially finished cohort.
"""

import multiprocessing as mp
import queue as queue_mod
import tkinter as tk

POLL_MS = 120
MAX_MESSAGES_PER_POLL = 40


class OptimizerRunner:
    """Drives one optimization run and reports into a tab's result panel.

    ``on_finish(result)`` is called once the run settles, so the owning tab can
    enable an "apply" action without the runner knowing what applying means.
    """

    def __init__(self, app, tab, on_finish=None, on_error=None):
        self.app = app
        self.tab = tab
        self.on_finish = on_finish
        self.on_error = on_error
        self.process = None
        self.queue = None
        self.stop_event = None
        self.poll_id = None
        self.result = None
        self._finished = False

    # ------------------------------------------------------------------ public
    def busy(self):
        return self.process is not None

    def start(self, request):
        """Launch the worker. ``request`` must be plain picklable data."""
        if self.busy():
            raise RuntimeError("已有优化任务在运行")
        self.result = None
        self._finished = False

        context = mp.get_context("spawn")
        self.queue = context.Queue()
        self.stop_event = context.Event()
        # Target the algorithm-side entry point directly: it is a module-level
        # function, so spawn pickles it by qualified name and the child imports
        # only the optimizer package -- never this GUI module.
        from src.optimizer.worker import search_worker
        self.process = context.Process(
            target=search_worker,
            args=(request, self.stop_event, self.queue), daemon=False)
        self.process.start()
        self._poll()

    def stop(self):
        """Request a cooperative stop; the worker finishes its current battle."""
        if self.stop_event is not None:
            self.stop_event.set()

    def close(self):
        """Tear down without blocking the UI."""
        self._cancel_poll()
        if self.stop_event is not None:
            self.stop_event.set()
        if self.process is not None:
            self.process.join(timeout=4)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
        if self.queue is not None:
            try:
                self.queue.close()
            except Exception:
                pass
        self.process = self.queue = self.stop_event = None

    # -------------------------------------------------------------------- poll
    def _cancel_poll(self):
        if self.poll_id is not None:
            try:
                self.tab.after_cancel(self.poll_id)
            except tk.TclError:
                pass
            self.poll_id = None

    def _poll(self):
        self.poll_id = None
        if self.queue is None:
            return
        latest_heartbeat = None
        latest_full = None
        for _ in range(MAX_MESSAGES_PER_POLL):
            try:
                message = self.queue.get_nowait()
            except queue_mod.Empty:
                break
            kind = message.get("type")
            if kind == "progress":
                # The ported worker publishes every report -- heartbeat and final
                # alike -- as {"type": "progress", "result": payload}. The payload
                # carries ``progress_only`` on interim beats; a payload WITHOUT it
                # is the final result and replaces anything shown so far.
                payload = message.get("result") or {}
                if payload.get("progress_only"):
                    latest_heartbeat = payload
                else:
                    latest_full = payload
                    latest_heartbeat = None
            elif kind == "error":
                self._report_error(message.get("summary")
                                   or message.get("message", "未知错误"))
            elif kind == "exit":
                self._finished = True

        if latest_full is not None:
            self.result = latest_full
        if latest_heartbeat is not None:
            self._show_progress(latest_heartbeat)

        alive = self.process is not None and self.process.is_alive()
        if alive or not self._finished:
            # Keep draining briefly after the process dies so the final result
            # message is not lost to pipe lag.
            self.poll_id = self.tab.after(POLL_MS, self._poll)
            return
        self._finish()

    # ------------------------------------------------------------------ report
    def _show_progress(self, info):
        panel = getattr(self.tab, "_result_panel", None)
        if panel is None:
            return
        phase = info.get("phase", "搜索中")
        # The ported engine reports its battle count as ``simulations``; reading the
        # old ``battles`` key would freeze the counter at 0 for the whole run.
        battles = info.get("simulations", 0)
        stage_progress = info.get("stage_progress") or {}
        done = stage_progress.get("completed_candidates")
        total = stage_progress.get("candidate_total")
        elapsed = info.get("elapsed", 0.0)
        line = f"优化中 · {phase}：{battles:,} 场"
        if done is not None and total:
            line += f"（{done}/{total}）"
        if elapsed:
            line += f"，已用 {int(elapsed)} 秒"
        panel.set_summary(line + "\n")

    def _report_error(self, message):
        self._cancel_poll()
        panel = getattr(self.tab, "_result_panel", None)
        if panel is not None:
            panel.append_summary(f"\n❌ 优化失败：\n{message}\n")
        if self.on_error is not None:
            self.on_error(message)

    def _finish(self):
        self._cancel_poll()
        result = self.result
        panel = getattr(self.tab, "_result_panel", None)
        if panel is not None:
            if result is None:
                panel.set_summary("优化已结束，但没有返回结果。\n")
            else:
                # A text leaderboard, not a table: see gui/optimizer_report.py.
                # The panel's table area is explicitly cleared so a previous
                # run's grid cannot linger beside the new report.
                panel.set_summary(self.format_report(result))
                panel.set_tables([])
        if self.process is not None:
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.terminate()
        if self.queue is not None:
            try:
                self.queue.close()
            except Exception:
                pass
        self.process = self.queue = self.stop_event = None
        if self.on_finish is not None:
            self.on_finish(result)

    # ---------------------------------------------------------------- rendering
    def format_report(self, result):
        """Render the result as readable prose, with names and no table.

        Delegates to :mod:`gui.optimizer_report`, which owns the presentation
        rules (no identifiers, no table). The resolver is built from the app's
        data loader so ids become the names the player actually sees.
        """
        from gui.optimizer_report import NameResolver, format_report
        loader = getattr(self.app, "data_loader", None)
        return format_report(result, NameResolver(loader))

