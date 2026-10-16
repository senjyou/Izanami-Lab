"""Spawn-only battle service. The coordinator owns order, cache and budget.

Bounded cohorts may share workers within a phase, one task per worker (no backlog).
A stopped/incomplete cohort is cached but never published as a comparable mean.
"""
import math
import multiprocessing as mp
from multiprocessing.connection import wait
import os
import platform
import time
import threading
import traceback
from collections import deque


class EvaluationStopped(Exception):
    pass


def usable_cpus():
    count = os.cpu_count() or 1
    if hasattr(os, 'sched_getaffinity'):
        count = min(count, len(os.sched_getaffinity(0)))
    # Linux container quotas can differ greatly from the host CPU count.
    try:
        with open('/sys/fs/cgroup/cpu.max') as handle:
            quota, period = handle.read().split()
        if quota != 'max':
            count = min(count, max(1, math.ceil(int(quota) / int(period))))
    except (OSError, ValueError):
        pass
    return max(1, count)


def resolve_workers(requested):
    """Map a user request to a worker count.

    ``0`` is "自动". The earlier cap of ``min(4, cores//2)`` was a conservative
    default from the reference branch that under-used the machine: on a 16-core box
    it ran only 4 workers, which is exactly the low CPU utilisation users saw. "Auto"
    should use the machine, so it now resolves to the full core count; anyone who
    wants fewer can still pick 1/2/4/8 explicitly.
    """
    cores = usable_cpus()
    if requested == 0:
        return cores
    return min(requested, cores)


def battle_worker(connection, base_path, user_data_dir, factory=None):
    """No GUI imports, fresh RNG/battle state per task; loader initialized once."""
    try:
        parent_pid = os.getppid()
        parent_process = mp.parent_process()
        def watch_parent():
            while True:
                time.sleep(.2)
                if (parent_process is not None and not parent_process.is_alive()) or os.getppid() != parent_pid:
                    os._exit(19)  # Coordinator disappeared; do not leave an orphan.
        threading.Thread(target=watch_parent,daemon=True).start()
        started = time.monotonic()
        from src.utils.batch_simulator import _silence_worker_battle_logging
        _silence_worker_battle_logging()
        if factory is None:
            from src.optimizer.engine import TacticalEvaluator
            factory = TacticalEvaluator
        evaluator = factory(base_path, user_data_dir)
        connection.send(('ready', time.monotonic() - started))
        timings_enabled=os.environ.get('IZANAMI_OPTIMIZER_TIMINGS','1')!='0'
        while True:
            idle_began=time.monotonic() if timings_enabled else None
            task = connection.recv()
            idle_seconds=time.monotonic()-idle_began if idle_began is not None else 0.
            if task is None:
                break
            ident, key, state, seed = task
            connection.send(('started', ident))
            began = time.monotonic()
            try:
                score = evaluator.evaluate(state, seed)
                if not isinstance(score, (int, float)) or not math.isfinite(score):
                    raise ValueError('战斗引擎返回无效分数')
                connection.send(('result', ident, key, seed, score, time.monotonic()-began, idle_seconds))
            except Exception:
                connection.send(('error', ident, traceback.format_exc()))
    except EOFError:
        pass  # Coordinator closed its pipe during shutdown.
    except Exception:
        try:
            connection.send(('fatal', traceback.format_exc()))
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


