"""Headless adapter: fresh battle state + original five-turn tactical controller."""
import copy
import random
from collections.abc import Mapping
from dataclasses import asdict

from src.combat_v2.battle_flow_controller import BattleConfig
from src.combat_v2.tactical_exercise_controller import TacticalExerciseController
from src.data.data_loader import DataLoader
from src.data.stat_calculator import StatCalculator
from src.entities.memory_card import MemoryCard, MemoryHighlight
from src.entities_v2.battlefield_state import BattlefieldState
from src.entities_v2.enums import Position, Side
from src.optimizer.model import active_snapshot, panel_from_dict, validate_snapshot
from src.utils.batch_simulator import (
    _create_circle_battle_enemy_worker, _create_tactical_enemy_worker,
    _create_unit_worker)

MODE_TACTICAL = "tactical"
MODE_CIRCLE = "circle"
MODES = (MODE_TACTICAL, MODE_CIRCLE)

ALLY_POSITIONS = [Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT, Position.ALLY_RIGHT_FRONT,
                  Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK, Position.ALLY_RIGHT_BACK]
ENEMY_POSITIONS = [Position.ENEMY_LEFT_FRONT, Position.ENEMY_CENTER_FRONT, Position.ENEMY_RIGHT_FRONT,
                   Position.ENEMY_LEFT_BACK, Position.ENEMY_CENTER_BACK, Position.ENEMY_RIGHT_BACK]


def speed_rank_signature(units):
    """Inspectable initial equivalence groups, including enemies, positions and ties.

    Deliberately excludes speed magnitudes; it is NOT sufficient for cache/pruning.
    """
    groups = {}
    for unit in units:
        groups.setdefault(unit.speed, []).append((unit.unit_id, unit.position.value))
    return tuple(tuple(sorted(groups[speed])) for speed in sorted(groups, reverse=True))


class IsolatedSkills(Mapping):
    def __init__(self, source):
        self.source, self.copies = source, {}

    def __iter__(self):
        return iter(self.source)

    def __len__(self):
        return len(self.source)

    def __getitem__(self, key):
        if key not in self.copies:
            self.copies[key] = copy.deepcopy(self.source[key])
        return self.copies[key]


class BattleDataView:
    """Copy mutable parsed effects on first access, without reloading all static data."""
    def __init__(self, loader):
        self.loader = loader
        self.parsed = IsolatedSkills(loader.load_parsed_skills())
        self.custom_parsed = {}

    def __getattr__(self, name):
        return getattr(self.loader, name)

    def get_parsed_skill_data(self, skill_id):
        if skill_id < 0:
            if skill_id not in self.custom_parsed:
                self.custom_parsed[skill_id] = copy.deepcopy(self.loader.get_parsed_skill_data(skill_id))
            return self.custom_parsed[skill_id]
        return self.parsed.get(str(skill_id))

    def load_parsed_skills(self):
        return self.parsed


