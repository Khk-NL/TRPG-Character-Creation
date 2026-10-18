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
  "feats": [{"name": "背景给的专长", "type": "origin", "acquired_level": 1, "source": "背景", "summary": "卡面简述", "description": "已核对的完整说明"}],
  "weapons": ["长剑"],
  "inventory": [{"name": "背包", "quantity": 1, "unit_weight": 5, "location": "bag1"}, {"name": "火把", "quantity": 2, "unit_weight": 1, "location": "bag1"}],
  "cantrips": [], "known_spells": [], "prepared_spells": [], "free_cast_spells": [],
  "combat": {
    "initiative_bonus": 0, "ac_bonus": 0, "shield": {"name": "", "equipped": false},
    "spell_slots_current": {}, "resources": [],
    "currency": {"gp": 0, "pp": 0, "ep": 0, "sp": 0, "cp": 0}
  }
}
```

5R 的 `prepared_spells` 每项为 `{name, source, description?}`，`source` 写明职业、背景、专长等准备来源，只写入主卡「准备法术」栏 `Y/AG/AO`。`free_cast_spells` 每项为 `{name, source, uses_max, uses_remaining, recharge, description?}`，只写入「无消耗法术」栏 `Q`；无限次施放可用 `uses_max: "at_will"` 并省略剩余次数。有限次数免费施法会占用主卡一行资源栏。不得把免费施法次数当作法术位。

5R 的 `inventory` 每项必须有名称、数量、单件重量（磅）与 `location`：`bag1` / `bag2` 写入实际背包栏和计重输入格；`equipped` 仅用于已在武器、护甲或盾牌栏登记的物品；`ammo` 写入主卡弹药输入格，由模板单独计重。背包里另有同名备用武器或护甲时设 `additional_copy: true`。`combat` 必须显式记录先攻和 AC 额外加值（非零时附 `initiative_bonus_source` / `ac_bonus_source`）、盾牌装备状态、当前法术位、有限次数资源与五类钱币。先确定这些机械输入，再核对重算后的卡面值。

5E 把 `background_bonus` 改成 `racial_bonus`，不填写 2024 起源专长；5E 的 `inventory`、`prepared_spells` 仍沿用字符串数组，`combat` 结构暂仅用于 5R。`basic.background_feature` 写入背景特性。5E 必须提供职业命中骰 `basic.hit_die`（6/8/10/12），可提供 `hp_gains` 数组记录 2 级起每级命中骰结果；未给时按固定平均值计算。`basic.armor_type`、`basic.armor`、`basic.speed` 写入桃子 v4.4.2 模板的装备与速度输入格。5E 当前生命值与模板等级骰格由脚本计算填写；5R 原模板自动按职业/体质等重算 HP。若有超过职业初始两项的豁免熟练，写 `extra_save_proficiency_source` 说明来源。`class_features`、`species_traits`、`feats` 可同时提供简短 `summary` 与完整 `description`：卡面放简述，另附默认生成的战斗速查全文；不要把规则书长段全文复制进公开仓库。

技能名称采用卡面中文：运动、特技、巧手、隐匿、奥秘、历史、调查、自然、宗教、驯兽、洞悉、医药、察觉、求生、欺瞒、威吓、表演、游说。专精项也要出现在 `skill_proficiencies`。脚本验证数值、版次、格位和常见规则冲突；职业选项、技能来源、专长和法术数量仍需 Agent 对照所选规则书审核。
