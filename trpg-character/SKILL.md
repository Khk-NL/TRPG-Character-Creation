---
name: trpg-character
description: 统一创建 COC 7版、DND 5E（2014）或 DND 5R（2024）新人物卡。根据表单 JSON 或玩家说明识别规则类型，再按对应规则生成 XLSX；不用于修改已有成长记录的角色。
---

# TRPG 人物建卡统一入口

玩家可用[同一份离线表单](../dnd-character/assets/intake-form.html)选择 COC、DND 5E 或 DND 5R，也可以直接描述角色。此入口只负责分流；实际规则、模板、脚本和验卡要求仍由已安装的 `$coc7-investigator`、`$dnd-character` Skill 负责。使用时只读取并执行当前规则对应的 Skill，不混用两套规则，也不要把表单的简短 intake JSON 直接交给填卡脚本。

## 识别规则

- 表单 JSON 有 `game_type` 时：`coc` 进入 COC 7版；`dnd5e` 进入 DND 5E；`dnd5r` 进入 DND 5R。DND 的 `ruleset` 应分别为 `5e` / `5r`；若 `game_type`、`kind`、`ruleset` 互相矛盾，先请玩家确认，不猜测版本。
- 旧版 JSON 没有 `game_type` 时：`kind: coc7-investigator-intake` 进入 COC；`kind: dnd-character-intake` 进入 DND，并以 `ruleset` 确定 5E / 5R。
- 自然语言输入按玩家明确指定的规则走。若只写「DND」而无法确定 5E / 5R，先问版本；无法确定是 COC 还是 DND 时也先问。COJ 仍未开放。
- 在同一次建卡中确认 5R 后锁定 2024 版；后来出现 2014 链接或摘录时，只提示差异并继续 5R，不把参考资料当成切版要求。只有玩家明确要求改版才重新分流。

## 执行

- COC：读取 `$coc7-investigator` 的 `SKILL.md` 和它要求的相关参考，仅按 COC 7版流程建卡、分点和验证。
- DND：读取 `$dnd-character` 的 `SKILL.md` 和它要求的相关参考，按选定的 5E 或 5R 流程建卡、填表和验证。不可用 5R 模板制作 5E 卡，反之亦然。
- 交付时注明使用的规则版本、输出文件、验证结果和待 KP / DM 确认的事项。若对应子 Skill 或所需模板未安装，说明缺项，不冒充已完成建卡。
