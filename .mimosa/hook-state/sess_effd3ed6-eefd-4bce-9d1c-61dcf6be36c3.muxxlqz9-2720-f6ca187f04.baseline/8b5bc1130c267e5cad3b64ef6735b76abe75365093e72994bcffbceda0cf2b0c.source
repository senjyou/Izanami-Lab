"""
角色属性计算器

用于计算角色在特定等级、稀有度、好感度下的最终属性
"""

from typing import Dict, Optional, Any
from .models import CalculatedStats, CharacterData, RarityBonus
from ..config.character_config import CharacterConfig
from ..config.player_config import PlayerConfig
from .data_loader import DataLoader


class StatCalculator:
    """角色属性计算器"""

    def __init__(self, level_lerp_data: Dict[int, float], data_loader: Optional[DataLoader] = None):
        self.level_lerp_data = level_lerp_data
        self.data_loader = data_loader if data_loader else DataLoader()

    def _get_net_rarity_bonus(self, character_id: int, target_rarity: int, default_rarity: int) -> Optional[RarityBonus]:
        target = self.data_loader.get_rarity_bonus(character_id, target_rarity)
        if target is None:
            return None
        default = self.data_loader.get_rarity_bonus(character_id, default_rarity)
        if default is None:
            return target
        return RarityBonus(
            character_id=character_id,
            rarity=target_rarity,
            additional_hp=target.additional_hp - default.additional_hp,
            additional_attack=target.additional_attack - default.additional_attack,
            additional_defense=target.additional_defense - default.additional_defense,
            additional_speed=target.additional_speed - default.additional_speed,
            additional_crit_rate=target.additional_crit_rate - default.additional_crit_rate,
            additional_action_point=target.additional_action_point - default.additional_action_point,
            additional_passive_point=target.additional_passive_point - default.additional_passive_point,
        )

    def calculate_stats(self, char_config: CharacterConfig, player_config: PlayerConfig) -> CalculatedStats:
        """
        根据配置计算角色最终属性
        """
        # 1. 获取静态数据
        char_data = self.data_loader.get_character(char_config.character_id)
        if not char_data:
            raise ValueError(f"Character {char_config.character_id} not found")
            
        # 基础属性计算
        min_stats = char_data.min_level_stats
        max_stats = char_data.max_level_stats
        bonus_stats = char_data.bonus_per_level
        
        base_hp = self.calculate_stat_at_level(char_config.level, min_stats.hp, max_stats.hp, bonus_stats.hp)
        base_atk = self.calculate_stat_at_level(char_config.level, min_stats.attack, max_stats.attack, bonus_stats.attack)
        base_def = self.calculate_stat_at_level(char_config.level, min_stats.defense, max_stats.defense, bonus_stats.defense)
        base_spd = self.calculate_stat_at_level(char_config.level, min_stats.speed, max_stats.speed, bonus_stats.speed)
        
        # 3. 稀有度加成 (delta = target_rarity - default_rarity)
        rarity_bonus_data = None
        if char_config.rarity != char_data.default_rarity:
            rarity_bonus_data = self._get_net_rarity_bonus(
                char_config.character_id, char_config.rarity, char_data.default_rarity)
        
        # 4. 好感度加成
        affection_bonus_data = self.data_loader.get_affection_bonus(char_config.affection_level, char_data.character_type)
        
        # 5. 学园等级加成 (Group 1: Type, Group 2: Attribute)
        school_hp = school_atk = school_def = 0
        if player_config.school_level > 0:
            # Group 1: Character Type
            type_level = player_config.school_levels.get_level_by_type(char_data.character_type)
            g1_bonus = self.data_loader.get_school_bonus(1, type_level)
            if g1_bonus:
                school_hp += g1_bonus.hp_bonus
                school_atk += g1_bonus.attack_bonus
                school_def += g1_bonus.defense_bonus
                
            # Group 2: Character Attribute
            attr_level = player_config.school_levels.get_level_by_attribute(char_data.attribute)
            g2_bonus = self.data_loader.get_school_bonus(2, attr_level)
            if g2_bonus:
                school_hp += g2_bonus.hp_bonus
                school_atk += g2_bonus.attack_bonus
                school_def += g2_bonus.defense_bonus
            
        # 6. 装备加成 (按角色类型取总值)
        equip_hp = equip_atk = equip_def = 0
        if player_config.equipment_enabled:
            type_bonus = player_config.equipment_bonuses.get(char_data.character_type, {})
            if type_bonus:
                equip_hp = type_bonus.get("hp", 0)
                equip_atk = type_bonus.get("attack", 0)
                equip_def = type_bonus.get("defense", 0)
        
        # 7. 模块加成
        mod_hp_fixed = mod_atk_fixed = mod_def_fixed = 0
        mod_hp_pct = mod_atk_pct = mod_def_pct = 0.0
        
        for mod_cfg in char_config.modules:
            # 模块ID是两位数，第一位是类型，第二位是功能
            # 需要先获取模块基础数据来确认tier数据是否存在
            mod_status = self.data_loader.get_module_status(mod_cfg.module_id, mod_cfg.tier)
            if mod_status:
                # 公式: base + per_level * (level - 1)
                hp_bonus = int(mod_status.hp_base + mod_status.hp_per_level * (mod_cfg.level - 1))
                atk_bonus = int(mod_status.attack_base + mod_status.attack_per_level * (mod_cfg.level - 1))
                def_bonus = int(mod_status.defense_base + mod_status.defense_per_level * (mod_cfg.level - 1))
                
                mod_hp_fixed += hp_bonus
                mod_atk_fixed += atk_bonus
                mod_def_fixed += def_bonus
                
                mod_hp_pct += mod_status.hp_rate
                mod_atk_pct += mod_status.attack_rate
                mod_def_pct += mod_status.defense_rate
        
        # 8. 词条加成（从模块配置中提取）
        gear_hp_pct = gear_atk_pct = gear_def_pct = gear_spd_pct = 0.0
        gear_crit_rate = gear_crit_damage = gear_advantage_damage = 0.0
        
        # 词条效果类型常量
        GEAR_TYPE_HP_PERCENT = 1
        GEAR_TYPE_ATTACK_PERCENT = 2
        GEAR_TYPE_DEFENSE_PERCENT = 3
        GEAR_TYPE_SPEED_PERCENT = 4
        GEAR_TYPE_CRIT_RATE = 5
        GEAR_TYPE_CRIT_DAMAGE = 6
        GEAR_TYPE_ADVANTAGE_DAMAGE = 7
        
        for mod_cfg in char_config.modules:
            for gear_effect in mod_cfg.gear_effects:
                effect_type = gear_effect.get('effect_type')
                value = gear_effect.get('value', 0.0) / 100.0
                
                if effect_type == GEAR_TYPE_HP_PERCENT:
                    gear_hp_pct += value
                elif effect_type == GEAR_TYPE_ATTACK_PERCENT:
                    gear_atk_pct += value
                elif effect_type == GEAR_TYPE_DEFENSE_PERCENT:
                    gear_def_pct += value
                elif effect_type == GEAR_TYPE_SPEED_PERCENT:
                    gear_spd_pct += value
                elif effect_type == GEAR_TYPE_CRIT_RATE:
                    gear_crit_rate += value
                elif effect_type == GEAR_TYPE_CRIT_DAMAGE:
                    gear_crit_damage += value
                elif effect_type == GEAR_TYPE_ADVANTAGE_DAMAGE:
                    gear_advantage_damage += value
                
        # 9. 计算最终面板
        final_hp = calculate_final_panel_stat(
            base_hp, 
            rarity_bonus_data.additional_hp if rarity_bonus_data else 0,
            affection_bonus_data.additional_hp if affection_bonus_data else 0,
            school_hp,
            equip_hp,
            mod_hp_fixed,
            mod_hp_pct,
            gear_hp_pct
        )
        
        final_atk = calculate_final_panel_stat(
            base_atk,
            rarity_bonus_data.additional_attack if rarity_bonus_data else 0,
            affection_bonus_data.additional_attack if affection_bonus_data else 0,
            school_atk,
            equip_atk,
            mod_atk_fixed,
            mod_atk_pct,
            gear_atk_pct
        )
        
        final_def = calculate_final_panel_stat(
            base_def,
            rarity_bonus_data.additional_defense if rarity_bonus_data else 0,
            affection_bonus_data.additional_defense if affection_bonus_data else 0,
            school_def,
            equip_def,
            mod_def_fixed,
            mod_def_pct,
            gear_def_pct
        )
        
        final_spd = calculate_final_panel_stat(
            base_spd,
            rarity_bonus_data.additional_speed if rarity_bonus_data else 0,
            affection_bonus_data.additional_speed if affection_bonus_data else 0,
            0, # school bonus spd (usually 0)
            0, # equip spd (usually 0)
            0, # mod spd fixed
            0.0, # mod spd pct
            gear_spd_pct
        )
        
        # 10. 资源点数
        base_ap = char_data.action_point
        base_pp = char_data.passive_point
        
        rarity_ap = rarity_bonus_data.additional_action_point if rarity_bonus_data else 0
        rarity_pp = rarity_bonus_data.additional_passive_point if rarity_bonus_data else 0
        
        aff_ap = affection_bonus_data.additional_action_point if affection_bonus_data else 0
        aff_pp = affection_bonus_data.additional_passive_point if affection_bonus_data else 0
        
        total_ap = base_ap + rarity_ap + aff_ap
        total_pp = base_pp + rarity_pp + aff_pp
        
        # 11. 暴击率、暴击伤害、有利属性伤害（加算）
        # 暴击率 = 基础 + 稀有度 + 词条
        crit_rate = min_stats.crit_rate
        if rarity_bonus_data:
            crit_rate += rarity_bonus_data.additional_crit_rate
        crit_rate += gear_crit_rate
        
        # 暴击伤害 = 1.5 + 词条
        crit_damage = 1.5 + gear_crit_damage
        
        # 有利属性伤害 = 1.25 + 词条
        advantage_damage = 1.25 + gear_advantage_damage
            
        return CalculatedStats(
            hp=final_hp,
            attack=final_atk,
            defense=final_def,
            speed=final_spd,
            critical_rate=crit_rate,
            critical_damage=crit_damage,
            advantage_damage=advantage_damage,
            initial_ap=total_ap,
            initial_pp=total_pp,
            max_ap=total_ap,
            max_pp=total_pp
        )
    def calculate_stat_at_level(
        self,
        level: int,
        min_stat: int,
        max_stat: int,
        bonus_per_level: int
    ) -> int:
        """
        计算角色在指定等级的属性值
        
        公式:
        - 1-200级: MinStat + (MaxStat - MinStat) * Amount[level]
        - 201级起: MaxStat + (level - 200) * BonusPerLevel
        
        Args:
            level: 角色等级
            min_stat: 1级基础属性
            max_stat: 200级基础属性
            bonus_per_level: 201级起每级加成
            
        Returns:
            计算后的属性值
        """
        if level < 1:
            return min_stat
        
        if level <= 200:
            # 使用插值数据
            if level in self.level_lerp_data:
                amount = self.level_lerp_data[level]
                return int(min_stat + (max_stat - min_stat) * amount)
            else:
                # 如果没有对应等级的数据，使用线性插值
                return int(min_stat + (max_stat - min_stat) * (level - 1) / 199)
        else:
            # 201级以上使用固定加成
            bonus_levels = level - 200
            return int(max_stat + bonus_levels * bonus_per_level)
    
    def apply_rarity_bonus(
        self,
        base_value: int,
        rarity_bonus: int
    ) -> int:
        """
        应用稀有度加成
        
        Args:
            base_value: 基础属性值
            rarity_bonus: 稀有度加成值
            
        Returns:
            加成后的属性值
        """
        return base_value + rarity_bonus
    
    def apply_affection_bonus(
        self,
        base_value: int,
        affection_bonus: int
    ) -> int:
        """
        应用好感度加成
        
        Args:
            base_value: 基础属性值
            affection_bonus: 好感度加成值（总加成，非逐级累加）
            
        Returns:
            加成后的属性值
        """
        return base_value + affection_bonus
    
    def apply_school_bonus(
        self,
        base_value: int,
        school_bonus: int
    ) -> int:
        """
        应用学园等级加成
        
        Args:
            base_value: 基础属性值
            school_bonus: 学园等级加成值
            
        Returns:
            加成后的属性值
        """
        return base_value + school_bonus
    
    def calculate_final_stat(
        self,
        level: int,
        min_stat: int,
        max_stat: int,
        bonus_per_level: int,
        rarity_bonus: int = 0,
        affection_bonus: int = 0,
        school_bonus: int = 0
    ) -> int:
        """
        计算最终属性值（包含所有加成）
        
        Args:
            level: 角色等级
            min_stat: 1级基础属性
            max_stat: 200级基础属性
            bonus_per_level: 201级起每级加成
            rarity_bonus: 稀有度加成
            affection_bonus: 好感度加成
            school_bonus: 学园等级加成
            
        Returns:
            最终属性值
        """
        # 1. 计算等级属性
        base_stat = self.calculate_stat_at_level(level, min_stat, max_stat, bonus_per_level)
        
        # 2. 应用稀有度加成
        stat_with_rarity = self.apply_rarity_bonus(base_stat, rarity_bonus)
        
        # 3. 应用好感度加成
        stat_with_affection = self.apply_affection_bonus(stat_with_rarity, affection_bonus)
        
        # 4. 应用学园等级加成
        final_stat = self.apply_school_bonus(stat_with_affection, school_bonus)
        
        return final_stat


