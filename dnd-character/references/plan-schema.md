# Agent 完整计划 JSON

表单的 `dnd-character-intake` 是简短请求；生成脚本只接受 `dnd-character-plan`。`ruleset` 必须为 `5e` 或 `5r`。5R 使用 `schema_version: 2`，5E 继续使用 `schema_version: 1`。`scores_base` 必须包含六个 3–20 的基础值：`STR,DEX,CON,INT,WIS,CHA`。下例展示字段结构；专长、资源上限和预期数值必须按实际规则来源重新核定，不能把示意值直接当作合法角色。

```json
{
  "kind": "dnd-character-plan",
  "schema_version": 2,
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
  "class_features": [
    {"name": "战斗风格", "source": "class", "acquired_level": 1, "summary": "按所选风格取得效果"},
    {"name": "回气", "source": "class", "acquired_level": 1, "summary": "按职业表恢复生命"},
    {"name": "武器精通", "source": "class", "acquired_level": 1, "summary": "使用所选武器精通属性"}
  ],
  "species_traits": [{"name": "特性名称", "description": "已核对的规则摘要"}],
  "feats": [{"name": "背景给的专长", "type": "origin", "acquired_level": 1, "source": "背景", "summary": "卡面简述", "description": "已核对的完整说明"}],
  "weapons": ["长剑"],
  "inventory": [{"name": "背包", "quantity": 1, "unit_weight": 5, "location": "bag1"}, {"name": "火把", "quantity": 2, "unit_weight": 1, "location": "bag1"}],
  "cantrips": [], "known_spells": [],
  "selected_prepared_spells": [], "always_prepared_spells": [], "free_cast_spells": [],
  "mechanical_effects": [],
  "level_audit": {
    "spell_slots_max": {}, "max_spell_level": 0,
    "selected_prepared_count": 0, "always_prepared_count": 0, "cantrip_count": 0,
    "class_features": ["战斗风格", "回气", "武器精通"], "subclass_features": [], "resources": {"回气": 2},
    "expected_totals": {"initiative": 1, "ac": 11, "hp": 12}
  },
  "combat": {
    "initiative_bonus": 0, "ac_bonus": 0, "hp_bonus_flat": 0,
    "shield": {"name": "", "equipped": false},
    "spell_slots_current": {}, "resources": [{"name": "回气", "current": 2, "max": 2, "recharge": "按职业规则恢复"}],
    "currency": {"gp": 0, "pp": 0, "ep": 0, "sp": 0, "cp": 0}
  }
}
```

5R 的 `selected_prepared_spells` 是玩家自选准备，`always_prepared_spells` 是职业／子职额外常备，每项为 `{name, source, level, description?}`，`level` 为法术环阶。脚本先合并两组，再按环阶升序写入主卡「准备法术」栏 `Y/AG/AO`，同环连续、每列自上而下；同名法术不可跨组重复。`free_cast_spells` 每项为 `{name, source, level, uses_max, uses_remaining, recharge, description?}`；无限次施放可用 `uses_max: "at_will"` 并省略剩余次数。若免费施放的法术已在准备区，`Q` 不重复列名，只在资源栏登记免费次数；仅未在准备区的免费法术进入 `Q`。有限次数免费施法会占用主卡一行资源栏。免费次数和准备来源是不同维度，不得把免费施法次数当作法术位。旧 5R `prepared_spells` 单数组被拒绝，避免丢失来源。

5R 的 `class_features` 只放当前等级及以下已取得的职业／子职特性及其子项，并须覆盖模板该等级的全部适用条目：`name` 必须与模板 `职业` 页原名完全相同，`source` 为 `class` 或 `subclass`，`acquired_level` 单独保存。脚本逐项比对当前等级的名称、来源和取得等级，缺项或高等级多项均拒绝。不得在名称中追加“（1级）”、战术标签或自拟别名；法术效果放法术区，战斗建议和建卡备注放战斗速查。`summary` 为卡面可读短句，超过 32 字会拒绝，全文放 `description`。职业能力查询键 `主要!AW9`、`BD9` 由职业／子职自动写入；映射见[5R 模板字段](template-field-map.md)。

