# 建卡计划 JSON

`fill` 子命令接受 UTF-8 JSON。可直接运行的完整样例见 [sample-plan.json](../tests/sample-plan.json)；其中的技能点恰好用完对应职业与兴趣点池。不要把只含人设与属性的表单 JSON 直接交给 `fill`。

## 字段说明

- `random_seed` 可省略；省略时脚本根据计划内容生成稳定种子。
- `basic.group_name` 是团名，用于默认文件名 `角色名-团名.xlsx`。表单中可选填；若公告标题可明确推断，Agent 应补入完整计划，否则在默认命名之前询问用户。文件名中的 Windows 不合法字符由脚本替换为 `-`。
- `basic.occupation` 必须能在模板 `职业列表` 中唯一匹配；运行 `catalog` 可先查询。
- `date` 可只填年份。月份、日期和时间缺失时保持空白。
- `characteristics` 是九项完整值。键不区分大小写，但九项必须齐全。
- `characteristics_are_final` 默认 `false`：视为 COC5 原始属性，脚本按年龄调整。若用户明确说已是调整后的七版最终属性，设为 `true`，脚本保留九项数值（仍按年龄计算 MOV）；不得同时提供 `age_adjustment`。
- `age_adjustment` 可选，用于房规或玩家指定的精确调整：`attribute_reductions`、`education_rolls`、`luck_second_roll`。一般不要填写，让脚本按规则处理。
- `skills` 中数值是投入点，不是最终技能值。`occupation` 总和必须等于职业点池；`interest` 总和必须等于 `INT×2`。同一技能可以同时投入两种点数。
- 职业说明中的开放名额由 `catalog` 的 `open_occupation_slots` 列出；相应 `skills` 项须设 `occupation_choice: true`，数量必须吻合，并投入职业点。该标记不能用于兴趣技能，也不改变技能名称。职业必选项与开放名额都遵守同一 KP 职业技能上限。未投入的一类点数可省略或写 `0`；脚本不会将 `0` 写进卡片技能格。
- 专精技能可写 `科学(化学)`、`科学：化学` 或 `科学（化学）`。脚本会寻找相应的模板分类槽位并写入专精名。
- `items` 的随身栏、背包栏各最多 15 行。`backpack: true` 或 `location` 含背包、挎包、提包、行李箱时，名称只写背包栏；否则写随身栏，可附 `location` 与 `status`。逗号、顿号分隔的物品拆成独立行；一套不可拆的组合物品可用“与”保留一个名称。
- `weapons` 最多 5 件；可使用模板准确名称，或使用已核对的常见别名（如小刀/折刀映射小型刀具、砍刀/柴刀映射大型刀具）。其他名字先用 `catalog --only weapons --weapon 名称` 检查候选，避免只凭模糊相似度自动选错。模板第 53 行的徒手攻击会保留。

`fill --output` 接受 `.xlsx` 完整路径，或目录。传目录时自动使用 `角色名-团名.xlsx`；Agent 默认选当前任务的 `outputs/<unique_thread_id>/`，用户指定位置则优先。脚本在同目录生成去掉 `.xlsx` 后缀的 `<角色名-团名>.report.json`，包含职业解析、年龄检定、派生值、点数合计和实际写入单元格。PowerShell 中用 `Get-ChildItem -LiteralPath <目录> -Filter '*.report.json'` 枚举，避免猜错文件名或重打中文路径。

## 团规的两类技能上限

公告明确限制职业/非职业技能时，在完整计划中增加：

```json
"skill_limits": {"occupation": 80, "non_occupation": 60, "basis": "final"}
```

数字仅是示例，不能作为默认团规。`basis: "final"` 限制基础值＋职业投入＋兴趣投入之和；`"investment"` 限制两类投入之和。原文只写“点数上限”且不能确定口径时先确认，不自行假设。

存在 `skill_limits` 时，每个 `skills` 项须包含 `is_occupation` 布尔值及非空的 `classification_reason`。分类按职业原文及已选的合法开放名额，不能按点池来源判断：纯用兴趣点提高的职业技能仍可为 `true`；使用职业点或 `occupation_choice` 的技能不能为 `false`。例如：

```json
{"name":"会计", "occupation":40, "interest":10,
 "is_occupation":true, "classification_reason":"会计师职业明列", "base_value":5}
```

`final` 模式还须提供按本卡时代、专精及最终属性核对的 `base_value` 非负整数；脚本不自动从复杂模板公式推断基础值。以上例为最终55，按职业上限检查，而不是把兴趣投入10单独套非职业上限。职业开放技能也适用职业上限。

脚本在写卡前检查实际投入的全部 `skills`，超限即报错，并在报告 `skill_limits.checked_skills` 记录分类、依据、检查值和上限。Agent 必须核对分类与基础值来源；脚本不证明声明真实，也不检查未投入的技能。团规有母语等例外时先按原文确认适用范围，当前通用两类配置无法表达的例外须明确说明并人工逐项核对，不能伪造基础值来通过检查。

## 分配依据

`build_strategy` 是可选字段，旧计划保持兼容；Agent 代选技能或点数时填写，玩家已全部指定时可省略。

```json
{
  "build_strategy": {
    "character_concept": "长期核账、谨慎求证的会计师",
    "party_context": "未知",
    "skill_reasons": {
      "会计": "日常核对商行账目，是最有经验的工作技能",
      "汽车驾驶": "过去经常开车往返客户商行"
    },
    "choices": [
      {
        "choice": "把主要投入留给会计和资料检索",
        "reason": "工作与求学经历均支持，符合处理可疑账目的导入",
        "synergy": "先检索交易记录，再用会计分析异常",
        "tradeoff": "没有据此补写用枪经历，遇到暴力主要依靠避险"
      }
    ]
  }
}
```

示例只展示结构；`skill_reasons` 的键必须与完整计划 `skills[].name` 逐项一致，覆盖包括信用评级在内的全部投入技能，不多不少。`character_concept`、`party_context`、每项依据及每个 `choice`/`reason` 均为非空字符串；`choices` 至少一项，`synergy`、`tradeoff` 可省略，填写时也须为非空字符串。没有真实配合时不硬填。

脚本校验结构与名称覆盖，并将原记录写入 `.report.json` 的 `build_strategy`；这不证明故事可信、技能最终值正确或职业资格和 KP 上限合法。技能基础值与最终值仍由 Agent 按规则/模板核对。此字段不参与隐式随机种子，补改说明不重掷年龄检定。

## 玩家填写的简短请求 JSON

`assets/intake-form.html` 生成 `kind: "coc7-investigator-intake"`、`schema_version: 1` 的简短请求，含 `basic`、`announcement`、`characteristics`、`characteristics_are_final`，可选 `basic.group_name`、`persona`、`background_notes`、`keeper_requirements` 与 `output_path`。表单不要求时代，也不输出 `basic.era`；Agent 从公告推断，并在完整计划里填写。属性可整段粘贴或逐项输入；粘贴 `.coc5` 多组结果时，玩家必须选择其中一组，JSON 只保留选中的九项数值。背景补充说明中已确定的事实应保留；KP 要求用于判断职业、技能、装备、年代和房规。这个简短请求要先交给 Agent 扩展成上述完整建卡计划，不能直接传给 `fill --input`。在没有 GUI 时，玩家直接用自然语言给出相同信息也可以。
