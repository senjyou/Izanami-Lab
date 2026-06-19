#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
逐步暴击模拟器
src/combat_v2/step_crit_simulator.py

功能：
  1. 预填序列模式：用户提供暴击序列（C/N字符串），模拟器按序列执行
  2. 交互式模式：每到一个暴击决策点暂停，等待用户决定是否暴击
  3. 记录所有暴击决策点和结果，生成详细报告用于对照视频debug
"""

import queue
import threading
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Callable, Tuple


class CritSource(Enum):
    """暴击来源类型"""
    MAIN_ATTACK = "main_attack"      # 普通技能攻击
    ENCHANT = "enchant"              # 附魔伤害
    SUB_UNIT = "sub_unit"            # 子单位伤害
    HEAL = "heal"                    # 治疗（含HOT）


@dataclass
class CritDecisionPoint:
    """暴击决策点"""
    index: int                        # 决策点序号（从1开始）
    source: str                       # 来源类型（CritSource.value）
    attacker_name: str                # 攻击者名称
    attacker_id: str                  # 攻击者unit_id
    target_name: str                  # 目标名称
    target_id: str                    # 目标unit_id
    skill_name: str                   # 技能名称
    skill_id: int                     # 技能ID
    hit_number: int                   # 第几hit（从1开始）
    total_hits: int                   # 总hit数
    crit_rate: float                  # 暴击率
    cannot_crit: bool                 # 是否禁止暴击
    sub_unit_name: str = ""           # 子单位名称（仅sub_unit类型）
    # 决策结果（事后填充）
    is_crit: Optional[bool] = None    # 是否暴击
    damage: int = 0                   # 造成的伤害
    target_hp_after: int = 0          # 目标剩余HP
    target_max_hp: int = 0            # 目标最大HP


@dataclass
class StepResult:
    """一步执行结果（从上一个决策点到当前决策点之间的所有输出）"""
    decision_point: CritDecisionPoint  # 当前决策点
    narrative_lines: List[str]         # 新增的叙事日志行
    battle_state_summary: str          # 战场状态摘要


@dataclass
class BranchCandidate:
    """分支候选项"""
    block_id: int                # block ID
    weight: int                  # 权重
    probability: float           # 概率（0-1）
    description: str             # 效果描述（从 effects 自动生成）


@dataclass
class BranchDecisionPoint:
    """分支决策点（random_choice / probability 分支选择）"""
    index: int                         # 决策点序号（从1开始）
    caster_name: str                   # 施法者名称
    caster_id: str                     # 施法者unit_id
    skill_name: str                    # 技能名称
    skill_id: int                      # 技能ID
    group_id: int                      # 分组ID
    candidates: List[BranchCandidate] = field(default_factory=list)  # 候选分支列表
    selected_block_id: Optional[int] = None  # 选中的block_id（事后填充）


class StepCritSimulator:
    """
    逐步暴击模拟器

    支持两种模式：
    1. 预填序列模式（sequence mode）：
       - 用户提供暴击序列字符串（如 "CNNCCN"，C=暴击, N=不暴击）
       - 模拟器按序列执行，序列用完后回退到随机
       - 无需线程，同步执行

    2. 交互式模式（interactive mode）：
       - 战斗在后台线程运行
       - 每到一个暴击决策点，暂停并通知GUI
       - GUI显示上下文，用户点击"暴击"或"不暴击"
       - 模拟器继续执行到下一个决策点
    """

    def __init__(self):
        # 通用状态
        self._decision_points: List[CritDecisionPoint] = []
        self._decision_index: int = 0
        self._narrative_snapshot: int = 0  # 上次检查时的叙事行数

        # 预填序列模式
        self._crit_sequence: List[bool] = []
        self._sequence_index: int = 0

        # 交互式模式
        self._interactive_queue: queue.Queue = queue.Queue()   # GUI -> Battle
        self._info_queue: queue.Queue = queue.Queue()          # Battle -> GUI
        self._battle_thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._battle_result: Optional[Dict] = None

        # 交互式模式的预填序列（自动应用到指定步骤后切换为交互式）
        self._interactive_prefill: List[bool] = []
        self._interactive_prefill_index: int = 0

        # 分支选择交互式模式（random_choice / probability 分支）
        self._branch_info_queue: queue.Queue = queue.Queue()      # Battle -> GUI
        self._branch_decision_queue: queue.Queue = queue.Queue()  # GUI -> Battle
        self._branch_decision_points: List[BranchDecisionPoint] = []
        self._branch_decision_index: int = 0
        # 分支预填序列（block_id 列表，按决策点顺序）
        self._interactive_branch_prefill: List[int] = []
        self._interactive_branch_prefill_index: int = 0

        # 回调
        self._on_decision_made: Optional[Callable[[CritDecisionPoint], None]] = None

    # ─── 预填序列模式 ───

    def set_crit_sequence(self, sequence_str: str):
        """
        设置预填暴击序列

        Args:
            sequence_str: 暴击序列字符串，支持以下格式：
                "CNNCCN" - C=暴击, N=不暴击
                "100110" - 1=暴击, 0=不暴击
                "YNNYYN" - Y=暴击, N=不暴击
        """
        self._crit_sequence = []
        for ch in sequence_str.strip().upper():
            if ch in ('C', '1', 'Y'):
                self._crit_sequence.append(True)
            elif ch in ('N', '0'):
                self._crit_sequence.append(False)
            # 忽略其他字符（空格、逗号等分隔符）
        self._sequence_index = 0

    def get_crit_sequence_length(self) -> int:
        """获取预填序列长度"""
        return len(self._crit_sequence)

    def get_remaining_sequence_count(self) -> int:
        """获取预填序列剩余数量"""
        return max(0, len(self._crit_sequence) - self._sequence_index)

    # ─── 交互式模式 ───

    def start_interactive_battle(self, battle_setup_func: Callable[[], Dict],
                                 narrative: Optional[Any] = None):
        """
        启动交互式战斗（后台线程）

        Args:
            battle_setup_func: 无参函数，返回battle result dict
                               内部应创建BattleFlowController并调用execute_battle
            narrative: BattleNarrativeWriter实例（可选，用于捕获叙事日志）
        """
        self._running = True
        self._battle_result = None
        self._decision_points = []
        self._decision_index = 0
        self._narrative_snapshot = 0
        self._narrative = narrative
        self._branch_decision_points = []
        self._branch_decision_index = 0

        # 清空队列
        while not self._interactive_queue.empty():
            try:
                self._interactive_queue.get_nowait()
            except queue.Empty:
                break
        while not self._info_queue.empty():
            try:
                self._info_queue.get_nowait()
            except queue.Empty:
                break
        while not self._branch_info_queue.empty():
            try:
                self._branch_info_queue.get_nowait()
            except queue.Empty:
                break
        while not self._branch_decision_queue.empty():
            try:
                self._branch_decision_queue.get_nowait()
            except queue.Empty:
                break

        self._battle_thread = threading.Thread(
            target=self._run_interactive_battle,
            args=(battle_setup_func,),
            daemon=True
        )
        self._battle_thread.start()

    def _run_interactive_battle(self, battle_setup_func: Callable[[], Dict]):
        """交互式战斗线程主函数"""
        try:
            result = battle_setup_func()
            self._battle_result = result
            self._info_queue.put(("battle_complete", result))
        except Exception as e:
            import traceback
            self._info_queue.put(("battle_error", str(e) + "\n" + traceback.format_exc()))
        finally:
            self._running = False

    def make_interactive_decision(self, is_crit: bool):
        """从GUI线程提供交互式暴击决策"""
        self._interactive_queue.put(is_crit)

    def poll_interactive_info(self) -> List[Tuple[str, Any]]:
        """
        从GUI线程轮询交互式信息

        Returns:
            List of (event_type, data) tuples:
            - ("crit_decision", CritDecisionPoint) - 需要用户决策
            - ("battle_complete", result_dict) - 战斗结束
            - ("battle_error", error_str) - 战斗出错
        """
        infos = []
        while not self._info_queue.empty():
            try:
                infos.append(self._info_queue.get_nowait())
            except queue.Empty:
                break
        return infos

    def is_interactive_running(self) -> bool:
        """交互式战斗是否正在运行"""
        return self._running

    def stop_interactive(self):
        """停止交互式战斗"""
        self._running = False
        # 发送一个默认决策以解锁等待的线程
        try:
            self._interactive_queue.put(False)
        except Exception:
            pass
        # 解锁分支决策等待（-1 表示无效 block_id，触发 fallback）
        try:
            self._branch_decision_queue.put(-1)
        except Exception:
            pass

    def set_interactive_prefill(self, sequence_str: str):
        """
        设置交互式模式的预填序列
        战斗开始后，前N步自动使用预填序列（不暂停），用完后切换为交互式

        Args:
            sequence_str: 暴击序列字符串，格式同set_crit_sequence（C/N/1/0/Y）
        """
        self._interactive_prefill = []
        for ch in sequence_str.strip().upper():
            if ch in ('C', '1', 'Y'):
                self._interactive_prefill.append(True)
            elif ch in ('N', '0'):
                self._interactive_prefill.append(False)
        self._interactive_prefill_index = 0

    def get_interactive_prefill_remaining(self) -> int:
        """获取交互式预填序列剩余数量"""
        return max(0, len(self._interactive_prefill) - self._interactive_prefill_index)

    def get_interactive_prefill_total(self) -> int:
        """获取交互式预填序列总长度"""
        return len(self._interactive_prefill)

    # ─── 暴击覆盖函数（由DamageService调用） ───

    def create_crit_override_func(self, mode: str = "sequence") -> Callable[[Dict], bool]:
        """
        创建暴击覆盖函数，供DamageService使用

        Args:
            mode: "sequence" - 预填序列模式
                  "interactive" - 交互式模式

        Returns:
            暴击覆盖函数，接收context dict，返回bool
        """
        if mode == "sequence":
            return self._sequence_crit_override
        elif mode == "interactive":
            return self._interactive_crit_override
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def _sequence_crit_override(self, context: Dict) -> bool:
        """预填序列模式的暴击覆盖"""
        self._decision_index += 1

        point = CritDecisionPoint(
            index=self._decision_index,
            source=context.get('source', 'unknown'),
            attacker_name=context.get('attacker_name', ''),
            attacker_id=context.get('attacker_id', ''),
            target_name=context.get('target_name', ''),
            target_id=context.get('target_id', ''),
            skill_name=context.get('skill_name', ''),
            skill_id=context.get('skill_id', 0),
            hit_number=context.get('hit_number', 0),
            total_hits=context.get('total_hits', 0),
            crit_rate=context.get('crit_rate', 0.0),
            cannot_crit=context.get('cannot_crit', False),
            sub_unit_name=context.get('sub_unit_name', ''),
        )

        # 从序列中获取决策
        if self._sequence_index < len(self._crit_sequence):
            is_crit = self._crit_sequence[self._sequence_index]
            self._sequence_index += 1
        else:
            # 序列用完，回退到随机
            is_crit = random.random() < point.crit_rate

        point.is_crit = is_crit
        self._decision_points.append(point)
        return is_crit

    def _interactive_crit_override(self, context: Dict) -> bool:
        """交互式模式的暴击覆盖"""
        # 如果已停止，直接返回随机结果
        if not self._running:
            return random.random() < context.get('crit_rate', 0.0)

        self._decision_index += 1

        point = CritDecisionPoint(
            index=self._decision_index,
            source=context.get('source', 'unknown'),
            attacker_name=context.get('attacker_name', ''),
            attacker_id=context.get('attacker_id', ''),
            target_name=context.get('target_name', ''),
            target_id=context.get('target_id', ''),
            skill_name=context.get('skill_name', ''),
            skill_id=context.get('skill_id', 0),
            hit_number=context.get('hit_number', 0),
            total_hits=context.get('total_hits', 0),
            crit_rate=context.get('crit_rate', 0.0),
            cannot_crit=context.get('cannot_crit', False),
            sub_unit_name=context.get('sub_unit_name', ''),
        )

        # 优先使用预填序列（自动应用，不暂停）
        if self._interactive_prefill_index < len(self._interactive_prefill):
            is_crit = self._interactive_prefill[self._interactive_prefill_index]
            self._interactive_prefill_index += 1
            point.is_crit = is_crit
            self._decision_points.append(point)
            # 通知GUI预填步骤已执行
            self._info_queue.put(("prefill_step", point))
            return is_crit

        # 预填序列用完，切换为交互式（暂停等待用户决策）
        # 发送决策点到GUI
        self._info_queue.put(("crit_decision", point))

        # 等待用户决策（带超时循环，可被stop中断）
        is_crit = False
        while self._running:
            try:
                is_crit = self._interactive_queue.get(timeout=0.2)
                break
            except queue.Empty:
                continue

        if not self._running:
            # 战斗已被停止，返回随机结果让战斗线程尽快结束
            is_crit = random.random() < point.crit_rate

        point.is_crit = is_crit
        self._decision_points.append(point)
        return is_crit

    # ─── 分支选择覆盖函数（由SkillService调用） ───

    def create_branch_override_func(self, mode: str = "interactive") -> Callable[[Dict], int]:
        """
        创建分支选择覆盖函数，供SkillService使用

        Args:
            mode: "sequence" - 预填序列模式（无暂停，按预填序列或随机）
                  "interactive" - 交互式模式（暂停等待用户决策）

        Returns:
            分支选择覆盖函数，接收context dict，返回选中的block_id
        """
        if mode == "sequence":
            return self._sequence_branch_override
        elif mode == "interactive":
            return self._interactive_branch_override
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def _sequence_branch_override(self, context: Dict) -> int:
        """预填序列模式的分支选择覆盖（无暂停，按预填序列或随机）"""
        self._branch_decision_index += 1

        candidates_raw = context.get('candidates', [])
        total_weight = sum(c.get('weight', 1) for c in candidates_raw) or 1
        candidates = [
            BranchCandidate(
                block_id=c.get('block_id', 0),
                weight=c.get('weight', 1),
                probability=c.get('weight', 1) / total_weight,
                description=c.get('description', ''),
            )
            for c in candidates_raw
        ]

        point = BranchDecisionPoint(
            index=self._branch_decision_index,
            caster_name=context.get('caster_name', ''),
            caster_id=context.get('caster_id', ''),
            skill_name=context.get('skill_name', ''),
            skill_id=context.get('skill_id', 0),
            group_id=context.get('group_id', 0),
            candidates=candidates,
        )

        # 从预填序列获取决策
        if self._interactive_branch_prefill_index < len(self._interactive_branch_prefill):
            selected = self._interactive_branch_prefill[self._interactive_branch_prefill_index]
            self._interactive_branch_prefill_index += 1
            # 验证 selected 是否在候选 block_id 中
            valid_ids = {c.block_id for c in candidates}
            if selected not in valid_ids:
                # 无效 block_id，回退随机
                weights = [c.weight for c in candidates]
                ids = [c.block_id for c in candidates]
                selected = random.choices(ids, weights=weights, k=1)[0]
        else:
            # 预填用完，回退随机
            weights = [c.weight for c in candidates]
            ids = [c.block_id for c in candidates]
            selected = random.choices(ids, weights=weights, k=1)[0]

        point.selected_block_id = selected
        self._branch_decision_points.append(point)
        return selected

    def _interactive_branch_override(self, context: Dict) -> int:
        """交互式模式的分支选择覆盖（暂停等待用户决策）"""
        # 如果已停止，直接返回随机结果
        if not self._running:
            candidates_raw = context.get('candidates', [])
            weights = [c.get('weight', 1) for c in candidates_raw]
            ids = [c.get('block_id', 0) for c in candidates_raw]
            if ids:
                return random.choices(ids, weights=weights, k=1)[0]
            return -1

        self._branch_decision_index += 1

        candidates_raw = context.get('candidates', [])
        total_weight = sum(c.get('weight', 1) for c in candidates_raw) or 1
        candidates = [
            BranchCandidate(
                block_id=c.get('block_id', 0),
                weight=c.get('weight', 1),
                probability=c.get('weight', 1) / total_weight,
                description=c.get('description', ''),
            )
            for c in candidates_raw
        ]

        point = BranchDecisionPoint(
            index=self._branch_decision_index,
            caster_name=context.get('caster_name', ''),
            caster_id=context.get('caster_id', ''),
            skill_name=context.get('skill_name', ''),
            skill_id=context.get('skill_id', 0),
            group_id=context.get('group_id', 0),
            candidates=candidates,
        )

        # 优先使用预填序列（自动应用，不暂停）
        if self._interactive_branch_prefill_index < len(self._interactive_branch_prefill):
            selected = self._interactive_branch_prefill[self._interactive_branch_prefill_index]
            self._interactive_branch_prefill_index += 1
            # 验证 selected 是否在候选 block_id 中
            valid_ids = {c.block_id for c in candidates}
            if selected not in valid_ids:
                # 无效 block_id，回退随机
                weights = [c.weight for c in candidates]
                ids = [c.block_id for c in candidates]
                selected = random.choices(ids, weights=weights, k=1)[0]
            point.selected_block_id = selected
            self._branch_decision_points.append(point)
            # 通知GUI预填步骤已执行
            self._branch_info_queue.put(("branch_prefill_step", point))
            return selected

        # 预填序列用完，切换为交互式（暂停等待用户决策）
        # 发送决策点到GUI
        self._branch_info_queue.put(("branch_decision", point))

        # 等待用户决策（带超时循环，可被stop中断）
        selected = -1
        while self._running:
            try:
                selected = self._branch_decision_queue.get(timeout=0.2)
                break
            except queue.Empty:
                continue

        if not self._running or selected == -1:
            # 战斗已被停止，返回随机结果让战斗线程尽快结束
            weights = [c.weight for c in candidates]
            ids = [c.block_id for c in candidates]
            selected = random.choices(ids, weights=weights, k=1)[0]

        point.selected_block_id = selected
        self._branch_decision_points.append(point)
        return selected

    def make_interactive_branch_decision(self, block_id: int):
        """从GUI线程提供交互式分支决策"""
        self._branch_decision_queue.put(block_id)

    def poll_branch_interactive_info(self) -> List[Tuple[str, Any]]:
        """
        从GUI线程轮询分支交互信息

        Returns:
            List of (event_type, data) tuples:
            - ("branch_decision", BranchDecisionPoint) - 需要用户决策
            - ("branch_prefill_step", BranchDecisionPoint) - 预填步骤已执行
        """
        infos = []
        while not self._branch_info_queue.empty():
            try:
                infos.append(self._branch_info_queue.get_nowait())
            except queue.Empty:
                break
        return infos

    def set_interactive_branch_prefill(self, block_ids: List[int]):
        """设置交互式模式的分支预填序列（block_id 列表）"""
        self._interactive_branch_prefill = list(block_ids)
        self._interactive_branch_prefill_index = 0

    def get_branch_decision_points(self) -> List[BranchDecisionPoint]:
        """获取所有已记录的分支决策点"""
        return list(self._branch_decision_points)

    def generate_branch_sequence_string(self) -> str:
        """从已记录的分支决策点生成分支序列字符串（block_id 逗号分隔）"""
        return ",".join(str(dp.selected_block_id) for dp in self._branch_decision_points
                         if dp.selected_block_id is not None)

    # ─── 结果查询 ───

    def get_decision_points(self) -> List[CritDecisionPoint]:
        """获取所有已记录的暴击决策点"""
        return list(self._decision_points)

    def get_decision_point(self, index: int) -> Optional[CritDecisionPoint]:
        """获取指定序号的暴击决策点"""
        for dp in self._decision_points:
            if dp.index == index:
                return dp
        return None

    def get_battle_result(self) -> Optional[Dict]:
        """获取战斗结果"""
        return self._battle_result

    def update_decision_result(self, index: int, damage: int,
                                target_hp_after: int, target_max_hp: int):
        """更新决策点的结果信息（由skill_service调用）"""
        for dp in self._decision_points:
            if dp.index == index:
                dp.damage = damage
                dp.target_hp_after = target_hp_after
                dp.target_max_hp = target_max_hp
                break

    # ─── 报告生成 ───

    def generate_report(self) -> str:
        """生成详细的暴击决策报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("  逐步暴击模拟报告")
        lines.append("=" * 70)
        lines.append("")

        source_labels = {
            "main_attack": "技能攻击",
            "enchant": "附魔伤害",
            "sub_unit": "子单位伤害",
        }

        for dp in self._decision_points:
            source_label = source_labels.get(dp.source, dp.source)
            crit_str = "★暴击" if dp.is_crit else "·不暴击"
            hp_str = f"HP:{dp.target_hp_after}/{dp.target_max_hp}" if dp.target_max_hp > 0 else ""

            lines.append(f"[#{dp.index:03d}] {dp.attacker_name} → {dp.target_name}")
            lines.append(f"      技能: {dp.skill_name} (ID:{dp.skill_id})")
            if dp.source == "sub_unit" and dp.sub_unit_name:
                lines.append(f"      子单位: {dp.sub_unit_name}")
            lines.append(f"      类型: {source_label} | Hit: {dp.hit_number}/{dp.total_hits}")
            lines.append(f"      暴击率: {dp.crit_rate * 100:.1f}% | 决策: {crit_str}")
            if dp.damage > 0:
                lines.append(f"      伤害: {dp.damage} | {hp_str}")
            lines.append("")

        # 统计
        total = len(self._decision_points)
        crit_count = sum(1 for dp in self._decision_points if dp.is_crit)
        no_crit_count = total - crit_count
        lines.append("-" * 70)
        lines.append(f"  总决策点: {total} | 暴击: {crit_count} | 不暴击: {no_crit_count}")
        if total > 0:
            lines.append(f"  实际暴击率: {crit_count / total * 100:.1f}%")
        lines.append("=" * 70)

        # 分支决策点记录
        if self._branch_decision_points:
            lines.append("")
            lines.append("=" * 70)
            lines.append("  分支决策记录（random_choice / probability）")
            lines.append("=" * 70)
            lines.append("")

            for bp in self._branch_decision_points:
                lines.append(f"[#{bp.index:03d}] {bp.caster_name} - {bp.skill_name} (ID:{bp.skill_id})")
                lines.append(f"      分组: group={bp.group_id}")
                for i, cand in enumerate(bp.candidates):
                    marker = " ★" if cand.block_id == bp.selected_block_id else ""
                    lines.append(f"      候选[{i+1}] block={cand.block_id} "
                                 f"概率={cand.probability * 100:.1f}% "
                                 f"权重={cand.weight}{marker} {cand.description}")
                lines.append(f"      → 选择: block {bp.selected_block_id}")
                lines.append("")

            lines.append("-" * 70)
            lines.append(f"  分支决策点总数: {len(self._branch_decision_points)}")
            lines.append(f"  分支序列: {self.generate_branch_sequence_string()}")
            lines.append("=" * 70)

        return "\n".join(lines)

    def generate_sequence_string(self) -> str:
        """从已记录的决策点生成暴击序列字符串（C/N格式）"""
        return "".join("C" if dp.is_crit else "N" for dp in self._decision_points)

    # ─── 重置 ───

    def reset(self):
        """重置模拟器状态"""
        self._decision_points = []
        self._decision_index = 0
        self._sequence_index = 0
        self._narrative_snapshot = 0
        self._battle_result = None
        self._running = False
        self._interactive_prefill_index = 0
        # 注意：不重置 _interactive_prefill，允许跨次复用
        self._branch_decision_points = []
        self._branch_decision_index = 0
        self._interactive_branch_prefill_index = 0
        # 注意：不重置 _interactive_branch_prefill，允许跨次复用

        # 清空队列
        while not self._interactive_queue.empty():
            try:
                self._interactive_queue.get_nowait()
            except queue.Empty:
                break
        while not self._info_queue.empty():
            try:
                self._info_queue.get_nowait()
            except queue.Empty:
                break
        while not self._branch_info_queue.empty():
            try:
                self._branch_info_queue.get_nowait()
            except queue.Empty:
                break
        while not self._branch_decision_queue.empty():
            try:
                self._branch_decision_queue.get_nowait()
            except queue.Empty:
                break
