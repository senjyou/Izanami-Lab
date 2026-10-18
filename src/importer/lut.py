# -*- coding: utf-8 -*-
"""运行时查找表：把游戏 master 数据与模拟器数据接到一起。

数据来源全部是仓库内 ``data/`` 下的成品（随发布包热更新），**运行时不依赖**
``split_data/``（那是开发期生成 LUT 的原料）。

其中两份 LUT 由 ``python -m src.importer.build_luts`` 生成：

* ``data/character_skill_master.json``  ``{CharacterSkillMasterId: SkillMasterId}``
* ``data/module_gear_effects.json``     ``{EffectMasterId: [gearMasterId, effectValue, rank]}``

其余直接复用模拟器已有数据：``characters.json`` / ``modules.json`` /
``equipment.json`` / ``school_systems.json`` / ``character_skills.json`` /
``gear_effects.json``。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

__all__ = ["DataIndex", "DEFAULT_DATA_DIR", "LutError", "max_rarity_for"]


class LutError(RuntimeError):
    """LUT / 数据文件缺失或损坏。"""


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


DEFAULT_DATA_DIR = _default_data_dir()


def max_rarity_for(default_rarity: int) -> int:
    """默认稀有度 → 允许的最大稀有度（与 gui/utils.py::get_max_rarity_for 一致）。"""
    if default_rarity <= 1:
        return 5
    if default_rarity <= 3:
        return 7
    return 14


# 学园：actuator master id 与 SchoolLevels 字段的对应（由 school_systems.json 定义推导）
_SCHOOL_TYPE_KEYS = {1: "physical_level", 2: "en_level", 3: "agility_level"}
_SCHOOL_ATTR_KEYS = {
    1: "fire_level", 2: "water_level", 3: "wind_level",
    4: "earth_level", 5: "light_level", 6: "dark_level",
}

# 词条：游戏 ModuleGearMaster.EffectType → 模拟器内部枚举
# 游戏 1=効果なし 2=有利属性 3=HP 4=ATK 5=DEF 6=SPD 7=会心率 8=会心伤害
# 模拟器 1=HP 2=ATK 3=DEF 4=SPD 5=会心率 6=会心伤害 7=有利属性
_GEAR_EFFECT_TYPE_MAP = {2: 7, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6}


@dataclass
class DataIndex:
    """一份只读的数据索引；一次导入只加载一次。"""

    data_dir: Path
    characters: Dict[int, dict]
    modules: Dict[int, dict]
    equipment: Dict[int, dict]
    character_skills: Dict[int, List[int]]
    school_systems: dict
    gear_effect_type: Dict[int, int]          # gear master id -> 游戏 EffectType
    skill_master: Dict[int, int]              # CharacterSkillMasterId -> SkillMasterId
    gear_effects: Dict[int, Tuple[int, float, int]]  # effect master id -> (gearMasterId, value, rank)
    gear_items: Dict[int, Tuple[int, float]]  # item master id -> (ItemMasterId, LossRate)
    school_key_by_actuator: Dict[int, str]

    # ---------------------------------------------------------------- 加载
    @classmethod
    def load(cls, data_dir: Optional[Path] = None) -> "DataIndex":
        base = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        if not base.is_dir():
            raise LutError(f"数据目录不存在：{base}")

        def read(name: str, *, required: bool = True):
            path = base / name
            if not path.exists():
                if required:
                    raise LutError(
                        f"缺少数据文件 data/{name}。若这是 LUT，请先运行 "
                        f"`python -m src.importer.build_luts` 生成。"
                    )
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 - 统一转成 LutError 便于 GUI 展示
                raise LutError(f"读取 data/{name} 失败：{exc}") from exc

        characters = {int(k): v for k, v in (read("characters.json") or {}).items()}
        modules = {int(k): v for k, v in (read("modules.json") or {}).items()}
        equipment = {int(k): v for k, v in (read("equipment.json") or {}).items()}
        character_skills = {
            int(k): list(v.get("skill_ids") or [])
            for k, v in (read("character_skills.json") or {}).items()
        }
        school_systems = read("school_systems.json") or {}

        gear_effect_type: Dict[int, int] = {}
        for entry in (read("gear_effects.json") or {}).get("definitions", {}).values():
            gear_effect_type[int(entry["gear_id"])] = int(entry["effect_type"])

        skill_master = {int(k): int(v) for k, v in (read("character_skill_master.json") or {}).items()}
        gear_effects_raw = read("module_gear_effects.json") or {}
        gear_effects: Dict[int, Tuple[int, float, int]] = {}
        for key, value in gear_effects_raw.items():
            if not isinstance(value, (list, tuple)) or len(value) < 2:
                raise LutError(f"module_gear_effects.json 条目非法：{key} -> {value!r}")
            gear_master_id = int(value[0])
            effect_value = float(value[1])
            rank = int(value[2]) if len(value) > 2 and value[2] is not None else 0
            gear_effects[int(key)] = (gear_master_id, effect_value, rank)

        # 词条道具（决定数值损耗率）：{itemMasterId: [ItemMasterId, LossRate]}
        gear_items: Dict[int, Tuple[int, float]] = {}
        for key, value in (read("module_gear_items.json") or {}).items():
            if not isinstance(value, (list, tuple)) or len(value) < 2:
                raise LutError(f"module_gear_items.json 条目非法：{key} -> {value!r}")
            gear_items[int(key)] = (int(value[0]), float(value[1]))

        index = cls(
            data_dir=base,
            characters=characters,
            modules=modules,
            equipment=equipment,
            character_skills=character_skills,
            school_systems=school_systems,
            gear_effect_type=gear_effect_type,
            skill_master=skill_master,
            gear_effects=gear_effects,
            gear_items=gear_items,
            school_key_by_actuator=cls._build_school_map(school_systems),
        )
        index._validate()
        return index

    @staticmethod
    def _build_school_map(school_systems: dict) -> Dict[int, str]:
        out: Dict[int, str] = {}
        for definition in (school_systems.get("definitions") or {}).values():
            actuator_id = int(definition["actuator_id"])
            character_type = definition.get("character_type")
            character_attribute = definition.get("character_attribute")
            if character_type:
                key = _SCHOOL_TYPE_KEYS.get(int(character_type))
            else:
                key = _SCHOOL_ATTR_KEYS.get(int(character_attribute or 0))
            if key:
                out[actuator_id] = key
        return out

    def _validate(self) -> None:
        if not self.school_key_by_actuator:
            raise LutError("school_systems.json 没有可用的学园等级定义")
        missing = [
            gear_id for gear_id in self.gear_effect_type
            if self.gear_effect_type[gear_id] not in (1, *_GEAR_EFFECT_TYPE_MAP)
        ]
        if missing:
            raise LutError(f"gear_effects.json 出现未知词条类型：{missing}")

    # ---------------------------------------------------------------- 查询
    def school_levels_from_rows(self, rows: List[dict]) -> Dict[str, int]:
        """type 33 行 → 9 个学园等级字段。"""
        out: Dict[str, int] = {}
        for row in rows:
            actuator_id = row.get("ActuatorMasterId")
            level = row.get("Level")
            if actuator_id is None or level is None:
                continue
            key = self.school_key_by_actuator.get(int(actuator_id))
            if key:
                out[key] = int(level)
        return out

    def equipment_totals(self, rows: List[dict]) -> Dict[int, Dict[str, int]]:
        """type 196 行 → 三类机体的装备总加成。"""
        totals: Dict[int, Dict[str, int]] = {
            ct: {"hp": 0, "attack": 0, "defense": 0} for ct in (1, 2, 3)
        }
        for row in rows:
            master_id = row.get("TypeEquipmentMasterId")
            equipment = self.equipment.get(int(master_id)) if master_id is not None else None
            if not equipment:
                continue
            ct = int(equipment.get("character_type") or 0)
            if ct not in totals:
                continue
            totals[ct]["hp"] += int(row.get("Hp") or 0)
            totals[ct]["attack"] += int(row.get("Attack") or 0)
            totals[ct]["defense"] += int(row.get("Defense") or 0)
        return totals

    def gear_sim_effect(
        self,
        effect_master_id: int,
        item_master_id: Optional[int] = None,
    ) -> Optional[Tuple[int, float]]:
        """ModuleGearEffectMasterId → (模拟器 effect_type, 百分比数值)。

        词条的数值必须再乘上"道具损耗率"（``ModuleGearItemMaster.LossRate``）：
        低阶道具（如 70001/70002）分别损耗 50% / 25%，高阶道具损耗 0。
        游戏中 ModuleGear 行记录的 ``ModuleGearItemMasterId`` 就是当初洗词条用的道具，
        所以同一 EffectMasterId + Rank 在不同道具下实际数值不同。

        ``effect_type == 0`` 表示"効果なし"（调用方应跳过）。未知 id 返回 ``None``。
        """
        raw = self.gear_effects.get(int(effect_master_id))
        if raw is None:
            return None
        gear_master_id, effect_value, _rank = raw
        game_type = self.gear_effect_type.get(gear_master_id)
        if game_type is None:
            return None
        if game_type == 1:
            return (0, 0.0)

        value = effect_value * 100.0
        if item_master_id is not None:
            item = self.gear_items.get(int(item_master_id))
            if item is not None:
                value *= (1.0 - item[1])
        return (_GEAR_EFFECT_TYPE_MAP[game_type], round(value, 4))

    def skill_ids_for(self, character_id: int) -> List[int]:
        return list(self.character_skills.get(int(character_id), []))

    def max_rarity_for(self, character_id: int) -> int:
        character = self.characters.get(int(character_id))
        if not character:
            return 14
        return max_rarity_for(int(character.get("default_rarity") or 1))
