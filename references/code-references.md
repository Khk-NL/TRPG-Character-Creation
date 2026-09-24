# 开源实现参考

这些项目只用于验证功能拆分与交互思路，规则数值仍以随 skill 提供的规则摘要和模板数据为准。

- [digitalghost/CoC-kb](https://github.com/digitalghost/CoC-kb)：八步建卡流程、专精技能、时代装备、可复现的数据导出结构。
- [Roll20 Call_of_Cthulhu_7th_Ed](https://github.com/Roll20/roll20-character-sheets/tree/master/Call_of_Cthulhu_7th_Ed)：派生属性自动计算、时代选项和年龄 MOV 修正。
- [Miskatonic-Investigative-Society/CoC7-FoundryVTT](https://github.com/Miskatonic-Investigative-Society/CoC7-FoundryVTT)：职业技能创建、职业点公式、武器与技能关联及建卡校验。
- [SLMT/coc7-character-generator](https://github.com/SLMT/coc7-character-generator)：轻量随机建卡交互；职业覆盖较少，只作为界面流程参考。
- [Miskatonic University Registrar](https://mur.arrowed.games/)：JSON/PDF/Markdown 多格式导出思路。

实现采用独立 Python 脚本和窄范围 OOXML 修改，不引入这些项目的运行时或复制其代码。
