"""
数据加载器
src/data/data_loader.py

负责加载所有JSON数据文件并提供缓存查询接口
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from .models import (
    BaseStats, BonusStats, StatGrades,
    CharacterData, SkillData, SkillDescription, AdditionalKind,
    TemplateTag, TemplateTagValue, DisplayInfo,
    CharacterSkillMapping, LevelLerpData, AffectionBonus, RarityBonus,
    SchoolLevelBonus, SchoolSystem, EquipmentData,
    ModuleData, ModuleStatus, GearEffect, ModuleGearData,
    EnemyData, MemoryData, MemoryHighlight,
)
from ..entities_v2.custom_dummy import (
    CustomDummyConfig, CustomASConfig, CustomPSConfig, CustomEffectConfig,
    build_synthetic_character_data, build_custom_skill_data,
    build_custom_parsed_skill, collect_custom_skill_ids,
)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def set_data_dir(path: str):
    """设置数据目录路径（供 PyInstaller 打包后使用）"""
    global _DATA_DIR
    _DATA_DIR = Path(path)


class DataLoader:
    """数据加载器 - 单例模式加载所有游戏数据"""

    def __init__(self, base_path: str = None, user_data_dir: str = None):
        if base_path:
            self._data_dir = Path(base_path) / "data"
        else:
            self._data_dir = _DATA_DIR
        self._user_data_dir = Path(user_data_dir) if user_data_dir else None

        self._characters: Optional[Dict[int, CharacterData]] = None
        self._skills: Optional[Dict[int, SkillData]] = None
        self._parsed_skills: Optional[Dict[str, Any]] = None
        self._character_skills: Optional[Dict[int, List[int]]] = None
        self._level_lerp: Optional[Dict[int, float]] = None
        self._affection_bonuses: Optional[Dict[int, Dict[int, AffectionBonus]]] = None
        self._rarity_bonuses: Optional[Dict[int, Dict[int, RarityBonus]]] = None
        self._school_systems_data: Optional[Dict[str, Any]] = None
        self._equipment: Optional[Dict[int, EquipmentData]] = None
        self._modules: Optional[Dict[int, ModuleData]] = None
        self._module_status: Optional[Dict[int, Dict[int, ModuleStatus]]] = None
        self._gear_effects: Optional[Dict[int, ModuleGearData]] = None
        self._enemies: Optional[Dict[int, EnemyData]] = None
        self._enemy_skills: Optional[Dict[int, List[int]]] = None
        self._memories: Optional[Dict[int, MemoryData]] = None
        self._memory_effects: Optional[Dict[str, Any]] = None
        self._team_data: Optional[Dict[int, str]] = None
        self._skill_master_names: Optional[Dict[int, str]] = None
        self._skill_master_descriptions: Optional[Dict[int, str]] = None
        self._character_team_mapping: Optional[Dict[int, int]] = None
        self._character_base_names: Optional[Dict[int, str]] = None
        self._tactical_exercise_enemies: Optional[Dict[int, Dict]] = None

        self._custom_characters: Dict[int, CharacterData] = {}
        self._custom_skills: Dict[int, SkillData] = {}
        self._custom_parsed_skills: Dict[str, Any] = {}
        self._custom_character_skills: Dict[int, List[int]] = {}
        self._custom_dummy_configs: Dict[int, CustomDummyConfig] = {}
        self._custom_dummy_count: int = 0

    def _load_json(self, filename: str) -> Any:
        path = self._data_dir / filename
        if not path.exists():
            print(f"  [WARN] 数据文件不存在: {path}")
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_all(self):
        """加载所有数据"""
        print("正在加载所有数据...")
        self.load_characters()
        self.load_skills()
        self.load_parsed_skills()
        self.load_character_skills()
        self.load_level_lerp_data()
        self.load_affection_bonuses()
        self.load_rarity_bonuses()
        self.load_academy()
        self.load_equipment()
        self.load_modules()
        self.load_module_status()
        self.load_enchant_types()
        self.load_enemies()
        self.load_memories()
        self.load_memory_effects()
        self.load_character_base_names()
        self.load_tactical_exercise_enemies()
        self.load_custom_dummies()
        print("[OK] 所有数据加载完成")

    def load_characters(self) -> Dict[int, CharacterData]:
        if self._characters is not None:
            return self._characters
        raw = self._load_json("characters.json")
        characters: Dict[int, CharacterData] = {}
        for key, data in raw.items():
            cid = data["character_id"]
            ms = data["min_level_stats"]
            xs = data["max_level_stats"]
            bp = data["bonus_per_level"]
            gr = data["grades"]
            characters[cid] = CharacterData(
                character_id=cid,
                name=data["name"],
                character_base_id=data["character_base_id"],
                default_rarity=data["default_rarity"],
                character_type=data["character_type"],
                attribute=data["attribute"],
                position_type=data["position_type"],
                role_type=data["role_type"],
                action_point=data["action_point"],
                passive_point=data["passive_point"],
                min_level_stats=BaseStats(
                    level=ms["level"], hp=ms["hp"], attack=ms["attack"],
                    defense=ms["defense"], speed=ms["speed"], crit_rate=ms["crit_rate"],
                ),
                max_level_stats=BaseStats(
                    level=xs["level"], hp=xs["hp"], attack=xs["attack"],
                    defense=xs["defense"], speed=xs["speed"], crit_rate=xs["crit_rate"],
                ),
                bonus_per_level=BonusStats(
                    hp=bp["hp"], attack=bp["attack"], defense=bp["defense"],
                    speed=bp["speed"], crit_rate=bp["crit_rate"],
                ),
                grades=StatGrades(
                    hp_grade=gr["hp_grade"], attack_grade=gr["attack_grade"],
                    defense_grade=gr["defense_grade"], speed_grade=gr["speed_grade"],
                    crit_rate_grade=gr["crit_rate_grade"],
                ),
                raw_data=data,
            )
        self._characters = characters
        print(f"[OK] 已加载 {len(characters)} 个角色数据")
        return characters

    def get_character_by_id(self, character_id: int) -> Optional[CharacterData]:
        if character_id < 0:
            return self._custom_characters.get(character_id)
        if self._characters is None:
            self.load_characters()
        return self._characters.get(character_id)

    def get_character(self, character_id: int) -> Optional[CharacterData]:
        return self.get_character_by_id(character_id)

    def load_skills(self) -> Dict[int, SkillData]:
        if self._skills is not None:
            return self._skills
        raw = self._load_json("skills.json")
        skills: Dict[int, SkillData] = {}
        for key, data in raw.items():
            sid = data["skill_id"]
            tags: Dict[str, TemplateTag] = {}
            for tag_name, tag_data in data.get("template_tags", {}).items():
                values = [
                    TemplateTagValue(level=v["level"], value=v["value"])
                    for v in tag_data.get("values", [])
                ]
                tags[tag_name] = TemplateTag(
                    tag_name=tag_name,
                    interpolation_mode=tag_data.get("interpolation_mode", 1),
                    values=values,
                )
            descriptions = [
                SkillDescription(min_level=d["min_level"], template=d["template"])
                for d in data.get("descriptions", [])
            ]
            additional_kinds = [
                AdditionalKind(level=a["level"], value=a["value"])
                for a in data.get("additional_kinds", [])
            ]
            skills[sid] = SkillData(
                skill_id=sid,
                name=data["name"],
                skill_type=data["skill_type"],
                skill_kind=data.get("skill_kind", 0),
                resource_cost=data["resource_cost"],
                cooldown=data.get("cooldown") or 0,
                cooldown_update_timing=data.get("cooldown_update_timing"),
                default_max_level=data.get("default_max_level", 10),
                features=data.get("features", 0),
                skill_level_pattern_id=data.get("skill_level_pattern_id", 0),
                additional_kinds=additional_kinds,
                descriptions=descriptions,
                template_tags=tags,
                display_info=DisplayInfo(),
                raw_data=data,
            )
        self._skills = skills
        print(f"[OK] 已加载 {len(skills)} 个技能数据")
        return skills

    def get_skill_by_id(self, skill_id: int) -> Optional[SkillData]:
        if skill_id < 0:
            return self._custom_skills.get(skill_id)
        if self._skills is None:
            self.load_skills()
        return self._skills.get(skill_id)

    def load_parsed_skills(self) -> Dict[str, Any]:
        if self._parsed_skills is not None:
            return self._parsed_skills
        raw = self._load_json("skill_effects_hybrid.json")
        self._parsed_skills = raw
        print(f"[OK] 已加载 {len(raw)} 个解析后的技能效果")
        return raw

    def get_parsed_skill_data(self, skill_id: int) -> Optional[Dict[str, Any]]:
        if skill_id < 0:
            return self._custom_parsed_skills.get(str(skill_id))
        if self._parsed_skills is None:
            self.load_parsed_skills()
        return self._parsed_skills.get(str(skill_id))

    def load_character_skills(self) -> Dict[int, List[int]]:
        if self._character_skills is not None:
            return self._character_skills
        raw = self._load_json("character_skills.json")
        result: Dict[int, List[int]] = {}
        for key, data in raw.items():
            cid = data["character_id"]
            result[cid] = list(data["skill_ids"])
        self._character_skills = result
        print(f"[OK] 已加载 {len(result)} 个角色技能映射")
        return result

    def get_character_skills(self, character_id: int) -> List[SkillData]:
        if character_id < 0:
            skill_ids = self._custom_character_skills.get(character_id, [])
            return [self._custom_skills[sid] for sid in skill_ids if sid in self._custom_skills]
        if self._character_skills is None:
            self.load_character_skills()
        if self._skills is None:
            self.load_skills()
        skill_ids = self._character_skills.get(character_id, [])
        # 如果character_skills中找不到，尝试从enemy_skills中查找（敌方单位）
        if not skill_ids:
            if self._enemy_skills is None:
                self.load_enemy_skills()
            skill_ids = self._enemy_skills.get(character_id, [])
        return [self._skills[sid] for sid in skill_ids if sid in self._skills]

    def load_enemy_skills(self) -> Dict[int, List[int]]:
        """加载敌方技能映射"""
        if self._enemy_skills is not None:
            return self._enemy_skills
        raw = self._load_json("enemy_skills.json")
        result: Dict[int, List[int]] = {}
        for key, data in raw.items():
            result[data["enemy_id"]] = list(data["skill_ids"])
        self._enemy_skills = result
        print(f"[OK] 已加载 {len(result)} 个敌方技能映射")
        return result

    def load_level_lerp_data(self) -> Dict[int, float]:
        if self._level_lerp is not None:
            return self._level_lerp
        raw = self._load_json("level_lerp.json")
        result: Dict[int, float] = {}
        for key, val in raw.items():
            result[int(key)] = float(val)
        self._level_lerp = result
        print(f"[OK] 已加载 {len(result)} 个等级的插值数据")
        return result

    def load_affection_bonuses(self) -> Dict[int, Dict[int, AffectionBonus]]:
        if self._affection_bonuses is not None:
            return self._affection_bonuses
        raw = self._load_json("affection_bonuses.json")
        result: Dict[int, Dict[int, AffectionBonus]] = {}
        for type_str, levels in raw.items():
            char_type = int(type_str)
            result[char_type] = {}
            for lvl_str, data in levels.items():
                result[char_type][data["affection_level"]] = AffectionBonus(
                    affection_level=data["affection_level"],
                    character_type=data["character_type"],
                    additional_hp=data["additional_hp"],
                    additional_attack=data["additional_attack"],
                    additional_defense=data["additional_defense"],
                    additional_speed=data["additional_speed"],
                    additional_action_point=data["additional_action_point"],
                    additional_passive_point=data["additional_passive_point"],
                )
        self._affection_bonuses = result
        print(f"[OK] 已加载 {len(result)} 种类型的好感度加成")
        return result

    def get_affection_bonus(self, affection_level: int, character_type: int) -> Optional[AffectionBonus]:
        if self._affection_bonuses is None:
            self.load_affection_bonuses()
        type_bonuses = self._affection_bonuses.get(character_type, {})
        return type_bonuses.get(affection_level)

    def load_rarity_bonuses(self) -> Dict[int, Dict[int, RarityBonus]]:
        if self._rarity_bonuses is not None:
            return self._rarity_bonuses
        raw = self._load_json("rarity_bonuses.json")
        result: Dict[int, Dict[int, RarityBonus]] = {}
        for cid_str, rarities in raw.items():
            cid = int(cid_str)
            result[cid] = {}
            for r_str, data in rarities.items():
                result[cid][data["rarity"]] = RarityBonus(
                    character_id=data["character_id"],
                    rarity=data["rarity"],
                    additional_hp=data["additional_hp"],
                    additional_attack=data["additional_attack"],
                    additional_defense=data["additional_defense"],
                    additional_speed=data["additional_speed"],
                    additional_crit_rate=data["additional_crit_rate"],
                    additional_action_point=data["additional_action_point"],
                    additional_passive_point=data["additional_passive_point"],
                )
        self._rarity_bonuses = result
        print(f"[OK] 已加载 {len(result)} 个角色的稀有度加成")
        return result

    def get_rarity_bonus(self, character_id: int, rarity: int) -> Optional[RarityBonus]:
        if self._rarity_bonuses is None:
            self.load_rarity_bonuses()
        char_rarities = self._rarity_bonuses.get(character_id, {})
        return char_rarities.get(rarity)

    def load_academy(self) -> Dict:
        if self._school_systems_data is not None:
            return self._school_systems_data
        raw = self._load_json("school_systems.json")
        self._school_systems_data = raw
        definitions = raw.get("definitions", {})
        bonus_groups = raw.get("bonuses", {})
        print(f"[OK] 已加载 {len(definitions)} 个学园系统, {len(bonus_groups)} 组等级加成")
        return raw

    def get_school_definitions(self) -> Dict[str, SchoolSystem]:
        if self._school_systems_data is None:
            self.load_academy()
        definitions = self._school_systems_data.get("definitions", {})
        return {
            k: SchoolSystem(
                actuator_id=v["actuator_id"],
                name=v["name"],
                character_type=v.get("character_type"),
                character_attribute=v.get("character_attribute"),
                group_type=1 if v.get("character_type") else 2,
            )
            for k, v in definitions.items()
        }

    def get_school_bonus(self, group_id: int, level: int) -> Optional[SchoolLevelBonus]:
        if self._school_systems_data is None:
            self.load_academy()
        groups = self._school_systems_data.get("bonuses", {})
        group = groups.get(str(group_id), {})
        data = group.get(str(level))
        if data is None:
            return None
        return SchoolLevelBonus(
            group_id=data["group_id"],
            level=data["level"],
            hp_bonus=data["hp_bonus"],
            attack_bonus=data["attack_bonus"],
            defense_bonus=data["defense_bonus"],
        )

    def load_equipment(self) -> Dict[int, EquipmentData]:
        if self._equipment is not None:
            return self._equipment
        raw = self._load_json("equipment.json")
        result: Dict[int, EquipmentData] = {}
        for key, data in raw.items():
            eid = data["equipment_id"]
            result[eid] = EquipmentData(
                equipment_id=eid,
                name=data["name"],
                character_type=data["character_type"],
                equipment_type=data["equipment_type"],
                hp_bonus=data["hp_bonus"],
                attack_bonus=data["attack_bonus"],
                defense_bonus=data["defense_bonus"],
                description=data.get("description", ""),
            )
        self._equipment = result
        print(f"[OK] 已加载 {len(result)} 个装备")
        return result

    def get_equipment(self, equipment_id: int) -> Optional[EquipmentData]:
        if self._equipment is None:
            self.load_equipment()
        return self._equipment.get(equipment_id)

    def load_modules(self) -> Dict[int, ModuleData]:
        if self._modules is not None:
            return self._modules
        raw = self._load_json("modules.json")
        result: Dict[int, ModuleData] = {}
        for key, data in raw.items():
            mid = data["module_id"]
            result[mid] = ModuleData(
                module_id=mid,
                name=data["name"],
                character_type=data["character_type"],
                module_type=data["module_type"],
            )
        self._modules = result
        print(f"[OK] 已加载 {len(result)} 个模块定义")
        return result

    def load_module_status(self) -> Dict[int, Dict[int, ModuleStatus]]:
        if self._module_status is not None:
            return self._module_status
        raw = self._load_json("module_status.json")
        result: Dict[int, Dict[int, ModuleStatus]] = {}
        for mid_str, tiers in raw.items():
            mid = int(mid_str)
            result[mid] = {}
            for tier_str, data in tiers.items():
                result[mid][data["tier"]] = ModuleStatus(
                    module_id=data["module_id"],
                    tier=data["tier"],
                    hp_base=data["hp_base"],
                    hp_per_level=data["hp_per_level"],
                    hp_rate=data["hp_rate"],
                    attack_base=data["attack_base"],
                    attack_per_level=data["attack_per_level"],
                    attack_rate=data["attack_rate"],
                    defense_base=data["defense_base"],
                    defense_per_level=data["defense_per_level"],
                    defense_rate=data["defense_rate"],
                )
        self._module_status = result
        print(f"[OK] 已加载 {len(result)} 个模块的状态数据")
        return result

    def get_module_status(self, module_id: int, tier: int) -> Optional[ModuleStatus]:
        if self._module_status is None:
            self.load_module_status()
        tiers = self._module_status.get(module_id, {})
        return tiers.get(tier)

    def load_enchant_types(self) -> Dict[int, ModuleGearData]:
        if self._gear_effects is not None:
            return self._gear_effects
        raw = self._load_json("gear_effects.json")
        definitions = raw.get("definitions", {})
        result: Dict[int, ModuleGearData] = {}
        for key, data in definitions.items():
            gid = data["gear_id"]
            result[gid] = ModuleGearData(
                gear_id=gid,
                title=data["title"],
                effect_type=data["effect_type"],
                effects_by_rank={},
            )
        self._gear_effects = result
        print(f"[OK] 已加载 {len(result)} 种词条类型")
        return result

    def load_enemies(self) -> Dict[int, EnemyData]:
        if self._enemies is not None:
            return self._enemies
        raw = self._load_json("enemies.json")
        result: Dict[int, EnemyData] = {}
        for key, data in raw.items():
            eid = data["enemy_id"]
            result[eid] = EnemyData(
                enemy_id=eid,
                name=data["name"],
                asset_id=data["asset_id"],
                hp=data["hp"],
                attack=data["attack"],
                defense=data["defense"],
                speed=data["speed"],
                hp_grade=data["hp_grade"],
                attack_grade=data["attack_grade"],
                defense_grade=data["defense_grade"],
                speed_grade=data["speed_grade"],
                critical_rate=data["critical_rate"],
                critical_rate_grade=data["critical_rate_grade"],
                attribute=data["attribute"],
                type=data["type"],
                role_type=data["role_type"],
                rarity=data["rarity"],
                skill_ids=data["skill_ids"],
            )
        self._enemies = result
        print(f"[OK] 已加载 {len(result)} 个敌方单位")
        return result

    def get_enemy_by_id(self, enemy_id: int) -> Optional[EnemyData]:
        if self._enemies is None:
            self.load_enemies()
        return self._enemies.get(enemy_id)

    def load_memories(self) -> Dict[int, MemoryData]:
        if self._memories is not None:
            return self._memories
        raw = self._load_json("memories.json")
        result: Dict[int, MemoryData] = {}
        for key, data in raw.items():
            mid = data["memory_id"]
            highlights = []
            for hl in data.get("highlights", []):
                highlights.append(MemoryHighlight(
                    character_attribute=hl.get("character_attribute"),
                    character_base_master_id=hl.get("character_base_master_id"),
                    character_master_id=hl.get("character_master_id"),
                    character_role=hl.get("character_role"),
                    character_team_master_id=hl.get("character_team_master_id"),
                    character_type=hl.get("character_type"),
                    is_targeting_friendly_party=hl.get("is_targeting_friendly_party", True),
                    party_position=hl.get("party_position"),
                    skill_master_id=hl.get("skill_master_id"),
                ))
            result[mid] = MemoryData(
                memory_id=mid,
                name=data["name"],
                description=data.get("description", ""),
                rarity=data["rarity"],
                highlights=highlights,
            )
        self._memories = result
        print(f"[OK] 已加载 {len(result)} 张回忆卡")
        return result

    def get_memory(self, memory_id: int) -> Optional[MemoryData]:
        if self._memories is None:
            self.load_memories()
        return self._memories.get(memory_id)

    def load_memory_effects(self) -> Dict[str, Any]:
        """加载回忆卡结构化效果数据（memory_effects.json）

        Schema 参考 docs/memory_card_system_refactor.md 第3章。
        若文件不存在或为空，返回空dict（回退到旧正则路径）。
        """
        if self._memory_effects is not None:
            return self._memory_effects
        raw = self._load_json("memory_effects.json")
        self._memory_effects = raw if raw else {}
        print(f"[OK] 已加载 {len(self._memory_effects)} 个回忆卡结构化效果")
        return self._memory_effects

    def get_memory_effect(self, skill_id: int) -> Optional[Dict[str, Any]]:
        """获取指定技能ID的回忆卡结构化效果数据

        Args:
            skill_id: 400xxx 回忆卡技能ID

        Returns:
            结构化效果dict（含trigger/blocks），若不存在返回None
        """
        if self._memory_effects is None:
            self.load_memory_effects()
        return self._memory_effects.get(str(skill_id))

    def load_character_teams(self) -> Optional[Dict[int, str]]:
        if self._team_data is not None:
            return self._team_data
        try:
            team_data = self._load_json("character_teams.json")
            if team_data:
                self._team_data = {t["team_id"]: t.get("name", "") for t in team_data}
                return self._team_data
        except Exception:
            pass
        try:
            split_path = self._data_dir.parent / "split_data" / "CharacterTeamMaster.json"
            if split_path.exists():
                with open(split_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._team_data = {item["Id"]: item.get("Name", "") for item in raw}
                return self._team_data
        except Exception:
            pass
        self._team_data = {}
        return self._team_data

    def load_character_team_mapping(self) -> Dict[int, int]:
        if self._character_team_mapping is not None:
            return self._character_team_mapping
        self._character_team_mapping = {}
        try:
            mapping_data = self._load_json("character_team_mapping.json")
            char_base = mapping_data.get("character_base", {})
            for base_id_str, info in char_base.items():
                try:
                    base_id = int(base_id_str)
                    team_id = info.get("team_id", 0)
                    if team_id:
                        self._character_team_mapping[base_id] = team_id
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass
        return self._character_team_mapping

    def get_character_team_id(self, character_base_id: int) -> Optional[int]:
        if self._character_team_mapping is None:
            self.load_character_team_mapping()
        return self._character_team_mapping.get(character_base_id)

    def load_character_base_names(self) -> Dict[int, str]:
        if self._character_base_names is not None:
            return self._character_base_names
        self._character_base_names = {}
        try:
            split_path = self._data_dir.parent / "split_data" / "CharacterBaseMaster.json"
            if split_path.exists():
                with open(split_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for item in raw:
                    bid = item.get("Id")
                    if bid is not None:
                        self._character_base_names[bid] = item.get("Name", "")
        except Exception:
            pass
        return self._character_base_names

    def get_character_base_name(self, character_base_id: int) -> Optional[str]:
        if self._character_base_names is None:
            self.load_character_base_names()
        return self._character_base_names.get(character_base_id)

    def load_tactical_exercise_enemies(self) -> Dict[int, Dict]:
        """加载战术演习敌方数据"""
        if self._tactical_exercise_enemies is not None:
            return self._tactical_exercise_enemies
        self._tactical_exercise_enemies = {}
        data_path = self._data_dir / "tactical_exercise_enemies.json"
        if not data_path.exists():
            return self._tactical_exercise_enemies
        with open(data_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        seen_names = set()
        for eid_str, data in sorted(raw.items(), key=lambda x: x[1]["character_name"]):
            if data["character_name"] not in seen_names:
                seen_names.add(data["character_name"])
                self._tactical_exercise_enemies[int(eid_str)] = data
        print(f"[OK] 已加载 {len(self._tactical_exercise_enemies)} 个战术演习敌方单位")
        return self._tactical_exercise_enemies

    def get_tactical_exercise_enemies(self) -> Dict[int, Dict]:
        if self._tactical_exercise_enemies is None:
            self.load_tactical_exercise_enemies()
        return self._tactical_exercise_enemies

    def load_skill_master_names(self) -> Dict[int, str]:
        if self._skill_master_names is not None:
            return self._skill_master_names
        try:
            split_path = self._data_dir.parent / "split_data" / "SkillMaster.json"
            if split_path.exists():
                with open(split_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._skill_master_names = {item["Id"]: item.get("Name", "") for item in raw}
                return self._skill_master_names
        except Exception:
            pass
        self._skill_master_names = {}
        return self._skill_master_names

    def get_skill_name_from_master(self, skill_id: int) -> Optional[str]:
        if self._skill_master_names is None:
            self.load_skill_master_names()
        return self._skill_master_names.get(skill_id)

    def get_skill_name(self, skill_id: int) -> str:
        skill_data = self.get_skill_by_id(skill_id)
        if skill_data:
            return skill_data.name
        name = self.get_skill_name_from_master(skill_id)
        if name:
            return name
        return f"技能#{skill_id}"

    def load_skill_master_descriptions(self) -> Dict[int, str]:
        if self._skill_master_descriptions is not None:
            return self._skill_master_descriptions
        self._skill_master_descriptions = {}
        try:
            split_path = self._data_dir.parent / "split_data" / "SkillMaster.json"
            if split_path.exists():
                with open(split_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for item in raw:
                    sid = item.get("Id")
                    if sid is None:
                        continue
                    templates = item.get("DescriptionTemplates", [])
                    if templates:
                        self._skill_master_descriptions[sid] = templates[0].get("Template", "")
        except Exception:
            pass
        return self._skill_master_descriptions

    def get_skill_description(self, skill_id: int) -> Optional[str]:
        if self._skill_master_descriptions is None:
            self.load_skill_master_descriptions()
        return self._skill_master_descriptions.get(skill_id)

    def load_level_lerp(self) -> Dict[int, float]:
        return self.load_level_lerp_data()

    def register_custom_dummy(self, cfg: CustomDummyConfig, dummy_index: Optional[int] = None) -> int:
        if dummy_index is None:
            dummy_index = self._custom_dummy_count
            self._custom_dummy_count += 1
        else:
            self._custom_dummy_count = max(self._custom_dummy_count, dummy_index + 1)

        char_data = build_synthetic_character_data(dummy_index, cfg)
        char_id = char_data.character_id
        self._custom_characters[char_id] = char_data

        skill_ids = []
        for i, as_cfg in enumerate(cfg.as_skills):
            effects = as_cfg.get_effects()
            sd = build_custom_skill_data(
                dummy_index, False, i + 1,
                as_cfg.name, effects,
                as_cfg.cooldown, as_cfg.cooldown_update_timing,
                as_cfg.target_type, as_cfg.target_range, as_cfg.target_priority,
                as_cfg.resource_cost,
            )
            self._custom_skills[sd.skill_id] = sd
            parsed = build_custom_parsed_skill(
                dummy_index, False, i + 1,
                as_cfg.target_type, as_cfg.target_range, as_cfg.target_priority,
                effects,
            )
            self._custom_parsed_skills[str(sd.skill_id)] = parsed
            skill_ids.append(sd.skill_id)

        for i, ps_cfg in enumerate(cfg.ps_skills):
            effects = ps_cfg.get_effects()
            sd = build_custom_skill_data(
                dummy_index, True, i + 1,
                ps_cfg.name, effects,
                ps_cfg.cooldown, ps_cfg.cooldown_update_timing,
                ps_cfg.target_type, ps_cfg.target_range, ps_cfg.target_priority,
                ps_cfg.resource_cost,
            )
            self._custom_skills[sd.skill_id] = sd
            parsed = build_custom_parsed_skill(
                dummy_index, True, i + 1,
                ps_cfg.target_type, ps_cfg.target_range, ps_cfg.target_priority,
                effects,
                ps_cfg.trigger_timing,
            )
            self._custom_parsed_skills[str(sd.skill_id)] = parsed
            skill_ids.append(sd.skill_id)

        self._custom_character_skills[char_id] = skill_ids
        self._custom_dummy_configs[char_id] = cfg
        return char_id

    def get_custom_dummy_config(self, character_id: int) -> Optional[CustomDummyConfig]:
        return self._custom_dummy_configs.get(character_id)

    def get_custom_dummy_ids(self) -> List[int]:
        return list(self._custom_characters.keys())

    def get_all_custom_dummies(self) -> Dict[int, CharacterData]:
        return dict(self._custom_characters)

    def clear_custom_dummies(self):
        self._custom_characters.clear()
        self._custom_skills.clear()
        self._custom_parsed_skills.clear()
        self._custom_character_skills.clear()
        self._custom_dummy_configs.clear()
        self._custom_dummy_count = 0

    def save_custom_dummies(self):
        import json
        from dataclasses import asdict
        configs = []
        for char_id, cfg in self._custom_dummy_configs.items():
            configs.append({
                "char_id": char_id,
                "name": cfg.name,
                "element": cfg.element,
                "character_type": cfg.character_type,
                "position_type": cfg.position_type,
                "role_type": cfg.role_type,
                "hp": cfg.hp,
                "attack": cfg.attack,
                "defense": cfg.defense,
                "crit_rate": cfg.crit_rate,
                "crit_damage": cfg.crit_damage,
                "speed": cfg.speed,
                "advantage_damage": cfg.advantage_damage,
                "ap": cfg.ap,
                "pp": cfg.pp,
                "permanent_shield_type": cfg.permanent_shield_type,
                "permanent_shield_value": cfg.permanent_shield_value,
                "as_skills": [asdict(s) for s in cfg.as_skills],
                "ps_skills": [asdict(s) for s in cfg.ps_skills],
            })
        path = self._user_data_dir / "custom_dummies.json" if self._user_data_dir else self._data_dir / "custom_dummies.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"dummies": configs, "dummy_count": self._custom_dummy_count}, f, ensure_ascii=False, indent=2)

    def load_custom_dummies(self):
        # 优先从用户数据目录加载，否则从数据目录加载
        path = self._user_data_dir / "custom_dummies.json" if self._user_data_dir else self._data_dir / "custom_dummies.json"
        if not path.exists():
            path = self._data_dir / "custom_dummies.json"
        if not path.exists():
            return
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.clear_custom_dummies()
        self._custom_dummy_count = data.get("dummy_count", 0)
        for item in data.get("dummies", []):
            # 解析技能效果列表
            as_skills = []
            for s in item.get("as_skills", []):
                effects = [CustomEffectConfig(**e) for e in s.get("effects", [])]
                as_skills.append(CustomASConfig(
                    name=s.get("name", "自定义AS"),
                    effects=effects,
                    cooldown=s.get("cooldown", 0),
                    cooldown_update_timing=s.get("cooldown_update_timing", 1),
                    target_type=s.get("target_type", 3),
                    target_range=s.get("target_range", 1),
                    target_priority=s.get("target_priority", 0),
                    resource_cost=s.get("resource_cost", 1),
                    power=s.get("power", 0),
                    hit_count_legacy=s.get("hit_count", 0) if not effects else 0,
                ))
            ps_skills = []
            for s in item.get("ps_skills", []):
                effects = [CustomEffectConfig(**e) for e in s.get("effects", [])]
                ps_skills.append(CustomPSConfig(
                    name=s.get("name", "自定义PS"),
                    effects=effects,
                    cooldown=s.get("cooldown", 0),
                    cooldown_update_timing=s.get("cooldown_update_timing", 1),
                    target_type=s.get("target_type", 3),
                    target_range=s.get("target_range", 1),
                    target_priority=s.get("target_priority", 0),
                    resource_cost=s.get("resource_cost", 1),
                    trigger_timing=s.get("trigger_timing", "BeforeAsAttacked"),
                    power=s.get("power", 0),
                    hit_count_legacy=s.get("hit_count", 0) if not effects else 0,
                ))
            cfg = CustomDummyConfig(
                name=item["name"],
                element=item["element"],
                character_type=item["character_type"],
                position_type=item.get("position_type", 3),
                role_type=item.get("role_type", 1),
                hp=item["hp"],
                attack=item["attack"],
                defense=item["defense"],
                crit_rate=item["crit_rate"],
                crit_damage=item["crit_damage"],
                speed=item["speed"],
                advantage_damage=item["advantage_damage"],
                ap=item["ap"],
                pp=item["pp"],
                permanent_shield_type=item.get("permanent_shield_type", 0),
                permanent_shield_value=item.get("permanent_shield_value", 0),
                as_skills=as_skills,
                ps_skills=ps_skills,
            )
            dummy_index = abs(item["char_id"]) - 1
            self.register_custom_dummy(cfg, dummy_index)