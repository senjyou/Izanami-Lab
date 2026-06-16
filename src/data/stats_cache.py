"""
角色属性缓存管理器（数据库版本）

功能:
- 管理预计算的角色面板数据缓存（存储在SQLite数据库）
- 支持从数据库读取和更新缓存
- 提供默认配置重置功能
"""

import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import asdict

from src.data.data_loader import DataLoader
# 使用数据库版本的属性计算器
from src.database.stat_calculator import DBStatCalculator, ModuleConfig as DBModuleConfig
from src.data.models import CalculatedStats
from src.config.character_config import CharacterConfig, ModuleConfig
from src.config.player_config import PlayerConfig, SchoolLevels


class CharacterStatsCache:
    """角色属性缓存管理器（数据库版本）"""
    
    DB_FILE = "db/character_stats.db"  # 数据库文件路径
    
    # 默认玩家配置
    DEFAULT_PLAYER_CONFIG = PlayerConfig(
        school_level=50,
        school_levels=SchoolLevels(
            physical_level=50,
            en_level=50,
            agility_level=50,
            fire_level=50,
            water_level=50,
            earth_level=50,
            wind_level=50,
            light_level=50,
            dark_level=50
        ),
        equipment_enabled=True
    )
    
    # 默认角色配置模板
    DEFAULT_CHARACTER_TEMPLATE = {
        "level": 200,
        "rarity": None,  # 将使用角色最高稀有度
        "affection_level": 40,
        "modules": [
            {"module_id": 0, "tier": 8, "level": 45, "gear_effects": []},
            {"module_id": 0, "tier": 8, "level": 45, "gear_effects": []},
            {"module_id": 0, "tier": 8, "level": 45, "gear_effects": []}
        ],
        "default_skill_level": 15
    }
    
    def __init__(self):
        self.data_loader = DataLoader()
        # 使用数据库版本的计算器
        self.stat_calculator = DBStatCalculator(self.DB_FILE)
        self.db_conn = sqlite3.connect(self.DB_FILE)
        
    def __del__(self):
        """析构函数：关闭数据库连接"""
        if hasattr(self, 'db_conn'):
            self.db_conn.close()
    
    def _get_max_rarity(self, char_id: int) -> int:
        """获取角色的最高稀有度"""
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT MAX(rarity) FROM rarity_bonuses WHERE character_id = ?", (char_id,))
        result = cursor.fetchone()
        return result[0] if result and result[0] else 5
    
    def _get_character_skill_ids(self, char_id: int) -> List[int]:
        """获取角色的技能ID列表"""
        character_skills = self.data_loader.load_character_skills()
        return character_skills.get(char_id, [])
    
    def _map_module_ids(self, char_type: int) -> List[int]:
        """根据角色类型自动映射模块ID"""
        base_id = char_type * 10
        return [base_id + 1, base_id + 2, base_id + 3]
    
    def _get_equipment_ids(self, char_type: int) -> List[int]:
        """根据角色类型获取装备ID"""
        base_id = char_type * 10
        return [base_id + 1, base_id + 2, base_id + 3, base_id + 4]
    
    def get_character_stats(self, char_id: int) -> Optional[dict]:
        """
        从数据库获取角色缓存数据
        
        Returns:
            包含角色信息、配置和属性的字典，如果不存在则返回None
        """
        cursor = self.db_conn.cursor()
        
        # 获取主记录
        cursor.execute("""
            SELECT character_id, name, character_type, attribute,
                   level, rarity, affection_level,
                   hp, attack, defense, speed,
                   critical_rate, critical_damage, advantage_damage,
                   action_point, passive_point,
                   last_modified
            FROM character_cache
            WHERE character_id = ?
        """, (char_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        # 构建返回数据
        result = {
            "character_id": row[0],
            "name": row[1],
            "character_type": row[2],
            "attribute": row[3],
            "config": {
                "level": row[4],
                "rarity": row[5],
                "affection_level": row[6],
                "modules": [],
                "equipment_ids": [],
                "skill_levels": {}
            },
            "stats": {
                "hp": row[7],
                "attack": row[8],
                "defense": row[9],
                "speed": row[10],
                "critical_rate": row[11],
                "critical_damage": row[12],
                "advantage_damage": row[13],
                "action_point": row[14],
                "passive_point": row[15]
            },
            "last_modified": row[16]
        }
        
        # 获取模块配置
        cursor.execute("""
            SELECT module_id, tier, level
            FROM character_modules
            WHERE character_id = ?
            ORDER BY slot
        """, (char_id,))
        
        for mod_row in cursor.fetchall():
            result["config"]["modules"].append({
                "module_id": mod_row[0],
                "tier": mod_row[1],
                "level": mod_row[2],
                "gear_effects": []  # 暂不加载词条
            })
        
        # 获取装备配置
        cursor.execute("""
            SELECT equipment_id
            FROM character_equipment
            WHERE character_id = ?
            ORDER BY slot
        """, (char_id,))
        
        result["config"]["equipment_ids"] = [row[0] for row in cursor.fetchall()]
        
        # 获取技能等级
        cursor.execute("""
            SELECT skill_id, skill_level
            FROM character_skills
            WHERE character_id = ?
        """, (char_id,))
        
        for skill_row in cursor.fetchall():
            result["config"]["skill_levels"][str(skill_row[0])] = skill_row[1]
        
        return result
    
    def _calculate_stats_with_db(self, config: CharacterConfig, player_config: PlayerConfig) -> CalculatedStats:
        """
        使用数据库计算器计算属性（适配器方法）
        """
        char_data = self.data_loader.get_character(config.character_id)
        if not char_data:
            raise ValueError(f"角色 {config.character_id} 不存在")
        
        # 确定学园等级
        type_level = player_config.school_levels.get_level_by_type(char_data.character_type)
        attr_level = player_config.school_levels.get_level_by_attribute(char_data.attribute)
        
        # 转换模块配置
        db_modules = []
        for m in config.modules:
            db_modules.append(DBModuleConfig(
                module_id=m.module_id,
                tier=m.tier,
                level=m.level,
                gear_effects=m.gear_effects
            ))
        
        # 调用数据库计算器
        db_stats = self.stat_calculator.calculate_stats(
            character_id=config.character_id,
            level=config.level,
            rarity=config.rarity,
            affection_level=config.affection_level,
            equipment_ids=config.equipment_ids if player_config.equipment_enabled else [],
            school_type_level=type_level,
            school_attribute_level=attr_level,
            modules=db_modules
        )
        
        # 转换为CalculatedStats
        return CalculatedStats(
            hp=db_stats.hp,
            attack=db_stats.attack,
            defense=db_stats.defense,
            speed=db_stats.speed,
            critical_rate=db_stats.critical_rate,
            critical_damage=db_stats.critical_damage,
            advantage_damage=db_stats.advantage_damage,
            action_point=db_stats.action_point,
            passive_point=db_stats.passive_point
        )
    
    def update_character(self, char_id: int, config: CharacterConfig):
        """
        更新单个角色配置并保存到数据库
        
        Args:
            char_id: 角色ID
            config: 新的角色配置
        """
        char_data = self.data_loader.get_character(char_id)
        if not char_data:
            raise ValueError(f"角色 {char_id} 不存在")
        
        # 重新计算属性（使用数据库版本）
        stats = self._calculate_stats_with_db(config, self.DEFAULT_PLAYER_CONFIG)
        
        cursor = self.db_conn.cursor()
        timestamp = datetime.now().isoformat()
        
        # 更新主记录
        cursor.execute("""
            INSERT OR REPLACE INTO character_cache
            (character_id, name, character_type, attribute,
             level, rarity, affection_level,
             hp, attack, defense, speed,
             critical_rate, critical_damage, advantage_damage,
             action_point, passive_point,
             last_modified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            char_id, char_data.name, char_data.character_type, char_data.attribute,
            config.level, config.rarity, config.affection_level,
            stats.hp, stats.attack, stats.defense, stats.speed,
            stats.critical_rate, stats.critical_damage, stats.advantage_damage,
            stats.action_point, stats.passive_point,
            timestamp
        ))
        
        # 更新模块配置
        cursor.execute("DELETE FROM character_modules WHERE character_id = ?", (char_id,))
        for slot, module in enumerate(config.modules, 1):
            cursor.execute("""
                INSERT INTO character_modules (character_id, slot, module_id, tier, level)
                VALUES (?, ?, ?, ?, ?)
            """, (char_id, slot, module.module_id, module.tier, module.level))
        
        # 更新装备配置
        cursor.execute("DELETE FROM character_equipment WHERE character_id = ?", (char_id,))
        for slot, eq_id in enumerate(config.equipment_ids, 1):
            cursor.execute("""
                INSERT INTO character_equipment (character_id, slot, equipment_id)
                VALUES (?, ?, ?)
            """, (char_id, slot, eq_id))
        
        self.db_conn.commit()
    
    def reset_to_default(self, char_id: int):
        """
        将角色重置为默认配置
        
        从character_cache_default复制数据到character_cache
        """
        cursor = self.db_conn.cursor()
        
        # 复制主记录
        cursor.execute("""
            INSERT OR REPLACE INTO character_cache
            SELECT character_id, name, character_type, attribute,
                   level, rarity, affection_level,
                   hp, attack, defense, speed,
                   critical_rate, critical_damage, advantage_damage,
                   action_point, passive_point,
                   datetime('now')
            FROM character_cache_default
            WHERE character_id = ?
        """, (char_id,))
        
        # 复制模块
        cursor.execute("DELETE FROM character_modules WHERE character_id = ?", (char_id,))
        cursor.execute("""
            INSERT INTO character_modules (character_id, slot, module_id, tier, level)
            SELECT character_id, slot, module_id, tier, level
            FROM character_modules_default
            WHERE character_id = ?
        """, (char_id,))
        
        # 复制装备
        cursor.execute("DELETE FROM character_equipment WHERE character_id = ?", (char_id,))
        cursor.execute("""
            INSERT INTO character_equipment (character_id, slot, equipment_id)
            SELECT character_id, slot, equipment_id
            FROM character_equipment_default
            WHERE character_id = ?
        """, (char_id,))
        
        # 复制技能
        cursor.execute("DELETE FROM character_skills WHERE character_id = ?", (char_id,))
        cursor.execute("""
            INSERT INTO character_skills (character_id, skill_id, skill_level)
            SELECT character_id, skill_id, skill_level
            FROM character_skills_default
            WHERE character_id = ?
        """, (char_id,))
        
        self.db_conn.commit()
    
    def reset_all_to_default(self):
        """将所有角色重置为默认配置"""
        cursor = self.db_conn.cursor()
        
        print("正在重置所有角色到默认配置...")
        
        # 清空当前缓存
        cursor.execute("DELETE FROM character_cache")
        cursor.execute("DELETE FROM character_modules")
        cursor.execute("DELETE FROM character_equipment")
        cursor.execute("DELETE FROM character_skills")
        
        # 从默认表复制
        cursor.execute("""
            INSERT INTO character_cache
            SELECT character_id, name, character_type, attribute,
                   level, rarity, affection_level,
                   hp, attack, defense, speed,
                   critical_rate, critical_damage, advantage_damage,
                   action_point, passive_point,
                   datetime('now')
            FROM character_cache_default
        """)
        
        cursor.execute("""
            INSERT INTO character_modules
            SELECT id, character_id, slot, module_id, tier, level
            FROM character_modules_default
        """)
        
        cursor.execute("""
            INSERT INTO character_equipment
            SELECT id, character_id, slot, equipment_id
            FROM character_equipment_default
        """)
        
        cursor.execute("""
            INSERT INTO character_skills
            SELECT id, character_id, skill_id, skill_level
            FROM character_skills_default
        """)
        
        self.db_conn.commit()
        print("重置完成！")