def calculate_resource_points(
    base_points: int,
    rarity_additional_points: int
) -> int:
    """
    计算资源点数（AP/PP）
    
    公式: 总点数 = 基础点数(CharacterMaster) + 稀有度加成(CharacterRarityStatusMaster)
    
    Args:
        base_points: 基础点数
        rarity_additional_points: 稀有度额外点数
        
    Returns:
        总资源点数
    """
    return base_points + rarity_additional_points


def calculate_final_panel_stat(
    base_stat: int,
    rarity_bonus: int,
    affection_bonus: int,
    school_bonus: int,
    equipment_bonus: int,
    module_fixed_bonus: int,
    module_percentage: float,
    gear_percentage: float = 0.0
) -> int:
    """
    计算最终面板属性（含装备和模块）
    
    公式:
    面板属性 = (角色原始属性 + 稀有度 + 好感度 + 学园 + 装备 + 模块固值) * (1 + 模块百分比 + 词条百分比)
    结果向下取整
    
    Args:
        base_stat: 角色原始属性（含等级成长）
        rarity_bonus: 稀有度加成
        affection_bonus: 好感度加成
        school_bonus: 学园等级加成
        equipment_bonus: 装备加成
        module_fixed_bonus: 模块固定值加成
        module_percentage: 模块百分比加成
        gear_percentage: 词条百分比加成（可选）
        
    Returns:
        最终面板属性值（向下取整）
    """
    # 固定值加算
    total_fixed = (
        base_stat + 
        rarity_bonus + 
        affection_bonus + 
        school_bonus + 
        equipment_bonus + 
        module_fixed_bonus
    )
    
    # 百分比乘算
    total_percentage = 1.0 + module_percentage + gear_percentage
    
    # 最终值向下取整
    final_stat = int(total_fixed * total_percentage)
    
    return final_stat


def calculate_additive_stat(
    base_value: float,
    *bonuses: float
) -> float:
    """
    计算普通加算属性（暴击率、克制伤害、暴击伤害等）
    
    公式: 最终值 = 基础值 + 加成1 + 加成2 + ...
    
    Args:
        base_value: 基础值
        *bonuses: 各种加成值
        
    Returns:
        最终属性值
    """
    return base_value + sum(bonuses)