class TacticalEvaluator:
    def __init__(self, base_path, user_data_dir=None):
        self.loader = DataLoader(base_path=str(base_path), user_data_dir=user_data_dir)
        self.loader.load_all()
        self.loader.get_tactical_exercise_enemies()

    def battlefield(self, state):
        # Empty list is the original engine's actual no-memory semantics. Public
        # lineup input still requires six cards; only internal preselection uses it.
        validate_snapshot(state, self.loader, affixes=False, allow_empty_memories=True)
        # Optimizer boundary: the original engine consumes lists sequentially.
        # Every shared-memory set must use the same deterministic engine input.
        state = dict(state, memory_ids=sorted(state["memory_ids"]))
        dl = BattleDataView(self.loader)
        # Unused candidates may have incomplete saved configuration. They are
        # initialized only when eligible for search, never parsed into this battle.
        panel = panel_from_dict(active_snapshot(state)["panel"])
        player = panel.get_player_config()
        calc = StatCalculator(dl.load_level_lerp_data(), data_loader=dl)
        bf = BattlefieldState()
        for i, cid in enumerate(state["friend_positions"]):
            if cid is not None:
                bf.add_unit(_create_unit_worker(dl, panel, player, calc, cid, Side.ALLY, ALLY_POSITIONS[i]))
        enemy = copy.deepcopy(dl.get_tactical_exercise_enemies()[state["enemy_id"]])
        pos = ENEMY_POSITIONS[enemy.get("position", 2) - 1]
        bf.add_unit(_create_tactical_enemy_worker(dl, enemy, pos))
        for mid in state["memory_ids"]:
            m = dl.get_memory(mid)
            bf.memory_cards.append(MemoryCard(mid, m.name, m.description, m.rarity,
                                              [MemoryHighlight(**asdict(h)) for h in m.highlights]))
        return bf, dl

    def evaluate(self, state, seed, narrative=None):
        # Worker owns RNG; isolated callers still get their ambient RNG restored.
        saved_random = random.getstate()
        try:
            random.seed(seed)
            bf, dl = self.battlefield(state)
            controller = TacticalExerciseController(bf, BattleConfig(max_turns=5, enable_rdps=False),
                                                     data_loader=dl, narrative=narrative)
            result = controller.execute_battle()
            return float(result["score"]["total_score"])
        finally:
            random.setstate(saved_random)

    def speed_ranking(self, state):
        return self.speed_preview(state)[0]

    def speed_preview(self, state):
        """Both display values from one construction; no dynamic-stat caching."""
        bf, _ = self.battlefield(state)
        # This is an inspectable initial ranking, not a proof of equivalence in later phases.
        groups = {}
        for unit in bf.friend_team + bf.enemy_team:
            groups.setdefault(unit.speed, []).append(unit.name)
        return (" > ".join(" = ".join(groups[speed]) + f" ({speed})"
                           for speed in sorted(groups, reverse=True)),
                speed_rank_signature(bf.friend_team + bf.enemy_team))

    def speed_signature(self, state):
        return self.speed_preview(state)[1]

    def pruning_enemy(self, state):
        """The enemy memory-validity pruning judges this lineup against.

        The tactical exercise has exactly one enemy, so pruning compares against it.
        """
        return self.loader.get_tactical_exercise_enemies().get(state.get("enemy_id"))


