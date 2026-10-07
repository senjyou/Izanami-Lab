import json

# 加载SkillMaster.json
with open("split_data/SkillMaster.json", "r", encoding="utf-8") as f:
    skill_master = json.load(f)

# 加载memories.json
with open("data/memories.json", "r", encoding="utf-8") as f:
    memories = json.load(f)

# 筛选400000-400019的技能
batch1_skills = [s for s in skill_master if 400000 <= s.get("Id", 0) <= 400019]
print(f"Batch 1 技能数: {len(batch1_skills)}")

# 构建 skill_id -> highlight 条件映射
skill_to_highlights = {}
for mid, mdata in memories.items():
    for hl in mdata.get("highlights", []):
        sid = hl.get("skill_master_id")
        if sid and 400000 <= sid <= 400019:
            if sid not in skill_to_highlights:
                skill_to_highlights[sid] = []
            skill_to_highlights[sid].append({
                "memory_id": int(mid),
                "memory_name": mdata.get("name", ""),
                "is_targeting_friendly_party": hl.get("is_targeting_friendly_party", True),
                "party_position": hl.get("party_position"),
                "character_master_id": hl.get("character_master_id"),
                "character_base_master_id": hl.get("character_base_master_id"),
                "character_attribute": hl.get("character_attribute"),
                "character_role": hl.get("character_role"),
                "character_team_master_id": hl.get("character_team_master_id"),
                "character_type": hl.get("character_type"),
            })

# 输出每个技能的转写所需信息
for skill in batch1_skills:
    sid = skill["Id"]
    name = skill.get("Name", "")
    kind = skill.get("Kind", 0)
    templates = skill.get("DescriptionTemplates", [])
    desc = templates[0].get("Template", "") if templates else ""

    highlights = skill_to_highlights.get(sid, [])

    print(f"\n{'='*60}")
    print(f"技能ID: {sid}")
    print(f"名称: {name}")
    print(f"Kind: {kind} ({'buff' if kind==2 else 'debuff' if kind==3 else 'heal' if kind==4 else 'unknown'})")
    print(f"描述: {desc}")
    if highlights:
        print(f"Highlight条件 ({len(highlights)}个):")
        for hl in highlights:
            print(f"  - memory={hl['memory_name']}, friendly={hl['is_targeting_friendly_party']}, "
                  f"pos={hl['party_position']}, char_id={hl['character_master_id']}, "
                  f"base_id={hl['character_base_master_id']}, attr={hl['character_attribute']}, "
                  f"role={hl['character_role']}, team={hl['character_team_master_id']}, "
                  f"type={hl['character_type']}")
    else:
        print("Highlight条件: 无")
