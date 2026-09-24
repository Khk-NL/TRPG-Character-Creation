# Skill 维护与发布

绑定仓库：`https://github.com/Khk-NL/TRPG-Character-Creation`。用户已同意把所提供的空白卡 XLSX 模板和 skill 一起推送。该仓库只存 skill 的维护文件；不要添加规则书 PDF、玩家输入、生成的卡、报告、凭据或 `outputs/`。

修改 skill 后，先运行测试和 `quick_validate.py`（若当前平台有 Codex 验证器），再运行：

```powershell
python scripts/publish_skill.py --source .
```

脚本会临时克隆仓库，只暂存白名单中的 skill 文件，创建提交并推送；没有变化则不提交。认证由已有 Git 凭据处理，脚本不读取令牌，也不设置长期 Git hook。推送失败时保留本地已验证的修改并报告错误；不得称远端已同步。普通建卡不触发发布。
