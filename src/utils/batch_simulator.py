#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多进程批量战斗模拟器
使用 multiprocessing.Pool 实现并行战斗模拟，充分利用多核CPU

设计要点:
- 每个worker进程独立加载DataLoader（一次性开销，摊销到多场战斗）
- seed分批次分发给worker，减少IPC开销
- imap_unordered流式收集结果，支持实时进度反馈
- 失败时自动回退到单进程模式
"""

from __future__ import annotations

import dataclasses
import multiprocessing as mp
import os
import random
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ============ Worker globals（每个进程独立拷贝） ============

_worker_dl = None                 # DataLoader
_worker_panel_config = None       # PanelConfig（pickle传入）
_worker_player_config = None      # PlayerConfig
_worker_stat_calculator = None    # StatCalculator
_worker_cfg = {}                  # 其他配置字典
_worker_mem_cards = []            # 记忆卡列表（常规模式）


def _worker_init(data_dir: str,
                 panel_config: Any,
                 friends_chars: List[int],
                 friend_positions: List[Any],
                 enemies_chars: List[int],
                 enemy_positions: List[Any],
                 max_turns: int,
                 positions_ally: List[Any],
                 positions_enemy: List[Any],
                 mem_cards_data: list = None):
    """Worker进程初始化——每个worker调用一次"""
    from src.data.data_loader import DataLoader
    from src.data.stat_calculator import StatCalculator

    global _worker_dl, _worker_panel_config, _worker_player_config
    global _worker_stat_calculator, _worker_cfg, _worker_mem_cards

    dl = DataLoader()
    dl._data_dir = Path(data_dir)
    dl.load_all()

    sc = StatCalculator(dl.load_level_lerp_data(), data_loader=dl)

    _worker_dl = dl
    _worker_panel_config = panel_config
    _worker_player_config = panel_config.get_player_config()
    _worker_stat_calculator = sc
    _worker_cfg = {
        'friends_chars': list(friends_chars),
        'friend_positions': list(friend_positions),
        'enemies_chars': list(enemies_chars),
        'enemy_positions': list(enemy_positions),
        'max_turns': max_turns,
        'positions_ally': list(positions_ally),
        'positions_enemy': list(positions_enemy),
    }
    _worker_mem_cards = list(mem_cards_data) if mem_cards_data else []


def _worker_run_batch(seeds: List[int]) -> List[Dict[str, Any]]:
    """Worker: 运行一批战斗（多个seed），返回每场战斗的统计"""
    from src.entities_v2.unit_state import UnitState
    from src.entities_v2.battlefield_state import BattlefieldState
    from src.entities_v2.enums import Side, Position
    from src.combat_v2.battle_flow_controller import BattleFlowController, BattleConfig

    global _worker_dl, _worker_panel_config, _worker_player_config
    global _worker_stat_calculator, _worker_cfg, _worker_mem_cards

    dl = _worker_dl
    pc = _worker_panel_config
    pl = _worker_player_config
    sc = _worker_stat_calculator
    cfg = _worker_cfg

    results = []

    for seed in seeds:
        random.seed(seed)

        bf = BattlefieldState()
        allies = []
        enemies = []

        # 创建己方单位
        f_positions = cfg['friend_positions']
        pos_a = cfg['positions_ally']
        for i, cid in enumerate(f_positions):
            if cid is not None:
                pos = pos_a[i] if i < len(pos_a) else Position.ALLY_CENTER_FRONT
                u = _create_unit_worker(dl, pc, pl, sc, cid, Side.ALLY, pos)
                if u:
                    bf.add_unit(u)
                    allies.append(u)

        # 创建敌方单位
        e_positions = cfg['enemy_positions']
        pos_e = cfg['positions_enemy']
        for i, cid in enumerate(e_positions):
            if cid is not None:
                pos = pos_e[i] if i < len(pos_e) else Position.ENEMY_CENTER_FRONT
                u = _create_unit_worker(dl, pc, pl, sc, cid, Side.ENEMY, pos)
                if u:
                    bf.add_unit(u)
                    enemies.append(u)

        # 设置记忆卡
        bf.memory_cards = list(_worker_mem_cards)

        # 战斗配置
        bc = BattleConfig()
        bc.max_turns = cfg['max_turns']

        controller = BattleFlowController(bf, data_loader=dl, config=bc)
        result = controller.execute_battle()

        winner = result['winner']
        if result['total_turns'] > cfg['max_turns']:
            winner = 'TIMEOUT'

        # 收集统计数据
        score_data = result.get("score", {})

        friend_stats = []
        for u in allies:
            friend_stats.append({
                'character_id': u.character_id,
                'damage': u.damage_dealt_total,
                'actions': u.action_count_total,
                'alive': u.is_alive,
            })

        enemy_stats = []
        for u in enemies:
            enemy_stats.append({
                'character_id': u.character_id,
                'damage': u.damage_dealt_total,
                'actions': u.action_count_total,
                'alive': u.is_alive,
            })

        results.append({
            'winner': winner,
            'total_turns': result['total_turns'],
            'friend_stats': friend_stats,
            'enemy_stats': enemy_stats,
            'ally_total_damage_dealt': score_data.get("ally_total_damage_dealt", 0) if score_data else 0,
            'ally_total_damage_received': score_data.get("ally_total_damage_received", 0) if score_data else 0,
            'ally_total_hp_healed': score_data.get("ally_total_hp_healed", 0) if score_data else 0,
            'enemy_total_damage_dealt': score_data.get("enemy_total_damage_dealt", 0) if score_data else 0,
            'enemy_total_damage_received': score_data.get("enemy_total_damage_received", 0) if score_data else 0,
            'enemy_total_hp_healed': score_data.get("enemy_total_hp_healed", 0) if score_data else 0,
            'enemy_healing_received': score_data.get("enemy_healing_received", 0) if score_data else 0,
        })

    return results


def _create_unit_worker(dl, panel_config, player_config, stat_calculator,
                        char_id: int, side, pos):
    """Worker内创建单位——与gui_app._create_unit逻辑一致，但不依赖GUI"""
    from src.entities_v2.unit_state import UnitState
    from src.entities_v2.enums import Side as _Side

    char = dl.get_character_by_id(char_id)
    if not char:
        return None

    pt = getattr(char, 'position_type', 0)

    # 自定义假人
    if char_id < 0:
        dummy_cfg = dl.get_custom_dummy_config(char_id)
        if not dummy_cfg:
            return None
        skill_ids = dl._custom_character_skills.get(char_id, [])
        max_ep = _compute_max_ep_worker(dl, skill_ids)
        side_prefix = "D" if side == _Side.ALLY else "E"
        hp = dummy_cfg.hp
        atk = dummy_cfg.attack
        defense = dummy_cfg.defense
        phys_shield = dummy_cfg.permanent_shield_value if dummy_cfg.permanent_shield_type == 1 else 0
        en_shld = dummy_cfg.permanent_shield_value if dummy_cfg.permanent_shield_type == 2 else 0
        all_shield = dummy_cfg.permanent_shield_value if dummy_cfg.permanent_shield_type == 3 else 0
        return UnitState(
            unit_id=f"{side_prefix}_{char_id}",
            name=char.name, side=side, position=pos,
            character_id=char_id, level=1,
            element=char.attribute, character_type=char.character_type,
            max_hp=hp, current_hp=hp,
            attack=atk, defense=defense,
            speed=dummy_cfg.speed,
            crit_rate=dummy_cfg.crit_rate,
            crit_damage=dummy_cfg.crit_damage - 1.5,
            advantage_damage=dummy_cfg.advantage_damage,
            initial_active_point=dummy_cfg.ap,
            initial_passive_point=dummy_cfg.pp,
            max_extra_point=max_ep,
            current_ap=dummy_cfg.ap, current_pp=dummy_cfg.pp,
            current_ep=0,
            shield=all_shield, physical_shield=phys_shield,
            en_shield=en_shld,
            skills=skill_ids,
            skill_levels={sid: 15 for sid in skill_ids},
            skill_cooldowns={},
            role_type=getattr(char, 'role_type', 0),
            position_type=pt,
        )

    # 正常角色
    char_config = panel_config.get_character_config(char_id, char.default_rarity)
    stats = stat_calculator.calculate_stats(char_config, player_config)
    skills = dl.load_character_skills().get(char_id, [])
    max_ep = _compute_max_ep_worker(dl, skills)
    side_prefix = "F" if side == _Side.ALLY else "E"

    return UnitState(
        unit_id=f"{side_prefix}_{char_id}",
        name=char.name, side=side, position=pos,
        character_id=char_id,
        level=char_config.level,
        element=char.attribute,
        character_type=char.character_type,
        max_hp=stats.hp, current_hp=stats.hp,
        attack=stats.attack, defense=stats.defense,
        speed=stats.speed,
        crit_rate=stats.critical_rate,
        crit_damage=stats.critical_damage - 1.5,
        advantage_damage=stats.advantage_damage - 1.25,
        initial_active_point=stats.initial_ap,
        initial_passive_point=stats.initial_pp,
        max_extra_point=max_ep,
        current_ap=stats.initial_ap, current_pp=stats.initial_pp,
        current_ep=0,
        skills=skills,
        skill_levels=panel_config.skill_levels.get(char_id, {}),
        skill_cooldowns={},
        role_type=getattr(char, 'role_type', 0),
        position_type=pt,
    )


def _compute_max_ep_worker(dl, skill_ids: list) -> int:
    for sid in skill_ids:
        sk = dl.get_skill_by_id(sid)
        if sk and sk.skill_type == 3:
            return sk.resource_cost
    return 0  # 无EX技能的单位无EP条


# ============ 战术演习 Worker ============

_worker_tactical_cfg = {}  # {enemy_data, enemy_pos}
_worker_mem_cards = []  # 记忆卡列表


def _worker_init_tactical(data_dir: str,
                          panel_config: Any,
                          friends_chars: List[int],
                          friend_positions: List[Any],
                          enemy_data: Dict[str, Any],
                          enemy_pos: Any,
                          positions_ally: List[Any],
                          mem_cards_data: list = None):
    """战术演习 worker 初始化——每个 worker 调用一次"""
    from src.data.data_loader import DataLoader
    from src.data.stat_calculator import StatCalculator

    global _worker_dl, _worker_panel_config, _worker_player_config
    global _worker_stat_calculator, _worker_cfg, _worker_tactical_cfg, _worker_mem_cards

    dl = DataLoader()
    dl._data_dir = Path(data_dir)
    dl.load_all()

    sc = StatCalculator(dl.load_level_lerp_data(), data_loader=dl)

    _worker_dl = dl
    _worker_panel_config = panel_config
    _worker_player_config = panel_config.get_player_config()
    _worker_stat_calculator = sc
    _worker_cfg = {
        'friends_chars': list(friends_chars),
        'friend_positions': list(friend_positions),
        'positions_ally': list(positions_ally),
    }
    _worker_tactical_cfg = {
        'enemy_data': enemy_data,
        'enemy_pos': enemy_pos,
    }
    _worker_mem_cards = list(mem_cards_data) if mem_cards_data else []


def _worker_run_batch_tactical(seeds: List[int]) -> List[Dict[str, Any]]:
    """战术演习 worker: 运行一批战斗，返回每场统计"""
    from src.entities_v2.unit_state import UnitState
    from src.entities_v2.battlefield_state import BattlefieldState
    from src.entities_v2.enums import Side, Position
    from src.combat_v2.tactical_exercise_controller import TacticalExerciseController
    from src.combat_v2.battle_flow_controller import BattleConfig

    global _worker_dl, _worker_panel_config, _worker_player_config
    global _worker_stat_calculator, _worker_cfg, _worker_tactical_cfg, _worker_mem_cards

    dl = _worker_dl
    pc = _worker_panel_config
    pl = _worker_player_config
    sc = _worker_stat_calculator
    cfg = _worker_cfg
    tc = _worker_tactical_cfg

    enemy_data = tc['enemy_data']
    enemy_pos = tc['enemy_pos']

    results = []

    for seed in seeds:
        random.seed(seed)

        bf = BattlefieldState()

        # 创建己方单位
        f_positions = cfg['friend_positions']
        pos_a = cfg['positions_ally']
        for i, cid in enumerate(f_positions):
            if cid is not None:
                pos = pos_a[i] if i < len(pos_a) else Position.ALLY_CENTER_FRONT
                u = _create_unit_worker(dl, pc, pl, sc, cid, Side.ALLY, pos)
                if u:
                    bf.add_unit(u)

        # 创建战术演习敌方
        enemy_unit = _create_tactical_enemy_worker(dl, enemy_data, enemy_pos)
        if enemy_unit:
            bf.add_unit(enemy_unit)

        # 设置记忆卡
        bf.memory_cards = list(_worker_mem_cards)

        bc = BattleConfig()
        bc.max_turns = 5

        controller = TacticalExerciseController(bf, data_loader=dl, config=bc)
        result = controller.execute_battle()

        stages = result.get("stages_cleared", 0)
        turns = result["total_turns"]
        winner = result.get('result', result.get('winner', 'ENEMY'))
        if turns > 5:
            winner = 'TIMEOUT'

        score_data = result.get("score", {})
        results.append({
            'seed': seed,
            'winner': winner,
            'stages_cleared': stages,
            'total_turns': turns,
            'score': score_data.get("total_score", 0) if score_data else 0,
            'ally_total_damage_dealt': score_data.get("ally_total_damage_dealt", 0) if score_data else 0,
            'ally_total_damage_received': score_data.get("ally_total_damage_received", 0) if score_data else 0,
            'ally_total_hp_healed': score_data.get("ally_total_hp_healed", 0) if score_data else 0,
            'enemy_total_damage_dealt': score_data.get("enemy_total_damage_dealt", 0) if score_data else 0,
            'enemy_total_damage_received': score_data.get("enemy_total_damage_received", 0) if score_data else 0,
            'enemy_total_hp_healed': score_data.get("enemy_total_hp_healed", 0) if score_data else 0,
            'enemy_healing_received': score_data.get("enemy_healing_received", 0) if score_data else 0,
            'unit_stats': score_data.get("unit_stats", {}) if score_data else {},
        })

    return results


def _create_tactical_enemy_worker(dl, enemy_data: Dict[str, Any], enemy_pos):
    """Worker内创建战术演习敌方单位"""
    from src.entities_v2.unit_state import UnitState
    from src.entities_v2.enums import Side

    skill_ids = enemy_data.get("skill_ids", [])
    skill_levels = {sid: 15 for sid in skill_ids}

    max_ep = 0
    for sid in skill_ids:
        sk = dl.get_skill_by_id(sid)
        if sk and sk.skill_type == 3:
            max_ep = max(max_ep, sk.resource_cost)

    unit_id = f"E_{enemy_data['enemy_id']}"

    return UnitState(
        unit_id=unit_id,
        name=enemy_data["character_name"],
        side=Side.ENEMY,
        position=enemy_pos,
        character_id=enemy_data["enemy_id"],
        level=1,
        element=enemy_data["attribute"],
        character_type=enemy_data["type"],
        max_hp=enemy_data["hp"],
        current_hp=enemy_data["hp"],
        attack=enemy_data["attack"],
        defense=enemy_data["defense"],
        speed=enemy_data["speed"],
        crit_rate=enemy_data["critical_rate"],
        crit_damage=0.0,
        advantage_damage=0.0,
        initial_active_point=enemy_data.get("action_point", 2),
        initial_passive_point=enemy_data.get("passive_point", 2),
        max_extra_point=max_ep,
        current_ap=enemy_data.get("action_point", 2),
        current_pp=enemy_data.get("passive_point", 2),
        current_ep=0,
        skills=skill_ids,
        skill_levels=skill_levels,
        skill_cooldowns={},
        role_type=enemy_data.get("role_type", 0),
        position_type=3,
    )


# ============ 对抗压制战 Worker ============

ENEMY_SLOT_POSITION_MAP_WORKER = {
    1: "enemy_left_front",
    2: "enemy_center_front",
    3: "enemy_right_front",
    4: "enemy_left_back",
    5: "enemy_center_back",
    6: "enemy_right_back",
}


def _create_circle_battle_enemy_worker(dl, enemy_data: Dict[str, Any]):
    """Worker内创建对抗压制战敌方单位"""
    from src.entities_v2.unit_state import UnitState
    from src.entities_v2.enums import Side, Position

    pos = enemy_data.get("position", 1)
    pos_str = ENEMY_SLOT_POSITION_MAP_WORKER.get(pos, "enemy_left_front")
    enemy_pos = Position(pos_str)

    skill_ids = enemy_data.get("skill_ids", [])
    skill_levels = {sid: 15 for sid in skill_ids}

    max_ep = 0
    for sid in skill_ids:
        sk = dl.get_skill_by_id(sid)
        if sk and sk.skill_type == 3:
            max_ep = max(max_ep, sk.resource_cost)

    unit_id = f"E_{enemy_data['enemy_id']}_{enemy_data['slot']}"

    return UnitState(
        unit_id=unit_id,
        name=enemy_data["name"],
        side=Side.ENEMY,
        position=enemy_pos,
        character_id=enemy_data["enemy_id"],
        level=enemy_data["level"],
        element=enemy_data["attribute"],
        character_type=enemy_data["type"],
        max_hp=enemy_data["hp"],
        current_hp=enemy_data["hp"],
        attack=enemy_data["attack"],
        defense=enemy_data["defense"],
        speed=enemy_data["speed"],
        crit_rate=enemy_data["critical_rate"],
        crit_damage=0.0,
        advantage_damage=0.0,
        initial_active_point=enemy_data.get("action_point", 2),
        initial_passive_point=enemy_data.get("passive_point", 2),
        max_extra_point=max_ep,
        current_ap=enemy_data.get("action_point", 2),
        current_pp=enemy_data.get("passive_point", 2),
        current_ep=0,
        skills=skill_ids,
        skill_levels=skill_levels,
        skill_cooldowns={},
        role_type=enemy_data.get("role_type", 0),
        position_type=3,
    )


# 对抗压制战 worker 全局变量
_worker_circle_cfg = None


def _worker_init_circle(data_dir: str,
                        panel_config: Any,
                        friends_chars: List[int],
                        friend_positions: List[Any],
                        enemies_data: List[Dict[str, Any]],
                        max_turns: int,
                        positions_ally: List[Any],
                        season: int,
                        stage: int,
                        mem_cards_data: list = None,
                        enemy_state_overrides: dict = None):
    """对抗压制战 worker 初始化"""
    from src.data.data_loader import DataLoader
    from src.data.stat_calculator import StatCalculator

    global _worker_dl, _worker_panel_config, _worker_player_config
    global _worker_stat_calculator, _worker_cfg, _worker_mem_cards
    global _worker_circle_cfg

    dl = DataLoader()
    dl._data_dir = Path(data_dir)
    dl.load_all()

    sc = StatCalculator(dl.load_level_lerp_data(), data_loader=dl)

    _worker_dl = dl
    _worker_panel_config = panel_config
    _worker_player_config = panel_config.get_player_config()
    _worker_stat_calculator = sc
    _worker_cfg = {
        'friends_chars': list(friends_chars),
        'friend_positions': list(friend_positions),
        'positions_ally': list(positions_ally),
    }
    _worker_circle_cfg = {
        'enemies_data': enemies_data,
        'max_turns': max_turns,
        'season': season,
        'stage': stage,
        'enemy_state_overrides': enemy_state_overrides or {},
    }
    _worker_mem_cards = list(mem_cards_data) if mem_cards_data else []


def _worker_run_batch_circle(seeds: List[int]) -> List[Dict[str, Any]]:
    """对抗压制战 worker: 运行一批战斗，返回每场统计"""
    from src.entities_v2.battlefield_state import BattlefieldState
    from src.entities_v2.enums import Side, Position
    from src.combat_v2.circle_battle_controller import CircleBattleController
    from src.combat_v2.battle_flow_controller import BattleConfig

    global _worker_dl, _worker_panel_config, _worker_player_config
    global _worker_stat_calculator, _worker_cfg, _worker_circle_cfg, _worker_mem_cards

    dl = _worker_dl
    pc = _worker_panel_config
    pl = _worker_player_config
    sc = _worker_stat_calculator
    cfg = _worker_cfg
    cc = _worker_circle_cfg

    enemies_data = cc['enemies_data']
    max_turns = cc['max_turns']
    season = cc['season']
    stage = cc['stage']
    enemy_state_overrides = cc.get('enemy_state_overrides', {})

    results = []

    for seed in seeds:
        random.seed(seed)

        bf = BattlefieldState()

        # 创建己方单位
        f_positions = cfg['friend_positions']
        pos_a = cfg['positions_ally']
        for i, cid in enumerate(f_positions):
            if cid is not None:
                pos = pos_a[i] if i < len(pos_a) else Position.ALLY_CENTER_FRONT
                u = _create_unit_worker(dl, pc, pl, sc, cid, Side.ALLY, pos)
                if u:
                    bf.add_unit(u)

        # 创建对抗压制战敌方
        for enemy_data in enemies_data:
            enemy_unit = _create_circle_battle_enemy_worker(dl, enemy_data)
            if enemy_unit:
                bf.add_unit(enemy_unit)

        # 设置记忆卡
        bf.memory_cards = list(_worker_mem_cards)

        bc = BattleConfig()
        bc.max_turns = max_turns

        controller = CircleBattleController(bf, data_loader=dl, config=bc,
                                            season=season, stage=stage,
                                            enemy_state_overrides=enemy_state_overrides)
        result = controller.execute_battle()

        winner = result.get('winner')
        result_str = result.get('result', 'UNKNOWN')
        turns = result["total_turns"]

        score_data = result.get("score", {})
        unit_stats = score_data.get("unit_stats", {})

        # 统计敌方未击杀单位受到的伤害
        enemy_damage_received = 0
        alive_enemy_count = 0
        for uid, stats in unit_stats.items():
            if stats.get("side") == "enemy":
                enemy_damage_received += stats.get("damage_received", 0)
                # 检查是否存活
                for u in bf.enemy_team:
                    if u.unit_id == uid and u.is_alive:
                        alive_enemy_count += 1
                        break

        results.append({
            'seed': seed,
            'winner': winner,
            'result': result_str,
            'total_turns': turns,
            'score': score_data.get("total_score", 0),
            'ally_total_damage_dealt': score_data.get("ally_total_damage_dealt", 0),
            'ally_total_damage_received': score_data.get("ally_total_damage_received", 0),
            'ally_total_hp_healed': score_data.get("ally_total_hp_healed", 0),
            'enemy_total_damage_dealt': score_data.get("enemy_total_damage_dealt", 0),
            'enemy_total_damage_received': score_data.get("enemy_total_damage_received", 0),
            'enemy_total_hp_healed': score_data.get("enemy_total_hp_healed", 0),
            'enemy_healing_received': score_data.get("enemy_healing_received", 0),
            'unit_stats': unit_stats,
            'alive_enemy_count': alive_enemy_count,
            'enemy_damage_received': enemy_damage_received,
        })

    return results


# ============ 主进程类 ============

@dataclass
class BatchResult:
    """批量模拟聚合结果"""
    total_runs: int = 0
    wins: int = 0
    losses: int = 0
    total_turns: int = 0
    turn_list: list = field(default_factory=list)
    elapsed: float = 0.0
    rate: float = 0.0  # 场/秒
    char_dmg: dict = field(default_factory=dict)
    char_actions: dict = field(default_factory=dict)
    char_survivals: dict = field(default_factory=dict)
    char_deaths: dict = field(default_factory=dict)
    friends_chars: list = field(default_factory=list)
    enemies_chars: list = field(default_factory=list)
    # 统计数据（参考战术演习）
    all_ally_damage: list = field(default_factory=list)
    all_ally_received: list = field(default_factory=list)
    all_ally_healed: list = field(default_factory=list)
    all_enemy_damage: list = field(default_factory=list)
    all_enemy_received: list = field(default_factory=list)
    all_enemy_healed: list = field(default_factory=list)
    all_enemy_healing_received: list = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.wins / self.total_runs * 100

    @property
    def avg_turns(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.total_turns / self.total_runs

    @property
    def min_turns(self) -> int:
        return min(self.turn_list) if self.turn_list else 0

    @property
    def max_turns(self) -> int:
        return max(self.turn_list) if self.turn_list else 0


class BatchSimulator:
    """多进程批量战斗模拟器

    用法:
        sim = BatchSimulator(data_loader, max_workers=8)
        result = sim.run_batch(panel_config, friends_chars, ...)
        print(f"胜率: {result.win_rate:.1f}%")
    """

    # 每个worker任务处理的最少战斗数（平衡IPC开销和进度粒度）
    DEFAULT_BATCH_SIZE = 20

    def __init__(self, data_loader, max_workers: int = None):
        self.data_loader = data_loader
        if max_workers is not None and max_workers >= 1:
            self.max_workers = max_workers
        else:
            self.max_workers = max(1, (os.cpu_count() or 4))
        self._data_dir = str(data_loader._data_dir)

    def run_batch(
        self,
        panel_config,
        friends_chars: List[int],
        friend_positions: List[Any],
        enemies_chars: List[int],
        enemy_positions: List[Any],
        total_runs: int,
        max_turns: int = 500,
        positions_ally: List[Any] = None,
        positions_enemy: List[Any] = None,
        progress_callback: Callable[[int, int], None] = None,
        batch_size: int = None,
        memory_cards: list = None,
    ) -> BatchResult:
        """执行多进程批量模拟

        Args:
            panel_config: PanelConfig面板配置
            friends_chars: 己方角色ID列表（用于输出排序）
            friend_positions: 己方位置列表（可含None）
            enemies_chars: 敌方角色ID列表（用于输出排序）
            enemy_positions: 敌方位置列表（可含None）
            total_runs: 总模拟次数
            max_turns: 最大回合数
            positions_ally: 己方Position枚举列表
            positions_enemy: 敌方Position枚举列表
            progress_callback: 进度回调 (done, total)
            batch_size: 每worker任务处理战斗数
        """
        if positions_ally is None:
            from src.entities_v2.enums import Position
            positions_ally = [
                Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT,
                Position.ALLY_RIGHT_FRONT,
                Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK,
                Position.ALLY_RIGHT_BACK,
            ]
        if positions_enemy is None:
            from src.entities_v2.enums import Position
            positions_enemy = [
                Position.ENEMY_LEFT_FRONT, Position.ENEMY_CENTER_FRONT,
                Position.ENEMY_RIGHT_FRONT,
                Position.ENEMY_LEFT_BACK, Position.ENEMY_CENTER_BACK,
                Position.ENEMY_RIGHT_BACK,
            ]
        if batch_size is None:
            batch_size = self.DEFAULT_BATCH_SIZE

        # 生成seeds: 用基础seed确保可复现
        base_seed = int(time.time() * 1000000) % (2**31)
        seeds = [(base_seed + i) % (2**31) for i in range(total_runs)]

        # 分割seed批次
        seed_batches = [seeds[i:i + batch_size] for i in range(0, len(seeds), batch_size)]

        print(f"\n  [多进程模拟] 总场数={total_runs} 批次={len(seed_batches)} "
              f"每批={batch_size} Workers={min(self.max_workers, len(seed_batches))}")

        # 尝试多进程模式
        try:
            return self._run_multiprocess(
                panel_config, friends_chars, friend_positions,
                enemies_chars, enemy_positions, total_runs, max_turns,
                positions_ally, positions_enemy,
                seed_batches, progress_callback,
                memory_cards=memory_cards,
            )
        except Exception as e:
            print(f"  [WARN] 多进程模拟失败，回退到单进程模式: {e}")
            traceback.print_exc()
            return self._run_single_process(
                panel_config, friends_chars, friend_positions,
                enemies_chars, enemy_positions, total_runs, max_turns,
                positions_ally, positions_enemy,
                seed_batches, progress_callback,
                memory_cards=memory_cards,
            )

    def _run_multiprocess(
        self, panel_config, friends_chars, friend_positions,
        enemies_chars, enemy_positions, total_runs, max_turns,
        positions_ally, positions_enemy,
        seed_batches, progress_callback,
        memory_cards=None,
    ) -> BatchResult:
        """多进程模式执行"""
        n_workers = min(self.max_workers, len(seed_batches))

        init_args = (
            self._data_dir,
            panel_config,
            friends_chars,
            friend_positions,
            enemies_chars,
            enemy_positions,
            max_turns,
            positions_ally,
            positions_enemy,
            memory_cards if memory_cards else [],
        )

        # 使用spawn上下文（Windows兼容）
        mp_ctx = mp.get_context('spawn')
        pool = mp_ctx.Pool(
            processes=n_workers,
            initializer=_worker_init,
            initargs=init_args,
        )

        # 聚合器
        wins = 0
        losses = 0
        total_turns = 0
        turn_list = []
        char_dmg = defaultdict(list)
        char_actions = defaultdict(list)
        char_survivals = defaultdict(int)
        char_deaths = defaultdict(int)
        all_ally_damage = []
        all_ally_received = []
        all_ally_healed = []
        all_enemy_damage = []
        all_enemy_received = []
        all_enemy_healed = []
        all_enemy_healing_received = []
        completed = 0
        t0 = time.time()

        try:
            # imap_unordered: 流式处理，哪个worker先完成就返回哪个结果
            for batch_results in pool.imap_unordered(_worker_run_batch, seed_batches):
                for stats in batch_results:
                    completed += 1

                    winner = stats['winner']
                    if winner == 'FRIEND':
                        wins += 1
                    else:
                        losses += 1

                    t = stats['total_turns']
                    total_turns += t
                    turn_list.append(t)

                    for u_stats in stats['friend_stats'] + stats['enemy_stats']:
                        cid = u_stats['character_id']
                        char_dmg[cid].append(u_stats['damage'])
                        char_actions[cid].append(u_stats['actions'])
                        if u_stats['alive']:
                            char_survivals[cid] += 1
                        else:
                            char_deaths[cid] += 1

                    # 收集统计数据
                    all_ally_damage.append(stats.get('ally_total_damage_dealt', 0))
                    all_ally_received.append(stats.get('ally_total_damage_received', 0))
                    all_ally_healed.append(stats.get('ally_total_hp_healed', 0))
                    all_enemy_damage.append(stats.get('enemy_total_damage_dealt', 0))
                    all_enemy_received.append(stats.get('enemy_total_damage_received', 0))
                    all_enemy_healed.append(stats.get('enemy_total_hp_healed', 0))
                    all_enemy_healing_received.append(stats.get('enemy_healing_received', 0))

                # 进度回调
                if progress_callback:
                    progress_callback(completed, total_runs)

        finally:
            pool.close()
            pool.join()

        elapsed = time.time() - t0

        return BatchResult(
            total_runs=total_runs,
            wins=wins,
            losses=losses,
            total_turns=total_turns,
            turn_list=turn_list,
            elapsed=elapsed,
            rate=total_runs / elapsed if elapsed > 0 else 0,
            char_dmg=dict(char_dmg),
            char_actions=dict(char_actions),
            char_survivals=dict(char_survivals),
            char_deaths=dict(char_deaths),
            friends_chars=list(friends_chars),
            enemies_chars=list(enemies_chars),
            all_ally_damage=all_ally_damage,
            all_ally_received=all_ally_received,
            all_ally_healed=all_ally_healed,
            all_enemy_damage=all_enemy_damage,
            all_enemy_received=all_enemy_received,
            all_enemy_healed=all_enemy_healed,
            all_enemy_healing_received=all_enemy_healing_received,
        )

    def _run_single_process(
        self, panel_config, friends_chars, friend_positions,
        enemies_chars, enemy_positions, total_runs, max_turns,
        positions_ally, positions_enemy,
        seed_batches, progress_callback,
        memory_cards=None,
    ) -> BatchResult:
        """单进程回退模式"""
        from src.entities_v2.unit_state import UnitState
        from src.entities_v2.battlefield_state import BattlefieldState
        from src.entities_v2.enums import Side, Position
        from src.combat_v2.battle_flow_controller import BattleFlowController, BattleConfig
        from src.data.stat_calculator import StatCalculator

        dl = self.data_loader
        lerp = dl.load_level_lerp_data()
        sc = StatCalculator(lerp, data_loader=dl)
        pl = panel_config.get_player_config()

        mem_cards = list(memory_cards) if memory_cards else []

        wins = 0
        losses = 0
        total_turns = 0
        turn_list = []
        char_dmg = defaultdict(list)
        char_actions = defaultdict(list)
        char_survivals = defaultdict(int)
        char_deaths = defaultdict(int)
        all_ally_damage = []
        all_ally_received = []
        all_ally_healed = []
        all_enemy_damage = []
        all_enemy_received = []
        all_enemy_healed = []
        all_enemy_healing_received = []
        completed = 0
        t0 = time.time()

        for seed_batch in seed_batches:
            for seed in seed_batch:
                random.seed(seed)
                completed += 1

                bf = BattlefieldState()
                allies = []
                enemies = []

                for i, cid in enumerate(friend_positions):
                    if cid is not None:
                        pos = positions_ally[i] if i < len(positions_ally) else Position.ALLY_CENTER_FRONT
                        u = _create_unit_worker(dl, panel_config, pl, sc, cid, Side.ALLY, pos)
                        if u:
                            bf.add_unit(u)
                            allies.append(u)

                for i, cid in enumerate(enemy_positions):
                    if cid is not None:
                        pos = positions_enemy[i] if i < len(positions_enemy) else Position.ENEMY_CENTER_FRONT
                        u = _create_unit_worker(dl, panel_config, pl, sc, cid, Side.ENEMY, pos)
                        if u:
                            bf.add_unit(u)
                            enemies.append(u)

                # 设置记忆卡
                bf.memory_cards = list(mem_cards)

                bc = BattleConfig()
                bc.max_turns = max_turns
                controller = BattleFlowController(bf, data_loader=dl, config=bc)
                result = controller.execute_battle()

                winner = result['winner']
                if result['total_turns'] > max_turns:
                    winner = 'TIMEOUT'
                    losses += 1
                elif winner == 'FRIEND':
                    wins += 1
                else:
                    losses += 1

                t = result['total_turns']
                total_turns += t
                turn_list.append(t)

                for u in allies + enemies:
                    cid = u.character_id
                    char_dmg[cid].append(u.damage_dealt_total)
                    char_actions[cid].append(u.action_count_total)
                    if u.is_alive:
                        char_survivals[cid] += 1
                    else:
                        char_deaths[cid] += 1

                # 收集统计数据
                score_data = result.get("score", {})
                all_ally_damage.append(score_data.get("ally_total_damage_dealt", 0))
                all_ally_received.append(score_data.get("ally_total_damage_received", 0))
                all_ally_healed.append(score_data.get("ally_total_hp_healed", 0))
                all_enemy_damage.append(score_data.get("enemy_total_damage_dealt", 0))
                all_enemy_received.append(score_data.get("enemy_total_damage_received", 0))
                all_enemy_healed.append(score_data.get("enemy_total_hp_healed", 0))
                all_enemy_healing_received.append(score_data.get("enemy_healing_received", 0))

            if progress_callback:
                progress_callback(completed, total_runs)

        elapsed = time.time() - t0

        return BatchResult(
            total_runs=total_runs,
            wins=wins,
            losses=losses,
            total_turns=total_turns,
            turn_list=turn_list,
            elapsed=elapsed,
            rate=total_runs / elapsed if elapsed > 0 else 0,
            char_dmg=dict(char_dmg),
            char_actions=dict(char_actions),
            char_survivals=dict(char_survivals),
            char_deaths=dict(char_deaths),
            friends_chars=list(friends_chars),
            enemies_chars=list(enemies_chars),
            all_ally_damage=all_ally_damage,
            all_ally_received=all_ally_received,
            all_ally_healed=all_ally_healed,
            all_enemy_damage=all_enemy_damage,
            all_enemy_received=all_enemy_received,
            all_enemy_healed=all_enemy_healed,
            all_enemy_healing_received=all_enemy_healing_received,
        )

    # ============ 战术演习批量模拟 ============

    def run_batch_tactical(
        self,
        panel_config,
        friends_chars: List[int],
        friend_positions: List[Any],
        enemy_data: Dict[str, Any],
        enemy_pos: Any,
        total_runs: int,
        positions_ally: List[Any] = None,
        progress_callback: Callable[[int, int], None] = None,
        batch_size: int = None,
        memory_cards: list = None,
    ) -> Dict[str, Any]:
        """执行战术演习多进程批量模拟"""
        if positions_ally is None:
            from src.entities_v2.enums import Position
            positions_ally = [
                Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT,
                Position.ALLY_RIGHT_FRONT,
                Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK,
                Position.ALLY_RIGHT_BACK,
            ]
        if batch_size is None:
            batch_size = self.DEFAULT_BATCH_SIZE

        base_seed = int(time.time() * 1000000) % (2**31)
        seeds = [(base_seed + i) % (2**31) for i in range(total_runs)]
        seed_batches = [seeds[i:i + batch_size] for i in range(0, len(seeds), batch_size)]

        print(f"\n  [多进程战术演习] 总场数={total_runs} 批次={len(seed_batches)} "
              f"每批={batch_size} Workers={min(self.max_workers, len(seed_batches))}")

        try:
            return self._run_multiprocess_tactical(
                panel_config, friends_chars, friend_positions,
                enemy_data, enemy_pos, total_runs,
                positions_ally, seed_batches, progress_callback,
                memory_cards=memory_cards,
            )
        except Exception as e:
            print(f"  [WARN] 多进程战术演习失败，回退到单进程模式: {e}")
            traceback.print_exc()
            return self._run_single_process_tactical(
                panel_config, friends_chars, friend_positions,
                enemy_data, enemy_pos, total_runs,
                positions_ally, seed_batches, progress_callback,
                memory_cards=memory_cards,
            )

    def _run_multiprocess_tactical(
        self, panel_config, friends_chars, friend_positions,
        enemy_data, enemy_pos, total_runs,
        positions_ally, seed_batches, progress_callback,
        memory_cards=None,
    ):
        n_workers = min(self.max_workers, len(seed_batches))

        init_args = (
            self._data_dir,
            panel_config,
            friends_chars,
            friend_positions,
            enemy_data,
            enemy_pos,
            positions_ally,
            memory_cards if memory_cards else [],
        )

        mp_ctx = mp.get_context('spawn')
        pool = mp_ctx.Pool(
            processes=n_workers,
            initializer=_worker_init_tactical,
            initargs=init_args,
        )

        total_stages = 0
        total_turns = 0
        max_stages = 0
        losses = 0
        timeouts = 0

        all_scores = []
        all_ally_damage = []
        all_ally_received = []
        all_ally_healed = []
        all_enemy_damage = []
        all_enemy_received = []
        all_enemy_healed = []
        all_enemy_healing_received = []
        all_unit_stats = []

        score_records = []
        completed = 0
        t0 = time.time()

        try:
            for batch_results in pool.imap_unordered(
                _worker_run_batch_tactical, seed_batches
            ):
                for stats in batch_results:
                    completed += 1

                    stages = stats['stages_cleared']
                    turns = stats['total_turns']
                    total_stages += stages
                    total_turns += turns
                    max_stages = max(max_stages, stages)

                    winner = stats['winner']
                    if winner == 'TIMEOUT':
                        timeouts += 1
                    elif winner == 'ENEMY':
                        losses += 1

                    all_scores.append(stats['score'])
                    all_ally_damage.append(stats['ally_total_damage_dealt'])
                    all_ally_received.append(stats['ally_total_damage_received'])
                    all_ally_healed.append(stats['ally_total_hp_healed'])
                    all_enemy_damage.append(stats['enemy_total_damage_dealt'])
                    all_enemy_received.append(stats['enemy_total_damage_received'])
                    all_enemy_healed.append(stats['enemy_total_hp_healed'])
                    all_enemy_healing_received.append(stats['enemy_healing_received'])
                    all_unit_stats.append(stats.get('unit_stats', {}))

                    score_records.append((stats['score'], completed - 1, stats['seed'], stats))

                if progress_callback:
                    progress_callback(completed, total_runs)

        finally:
            pool.close()
            pool.join()

        elapsed = time.time() - t0

        return {
            "total_stages": total_stages,
            "total_turns": total_turns,
            "max_stages": max_stages,
            "losses": losses,
            "timeouts": timeouts,
            "all_scores": all_scores,
            "all_ally_damage": all_ally_damage,
            "all_ally_received": all_ally_received,
            "all_ally_healed": all_ally_healed,
            "all_enemy_damage": all_enemy_damage,
            "all_enemy_received": all_enemy_received,
            "all_enemy_healed": all_enemy_healed,
            "all_enemy_healing_received": all_enemy_healing_received,
            "score_records": score_records,
            "all_unit_stats": all_unit_stats,
            "elapsed": elapsed,
            "rate": total_runs / elapsed if elapsed > 0 else 0,
        }

    def _run_single_process_tactical(
        self, panel_config, friends_chars, friend_positions,
        enemy_data, enemy_pos, total_runs,
        positions_ally, seed_batches, progress_callback,
        memory_cards=None,
    ):
        from src.entities_v2.battlefield_state import BattlefieldState
        from src.entities_v2.enums import Side, Position
        from src.combat_v2.tactical_exercise_controller import TacticalExerciseController
        from src.combat_v2.battle_flow_controller import BattleConfig
        from src.data.stat_calculator import StatCalculator

        dl = self.data_loader
        lerp = dl.load_level_lerp_data()
        sc = StatCalculator(lerp, data_loader=dl)
        pl = panel_config.get_player_config()

        mem_cards = list(memory_cards) if memory_cards else []

        total_stages = 0
        total_turns = 0
        max_stages = 0
        losses = 0
        timeouts = 0

        all_scores = []
        all_ally_damage = []
        all_ally_received = []
        all_ally_healed = []
        all_enemy_damage = []
        all_enemy_received = []
        all_enemy_healed = []
        all_enemy_healing_received = []
        all_unit_stats = []

        score_records = []
        completed = 0
        t0 = time.time()

        for seed_batch in seed_batches:
            for seed in seed_batch:
                random.seed(seed)
                completed += 1

                bf = BattlefieldState()

                for i, cid in enumerate(friend_positions):
                    if cid is not None:
                        pos = positions_ally[i] if i < len(positions_ally) else Position.ALLY_CENTER_FRONT
                        u = _create_unit_worker(dl, panel_config, pl, sc, cid, Side.ALLY, pos)
                        if u:
                            bf.add_unit(u)

                enemy_unit = _create_tactical_enemy_worker(dl, enemy_data, enemy_pos)
                if enemy_unit:
                    bf.add_unit(enemy_unit)

                # 设置记忆卡
                bf.memory_cards = list(mem_cards)

                bc = BattleConfig()
                bc.max_turns = 5
                controller = TacticalExerciseController(bf, data_loader=dl, config=bc)
                result = controller.execute_battle()

                stages = result.get("stages_cleared", 0)
                turns = result["total_turns"]
                total_stages += stages
                total_turns += turns
                max_stages = max(max_stages, stages)

                winner = result.get('result', result.get('winner', 'ENEMY'))
                if turns > 5:
                    timeouts += 1
                elif winner == 'ENEMY':
                    losses += 1

                score_data = result.get("score", {})
                if score_data:
                    all_scores.append(score_data.get("total_score", 0))
                    all_ally_damage.append(score_data.get("ally_total_damage_dealt", 0))
                    all_ally_received.append(score_data.get("ally_total_damage_received", 0))
                    all_ally_healed.append(score_data.get("ally_total_hp_healed", 0))
                    all_enemy_damage.append(score_data.get("enemy_total_damage_dealt", 0))
                    all_enemy_received.append(score_data.get("enemy_total_damage_received", 0))
                    all_enemy_healed.append(score_data.get("enemy_total_hp_healed", 0))
                    all_enemy_healing_received.append(score_data.get("enemy_healing_received", 0))
                    all_unit_stats.append(score_data.get("unit_stats", {}))
                    score_records.append((score_data.get("total_score", 0), completed - 1, seed, result))

            if progress_callback:
                progress_callback(completed, total_runs)

        elapsed = time.time() - t0

        return {
            "total_stages": total_stages,
            "total_turns": total_turns,
            "max_stages": max_stages,
            "losses": losses,
            "timeouts": timeouts,
            "all_scores": all_scores,
            "all_ally_damage": all_ally_damage,
            "all_ally_received": all_ally_received,
            "all_ally_healed": all_ally_healed,
            "all_enemy_damage": all_enemy_damage,
            "all_enemy_received": all_enemy_received,
            "all_enemy_healed": all_enemy_healed,
            "all_enemy_healing_received": all_enemy_healing_received,
            "score_records": score_records,
            "all_unit_stats": all_unit_stats,
            "elapsed": elapsed,
            "rate": total_runs / elapsed if elapsed > 0 else 0,
        }

    # ============ 对抗压制战批量模拟 ============

    def run_batch_circle(
        self,
        panel_config,
        friends_chars: List[int],
        friend_positions: List[Any],
        enemies_data: List[Dict[str, Any]],
        max_turns: int,
        total_runs: int,
        season: int = 5,
        stage: int = 100,
        positions_ally: List[Any] = None,
        progress_callback: Callable[[int, int], None] = None,
        batch_size: int = None,
        memory_cards: list = None,
        enemy_state_overrides: dict = None,
    ) -> Dict[str, Any]:
        """执行对抗压制战多进程批量模拟"""
        if positions_ally is None:
            from src.entities_v2.enums import Position
            positions_ally = [
                Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT,
                Position.ALLY_RIGHT_FRONT,
                Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK,
                Position.ALLY_RIGHT_BACK,
            ]
        if batch_size is None:
            batch_size = self.DEFAULT_BATCH_SIZE

        base_seed = int(time.time() * 1000000) % (2**31)
        seeds = [(base_seed + i) % (2**31) for i in range(total_runs)]
        seed_batches = [seeds[i:i + batch_size] for i in range(0, len(seeds), batch_size)]

        print(f"\n  [多进程对抗压制战] 总场数={total_runs} 批次={len(seed_batches)} "
              f"每批={batch_size} Workers={min(self.max_workers, len(seed_batches))}")

        try:
            return self._run_multiprocess_circle(
                panel_config, friends_chars, friend_positions,
                enemies_data, max_turns, total_runs,
                positions_ally, seed_batches, progress_callback,
                season=season, stage=stage, memory_cards=memory_cards,
                enemy_state_overrides=enemy_state_overrides,
            )
        except Exception as e:
            print(f"  [WARN] 多进程对抗压制战失败，回退到单进程模式: {e}")
            traceback.print_exc()
            return self._run_single_process_circle(
                panel_config, friends_chars, friend_positions,
                enemies_data, max_turns, total_runs,
                positions_ally, seed_batches, progress_callback,
                season=season, stage=stage, memory_cards=memory_cards,
                enemy_state_overrides=enemy_state_overrides,
            )

    def _run_multiprocess_circle(
        self, panel_config, friends_chars, friend_positions,
        enemies_data, max_turns, total_runs,
        positions_ally, seed_batches, progress_callback,
        season=5, stage=100, memory_cards=None, enemy_state_overrides=None,
    ):
        n_workers = min(self.max_workers, len(seed_batches))

        init_args = (
            self._data_dir,
            panel_config,
            friends_chars,
            friend_positions,
            enemies_data,
            max_turns,
            positions_ally,
            season,
            stage,
            memory_cards if memory_cards else [],
            enemy_state_overrides if enemy_state_overrides else {},
        )

        mp_ctx = mp.get_context('spawn')
        pool = mp_ctx.Pool(
            processes=n_workers,
            initializer=_worker_init_circle,
            initargs=init_args,
        )

        wins = 0
        losses = 0
        total_turns = 0

        all_ally_damage = []
        all_ally_received = []
        all_ally_healed = []
        all_enemy_damage = []
        all_enemy_received = []
        all_enemy_healed = []
        all_enemy_healing_received = []
        failed_enemy_damage_received = []
        all_unit_stats = []

        completed = 0
        t0 = time.time()

        try:
            for batch_results in pool.imap_unordered(
                _worker_run_batch_circle, seed_batches
            ):
                for stats in batch_results:
                    completed += 1

                    winner = stats['winner']
                    turns = stats['total_turns']
                    total_turns += turns

                    if winner == 'FRIEND':
                        wins += 1
                    else:
                        losses += 1
                        failed_enemy_damage_received.append(stats.get('enemy_damage_received', 0))

                    all_ally_damage.append(stats['ally_total_damage_dealt'])
                    all_ally_received.append(stats['ally_total_damage_received'])
                    all_ally_healed.append(stats['ally_total_hp_healed'])
                    all_enemy_damage.append(stats['enemy_total_damage_dealt'])
                    all_enemy_received.append(stats['enemy_total_damage_received'])
                    all_enemy_healed.append(stats['enemy_total_hp_healed'])
                    all_enemy_healing_received.append(stats['enemy_healing_received'])
                    all_unit_stats.append(stats.get('unit_stats', {}))

                if progress_callback:
                    progress_callback(completed, total_runs)

        finally:
            pool.close()
            pool.join()

        elapsed = time.time() - t0

        return {
            "wins": wins,
            "losses": losses,
            "total_runs": total_runs,
            "total_turns": total_turns,
            "pass_rate": wins / total_runs if total_runs > 0 else 0,
            "all_ally_damage": all_ally_damage,
            "all_ally_received": all_ally_received,
            "all_ally_healed": all_ally_healed,
            "all_enemy_damage": all_enemy_damage,
            "all_enemy_received": all_enemy_received,
            "all_enemy_healed": all_enemy_healed,
            "all_enemy_healing_received": all_enemy_healing_received,
            "all_unit_stats": all_unit_stats,
            "failed_enemy_damage_received": failed_enemy_damage_received,
            "elapsed": elapsed,
            "rate": total_runs / elapsed if elapsed > 0 else 0,
        }

    def _run_single_process_circle(
        self, panel_config, friends_chars, friend_positions,
        enemies_data, max_turns, total_runs,
        positions_ally, seed_batches, progress_callback,
        season=5, stage=100, memory_cards=None, enemy_state_overrides=None,
    ):
        from src.entities_v2.battlefield_state import BattlefieldState
        from src.entities_v2.enums import Side, Position
        from src.combat_v2.circle_battle_controller import CircleBattleController
        from src.combat_v2.battle_flow_controller import BattleConfig
        from src.data.stat_calculator import StatCalculator

        dl = self.data_loader
        lerp = dl.load_level_lerp_data()
        sc = StatCalculator(lerp, data_loader=dl)
        pl = panel_config.get_player_config()

        mem_cards = list(memory_cards) if memory_cards else []

        wins = 0
        losses = 0
        total_turns = 0

        all_ally_damage = []
        all_ally_received = []
        all_ally_healed = []
        all_enemy_damage = []
        all_enemy_received = []
        all_enemy_healed = []
        all_enemy_healing_received = []
        failed_enemy_damage_received = []
        all_unit_stats = []

        completed = 0
        t0 = time.time()

        for seed_batch in seed_batches:
            for seed in seed_batch:
                random.seed(seed)
                completed += 1

                bf = BattlefieldState()

                for i, cid in enumerate(friend_positions):
                    if cid is not None:
                        pos = positions_ally[i] if i < len(positions_ally) else Position.ALLY_CENTER_FRONT
                        u = _create_unit_worker(dl, panel_config, pl, sc, cid, Side.ALLY, pos)
                        if u:
                            bf.add_unit(u)

                for enemy_data in enemies_data:
                    enemy_unit = _create_circle_battle_enemy_worker(dl, enemy_data)
                    if enemy_unit:
                        bf.add_unit(enemy_unit)

                bf.memory_cards = list(mem_cards)

                bc = BattleConfig()
                bc.max_turns = max_turns

                controller = CircleBattleController(bf, data_loader=dl, config=bc,
                                                    season=season, stage=stage,
                                                    enemy_state_overrides=enemy_state_overrides)
                result = controller.execute_battle()

                winner = result.get('winner')
                turns = result["total_turns"]
                total_turns += turns

                if winner == 'FRIEND':
                    wins += 1
                else:
                    losses += 1

                score_data = result.get("score", {})
                unit_stats = score_data.get("unit_stats", {})

                enemy_damage_received = 0
                if winner != 'FRIEND':
                    for uid, stats in unit_stats.items():
                        if stats.get("side") == "enemy":
                            enemy_damage_received += stats.get("damage_received", 0)
                    failed_enemy_damage_received.append(enemy_damage_received)

                all_ally_damage.append(score_data.get("ally_total_damage_dealt", 0))
                all_ally_received.append(score_data.get("ally_total_damage_received", 0))
                all_ally_healed.append(score_data.get("ally_total_hp_healed", 0))
                all_enemy_damage.append(score_data.get("enemy_total_damage_dealt", 0))
                all_enemy_received.append(score_data.get("enemy_total_damage_received", 0))
                all_enemy_healed.append(score_data.get("enemy_total_hp_healed", 0))
                all_enemy_healing_received.append(score_data.get("enemy_healing_received", 0))
                all_unit_stats.append(unit_stats)

                if progress_callback:
                    progress_callback(completed, total_runs)

        elapsed = time.time() - t0

        return {
            "wins": wins,
            "losses": losses,
            "total_runs": total_runs,
            "total_turns": total_turns,
            "pass_rate": wins / total_runs if total_runs > 0 else 0,
            "all_ally_damage": all_ally_damage,
            "all_ally_received": all_ally_received,
            "all_ally_healed": all_ally_healed,
            "all_enemy_damage": all_enemy_damage,
            "all_enemy_received": all_enemy_received,
            "all_enemy_healed": all_enemy_healed,
            "all_enemy_healing_received": all_enemy_healing_received,
            "all_unit_stats": all_unit_stats,
            "failed_enemy_damage_received": failed_enemy_damage_received,
            "elapsed": elapsed,
            "rate": total_runs / elapsed if elapsed > 0 else 0,
        }

    # ============ 联合战术演习 ============

    def run_batch_composite_tactic(
        self,
        panel_config,
        teams_positions: List[List[Any]],
        enemies_data: List[Dict[str, Any]],
        max_turns: int,
        total_runs: int,
        positions_ally: List[Any] = None,
        progress_callback: Callable[[int, int], None] = None,
        batch_size: int = None,
        teams_mem_cards: List[List[Any]] = None,
    ) -> Dict[str, Any]:
        """执行联合战术演习多进程批量模拟

        Args:
            teams_positions: 3支队伍的角色ID位置列表
            teams_mem_cards: 3支队伍的回忆卡ID列表
        """
        if positions_ally is None:
            from src.entities_v2.enums import Position
            positions_ally = [
                Position.ALLY_LEFT_FRONT, Position.ALLY_CENTER_FRONT,
                Position.ALLY_RIGHT_FRONT,
                Position.ALLY_LEFT_BACK, Position.ALLY_CENTER_BACK,
                Position.ALLY_RIGHT_BACK,
            ]
        if batch_size is None:
            batch_size = self.DEFAULT_BATCH_SIZE

        base_seed = int(time.time() * 1000000) % (2**31)
        seeds = [(base_seed + i) % (2**31) for i in range(total_runs)]
        seed_batches = [seeds[i:i + batch_size] for i in range(0, len(seeds), batch_size)]

        print(f"\n  [多进程联合战术演习] 总场数={total_runs} 批次={len(seed_batches)} "
              f"每批={batch_size} Workers={min(self.max_workers, len(seed_batches))}")

        try:
            return self._run_multiprocess_composite(
                panel_config, teams_positions, enemies_data, max_turns,
                total_runs, positions_ally, seed_batches, progress_callback,
                teams_mem_cards=teams_mem_cards,
            )
        except Exception as e:
            print(f"  [WARN] 多进程联合战术演习失败，回退到单进程模式: {e}")
            traceback.print_exc()
            return self._run_single_process_composite(
                panel_config, teams_positions, enemies_data, max_turns,
                total_runs, positions_ally, seed_batches, progress_callback,
                teams_mem_cards=teams_mem_cards,
            )

    def _run_multiprocess_composite(
        self, panel_config, teams_positions, enemies_data, max_turns,
        total_runs, positions_ally, seed_batches, progress_callback,
        teams_mem_cards=None,
    ):
        n_workers = min(self.max_workers, len(seed_batches))

        init_args = (
            self._data_dir,
            panel_config,
            teams_positions,
            enemies_data,
            max_turns,
            positions_ally,
            teams_mem_cards if teams_mem_cards else [[], [], []],
        )

        mp_ctx = mp.get_context('spawn')
        pool = mp_ctx.Pool(
            processes=n_workers,
            initializer=_worker_init_composite,
            initargs=init_args,
        )

        all_scores = []
        all_boss_stages = []
        all_boss_kills = []
        all_team_damages = []  # 每场的3队伤害列表
        all_unit_stats = []
        total_turns_sum = 0

        completed = 0
        t0 = time.time()

        try:
            for batch_results in pool.imap_unordered(
                _worker_run_batch_composite, seed_batches
            ):
                for stats in batch_results:
                    completed += 1
                    all_scores.append(stats['score'])
                    all_boss_stages.append(stats['boss_stage'])
                    all_boss_kills.append(stats['boss_killed_count'])
                    all_team_damages.append(stats['team_damages'])
                    all_unit_stats.append(stats.get('unit_stats', {}))
                    total_turns_sum += stats['total_turns']

                if progress_callback:
                    progress_callback(completed, total_runs)
        finally:
            pool.close()
            pool.join()

        elapsed = time.time() - t0

        return self._aggregate_composite_results(
            all_scores, all_boss_stages, all_boss_kills,
            all_team_damages, all_unit_stats, total_turns_sum,
            total_runs, elapsed,
        )

    def _run_single_process_composite(
        self, panel_config, teams_positions, enemies_data, max_turns,
        total_runs, positions_ally, seed_batches, progress_callback,
        teams_mem_cards=None,
    ):
        from src.entities_v2.battlefield_state import BattlefieldState
        from src.entities_v2.enums import Side, Position
        from src.combat_v2.composite_tactic_controller import CompositeTacticController
        from src.combat_v2.battle_flow_controller import BattleConfig
        from src.data.stat_calculator import StatCalculator
        from src.entities.memory_card import MemoryCard, MemoryHighlight

        dl = self.data_loader
        lerp = dl.load_level_lerp_data()
        sc = StatCalculator(lerp, data_loader=dl)
        pl = panel_config.get_player_config()

        teams_mem = teams_mem_cards if teams_mem_cards else [[], [], []]

        all_scores = []
        all_boss_stages = []
        all_boss_kills = []
        all_team_damages = []
        all_unit_stats = []
        total_turns_sum = 0

        completed = 0
        t0 = time.time()

        for seed_batch in seed_batches:
            for seed in seed_batch:
                random.seed(seed)
                completed += 1

                # 创建3支队伍
                teams_units = []
                for team_idx, team_positions in enumerate(teams_positions):
                    team_units = []
                    for i, cid in enumerate(team_positions):
                        if cid is not None:
                            pos = positions_ally[i] if i < len(positions_ally) else Position.ALLY_CENTER_FRONT
                            u = _create_unit_worker(dl, panel_config, pl, sc, cid, Side.ALLY, pos)
                            if u:
                                existing_ids = {x.unit_id for x in team_units}
                                if u.unit_id in existing_ids:
                                    suffix = 1
                                    while f"{u.unit_id}_{suffix}" in existing_ids:
                                        suffix += 1
                                    u.unit_id = f"{u.unit_id}_{suffix}"
                                team_units.append(u)
                    teams_units.append(team_units)

                # 创建敌方
                bf = BattlefieldState()
                for enemy_data in enemies_data:
                    enemy_unit = _create_composite_enemy_worker(dl, enemy_data)
                    if enemy_unit:
                        bf.add_unit(enemy_unit)

                boss_unit_id = ""
                for ed in enemies_data:
                    if ed.get("is_boss"):
                        boss_unit_id = f"E_{ed['enemy_id']}_{ed['slot']}"
                        break

                # 回忆卡
                teams_mem_cards_built = []
                for team_mem in teams_mem:
                    cards = []
                    for mem_id in team_mem:
                        if mem_id is None:
                            continue
                        memory_data = dl.get_memory(mem_id)
                        if not memory_data:
                            continue
                        highlights = [
                            MemoryHighlight(
                                character_attribute=hl.character_attribute,
                                character_base_master_id=hl.character_base_master_id,
                                character_master_id=hl.character_master_id,
                                character_role=hl.character_role,
                                character_team_master_id=hl.character_team_master_id,
                                character_type=hl.character_type,
                                is_targeting_friendly_party=hl.is_targeting_friendly_party,
                                party_position=hl.party_position,
                                skill_master_id=hl.skill_master_id,
                            )
                            for hl in memory_data.highlights
                        ]
                        cards.append(MemoryCard(
                            card_id=mem_id,
                            name=memory_data.name,
                            description=memory_data.description,
                            rarity=memory_data.rarity,
                            highlights=highlights,
                        ))
                    teams_mem_cards_built.append(cards)

                bc = BattleConfig()
                bc.max_turns = max_turns

                controller = CompositeTacticController(
                    bf, data_loader=dl, config=bc, narrative=None,
                    teams=teams_units, team_memories=teams_mem_cards_built,
                    boss_unit_id=boss_unit_id,
                )
                result = controller.execute_battle()

                all_scores.append(result.get("score", 0))
                all_boss_stages.append(result.get("boss_stage", 0))
                all_boss_kills.append(result.get("boss_killed_count", 0))
                all_team_damages.append([tr.get("damage_to_boss", 0) for tr in result.get("team_results", [])])
                total_turns_sum += result.get("total_turns", 0)

                # 单位统计（己方单位key含队伍索引，避免同角色重复编组时key冲突）
                # hp_healed 从 team_results.ally_stats 提取（CompositeTacticController已采集）
                team_results = result.get("team_results", [])
                unit_stats = {}
                for team_idx, team_units in enumerate(teams_units):
                    # 该队的 ally_stats（按队伍顺序对应）
                    team_ally_stats = (team_results[team_idx].get("ally_stats", [])
                                       if team_idx < len(team_results) else [])
                    # 按 name 建立索引（ally_stats 顺序与 team_units 顺序一致）
                    for u_idx, u in enumerate(team_units):
                        key = f"{u.unit_id}_t{team_idx}"
                        hp_healed = 0
                        if u_idx < len(team_ally_stats):
                            hp_healed = team_ally_stats[u_idx].get("hp_healed", 0)
                        unit_stats[key] = {
                            "name": u.name, "side": "ally", "team": team_idx,
                            "uid": u.unit_id,
                            "damage_dealt": getattr(u, 'damage_dealt_total', 0),
                            "damage_received": getattr(u, 'damage_taken_total', 0),
                            "hp_healed": hp_healed,
                            "hp_received": 0,
                        }
                for u in bf.enemy_team:
                    unit_stats[u.unit_id] = {
                        "name": u.name, "side": "enemy",
                        "damage_dealt": getattr(u, 'damage_dealt_total', 0),
                        "damage_received": getattr(u, 'damage_taken_total', 0),
                        "hp_healed": 0,
                        "hp_received": 0,
                    }
                all_unit_stats.append(unit_stats)

                if progress_callback:
                    progress_callback(completed, total_runs)

        elapsed = time.time() - t0

        return self._aggregate_composite_results(
            all_scores, all_boss_stages, all_boss_kills,
            all_team_damages, all_unit_stats, total_turns_sum,
            total_runs, elapsed,
        )

    @staticmethod
    def _aggregate_composite_results(
        all_scores, all_boss_stages, all_boss_kills,
        all_team_damages, all_unit_stats, total_turns_sum,
        total_runs, elapsed,
    ):
        """聚合联合战术演习批量模拟结果"""
        n = total_runs if total_runs > 0 else 1

        # 各队平均伤害
        team_avg_damages = [0.0, 0.0, 0.0]
        for td_list in all_team_damages:
            for i, dmg in enumerate(td_list[:3]):
                team_avg_damages[i] += dmg
        team_avg_damages = [d / n for d in team_avg_damages]

        # 聚合单位统计（己方按角色uid汇总 + 按队伍分组汇总）
        ally_agg = {}
        enemy_agg = {}
        team_ally_agg = [{}, {}, {}]  # 每队单独聚合，避免重复角色混在一起
        for unit_stats in all_unit_stats:
            for key, stats in unit_stats.items():
                if stats.get("side") == "ally":
                    # 按角色uid汇总（跨队伍合计）
                    uid = stats.get("uid", key)
                    if uid not in ally_agg:
                        ally_agg[uid] = {
                            "name": stats.get("name", uid),
                            "damage_dealt": 0, "damage_received": 0,
                            "hp_healed": 0, "hp_received": 0, "count": 0,
                        }
                    ally_agg[uid]["damage_dealt"] += stats.get("damage_dealt", 0)
                    ally_agg[uid]["damage_received"] += stats.get("damage_received", 0)
                    ally_agg[uid]["hp_healed"] += stats.get("hp_healed", 0)
                    ally_agg[uid]["hp_received"] += stats.get("hp_received", 0)
                    ally_agg[uid]["count"] += 1

                    # 按队伍分组汇总
                    team_idx = stats.get("team", 0)
                    if 0 <= team_idx < 3:
                        if uid not in team_ally_agg[team_idx]:
                            team_ally_agg[team_idx][uid] = {
                                "name": stats.get("name", uid),
                                "damage_dealt": 0, "damage_received": 0,
                                "hp_healed": 0, "hp_received": 0, "count": 0,
                            }
                        team_ally_agg[team_idx][uid]["damage_dealt"] += stats.get("damage_dealt", 0)
                        team_ally_agg[team_idx][uid]["damage_received"] += stats.get("damage_received", 0)
                        team_ally_agg[team_idx][uid]["hp_healed"] += stats.get("hp_healed", 0)
                        team_ally_agg[team_idx][uid]["hp_received"] += stats.get("hp_received", 0)
                        team_ally_agg[team_idx][uid]["count"] += 1
                else:
                    if key not in enemy_agg:
                        enemy_agg[key] = {
                            "name": stats.get("name", key),
                            "damage_dealt": 0, "damage_received": 0,
                            "hp_healed": 0, "hp_received": 0, "count": 0,
                        }
                    enemy_agg[key]["damage_dealt"] += stats.get("damage_dealt", 0)
                    enemy_agg[key]["damage_received"] += stats.get("damage_received", 0)
                    enemy_agg[key]["hp_healed"] += stats.get("hp_healed", 0)
                    enemy_agg[key]["hp_received"] += stats.get("hp_received", 0)
                    enemy_agg[key]["count"] += 1

        return {
            "total_runs": total_runs,
            "avg_score": sum(all_scores) / n if all_scores else 0,
            "max_score": max(all_scores) if all_scores else 0,
            "min_score": min(all_scores) if all_scores else 0,
            "avg_boss_stage": sum(all_boss_stages) / n if all_boss_stages else 0,
            "avg_boss_kills": sum(all_boss_kills) / n if all_boss_kills else 0,
            "team_avg_damages": team_avg_damages,
            "avg_turns": total_turns_sum / n,
            "all_scores": all_scores,
            "ally_agg": ally_agg,
            "enemy_agg": enemy_agg,
            "team_ally_agg": team_ally_agg,
            "all_unit_stats": all_unit_stats,
            "elapsed": elapsed,
            "rate": total_runs / elapsed if elapsed > 0 else 0,
        }


# ============ 联合战术演习 Worker ============

_worker_composite_cfg = None


def _create_composite_enemy_worker(dl, enemy_data: Dict[str, Any]):
    """Worker内创建联合战术演习敌方单位（含技能等级）"""
    from src.entities_v2.unit_state import UnitState
    from src.entities_v2.enums import Side, Position

    pos = enemy_data.get("position", 1)
    pos_str = ENEMY_SLOT_POSITION_MAP_WORKER.get(pos, "enemy_left_front")
    enemy_pos = Position(pos_str)

    skill_ids = enemy_data.get("skill_ids", [])
    raw_levels = enemy_data.get("skill_levels", {})
    skill_levels = {}
    for sid in skill_ids:
        sid_str = str(sid)
        skill_levels[sid] = int(raw_levels.get(sid_str, raw_levels.get(sid, 1)))

    max_ep = 0
    for sid in skill_ids:
        sk = dl.get_skill_by_id(sid)
        if sk and sk.skill_type == 3:
            max_ep = max(max_ep, sk.resource_cost)

    unit_id = f"E_{enemy_data['enemy_id']}_{enemy_data['slot']}"

    return UnitState(
        unit_id=unit_id,
        name=enemy_data["name"],
        side=Side.ENEMY,
        position=enemy_pos,
        character_id=enemy_data["enemy_id"],
        level=enemy_data["level"],
        element=enemy_data["attribute"],
        character_type=enemy_data["type"],
        max_hp=enemy_data["hp"],
        current_hp=enemy_data["hp"],
        attack=enemy_data["attack"],
        defense=enemy_data["defense"],
        speed=enemy_data["speed"],
        crit_rate=enemy_data["critical_rate"],
        crit_damage=0.0,
        advantage_damage=0.0,
        initial_active_point=enemy_data.get("action_point", 2),
        initial_passive_point=enemy_data.get("passive_point", 2),
        max_extra_point=max_ep,
        current_ap=enemy_data.get("action_point", 2),
        current_pp=enemy_data.get("passive_point", 2),
        current_ep=0,
        skills=skill_ids,
        skill_levels=skill_levels,
        skill_cooldowns={},
        role_type=enemy_data.get("role_type", 0),
        position_type=3,
    )


def _worker_init_composite(data_dir: str,
                            panel_config: Any,
                            teams_positions: List[List[Any]],
                            enemies_data: List[Dict[str, Any]],
                            max_turns: int,
                            positions_ally: List[Any],
                            mem_cards_data: List[List[Any]] = None):
    """联合战术演习 worker 初始化

    Args:
        teams_positions: 3支队伍的角色ID位置列表（每个列表6个元素，None表示空位）
        mem_cards_data: 3支队伍的回忆卡数据列表
    """
    from src.data.data_loader import DataLoader
    from src.data.stat_calculator import StatCalculator

    global _worker_dl, _worker_panel_config, _worker_player_config
    global _worker_stat_calculator, _worker_cfg
    global _worker_composite_cfg, _worker_mem_cards

    dl = DataLoader()
    dl._data_dir = Path(data_dir)
    dl.load_all()

    sc = StatCalculator(dl.load_level_lerp_data(), data_loader=dl)

    _worker_dl = dl
    _worker_panel_config = panel_config
    _worker_player_config = panel_config.get_player_config()
    _worker_stat_calculator = sc
    _worker_cfg = {
        'teams_positions': [list(t) for t in teams_positions],
        'positions_ally': list(positions_ally),
    }
    _worker_composite_cfg = {
        'enemies_data': enemies_data,
        'max_turns': max_turns,
    }
    # 3支队伍的回忆卡
    if mem_cards_data:
        _worker_mem_cards = [list(mc) for mc in mem_cards_data]
    else:
        _worker_mem_cards = [[], [], []]


def _worker_run_batch_composite(seeds: List[int]) -> List[Dict[str, Any]]:
    """联合战术演习 worker: 运行一批战斗，返回每场统计"""
    from src.entities_v2.battlefield_state import BattlefieldState
    from src.entities_v2.enums import Side, Position
    from src.combat_v2.composite_tactic_controller import CompositeTacticController
    from src.combat_v2.battle_flow_controller import BattleConfig

    global _worker_dl, _worker_panel_config, _worker_player_config
    global _worker_stat_calculator, _worker_cfg
    global _worker_composite_cfg, _worker_mem_cards

    dl = _worker_dl
    pc = _worker_panel_config
    pl = _worker_player_config
    sc = _worker_stat_calculator
    cfg = _worker_cfg
    cc = _worker_composite_cfg

    enemies_data = cc['enemies_data']
    max_turns = cc['max_turns']
    teams_positions = cfg['teams_positions']
    pos_a = cfg['positions_ally']
    teams_mem = _worker_mem_cards if _worker_mem_cards else [[], [], []]

    results = []

    for seed in seeds:
        random.seed(seed)

        # 创建3支队伍的单位
        teams_units = []
        for team_idx, team_positions in enumerate(teams_positions):
            team_units = []
            for i, cid in enumerate(team_positions):
                if cid is not None:
                    pos = pos_a[i] if i < len(pos_a) else Position.ALLY_CENTER_FRONT
                    u = _create_unit_worker(dl, pc, pl, sc, cid, Side.ALLY, pos)
                    if u:
                        # 为同队内的相同角色添加后缀避免unit_id冲突
                        existing_ids = {x.unit_id for x in team_units}
                        if u.unit_id in existing_ids:
                            suffix = 1
                            while f"{u.unit_id}_{suffix}" in existing_ids:
                                suffix += 1
                            u.unit_id = f"{u.unit_id}_{suffix}"
                        team_units.append(u)
            teams_units.append(team_units)

        # 创建敌方单位
        bf = BattlefieldState()
        for enemy_data in enemies_data:
            enemy_unit = _create_composite_enemy_worker(dl, enemy_data)
            if enemy_unit:
                bf.add_unit(enemy_unit)

        # BOSS unit_id
        boss_unit_id = ""
        for ed in enemies_data:
            if ed.get("is_boss"):
                boss_unit_id = f"E_{ed['enemy_id']}_{ed['slot']}"
                break

        # 回忆卡
        from src.entities.memory_card import MemoryCard, MemoryHighlight
        teams_mem_cards = []
        for team_mem in teams_mem:
            cards = []
            for mem_entry in team_mem:
                if mem_entry is None:
                    continue
                card_id = mem_entry.get("card_id") if isinstance(mem_entry, dict) else mem_entry
                if card_id is None:
                    continue
                memory_data = dl.get_memory(card_id)
                if not memory_data:
                    continue
                highlights = [
                    MemoryHighlight(
                        character_attribute=hl.character_attribute,
                        character_base_master_id=hl.character_base_master_id,
                        character_master_id=hl.character_master_id,
                        character_role=hl.character_role,
                        character_team_master_id=hl.character_team_master_id,
                        character_type=hl.character_type,
                        is_targeting_friendly_party=hl.is_targeting_friendly_party,
                        party_position=hl.party_position,
                        skill_master_id=hl.skill_master_id,
                    )
                    for hl in memory_data.highlights
                ]
                cards.append(MemoryCard(
                    card_id=card_id,
                    name=memory_data.name,
                    description=memory_data.description,
                    rarity=memory_data.rarity,
                    highlights=highlights,
                ))
            teams_mem_cards.append(cards)

        bc = BattleConfig()
        bc.max_turns = max_turns

        controller = CompositeTacticController(
            bf, data_loader=dl, config=bc, narrative=None,
            teams=teams_units, team_memories=teams_mem_cards,
            boss_unit_id=boss_unit_id,
        )
        result = controller.execute_battle()

        score = result.get("score", 0)
        boss_stage = result.get("boss_stage", 0)
        boss_killed = result.get("boss_killed_count", 0)
        team_results = result.get("team_results", [])
        total_turns = result.get("total_turns", 0)

        # 收集单位统计（己方单位key含队伍索引，避免同角色重复编组时key冲突）
        # hp_healed 从 team_results.ally_stats 提取（CompositeTacticController已采集）
        unit_stats = {}
        for team_idx, team_units in enumerate(teams_units):
            team_ally_stats = (team_results[team_idx].get("ally_stats", [])
                               if team_idx < len(team_results) else [])
            for u_idx, u in enumerate(team_units):
                key = f"{u.unit_id}_t{team_idx}"
                hp_healed = 0
                if u_idx < len(team_ally_stats):
                    hp_healed = team_ally_stats[u_idx].get("hp_healed", 0)
                unit_stats[key] = {
                    "name": u.name,
                    "side": "ally",
                    "team": team_idx,
                    "uid": u.unit_id,
                    "damage_dealt": getattr(u, 'damage_dealt_total', 0),
                    "damage_received": getattr(u, 'damage_taken_total', 0),
                    "hp_healed": hp_healed,
                    "hp_received": 0,
                }

        for u in bf.enemy_team:
            uid = u.unit_id
            unit_stats[uid] = {
                "name": u.name,
                "side": "enemy",
                "damage_dealt": getattr(u, 'damage_dealt_total', 0),
                "damage_received": getattr(u, 'damage_taken_total', 0),
                "hp_healed": 0,
                "hp_received": 0,
            }

        # 各队得分（对敌方伤害 - 敌方回血）
        team_damages = [tr.get("damage_to_boss", 0) for tr in team_results]

        results.append({
            'seed': seed,
            'score': score,
            'boss_stage': boss_stage,
            'boss_killed_count': boss_killed,
            'total_turns': total_turns,
            'team_damages': team_damages,
            'unit_stats': unit_stats,
        })

    return results