class CircleEvaluator(TacticalEvaluator):
    """对抗压制战: the same battle, scored by the original circle controller.

    A circle stage differs from the tactical exercise in exactly three ways, so this
    subclass overrides only the two methods involved and leaves every other part of
    the ported evaluator untouched:

      * the enemy side is a whole stage lineup (`stage_data["enemies"]`, one or more
        units at their own positions) rather than one tactical boss;
      * scoring and win conditions come from ``CircleBattleController``, which is the
        original implementation and remains the only judge of a battle;
      * the turn budget comes from ``stage_data["max_turn"]`` instead of a fixed 5.

    Everything shared -- ally construction from the panel, memory cards, RNG handling,
    numerical output -- goes through the inherited code, so a circle search and a
    tactical search cannot drift apart in how they build the player's side.
    """

    def __init__(self, base_path, user_data_dir=None, circle_context=None):
        super().__init__(base_path, user_data_dir)
        self.circle_context = dict(circle_context or {})
        if not self.circle_context.get("stage_data"):
            raise ValueError("对抗压制战缺少阶段数据")

    def battlefield(self, state):
        validate_snapshot(state, self.loader, affixes=False,
                          allow_empty_memories=True, check_enemy=False)
        state = dict(state, memory_ids=sorted(state["memory_ids"]))
        dl = BattleDataView(self.loader)
        panel = panel_from_dict(active_snapshot(state)["panel"])
        player = panel.get_player_config()
        calc = StatCalculator(dl.load_level_lerp_data(), data_loader=dl)
        bf = BattlefieldState()
        for i, cid in enumerate(state["friend_positions"]):
            if cid is not None:
                bf.add_unit(_create_unit_worker(dl, panel, player, calc, cid,
                                                Side.ALLY, ALLY_POSITIONS[i]))
        for enemy in self.circle_context["stage_data"].get("enemies", []):
            unit = _create_circle_battle_enemy_worker(dl, copy.deepcopy(enemy))
            if unit is not None:
                bf.add_unit(unit)
        for mid in state["memory_ids"]:
            m = dl.get_memory(mid)
            bf.memory_cards.append(MemoryCard(mid, m.name, m.description, m.rarity,
                                              [MemoryHighlight(**asdict(h))
                                               for h in m.highlights]))
        return bf, dl

    def pruning_enemy(self, state):
        """The boss of this circle stage: the enemy with the most HP.

        Chosen by HP rather than by slot. `position == 5` happens to hold the boss in
        every stage this simulator ships, but the game has fielded bosses outside the
        fifth slot in earlier seasons, so a positional rule would silently name a
        regular enemy as the reference and prune against the wrong unit. HP is the
        property that makes it a boss, so it is the property used here.

        The margin is large enough to be unambiguous: in the shipped stages the boss
        has orders of magnitude more HP than the escort (e.g. 7,299,270 against
        roughly 40,000), so ties are not a practical concern -- and a tie still
        resolves deterministically by the max() order.
        """
        enemies = self.circle_context["stage_data"].get("enemies") or []
        if not enemies:
            return None
        return max(enemies, key=lambda e: e.get("hp", 0) or 0)

    def evaluate(self, state, seed, narrative=None):
        saved_random = random.getstate()
        try:
            random.seed(seed)
            bf, dl = self.battlefield(state)
            from src.combat_v2.circle_battle_controller import CircleBattleController
            stage_data = self.circle_context["stage_data"]
            config = BattleConfig(max_turns=int(stage_data.get("max_turn", 5)),
                                  enable_rdps=False)
            controller = CircleBattleController(
                bf, config, data_loader=dl, narrative=narrative,
                season=int(self.circle_context.get("season", 1)),
                stage=int(self.circle_context.get("stage", 1)),
                enemy_state_overrides=self.circle_context.get("enemy_state_overrides"))
            result = controller.execute_battle()
            return float(result["score"]["total_score"])
        finally:
            random.setstate(saved_random)


def make_evaluator(mode=MODE_TACTICAL, base_path=None, user_data_dir=None,
                   circle_context=None):
    """Build the evaluator for a mode.

    One factory so the worker never guesses: an unknown mode is rejected here rather
    than silently falling through to the tactical engine and scoring the wrong battle.
    """
    if mode == MODE_CIRCLE:
        return CircleEvaluator(base_path, user_data_dir, circle_context)
    if mode == MODE_TACTICAL:
        return TacticalEvaluator(base_path, user_data_dir)
    raise ValueError(f"未知的战斗模式：{mode!r}（可选 {'、'.join(MODES)}）")


class EvaluatorFactory:
    """A picklable ``(base_path, user_data_dir) -> evaluator`` factory for BattlePool.

    ``BattlePool`` hands this to each spawned worker process; without it the worker's
    default builds a :class:`TacticalEvaluator`, which on a circle state (``enemy_id``
    is None) crashes with ``KeyError: None`` in ``get_tactical_exercise_enemies``.

    It must be a module-level object with plain-data attributes: a closure or
    ``functools.partial`` over a nested function is NOT picklable across the spawn
    boundary on Windows, which is the very failure this class exists to avoid.
    """

    def __init__(self, mode=MODE_TACTICAL, circle_context=None):
        self.mode = mode
        self.circle_context = circle_context

    def __call__(self, base_path, user_data_dir):
        return make_evaluator(self.mode, base_path, user_data_dir,
                              self.circle_context)
