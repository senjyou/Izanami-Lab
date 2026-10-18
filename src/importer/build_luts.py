# -*- coding: utf-8 -*-
"""开发期工具：从 ``split_data/`` 生成 ``data/`` 下的导入 LUT。

用法::

    python -m src.importer.build_luts            # 重新生成两份 LUT
    python -m src.importer.build_luts --check    # 只校验现有 LUT 是否与分表一致

``split_data/`` 是开发机上的 masterdata 分表（未随包发布），所以本脚本只用于
开发/维护；模拟器运行时只读 ``data/`` 下的成品。

生成物：
    data/character_skill_master.json   {CharacterSkillMasterId: SkillMasterId}
    data/module_gear_effects.json      {EffectMasterId: [gearMasterId, effectValue, rank]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent

CHAR_SKILL_LUT = "character_skill_master.json"
GEAR_EFFECT_LUT = "module_gear_effects.json"
GEAR_ITEM_LUT = "module_gear_items.json"


class BuildError(RuntimeError):
    pass


def _read_json(path: Path):
    if not path.exists():
        raise BuildError(f"缺少源文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_character_skill_master(split_dir: Path) -> Dict[int, int]:
    rows = _read_json(split_dir / "CharacterSkillMaster.json")
    lut: Dict[int, int] = {}
    for row in rows:
        master_id = int(row["Id"])
        character_id = int(row["CharacterMasterId"])
        # validate() 依赖这个编码约定（CharacterSkillMasterId = 角色 id × 10 + 序号）
        if master_id // 10 != character_id:
            raise BuildError(
                f"CharacterSkillMaster Id={master_id} 与 CharacterMasterId={character_id} "
                "不满足 ×10 编码约定，请调整 build_luts.validate 的归组逻辑"
            )
        lut[master_id] = int(row["SkillMasterId"])
    if not lut:
        raise BuildError("CharacterSkillMaster.json 为空")
    return lut


def build_module_gear_effects(split_dir: Path) -> Dict[int, List]:
    rows = _read_json(split_dir / "ModuleGearEffectMaster.json")
    lut: Dict[int, List] = {}
    for row in rows:
        lut[int(row["Id"])] = [
            int(row["ModuleGearMasterId"]),
            float(row["EffectValue"]),
            int(row.get("Rank") or 0),
        ]
    if not lut:
        raise BuildError("ModuleGearEffectMaster.json 为空")
    return lut


def build_module_gear_items(split_dir: Path) -> Dict[int, List]:
    """词条道具 → [ItemMasterId, LossRate]。

    同一 EffectMasterId/Rank 的实际数值要乘 ``1 - LossRate``：低阶道具洗出来的
    词条有 50% / 25% 的数值损耗，高阶道具为 0。
    """
    rows = _read_json(split_dir / "ModuleGearItemMaster.json")
    lut: Dict[int, List] = {}
    for row in rows:
        loss_rate = float(row.get("LossRate") or 0.0)
        if not 0.0 <= loss_rate <= 1.0:
            raise BuildError(f"ModuleGearItemMaster Id={row.get('Id')} 的 LossRate 非法：{loss_rate}")
        lut[int(row["Id"])] = [int(row["ItemMasterId"]), loss_rate]
    if not lut:
        raise BuildError("ModuleGearItemMaster.json 为空")
    return lut


def validate(skill_lut: Dict[int, int], data_dir: Path) -> List[str]:
    """LUT 与模拟器数据的一致性校验，返回问题列表（空表示通过）。"""
    problems: List[str] = []

    character_skills_path = data_dir / "character_skills.json"
    if character_skills_path.exists():
        character_skills = json.loads(character_skills_path.read_text(encoding="utf-8"))
        skill_ids_by_master = {}
        for master_id, skill_id in skill_lut.items():
            skill_ids_by_master.setdefault(int(master_id) // 10, set()).add(int(skill_id))
        for cid_str, entry in character_skills.items():
            cid = int(cid_str)
            known = skill_ids_by_master.get(cid, set())
            for skill_id in entry.get("skill_ids") or []:
                if int(skill_id) not in known:
                    problems.append(f"角色 {cid} 的技能 {skill_id} 不在 character_skill_master 中")

    if not skill_lut:
        problems.append("character_skill_master 为空")
    return problems


def write_lut(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def _load_existing(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _comparable(payload):
    """JSON 往返后 int 键会变字符串，统一成字符串键比较。"""
    return {str(k): v for k, v in payload.items()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成/校验导入 LUT")
    parser.add_argument("--split-dir", default=str(ROOT / "split_data"), help="masterdata 分表目录")
    parser.add_argument("--data-dir", default=str(ROOT / "data"), help="模拟器数据目录")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args(argv)

    split_dir = Path(args.split_dir)
    data_dir = Path(args.data_dir)

    try:
        skill_lut = build_character_skill_master(split_dir)
        gear_lut = build_module_gear_effects(split_dir)
        item_lut = build_module_gear_items(split_dir)
    except BuildError as exc:
        print(f"[错误] {exc}")
        return 2

    problems = validate(skill_lut, data_dir)
    for problem in problems:
        print(f"[校验] {problem}")

    skill_path = data_dir / CHAR_SKILL_LUT
    gear_path = data_dir / GEAR_EFFECT_LUT
    item_path = data_dir / GEAR_ITEM_LUT

    if args.check:
        ok = True
        for path, payload in (
            (skill_path, skill_lut), (gear_path, gear_lut), (item_path, item_lut)
        ):
            existing = _load_existing(path)
            if existing is None:
                print(f"[缺失] {path.name}")
                ok = False
            elif _comparable(existing) != _comparable(payload):
                print(f"[过期] {path.name} 与 split_data 不一致，请重新生成")
                ok = False
            else:
                print(f"[一致] {path.name}")
        return 0 if ok and not problems else 1

    write_lut(skill_path, skill_lut)
    write_lut(gear_path, gear_lut)
    write_lut(item_path, item_lut)
    print(f"[写入] {skill_path}（{len(skill_lut)} 条）")
    print(f"[写入] {gear_path}（{len(gear_lut)} 条）")
    print(f"[写入] {item_path}（{len(item_lut)} 条）")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
