#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
技能数据解析桥接器
src/combat_v2/skill_data_resolver.py

职责：
- 将 skills.json (模板标签) + skill_effects_hybrid.json (解析后效果) 
  合并为运行时可直接使用的 ResolvedSkillData
- 在指定技能等级下解析 template_tags 中的变量值（如威力、攻击回数）
- 提取目标选择信息（target_type, target_range, target_priority）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from ..entities_v2.enums import SkillEffectType, Attribute, SkillType
from .battle_logger import battle_logger

_log = battle_logger()


@dataclass
class ResolvedEffect:
    """解析后的单个技能效果"""
    effect_type: str
    target_type: str  
    target_identifier: Optional[str] = None
    value: Optional[float] = None
    duration: Optional[int] = None
    duration_type: Optional[str] = None
    hit_count: Optional[int] = None
    ignore_defense: int = 0
    ignore_shield: int = 0
    condition: Optional[Dict[str, Any]] = None
    flags: Dict[str, Any] = field(default_factory=dict)
    value_tag: Optional[str] = None
    duration_tag: Optional[str] = None
    value_source: Optional[str] = None


@dataclass
class ResolvedEffectBlock:
    """解析后的效果块"""
    block_id: int
    effects: List[ResolvedEffect] = field(default_factory=list)
    condition: Optional[Dict[str, Any]] = None


@dataclass
class ResolvedSkillData:
    """运行时可直接使用的技能数据"""
    skill_id: int
    name: str
    skill_type: int               # 1=AS, 2=PS, 3=EX
    resource_cost: int            # AP/PP/EP消耗
    cooldown: int                 # 冷却回合数
    cooldown_update_timing: Optional[int] = None
    
    # 技能基础属性 (从template_tags解析)
    power: float = 100.0          # 技能威力 (百分比)
    hit_count: int = 1            # 攻击回数
    element: Optional[int] = None # 技能元素（None=施法者元素）
    
    # 目标信息
    display_target_type: Optional[int] = None    # DisplayTargetType
    display_target_range: Optional[int] = None   # DisplayTargetRange
    display_target_priority: Optional[int] = None # DisplayTargetPriority
    
    # 效果数据
    effect_blocks: List[ResolvedEffectBlock] = field(default_factory=list)
    
    # 触发器信息
    trigger_type: Optional[int] = None
    global_condition: Optional[Dict[str, Any]] = None
    
    # 特殊属性
    ignore_defense: int = 0
    ignore_shield: int = 0


