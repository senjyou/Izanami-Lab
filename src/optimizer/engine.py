"""Headless battle evaluation for the optimizer.

Two game modes are supported, both reusing the official engine unchanged:

``tactical``  the five-turn tactical exercise, scored by the original
              ``TacticalExerciseController`` total score
``circle``    a circle-battle (对抗压制战) stage, season and stage supplied by
              the caller, scored by the original ``CircleBattleController``

The optimizer adds no combat rules of its own. It builds a battlefield exactly as
``src.utils.batch_simulator`` does, runs one battle, and returns the engine's own
score. That guarantees the optimizer optimizes the same number the player sees.

Each evaluation reseeds the global RNG (the engine uses the ``random`` module
directly), then restores the ambient RNG state so that a caller's own randomness
is unaffected.

Maps are deep-copied per battle through ``BattleDataView`` so that mutable parsed
skill effects written during one battle cannot leak into the next candidate.
"""

import copy
import random
from collections.abc import Mapping

from src.combat_v2.battle_flow_controller import BattleConfig
from src.entities_v2.battlefield_state import BattlefieldState
from src.entities_v2.enums import Position, Side
from src.entities.memory_card import MemoryCard, MemoryHighlight
from src.data.data_loader import DataLoader
from src.data.stat_calculator import StatCalculator
from src.optimizer.snapshot import panel_from_dict, validate
from src.utils.batch_simulator import (
    _create_circle_battle_enemy_worker,
    _create_tactical_enemy_worker,
    _create_unit_worker,
    _silence_worker_battle_logging,
)

MODE_TACTICAL = "tactical"
MODE_CIRCLE = "circle"
MODES = (MODE_TACTICAL, MODE_CIRCLE)

ALLY_POSITIONS = [Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT,
                  Position.ALLY_RIGHT_FRONT, Position.ALLY_LEFT_BACK,
                  Position.ALLY_CENTER_BACK, Position.ALLY_RIGHT_BACK]
ENEMY_POSITIONS = [Position.ENEMY_LEFT_FRONT, Position.ENEMY_CENTER_FRONT,
                   Position.ENEMY_RIGHT_FRONT, Position.ENEMY_LEFT_BACK,
                   Position.ENEMY_CENTER_BACK, Position.ENEMY_RIGHT_BACK]


class EvaluationError(RuntimeError):
    """A battle could not be built or run."""


class IsolatedSkills(Mapping):
    """Copy each parsed skill on first access.

    The engine's parsed skill data carries mutable effect state (dynamic flags
    written while a battle runs). Handing the same object to a second battle
    would let that state bleed across candidates, so each skill is copied once
    per battle view and reused within that battle only.
    """

    def __init__(self, source):
        self.source = source
        self.copies = {}

    def __iter__(self):
        return iter(self.source)

    def __len__(self):
        return len(self.source)

    def __getitem__(self, key):
        if key not in self.copies:
            self.copies[key] = copy.deepcopy(self.source[key])
        return self.copies[key]


class BattleDataView:
    """A per-battle view over the shared DataLoader.

    Static tables are read straight through; only the mutable parsed skills are
    isolated, so a battle gets a clean engine state without reloading all data.
    """

    def __init__(self, loader):
        self.loader = loader
        self.parsed = IsolatedSkills(loader.load_parsed_skills())
        self.custom_parsed = {}

    def __getattr__(self, name):
        return getattr(self.loader, name)

    def get_parsed_skill_data(self, skill_id):
        if skill_id < 0:
            if skill_id not in self.custom_parsed:
                self.custom_parsed[skill_id] = copy.deepcopy(
                    self.loader.get_parsed_skill_data(skill_id))
            return self.custom_parsed[skill_id]
        return self.parsed.get(str(skill_id))

    def load_parsed_skills(self):
        return self.parsed


