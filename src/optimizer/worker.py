"""Spawn-safe background entrypoints; Tk objects never cross process boundaries."""
import traceback
import logging
import time
from pathlib import Path

from src.optimizer.engine import MODE_TACTICAL, TacticalEvaluator, make_evaluator
from src.optimizer.search import BudgetedSearch, SearchSettings
from src.optimizer.model import diagnostic_configuration_id
from src.utils.batch_simulator import _silence_worker_battle_logging


def search_worker(request, stop_event, queue):
    logger = logging.getLogger("izanami.optimizer")
    handler, log_path = None, None
    pool = search = recording = None
    try:
        if request.get("output"):
            log_path = Path(request["output"]).with_suffix(".log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        logger.info("开始优化：配置=%s 约束=%s 设置=%s",
                    diagnostic_configuration_id(request["state"]), request["constraints"], request["settings"])
        _silence_worker_battle_logging()
        initialization_started = time.monotonic()
        # Mode-aware: a circle stage needs its own controller and stage lineup, so the
        # evaluator is built through the factory rather than assuming tactical.
        evaluator = make_evaluator(request.get("mode", MODE_TACTICAL),
                                   request["base_path"],
                                   request.get("user_data_dir"),
                                   request.get("circle"))
        coordinator_initialization = time.monotonic()-initialization_started
        from src.optimizer.parallel import BattlePool
        from src.optimizer.engine import EvaluatorFactory
        settings = SearchSettings(**request["settings"])
        settings.validate()
        # The factory MUST match the mode AND be picklable: the default builds a
        # TacticalEvaluator, which on a circle state (enemy_id None) crashes every
        # worker with KeyError: None. The class keeps the mode + circle context on
        # plain attributes so it survives the spawn boundary on Windows.
        factory = EvaluatorFactory(request.get("mode", MODE_TACTICAL),
                                   request.get("circle"))
        pool = BattlePool(evaluator, request["base_path"], request.get("user_data_dir"),
                          requested=settings.battle_workers, stop=stop_event.is_set,
                          factory=factory)
        pool.stats["coordinator_initialization_seconds"] = coordinator_initialization
        try:
            from src.learning.store import EvaluationStore
            from src.learning.fingerprint import build_fingerprint
            from src.learning.collector import RecordingSession
            store=EvaluationStore(request.get('learning_path'))
            if store.get_setting('collection',True):
                recording=RecordingSession(store,evaluator,build_fingerprint(request['base_path']),
                    request['state'],request['constraints'],request['settings'],
                    warning=lambda text:queue.put({'type':'learning_warning','message':text})).attach(pool)
                pool.cohort_observer=recording.completed  # Same observer, new transport; cache commits first.
        except Exception as exc:
            logger.exception('学习数据采集初始化失败；原优化搜索继续')
            queue.put({'type':'learning_warning','message':f'学习采集不可用：{exc}；原搜索继续。'})
        search = BudgetedSearch(pool, request["state"], request["constraints"],
                                settings, stop_event.is_set,
                                lambda result: queue.put({"type": "progress", "result": result}),
                                request.get("output"),
                                heartbeat=lambda result: queue.put({"type":"progress","result":result}))
        result=search.run()
        if recording:
            status='stopped' if '用户' in result.get('termination_reason','') else 'completed'
            recording.finish(status,result)
    except Exception as exc:
        error_trace=traceback.format_exc()
        if recording:recording.finish("failed")
        if pool:
            pool.close()
        if search:
            try:search.finish("数据错误或模拟异常" if settings.search_kind=='layered' else "战斗评价失败", str(exc), stopped=True)
            except Exception:logger.exception("失败结果保存失败；原始错误仍反馈到GUI")
        logger.exception("优化失败：配置=%s 角色=%s 模块=%s",
                         diagnostic_configuration_id(request.get("state", {})),
                         request.get("state", {}).get("friend_positions"),
                         request.get("state", {}).get("panel", {}).get("modules"))
        queue.put({"type": "error", "message": error_trace, "summary": str(exc),
                   "diagnostic_log": str(log_path) if log_path else None})
    finally:
        if pool:
            pool.close()
        if handler:
            logger.removeHandler(handler)
            handler.close()
        queue.put({"type": "exit"})


def replay_worker(request, queue):
    try:
        _silence_worker_battle_logging()
        from src.combat_v2.battle_narrative import BattleNarrativeWriter
        evaluator = TacticalEvaluator(request["base_path"], request.get("user_data_dir"))
        narrative = BattleNarrativeWriter()
        score = evaluator.evaluate(request["state"], request["seed"], narrative=narrative)
        narrative.write(request["path"])
        queue.put({"type": "replay", "path": request["path"], "score": score, "seed": request["seed"]})
    except Exception:
        queue.put({"type": "error", "message": traceback.format_exc()})
    finally:
        queue.put({"type": "exit"})