class SkillDataResolver:
    """
    技能数据解析器
    
    将 skills.json 中的模板标签与 skill_effects_hybrid.json 中的效果结构
    合并为 ResolvedSkillData，填补运行时可直接使用的具体数值。
    """
    
    def __init__(self, data_loader):
        """
        Args:
            data_loader: DataLoader实例 (src.data.data_loader.DataLoader)
        """
        self.data_loader = data_loader
        self._parsed_skills: Optional[Dict[str, Any]] = None
        self._skills_meta: Optional[Dict[int, Any]] = None
    
    def _ensure_loaded(self):
        """确保数据已加载"""
        if self._parsed_skills is None:
            self._parsed_skills = self.data_loader.load_parsed_skills()
        if self._skills_meta is None:
            self._skills_meta = self.data_loader.load_skills()
    
    def resolve(self, skill_id: int, skill_level: int = 1) -> Optional[ResolvedSkillData]:
        """
        解析技能数据
        
        Args:
            skill_id: 技能ID
            skill_level: 技能等级 (默认1)
            
        Returns:
            ResolvedSkillData 或 None
        """
        self._ensure_loaded()
        
        meta = self._skills_meta.get(skill_id)
        parsed = self._parsed_skills.get(str(skill_id))
        
        if (not meta or not parsed) and skill_id < 0:
            meta = self.data_loader.get_skill_by_id(skill_id)
            parsed = self.data_loader.get_parsed_skill_data(skill_id)
        
        if not meta:
            print(f"  [WARN] 技能 {skill_id} 元数据不存在")
            return None
        if not parsed:
            print(f"  [WARN] 技能 {skill_id} 效果数据不存在")
            return None
        
        tag_values = self._resolve_template_tags(meta, skill_level)
        
        effect_blocks = self._resolve_effect_blocks(parsed, tag_values, skill_level, skill_id)
        
        return ResolvedSkillData(
            skill_id=skill_id,
            name=meta.name if hasattr(meta, 'name') else parsed.get('name', f'Skill_{skill_id}'),
            skill_type=meta.skill_type if hasattr(meta, 'skill_type') else parsed.get('skill_type', 1),
            resource_cost=meta.resource_cost if hasattr(meta, 'resource_cost') else parsed.get('resource_cost', 0),
            cooldown=parsed.get('cooldown') or (meta.cooldown if hasattr(meta, 'cooldown') else 0),
            cooldown_update_timing=meta.cooldown_update_timing if hasattr(meta, 'cooldown_update_timing') and meta.cooldown_update_timing is not None else parsed.get('cooldown_update_timing'),
            power=tag_values.get('威力', 100.0),
            hit_count=int(tag_values.get('攻撃回数', 1)),
            display_target_type=parsed.get('display_target_type'),
            display_target_range=parsed.get('display_target_range'),
            display_target_priority=parsed.get('display_target_priority'),
            effect_blocks=effect_blocks,
            trigger_type=parsed.get('trigger_type'),
            global_condition=parsed.get('global_condition'),
            ignore_defense=parsed.get('ignore_defense', 0),
            ignore_shield=parsed.get('ignore_shield', 0),
        )
    
    def _resolve_template_tags(self, meta, level: int) -> Dict[str, float]:
        """解析模板标签值（委托给 TemplateTag.get_value_at_level）"""
        values = {}
        
        if not hasattr(meta, 'template_tags'):
            return values
        
        for tag_name, tag in meta.template_tags.items():
            if hasattr(tag, 'get_value_at_level'):
                values[tag_name] = tag.get_value_at_level(level)
            elif hasattr(tag, 'values'):
                sorted_vals = sorted(tag.values, key=lambda v: v.level)
                if sorted_vals:
                    values[tag_name] = sorted_vals[0].value
        
        return values
    
    def _resolve_effect_blocks(self, parsed: dict, tag_values: Dict[str, float], skill_level: int = 1, skill_id: int = 0) -> List[ResolvedEffectBlock]:
        """解析效果块"""
        blocks = []
        
        known_tags = {'威力', '攻撃回数'}

        for block_data in parsed.get('effect_blocks', []):
            block_condition = block_data.get('condition')
            if block_condition and isinstance(block_condition, dict):
                if block_condition.get('type') == 'active_level_min':
                    min_level = block_condition.get('value', 0)
                    if skill_level < min_level:
                        continue

            level_min = block_data.get('level_min')
            if level_min is not None and skill_level < level_min:
                continue

            level_max = block_data.get('level_max')
            if level_max is not None and skill_level > level_max:
                continue

            effects = []
            for effect_data in block_data.get('effects', []):
                value = effect_data.get('value')
                value_tag_name = effect_data.get('value_tag')
                if value_tag_name:
                    resolved = tag_values.get(value_tag_name)
                    if resolved is not None:
                        value = resolved

                if value is None or value == 0:
                    etype = effect_data.get('effect_type', '')
                    if etype in ('shield', 'heal', 'recover'):
                        for tag_name, tag_value in tag_values.items():
                            if tag_name not in known_tags:
                                value = tag_value
                                break
                
                hit_count = effect_data.get('hit_count')
                if hit_count is None and effect_data.get('hit_count_tag'):
                    hit_count = int(tag_values.get(effect_data.get('hit_count_tag'), 1))
                
                duration = effect_data.get('duration')
                if duration is None and effect_data.get('duration_tag'):
                    duration = int(tag_values.get(effect_data.get('duration_tag'), 0))
                
                flags = effect_data.get('flags', {})
                if isinstance(flags, dict):
                    hp_scaling_data = flags.get('hp_scaling')
                    if isinstance(hp_scaling_data, dict) and hp_scaling_data.get('max_tag'):
                        max_val = tag_values.get(hp_scaling_data.get('max_tag'))
                        if max_val is not None:
                            hp_scaling_data['max'] = max_val
                            _log.info("[RESOLVER] skill=%d hp_scaling max_tag=%s resolved=%.1f",
                                      skill_id, hp_scaling_data.get('max_tag'), max_val)

                    target_crit_data = flags.get('target_hp_below_crit')
                    if isinstance(target_crit_data, dict) and target_crit_data.get('value_tag'):
                        crit_val = tag_values.get(target_crit_data['value_tag'])
                        if crit_val is not None:
                            target_crit_data['resolved_value'] = crit_val
                            _log.info("[RESOLVER] skill=%d target_hp_below_crit value_tag=%s resolved=%.1f",
                                      skill_id, target_crit_data['value_tag'], crit_val)

                    sub_unit_hp_pct_tag = flags.get('sub_unit_hp_pct_tag')
                    if sub_unit_hp_pct_tag:
                        resolved_val = tag_values.get(sub_unit_hp_pct_tag)
                        if resolved_val is not None:
                            flags['sub_unit_hp_pct'] = resolved_val
                            _log.info("[RESOLVER] skill=%d sub_unit_hp_pct_tag=%s resolved=%.1f",
                                      skill_id, sub_unit_hp_pct_tag, resolved_val)

                effects.append(ResolvedEffect(
                    effect_type=effect_data.get('effect_type', 'unknown'),
                    target_type=effect_data.get('target_type', 'unknown'),
                    target_identifier=effect_data.get('target_identifier'),
                    value=value,
                    duration=duration,
                    duration_type=effect_data.get('duration_type'),
                    hit_count=hit_count,
                    ignore_defense=effect_data.get('ignore_defense', 0),
                    ignore_shield=effect_data.get('ignore_shield', 0),
                    condition=effect_data.get('condition'),
                    flags=flags,
                    value_tag=effect_data.get('value_tag'),
                    duration_tag=effect_data.get('duration_tag'),
                    value_source=effect_data.get('value_source'),
                ))
            
            blocks.append(ResolvedEffectBlock(
                block_id=block_data.get('block_id', 0),
                effects=effects,
                condition=block_data.get('condition'),
            ))
        
        return blocks
    
    def get_character_skills(self, character_id: int, skill_level: int = 1) -> Dict[int, Optional[ResolvedSkillData]]:
        """
        获取角色所有技能的解析数据
        
        Returns:
            {skill_id: ResolvedSkillData}
        """
        skill_ids = self.data_loader.load_character_skills().get(character_id, [])
        result = {}
        for sid in skill_ids:
            resolved = self.resolve(sid, skill_level)
            if resolved:
                result[sid] = resolved
        return result