class Evaluator:
    """Runs one battle for one snapshot and returns the official score."""

    def __init__(self, base_path, user_data_dir=None, mode=MODE_TACTICAL,
                 circle_context=None):
        if mode not in MODES:
            raise EvaluationError(f"未知的模拟模式：{mode!r}")
        self.mode = mode
        self.circle_context = dict(circle_context or {})
        self.loader = DataLoader(base_path=str(base_path),
                                 user_data_dir=user_data_dir)
        self.loader.load_all()
        if mode == MODE_TACTICAL:
            self.loader.get_tactical_exercise_enemies()

    # ------------------------------------------------------------------ build
    @staticmethod
    def _highlight(data):
        """Copy one memory highlight into the engine's dataclass.

        Fields are mapped explicitly rather than splatted, so a data-side field
        that the engine does not know about cannot break battle construction.
        """
        return MemoryHighlight(
            character_attribute=data.character_attribute,
            character_base_master_id=data.character_base_master_id,
            character_master_id=data.character_master_id,
            character_role=data.character_role,
            character_team_master_id=data.character_team_master_id,
            character_type=data.character_type,
            is_targeting_friendly_party=data.is_targeting_friendly_party,
            party_position=data.party_position,
            skill_master_id=data.skill_master_id,
        )

    def _memories(self, state, loader):
        cards = []
        for mid in state["memory_ids"]:
            memory = loader.get_memory(mid)
            if memory is None:
                raise EvaluationError(f"未知回忆编号 {mid}")
            cards.append(MemoryCard(
                mid, memory.name, memory.description, memory.rarity,
                [self._highlight(h) for h in memory.highlights]))
        return cards

    def battlefield(self, state):
        """Build a battlefield for one snapshot. Runs no battle."""
        validate(state, self.loader, strict_affixes=False)
        # Shared memories are a set: normalise the order so that two identical
        # sets always produce an identical engine input.
        state = dict(state, memory_ids=sorted(state["memory_ids"]))

        loader = BattleDataView(self.loader)
        panel = panel_from_dict(state["panel"])
        player = panel.get_player_config()
        calculator = StatCalculator(loader.load_level_lerp_data(),
                                    data_loader=loader)

        bf = BattlefieldState()
        for index, cid in enumerate(state["friend_positions"]):
            if cid is None:
                continue
            unit = _create_unit_worker(loader, panel, player, calculator, cid,
                                       Side.ALLY, ALLY_POSITIONS[index])
            if unit is None:
                raise EvaluationError(f"无法创建角色 {cid}")
            bf.add_unit(unit)

        self._add_enemies(bf, state, loader)
        bf.memory_cards = self._memories(state, loader)
        return bf, loader

    def _add_enemies(self, bf, state, loader):
        if self.mode == MODE_TACTICAL:
            enemy_id = state.get("enemy_id")
            enemies = loader.get_tactical_exercise_enemies()
            data = enemies.get(enemy_id)
            if data is None:
                raise EvaluationError(f"未知敌方单位 {enemy_id}")
            data = copy.deepcopy(data)
            slot = data.get("position", 2)
            position = ENEMY_POSITIONS[max(0, min(5, int(slot) - 1))]
            bf.add_unit(_create_tactical_enemy_worker(loader, data, position))
            return

        stage_data = self.circle_context.get("stage_data")
        if not stage_data:
            raise EvaluationError("对抗压制战缺少阶段数据")
        for enemy in stage_data.get("enemies", []):
            unit = _create_circle_battle_enemy_worker(loader, copy.deepcopy(enemy))
            if unit is not None:
                bf.add_unit(unit)

    # ---------------------------------------------------------------- evaluate
    def evaluate(self, state, seed):
        """Run one battle and return the official total score."""
        saved = random.getstate()
        try:
            random.seed(int(seed))
            bf, loader = self.battlefield(state)
            controller = self._controller(bf, loader)
            result = controller.execute_battle()
            score = result.get("score") or {}
            total = score.get("total_score", result.get("score"))
            if not isinstance(total, (int, float)):
                raise EvaluationError(f"战斗未返回有效分数：{result.get('score')!r}")
            return float(total)
        finally:
            random.setstate(saved)

    def _controller(self, bf, loader):
        if self.mode == MODE_TACTICAL:
            from src.combat_v2.tactical_exercise_controller import (
                TacticalExerciseController)
            return TacticalExerciseController(
                bf, BattleConfig(max_turns=5, enable_rdps=False),
                data_loader=loader)

        from src.combat_v2.circle_battle_controller import CircleBattleController
        stage_data = self.circle_context["stage_data"]
        config = BattleConfig(max_turns=stage_data.get("max_turn", 5),
                              enable_rdps=False)
        return CircleBattleController(
            bf, config, data_loader=loader,
            season=int(self.circle_context.get("season", 1)),
            stage=int(self.circle_context.get("stage", 1)),
            enemy_state_overrides=self.circle_context.get("enemy_state_overrides"))


def silence_worker_logging():
    """Suppress the engine's per-hit INFO logging inside a search worker."""
    _silence_worker_battle_logging()