class BattlePool:
    def __init__(self, evaluator, base_path, user_data_dir=None, requested=0, stop=None,
                 factory=None, task_timeout=120, stop_timeout=3):
        self.evaluator = evaluator
        self.loader = evaluator.loader if hasattr(evaluator, 'loader') else None
        self.base_path, self.user_data_dir = str(base_path), user_data_dir
        self.requested, self.count = requested, resolve_workers(requested)
        self.stop = stop or (lambda: False)
        self.factory, self.task_timeout, self.stop_timeout = factory, task_timeout, stop_timeout
        self.workers, self.ready, self.active = [], set(), {}
        self.started_ids = set()
        self.sequence = 0
        self.cohort_observer = None
        self.progress_callback = None
        self.current_phase = "unclassified"
        self.phase_stats = {}
        self.timings_enabled = os.environ.get("IZANAMI_OPTIMIZER_TIMINGS", "1") != "0"
        self.stats = dict(parallel_mode='spawn单工作进程' if self.count == 1 else 'spawn战斗池',
                          requested_workers='自动' if requested == 0 else requested,
                          actual_workers=0,
                          cpu_architecture=platform.machine(), usable_cpu_count=usable_cpus(),
                          submitted_tasks=0, started_tasks=0, completed_battles=0,
                          failed_tasks=0, cancelled_tasks=0, unknown_execution_tasks=0, worker_initialization_seconds=[],
                          batch_wait_seconds=0., battle_compute_seconds=0., worker_receive_wait_seconds=0.,
                          task_submission_seconds=0., result_collection_seconds=0., connection_wait_seconds=0.,
                          in_flight_tasks=0, running_tasks=0, dispatched_not_started_tasks=0, pending_batch_tasks=0)
        self.stats.update(cohort_batches=0,cohort_scheduler_enabled=False,
                          peak_in_flight_tasks=0,peak_active_configurations=0,
                          peak_reorder_buffer=0,worker_metrics=[],failed_task_records=[])

    def speed_preview(self, state):
        return self.evaluator.speed_preview(state)

    def _start(self):
        if self.workers:
            return
        context = mp.get_context('spawn')
        try:
            for _ in range(self.count):
                parent, child = context.Pipe()
                proc = context.Process(target=battle_worker,
                    args=(child, self.base_path, self.user_data_dir, self.factory), daemon=True)
                try:
                    proc.start()
                except Exception:
                    parent.close()
                    proc.close()
                    raise
                finally:
                    child.close()
                self.workers.append((parent, proc))
                self.stats['actual_workers'] = len(self.workers)
            self.stats['actual_workers'] = len(self.workers)
        except Exception:
            self.close()
            raise

    def evaluate_cohorts(self, cohorts, accept, *, planned_samples=None):
        """Stream (key,state,seeds); accept(key,seed,score) in dispatch order.

        One active job per worker; a bounded reorder window prevents a slow
        early task from retaining unlimited later states. No stage decisions
        are made here. Successful samples are drained even on stop/failure.
        """
        if self.stop():raise EvaluationStopped('用户主动停止')
        self._start();began=time.monotonic()
        submitted_before=self.stats['submitted_tasks']
        self.stats['pending_cohort_samples_known']=planned_samples is not None
        self.stats['cohort_batches']+=1
        self.stats['cohort_scheduler_enabled']=True
        phase=self.phase_stats.setdefault(self.current_phase,dict(completed_battles=0,battle_compute_seconds=0.,worker_receive_wait_seconds=0.))
        phase.setdefault('cohort_batches',0);phase['cohort_batches']+=1
        phase.setdefault('wall_seconds',0.)
        seen=set();seen_keys=set()
        def tasks():
            for key,state,seeds in cohorts:
                seen_keys.add(key)
                for seed in seeds:
                    pair=(key,seed)
                    if pair not in seen:
                        seen.add(pair);yield key,state,seed
        source=iter(tasks());exhausted=False;pending=None
        order=deque();submitted={};results={};errors=[];dead=set()
        stopping_since=None;abnormal=True
        # Dynamic with worker count; no fixed 4/8 cap in transport.
        reorder_limit=max(1,self.count*32)
        worker_indices={conn:index for index,(conn,_) in enumerate(self.workers)}
        while len(self.stats['worker_metrics'])<len(self.workers):
            self.stats['worker_metrics'].append(dict(completed_battles=0,battle_compute_seconds=0.,receive_wait_seconds=0.))
        def flush(force=False):
            # At a failed identity gap, successful later jobs still survive.
            identities=list(order) if force else None
            while (order if not force else identities):
                ident=identities.pop(0) if force else order[0]
                if ident not in results:
                    if force:continue
                    break
                key,state,seed=submitted[ident]
                score=results.pop(ident)
                accept(key,seed,score)
                if self.cohort_observer:self.cohort_observer(state,seed,score,self.current_phase)
                if force:order.remove(ident)
                else:order.popleft()
                del submitted[ident]
        def fail(message,ident=None):
            nonlocal stopping_since,exhausted,pending
            errors.append(message);exhausted=True;pending=None
            if len(self.stats['failed_task_records'])<32:
                key,state,seed=submitted.get(ident,(None,None,None))
                self.stats['failed_task_records'].append(dict(task_id=ident,configuration_key=key,
                    seed=seed,phase=self.current_phase,error=message))
            stopping_since=stopping_since or time.monotonic()
        try:
            while not exhausted or pending is not None or self.active or len(self.ready|dead)<len(self.workers):
                if self.stop() and stopping_since is None:
                    stopping_since=time.monotonic();exhausted=True;pending=None
                if stopping_since is None:
                    for conn,_ in self.workers:
                        if conn not in self.ready or conn in self.active or conn in dead:continue
                        if len(order)>=reorder_limit:break
                        if pending is None and not exhausted:
                            pending=next(source,None);exhausted=pending is None
                        if pending is None:break
                        key,state,seed=pending;pending=None
                        self.sequence+=1;ident=self.sequence
                        submitted[ident]=(key,state,seed)
                        send_began=time.monotonic()
                        try:conn.send((ident,key,state,seed))
                        except (OSError,EOFError):
                            # send may have partially reached the pipe: reserve
                            # its budget as a failed/unknown task, never retry.
                            self.stats['submitted_tasks']+=1;self.stats['failed_tasks']+=1
                            self.stats['unknown_execution_tasks']+=1;dead.add(conn)
                            fail('战斗任务通信提交失败；执行状态未知，未自动重试',ident);break
                        if self.timings_enabled:self.stats['task_submission_seconds']+=time.monotonic()-send_began
                        self.active[conn]=(ident,(key,seed),time.monotonic())
                        self.stats['submitted_tasks']+=1
                        submitted[ident]=(key,state,seed);order.append(ident)
                        self.stats['peak_in_flight_tasks']=max(self.stats['peak_in_flight_tasks'],len(self.active))
                        self.stats['peak_active_configurations']=max(self.stats['peak_active_configurations'],
                            len({pair[0] for _,pair,_ in self.active.values()}))
                if exhausted and pending is None and not self.active and len(self.ready|dead)==len(self.workers):
                    break  # No final idle 50ms poll after the last completion.
                connections=[conn for conn,_ in self.workers if conn not in dead]
                wait_began=time.monotonic();readable=wait(connections,timeout=.05) if connections else []
                if self.timings_enabled:self.stats['connection_wait_seconds']+=time.monotonic()-wait_began
                for conn in readable:
                    collect_began=time.monotonic()
                    try:msg=conn.recv()
                    except (EOFError,OSError):
                        ident=self.active.get(conn,(None,))[0]
                        self._lost_worker(conn);dead.add(conn);fail('战斗工作进程通信中断；未自动重试',ident);continue
                    if self.timings_enabled:self.stats['result_collection_seconds']+=time.monotonic()-collect_began
                    if msg[0]=='ready':
                        self.ready.add(conn);self.stats['worker_initialization_seconds'].append(msg[1])
                    elif msg[0]=='started':
                        if conn not in self.active or self.active[conn][0]!=msg[1]:
                            fail('战斗任务启动身份不匹配',msg[1]);continue
                        self.started_ids.add(msg[1]);self.stats['started_tasks']+=1
                    elif msg[0]=='result':
                        _,ident,key,seed,score,seconds,idle=msg
                        if conn not in self.active or self.active[conn][:2]!=(ident,(key,seed)) or not math.isfinite(score):
                            fail('战斗任务结果身份/分数不匹配',ident);continue
                        del self.active[conn];self.started_ids.discard(ident);results[ident]=score
                        self.stats['completed_battles']+=1;self.stats['battle_compute_seconds']+=seconds
                        phase['completed_battles']+=1;phase['battle_compute_seconds']+=seconds
                        metric=self.stats['worker_metrics'][worker_indices[conn]]
                        metric['completed_battles']+=1;metric['battle_compute_seconds']+=seconds
                        if self.timings_enabled:
                            self.stats['worker_receive_wait_seconds']+=idle;phase['worker_receive_wait_seconds']+=idle
                            metric['receive_wait_seconds']+=idle
                    elif msg[0] in ('error','fatal'):
                        if msg[0]=='error' and conn in self.active:
                            ident=self.active.pop(conn)[0];self.started_ids.discard(ident);self.stats['failed_tasks']+=1
                        if msg[0]=='fatal':dead.add(conn);self._lost_worker(conn)
                        fail(msg[-1],msg[1] if msg[0]=='error' else None)
                flush()
                self.stats['peak_reorder_buffer']=max(self.stats['peak_reorder_buffer'],len(results))
                for conn,proc in self.workers:
                    if conn not in dead and not proc.is_alive() and not conn.poll():
                        ident=self.active.get(conn,(None,))[0]
                        self._lost_worker(conn);dead.add(conn);fail('战斗工作进程异常退出；未自动重试',ident)
                pending_count=(max(0,planned_samples-(self.stats['submitted_tasks']-submitted_before))
                               if planned_samples is not None and stopping_since is None else int(pending is not None))
                self._notify_progress(pending_count)
                now=time.monotonic()
                if stopping_since is None and ((len(self.ready|dead)<len(self.workers) and now-began>self.task_timeout)
                        or any(now-start>self.task_timeout for _,_,start in self.active.values())):
                    ident=next((ident for ident,_,start in self.active.values() if now-start>self.task_timeout),None)
                    fail('战斗池初始化/单项战斗等待超时',ident)
                if stopping_since is not None and (not self.active or now-stopping_since>=self.stop_timeout):break
            abnormal=False
        finally:
            seconds=time.monotonic()-began
            self.stats['batch_wait_seconds']+=seconds;phase['wall_seconds']+=seconds
            phase['throughput']=phase['completed_battles']/max(.001,phase['wall_seconds'])
            phase['cohort_configuration_count']=phase.get('cohort_configuration_count',0)+len(seen_keys)
            try:flush(force=True)
            finally:
                if abnormal or self.active or errors or stopping_since is not None:self.close()
                self._notify_progress([])
        if errors:raise RuntimeError('跨阵容战斗评价失败：\n'+errors[0])
        if stopping_since is not None:raise EvaluationStopped('用户主动停止；未完成共同种子轮次不参与评分')

    def evaluate_many(self, state, key, seeds, accept):
        """accept(seed, score) is called deterministically in input order.

        All completions are committed before an error/stop is raised. Actual
        started/failed tasks are separately accounted; no retry is automatic.
        """
        seeds = list(dict.fromkeys(seeds))
        if self.stop():
            raise EvaluationStopped('用户主动停止')
        self._start()
        began = time.monotonic()
        pending = list(seeds)
        phase=self.phase_stats.setdefault(self.current_phase,dict(completed_battles=0,battle_compute_seconds=0.,worker_receive_wait_seconds=0.))
        phase.setdefault('wall_seconds',0.)
        worker_indices={conn:index for index,(conn,_) in enumerate(self.workers)}
        while len(self.stats['worker_metrics'])<len(self.workers):
            self.stats['worker_metrics'].append(dict(completed_battles=0,battle_compute_seconds=0.,receive_wait_seconds=0.))
        results, errors = {}, []
        stopping_since = None
        try:
            while pending or self.active or len(self.ready) < len(self.workers):
                if self.stop() and stopping_since is None:
                    stopping_since = time.monotonic()
                    pending.clear()  # Unsubmitted tasks do not count as cancellations.
                if stopping_since is None:
                    for conn in list(self.ready):
                        if conn not in self.active and pending:
                            seed = pending.pop(0)
                            self.sequence += 1
                            ident = self.sequence
                            send_began=time.monotonic() if self.timings_enabled else None
                            conn.send((ident, key, state, seed))
                            if send_began is not None:self.stats["task_submission_seconds"]+=time.monotonic()-send_began
                            self.active[conn] = (ident, seed, time.monotonic())
                            self.stats['submitted_tasks'] += 1
                            self.stats['peak_in_flight_tasks']=max(self.stats['peak_in_flight_tasks'],len(self.active))
                            self.stats['peak_active_configurations']=max(self.stats['peak_active_configurations'],1)
                wait_began=time.monotonic() if self.timings_enabled else None
                readable=wait([c for c, _ in self.workers], timeout=.05)
                if wait_began is not None:self.stats['connection_wait_seconds']+=time.monotonic()-wait_began
                for conn in readable:
                    try:
                        collect_began=time.monotonic() if self.timings_enabled else None
                        msg = conn.recv()
                        if collect_began is not None:self.stats["result_collection_seconds"]+=time.monotonic()-collect_began
                    except (EOFError, OSError):
                        self._lost_worker(conn)
                        raise RuntimeError('战斗工作进程退出，未返回完整结果；已停止，不自动重试')
                    if msg[0] == 'ready':
                        self.ready.add(conn)
                        self.stats['worker_initialization_seconds'].append(msg[1])
                    elif msg[0] == 'started':
                        self.started_ids.add(msg[1])
                        self.stats['started_tasks'] += 1
                    elif msg[0] == 'result':
                        _, ident, returned_key, seed, score, seconds, idle_seconds = msg
                        if conn not in self.active or self.active[conn][:2] != (ident, seed) or returned_key != key:
                            raise RuntimeError('战斗任务身份不匹配')
                        del self.active[conn]
                        self.started_ids.discard(ident)
                        results[seed] = score
                        self.stats['completed_battles'] += 1
                        self.stats['battle_compute_seconds'] += seconds
                        phase['completed_battles']+=1;phase['battle_compute_seconds']+=seconds
                        metric=self.stats['worker_metrics'][worker_indices[conn]]
                        metric['completed_battles']+=1;metric['battle_compute_seconds']+=seconds
                        if self.timings_enabled:
                            self.stats['worker_receive_wait_seconds']+=idle_seconds
                            phase['worker_receive_wait_seconds']+=idle_seconds
                            metric['receive_wait_seconds']+=idle_seconds
                    elif msg[0] in ('error', 'fatal'):
                        if msg[0] == 'error':
                            self.started_ids.discard(self.active[conn][0])
                            del self.active[conn]
                            self.stats['failed_tasks'] += 1
                        errors.append(msg[-1])
                        pending.clear()
                        stopping_since = stopping_since or time.monotonic()
                for conn, proc in self.workers:
                    if not proc.is_alive() and not conn.poll():
                        self._lost_worker(conn)
                        raise RuntimeError('战斗工作进程异常退出；未自动重试')
                self._notify_progress(pending)
                now=time.monotonic()
                if ((len(self.ready)<len(self.workers) and now-began>self.task_timeout)
                        or any(now-started>self.task_timeout for _,_,started in self.active.values())):
                    raise RuntimeError('战斗池初始化/单项战斗等待超时')
                if stopping_since is not None and (not self.active or time.monotonic()-stopping_since >= self.stop_timeout):
                    break
        finally:
            seconds=time.monotonic()-began
            self.stats['batch_wait_seconds'] += seconds;phase['wall_seconds']+=seconds
            phase['throughput']=phase['completed_battles']/max(.001,phase['wall_seconds'])
            # Commit only successful samples; preserving seed order makes cache
            # insertion/tie decisions independent of worker arrival order.
            for seed in seeds:
                if seed in results:
                    accept(seed, results[seed])
            if self.active or errors or stopping_since is not None:
                self.close()
            self._notify_progress([])
        if errors:
            raise RuntimeError('战斗工作进程评价失败：\n'+errors[0])
        if stopping_since is not None:
            raise EvaluationStopped('用户主动停止；未完成共同种子轮次不参与评分')

    def _notify_progress(self,pending):
        self.stats['in_flight_tasks']=len(self.active)
        self.stats['running_tasks']=sum(ident in self.started_ids for ident,_,_ in self.active.values())
        self.stats['dispatched_not_started_tasks']=len(self.active)-self.stats['running_tasks']
        self.stats['pending_batch_tasks']=pending if isinstance(pending,int) else len(pending)
        self.stats['reserved_tasks']=len(self.active)
        if self.progress_callback:self.progress_callback()

    def _lost_worker(self, conn):
        if conn in self.active:
            ident=self.active.pop(conn)[0]
            self.stats['failed_tasks'] += 1
            if ident not in self.started_ids:self.stats['unknown_execution_tasks'] += 1
            self.started_ids.discard(ident)

    def close(self):
        for conn, proc in self.workers:
            if conn in self.active:
                ident = self.active[conn][0]
                self.stats['failed_tasks' if ident in self.started_ids else 'cancelled_tasks'] += 1
                if ident not in self.started_ids:self.stats['unknown_execution_tasks']+=1
                if proc.is_alive():
                    proc.terminate()
            else:
                try:
                    conn.send(None)
                except (OSError, EOFError):
                    pass
        for conn, proc in self.workers:
            proc.join(timeout=.5)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=.5)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=.5)
            conn.close()
            proc.close()
        self.workers.clear()
        self.active.clear()
        self.ready.clear()
        self.started_ids.clear()