填卡前，Agent 对照当前等级职业表、已允许书籍和 DM 房规生成 `level_audit`：最大法术位逐环数量、最高环阶、自选／额外常备法术数、戏法数、主职业／子职特性原名、每项资源上限、先攻／AC／HP 预期结果。脚本核对计划内部一致性并写出 `角色名-团名-等级核对.json`，**不替代 Agent 对规则来源的人工核查**。原生重算并保存关闭后，用 `--verify-only` 对保存文件的先攻、AC、HP 与预期值逐项比对。

5R 的 `inventory` 每项必须有名称、数量、单件重量（磅）与 `location`：`bag1` / `bag2` 写入实际背包栏和计重输入格；`equipped` 仅用于已在武器、护甲或盾牌栏登记的物品；`ammo` 写入主卡弹药输入格，由模板单独计重。背包里另有同名备用武器或护甲时设 `additional_copy: true`。`combat` 必须显式记录先攻、AC、固定 HP 额外加值、盾牌状态、当前法术位、有限次数资源和五类钱币。非零加值注明 `initiative_bonus_source` / `ac_bonus_source` / `hp_bonus_flat_source`。每项会影响数值的特性／专长还应放进 `mechanical_effects: [{source,target,amount}]`；脚本核对效果之和等于相应输入，并特别要求警觉、防御、健壮等已知项目不只停留在文字说明。

5E 把 `background_bonus` 改成 `racial_bonus`，不填写 2024 起源专长；5E 的 `inventory`、`prepared_spells` 仍沿用字符串数组，`combat` 结构暂仅用于 5R。`basic.background_feature` 写入背景特性。5E 必须提供职业命中骰 `basic.hit_die`（6/8/10/12），可提供 `hp_gains` 数组记录 2 级起每级命中骰结果；未给时按固定平均值计算。`basic.armor_type`、`basic.armor`、`basic.speed` 写入桃子 v4.4.2 模板的装备与速度输入格。5E 当前生命值与模板等级骰格由脚本计算填写；5R 原模板自动按职业/体质等重算 HP。若有超过职业初始两项的豁免熟练，写 `extra_save_proficiency_source` 说明来源。`class_features`、`species_traits`、`feats` 可同时提供简短 `summary` 与完整 `description`：卡面放简述，另附默认生成的战斗速查全文；不要把规则书长段全文复制进公开仓库。

技能名称采用卡面中文：运动、特技、巧手、隐匿、奥秘、历史、调查、自然、宗教、驯兽、洞悉、医药、察觉、求生、欺瞒、威吓、表演、游说。专精项也要出现在 `skill_proficiencies`。脚本验证数值、版次、格位和常见规则冲突；职业选项、技能来源、专长和法术数量仍需 Agent 对照所选规则书审核。

## 5R 魔法装备的计算输入

出现魔法物品时先读[魔法物品核对与落卡](magic-items.md)。以下字段只记录已获准且当前启用的加值，不依物品名称自动推断：

```json
{
  "combat": {
    "shield": {"name": "+1盾牌", "equipped": true, "ac": 3, "ac_source": "2024魔法物品：+1盾牌"},
    "save_bonuses": {"STR": 0, "DEX": 0, "CON": 0, "INT": 0, "WIS": 0, "CHA": 0}
  }
}
```

这是局部字段示例，不能独立传入填卡脚本。`shield.ac` 为盾牌提供的总AC，默认2，当前支持2–5；非2时必须填写 `ac_source`，且不再把其附魔额外计入 `ac_bonus`。`save_bonuses` 缺省各项为0；有非零值时，须提供 `combat.save_bonuses_source` 和 `level_audit.expected_save_totals`（完整六项最终豁免整数），供原生保存后核对。防护斗篷需要同时处理额外AC和全部豁免，不能仅写物品名或只增加AC。现有 `mechanical_effects` 支持的目标仍为先攻、AC和固定HP；豁免来源另记在 `save_bonuses_source`。
