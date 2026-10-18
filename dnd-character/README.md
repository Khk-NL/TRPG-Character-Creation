# DND 5E / 5R 人物建卡 Skill

安装到 Agent 的 skills 目录后，建议以 `$trpg-character` 统一调用（原 `$dnd-character` 仍可用）；玩家可打开 `assets/intake-form.html`，在同一页面切换 COC、DND 5E、DND 5R 并生成简短 JSON。表单 JSON 需要由 Agent 按规则扩展为完整计划，再交给 `scripts/fill_character.py`。

此仓库仅发布代码和说明。请自行将合法持有的两张原卡放到本目录的 `assets/`：

| 规则 | 来源文件 | 本地目标名 |
|---|---|---|
| 5E / 2014 | `DND 5E人物卡（法术查询列表整合版v4.4.2） - by桃子.xlsx` | `dnd5e-blank.xlsx` |
| 5R / 2024 | `DND5R人物卡_悲灵_弗人_枭熊适配版.xlsx` | `dnd5r-blank.xlsx` |

不要把 5R 卡当作 5E 卡使用。两张原卡、CHM 规则书、已填样卡以及生成的人物卡均不会随公开仓库提交。具体计划格式、命令与验证要求见 [SKILL.md](SKILL.md) 和 [计划字段](references/plan-schema.md)。
