# Agent 完整计划 JSON

表单的 `dnd-character-intake` 是简短请求；生成脚本只接受 `dnd-character-plan`。`ruleset` 必须为 `5e` 或 `5r`。`scores_base` 必须包含六个 3–20 的基础值：`STR,DEX,CON,INT,WIS,CHA`。

```json
{
  "kind": "dnd-character-plan",
  "schema_version": 1,
  "ruleset": "5r",
  "basic": {
    "name": "角色名", "player": "玩家", "group_name": "团名",
    "class": "战士", "subclass": "", "level": 1,
    "species": "人类", "subspecies": "", "background": "士兵",
    "gender": "", "age": 25, "alignment": "", "hometown": "",
    "faith": "", "height": "", "weight": "", "size": "中型", "speed": 30,
    "personality": "", "appearance": "", "ideal": "", "bond": "", "flaw": "",
    "story": "背景故事"
  },
  "scores_base": {"STR": 15, "DEX": 13, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8},
  "background_bonus": {"STR": 2, "CON": 1},
  "growth_bonus": {}, "other_bonus": {},
  "save_proficiencies": ["STR", "CON"],
  "skill_proficiencies": ["运动", "察觉"], "skill_expertise": [],
  "languages": ["通用语", "矮人语", "精灵语"], "tools": [],
  "class_features": [{"name": "特性名称", "description": "已核对的规则摘要"}],
  "species_traits": [{"name": "特性名称", "description": "已核对的规则摘要"}],
  "feats": [{"name": "背景给的专长", "type": "origin", "description": "已核对的规则摘要"}],
  "weapons": ["长剑"], "inventory": ["背包", "火把"],
  "cantrips": [], "known_spells": [], "prepared_spells": []
}
```

5E 把 `background_bonus` 改成 `racial_bonus`，不填写 2024 起源专长；`basic.background_feature` 写入背景特性。5E 必须提供职业命中骰 `basic.hit_die`（6/8/10/12），可提供 `hp_gains` 数组记录 2 级起每级命中骰结果；未给时按固定平均值计算。`basic.armor_type`、`basic.armor`、`basic.speed` 写入桃子 v4.4.2 模板的装备与速度输入格。5E 当前生命值与模板等级骰格由脚本计算填写；5R 原模板自动按职业/体质等重算 HP。若有超过职业初始两项的豁免熟练，写 `extra_save_proficiency_source` 说明来源。`class_features`、`species_traits`、`feats` 的说明请简述并核对来源，勿将规则书长段全文复制进公开仓库。

技能名称采用卡面中文：运动、特技、巧手、隐匿、奥秘、历史、调查、自然、宗教、驯兽、洞悉、医药、察觉、求生、欺瞒、威吓、表演、游说。专精项也要出现在 `skill_proficiencies`。脚本验证数值、版次、格位和常见规则冲突；职业选项、技能来源、专长和法术数量仍需 Agent 对照所选规则书审核。
