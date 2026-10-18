#!/usr/bin/env python3
"""Fill a version-specific D&D character workbook without rewriting its OOXML features."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", NS)
ET.register_namespace("r", REL)
ROOT = Path(__file__).resolve().parents[1]
ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
SKILLS = ("运动", "特技", "巧手", "隐匿", "奥秘", "历史", "调查", "自然", "宗教",
          "驯兽", "洞悉", "医药", "察觉", "求生", "欺瞒", "威吓", "表演", "游说")
SKILL_5R = {"运动": 41, "特技": 43, "巧手": 44, "隐匿": 45, "调查": 47,
            "奥秘": 48, "历史": 49, "自然": 50, "宗教": 51, "察觉": 53,
            "洞悉": 54, "驯兽": 55, "医药": 56, "求生": 57, "游说": 59,
            "欺瞒": 60, "威吓": 61, "表演": 62}
SKILL_5E = {name: 21 + i for i, name in enumerate(SKILLS)}
AMMO_5R = {"箭矢": 1/20, "弩矢": 1.5/20, "枪械子弹": 2/10,
           "投石索子弹": 1.5/20, "吹矢": 1/50}


class PlanError(ValueError):
    pass


def require(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    if value is None or value == "":
        raise PlanError(f"缺少 {key}")
    return value


def names(data: dict[str, Any], key: str, allowed: set[str] | None = None) -> list[str]:
    raw = data.get(key, [])
    if not isinstance(raw, list) or any(not isinstance(x, str) or not x.strip() for x in raw):
        raise PlanError(f"{key} 必须是非空字符串数组")
    result = [x.strip() for x in raw]
    if len(result) != len(set(result)):
        raise PlanError(f"{key} 有重复项")
    if allowed is not None and set(result) - allowed:
        raise PlanError(f"{key} 有未知名称：{'、'.join(sorted(set(result) - allowed))}")
    return result


def score_map(data: dict[str, Any], key: str, *, required: bool = False) -> dict[str, int]:
    raw = data.get(key)
    if raw is None and not required:
        raw = {}
    if not isinstance(raw, dict):
        raise PlanError(f"{key} 必须是属性字典")
    if required and set(raw) != set(ABILITIES):
        raise PlanError(f"{key} 必须包含 STR、DEX、CON、INT、WIS、CHA 六项")
    if set(raw) - set(ABILITIES):
        raise PlanError(f"{key} 包含未知属性")
    result = {}
    for ability in ABILITIES:
        value = raw.get(ability, 0)
        if isinstance(value, bool) or not isinstance(value, int) or (required and not 3 <= value <= 20) or (not required and not -10 <= value <= 10):
            raise PlanError(f"{key}.{ability} 数值无效")
        result[ability] = value
    return result


def validate_5r_details(plan: dict[str, Any], level: int) -> dict[str, Any]:
    combat = plan.get("combat")
    if not isinstance(combat, dict):
        raise PlanError("5R 计划须填写 combat：先攻、AC、盾牌、法术位、资源和钱币")
    shield = combat.get("shield", {})
    if not isinstance(shield, dict) or not isinstance(shield.get("equipped", False), bool):
        raise PlanError("combat.shield 须为含 equipped 布尔值的对象")
    inventory = plan.get("inventory", [])
    if not isinstance(inventory, list):
        raise PlanError("5R inventory 必须是含 name、quantity、unit_weight、location 的物品数组")
    bag_counts = {"bag1": 0, "bag2": 0}
    ammo_count = 0
    equipped_names = set(names(plan, "weapons")) | {str(plan["basic"].get("armor", ""))}
    for item in inventory:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise PlanError("5R inventory 每项必须有 name")
        quantity, weight, location = item.get("quantity"), item.get("unit_weight"), item.get("location")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise PlanError(f"{item['name']} 的 quantity 须为正整数")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight < 0:
            raise PlanError(f"{item['name']} 的 unit_weight 须为非负磅数")
        if location not in {"bag1", "bag2", "equipped", "ammo"}:
            raise PlanError(f"{item['name']} 的 location 只能是 bag1、bag2、equipped、ammo")
        if location in bag_counts:
            bag_counts[location] += 1
            if item["name"] in equipped_names and item.get("additional_copy") is not True:
                raise PlanError(f"{item['name']} 已在装备/武器栏，若背包内另有一件请标记 additional_copy: true")
        elif location == "ammo":
            ammo_count += 1
            expected = AMMO_5R.get(item["name"])
            if expected is None or not math.isclose(weight, expected, abs_tol=0.0001):
                raise PlanError(f"{item['name']} 的弹药名称或 unit_weight 与 5R 模板弹药表不符")
        elif item["name"] not in equipped_names and item["name"] != shield.get("name"):
            raise PlanError(f"{item['name']} 标为 equipped，但未在武器、护甲或盾牌栏登记")
    if any(count > 20 for count in bag_counts.values()):
        raise PlanError("5R 背包1/背包2各最多 20 项")
    if ammo_count > 1:
        raise PlanError("5R 主卡弹药栏只能登记一种弹药")

    prepared = plan.get("prepared_spells", [])
    free = plan.get("free_cast_spells", [])
    for key, spells in (("prepared_spells", prepared), ("free_cast_spells", free)):
        if not isinstance(spells, list) or any(not isinstance(spell, dict) or
            not isinstance(spell.get("name"), str) or not spell["name"].strip() or
            not isinstance(spell.get("source"), str) or not spell["source"].strip() for spell in spells):
            raise PlanError(f"5R {key} 每项须有 name 和 source")
        if len({spell["name"] for spell in spells}) != len(spells):
            raise PlanError(f"5R {key} 有重复法术")
    if len(free) > 8 or len(prepared) > 26:
        raise PlanError("5R 无消耗法术最多 8 道，主卡准备法术最多 26 道")
    for spell in free:
        maximum = spell.get("uses_max")
        remaining = spell.get("uses_remaining")
        if maximum == "at_will":
            if remaining is not None:
                raise PlanError(f"{spell['name']} 为无限次施放，不应填写 uses_remaining")
        elif (isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1 or
              isinstance(remaining, bool) or not isinstance(remaining, int) or not 0 <= remaining <= maximum or
              not isinstance(spell.get("recharge"), str) or not spell["recharge"].strip()):
            raise PlanError(f"{spell['name']} 须填写免费施放次数 uses_max、uses_remaining 和 recharge")

    for feat in plan.get("feats", []):
        acquired = feat.get("acquired_level")
        if isinstance(acquired, bool) or not isinstance(acquired, int) or not 1 <= acquired <= level:
            raise PlanError(f"专长 {feat['name']} 须注明 1–{level} 的取得等级 acquired_level")
        if not isinstance(feat.get("source"), str) or not feat["source"].strip():
            raise PlanError(f"专长 {feat['name']} 须注明取得来源 source")
        if str(feat.get("type", "")).lower() == "origin" and acquired != 1:
            raise PlanError(f"起源专长 {feat['name']} 应在 1 级取得")

    for key in ("initiative_bonus", "ac_bonus"):
        value = combat.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not -20 <= value <= 20:
            raise PlanError(f"combat.{key} 须为 -20–20 的整数，未加值时填 0")
        if value and not str(combat.get(key + "_source", "")).strip():
            raise PlanError(f"combat.{key} 非零时须注明来源")
    if shield.get("equipped") and not str(shield.get("name", "")).strip():
        raise PlanError("装备盾牌时须填写 combat.shield.name")
    slots = combat.get("spell_slots_current")
    if not isinstance(slots, dict) or any(str(key) not in {str(x) for x in range(1, 10)} or
        isinstance(value, bool) or not isinstance(value, int) or value < 0 for key, value in slots.items()):
        raise PlanError("combat.spell_slots_current 须为环阶 1–9 到非负剩余位数的对象")
    if prepared and not slots:
        raise PlanError("有准备法术时须填写 combat.spell_slots_current；用 0 明确表示已耗尽")
    resources = combat.get("resources")
    if not isinstance(resources, list) or any(not isinstance(resource, dict) or
        not str(resource.get("name", "")).strip() or
        isinstance(resource.get("current"), bool) or not isinstance(resource.get("current"), int) or
        isinstance(resource.get("max"), bool) or not isinstance(resource.get("max"), int) or
        not 0 <= resource["current"] <= resource["max"] or
        not str(resource.get("recharge", "")).strip() for resource in resources):
        raise PlanError("combat.resources 每项须有 name、current、max、recharge")
    if len(resources) + sum(spell["uses_max"] != "at_will" for spell in free) > 3:
        raise PlanError("5R 主卡最多能显示 3 项有限次数资源（含免费施法次数）")
    currency = combat.get("currency")
    if not isinstance(currency, dict) or set(currency) != {"gp", "pp", "ep", "sp", "cp"} or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in currency.values()
    ):
        raise PlanError("combat.currency 须明确填写 gp、pp、ep、sp、cp 五项非负整数")
    return {"inventory": inventory, "prepared_spells": prepared, "free_cast_spells": free, "combat": combat}


def sheet_path(zf: zipfile.ZipFile, name: str) -> str:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    node = next((x for x in wb.findall(f"{{{NS}}}sheets/{{{NS}}}sheet") if x.get("name") == name), None)
    if node is None:
        raise PlanError(f"模板缺少页签：{name}")
    rid = node.get(f"{{{REL}}}id")
    link = next((x for x in rels.findall(f"{{{PKG}}}Relationship") if x.get("Id") == rid), None)
    if link is None:
        raise PlanError(f"模板页签关系损坏：{name}")
    target = link.get("Target", "").replace("\\", "/")
    return target.lstrip("/") if target.startswith("/") else "xl/" + target.lstrip("./")


def col_number(ref: str) -> int:
    n = 0
    for char in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(char) - 64
    return n


def set_cell(root: ET.Element, ref: str, value: str | int | float | bool) -> None:
    if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]*", ref):
        raise PlanError(f"无效单元格：{ref}")
    data = root.find(f"{{{NS}}}sheetData")
    row_no = int(re.search(r"\d+", ref).group())
    row = data.find(f"{{{NS}}}row[@r='{row_no}']")
    if row is None:
        row = ET.SubElement(data, f"{{{NS}}}row", {"r": str(row_no)})
    cell = row.find(f"{{{NS}}}c[@r='{ref}']")
    if cell is None:
        cell = ET.Element(f"{{{NS}}}c", {"r": ref})
        after = next((c for c in row.findall(f"{{{NS}}}c") if col_number(c.get("r")) > col_number(ref)), None)
        row.insert(list(row).index(after), cell) if after is not None else row.append(cell)
    if cell.find(f"{{{NS}}}f") is not None:
        raise PlanError(f"拒绝覆盖模板公式：{ref}")
    for child in list(cell):
        if child.tag in {f"{{{NS}}}v", f"{{{NS}}}is"}:
            cell.remove(child)
    if isinstance(value, bool):
        cell.set("t", "b")
        ET.SubElement(cell, f"{{{NS}}}v").text = "1" if value else "0"
    elif isinstance(value, (int, float)):
        cell.attrib.pop("t", None)
        ET.SubElement(cell, f"{{{NS}}}v").text = str(value)
    else:
        cell.set("t", "inlineStr")
        inline = ET.SubElement(cell, f"{{{NS}}}is")
        text = ET.SubElement(inline, f"{{{NS}}}t")
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = value


def patch(template: Path, output: Path, changes: dict[str, dict[str, str | int | float | bool]]) -> None:
    if template.resolve() == output.resolve():
        raise PlanError("输出不能覆盖模板")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(template) as source:
        paths = {sheet_path(source, name): cells for name, cells in changes.items()}
        rewritten = {}
        for path, cells in paths.items():
            root = ET.fromstring(source.read(path))
            for ref, value in cells.items():
                set_cell(root, ref, value)
            rewritten[path] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        wb = ET.fromstring(source.read("xl/workbook.xml"))
        calc = wb.find(f"{{{NS}}}calcPr")
        if calc is None:
            calc = ET.SubElement(wb, f"{{{NS}}}calcPr")
        calc.attrib.update(calcMode="auto", fullCalcOnLoad="1", forceFullCalc="1")
        rewritten["xl/workbook.xml"] = ET.tostring(wb, encoding="utf-8", xml_declaration=True)
        fd, temporary = tempfile.mkstemp(suffix=".xlsx", dir=output.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, "w") as target:
                for item in source.infolist():
                    target.writestr(item, rewritten.get(item.filename, source.read(item.filename)))
            shutil.move(temporary, output)
        finally:
            Path(temporary).unlink(missing_ok=True)


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("kind") != "dnd-character-plan" or plan.get("schema_version") != 1:
        raise PlanError("需要 dnd-character-plan schema_version 1 计划")
    ruleset = require(plan, "ruleset")
    if ruleset not in {"5e", "5r"}:
        raise PlanError("ruleset 只能是 5e（2014）或 5r（2024）")
    basic = require(plan, "basic")
    if not isinstance(basic, dict):
        raise PlanError("basic 必须是对象")
    for key in ("name", "class", "species", "background"):
        require(basic, key)
    level = basic.get("level", 1)
    if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 20:
        raise PlanError("basic.level 应为 1–20")
    base = score_map(plan, "scores_base", required=True)
    key = "background_bonus" if ruleset == "5r" else "racial_bonus"
    bonus = score_map(plan, key)
    wrong_key = "racial_bonus" if ruleset == "5r" else "background_bonus"
    if plan.get(wrong_key):
        raise PlanError(f"{ruleset} 不使用 {wrong_key}；请核对版本")
    growth = score_map(plan, "growth_bonus")
    other = score_map(plan, "other_bonus")
    if ruleset == "5r":
        positive = sorted((x for x in bonus.values() if x), reverse=True)
        if any(x < 0 for x in bonus.values()) or positive not in ([2, 1], [1, 1, 1]):
            raise PlanError("5R 背景属性加值应为 +2/+1 或三项 +1")
    final = {key: base[key] + bonus[key] + growth[key] + other[key] for key in ABILITIES}
    if any(not 3 <= x <= 20 for x in final.values()):
        raise PlanError("最终属性超出通常的 3–20；特殊上限需单独核对")
    skills = names(plan, "skill_proficiencies", set(SKILLS))
    expertise = names(plan, "skill_expertise", set(SKILLS))
    if set(expertise) - set(skills):
        raise PlanError("专精选项必须已具备技能熟练")
    saves = names(plan, "save_proficiencies", set(ABILITIES))
    if len(saves) > 2 and not plan.get("extra_save_proficiency_source"):
        raise PlanError("超过两项豁免熟练需注明额外来源")
    for key in ("languages", "tools", "weapons", "cantrips", "known_spells"):
        names(plan, key)
    if ruleset == "5e":
        names(plan, "inventory")
        names(plan, "prepared_spells")
    for key, maximum in (("class_features", 48), ("species_traits", 13), ("feats", 11)):
        raw = plan.get(key, [])
        if not isinstance(raw, list) or len(raw) > maximum or any(not isinstance(x, dict) or not x.get("name") for x in raw):
            raise PlanError(f"{key} 需为至多 {maximum} 项、每项有 name 的数组")
    if ruleset == "5r" and not any(str(x.get("type", "")).lower() == "origin" for x in plan.get("feats", [])):
        raise PlanError("5R 需要注明背景授予的起源专长（feats[].type=origin）")
    if ruleset == "5e" and any(str(x.get("type", "")).lower() == "origin" for x in plan.get("feats", [])):
        raise PlanError("5E 不自动取得 2024 起源专长；请按 2014 版重选")
    details = validate_5r_details(plan, level) if ruleset == "5r" else {}
    return {"ruleset": ruleset, "basic": basic, "level": level, "base": base, "bonus": bonus,
            "growth": growth, "other": other, "final": final, "skills": skills,
            "expertise": expertise, "saves": saves, **details}


def put_optional(cells: dict[str, str | int | float], ref: str, value: Any) -> None:
    if value is not None and value != "":
        cells[ref] = str(value) if not isinstance(value, int) else value


def card_summary(entry: dict[str, Any], *, include_source: bool = False) -> str:
    description = str(entry.get("summary") or entry.get("description") or "").strip()
    source = str(entry.get("source", "")).strip() if include_source else ""
    text = f"{source}｜{description}" if source and description else source or description
    return text if len(text) <= 32 else text[:31] + "…"


def build_5r(plan: dict[str, Any], valid: dict[str, Any]) -> dict[str, dict[str, str | int | float]]:
    basic = valid["basic"]
    main: dict[str, str | int] = {"E3": str(basic["name"]), "E4": str(basic.get("player", "")),
                                  "E6": str(basic["class"]), "O6": valid["level"],
                                  "T6": str(basic["species"])}
    origin: dict[str, str | int] = {"E3": str(basic["name"]), "E4": str(basic.get("player", "")),
                                    "E6": str(basic["background"])}
    for ref, key in {"I6":"subclass", "T7":"subspecies", "T8":"alignment", "T9":"faith",
                     "AR23":"size", "AR24":"speed", "L40":"armor"}.items():
        put_optional(main, ref, basic.get(key))
    for ref, key in {"E5":"hometown", "E8":"age", "K8":"height", "E9":"gender",
                     "K9":"weight", "S11":"personality", "S12":"appearance", "S13":"ideal",
                     "S14":"bond", "S15":"flaw", "S17":"story"}.items():
        put_optional(origin, ref, basic.get(key))
    for i, ability in enumerate(ABILITIES):
        row = 13 + i
        main[f"I{row}"] = valid["base"][ability]
        for col, key in (("K", "bonus"), ("M", "growth"), ("O", "other")):
            if valid[key][ability]:
                main[f"{col}{row}"] = valid[key][ability]
        if ability in valid["saves"]:
            main[f"B{row}"] = "O"
    for name in valid["skills"]:
        main[f"B{SKILL_5R[name]}"] = "🅞" if name in valid["expertise"] else "O"
    for i, name in enumerate(names(plan, "weapons")):
        if i >= 5: raise PlanError("5R 主卡最多放 5 件武器")
        main[f"B{32+i}"] = name
    for i, feat in enumerate(plan.get("class_features", [])):
        main[f"AX{17+i}"] = str(feat["name"])
        put_optional(main, f"BC{17+i}", card_summary(feat))
    for i, trait in enumerate(plan.get("species_traits", [])):
        main[f"BT{6+i}"] = str(trait["name"])
        put_optional(main, f"BZ{6+i}", card_summary(trait))
    for i, feat in enumerate(plan.get("feats", [])):
        main[f"BT{19+i}"] = feat["acquired_level"]
        main[f"BU{19+i}"] = str(feat["name"])
        put_optional(main, f"BZ{19+i}", card_summary(feat, include_source=True))
    for i, language in enumerate(names(plan, "languages")):
        if i >= 10: raise PlanError("5R 起源页最多放 10 门语言")
        origin[f"{'B' if i % 2 == 0 else 'H'}{24+i//2}"] = language
    for i, tool in enumerate(names(plan, "tools")):
        if i >= 10: raise PlanError("5R 起源页最多放 10 项工具")
        origin[f"{'B' if i % 2 == 0 else 'H'}{31+i//2}"] = tool
    backpack: dict[str, str | int | float] = {}
    bag_rows = {"bag1": list(range(5, 15)) + list(range(16, 26)),
                "bag2": list(range(29, 39)) + list(range(40, 50))}
    bag_counts = {"bag1": 0, "bag2": 0}
    for item in valid["inventory"]:
        location = item["location"]
        if location == "ammo":
            main["AK30"] = item["name"]
            main["AS30"] = item["quantity"]
        elif location in bag_rows:
            row = bag_rows[location][bag_counts[location]]
            bag_counts[location] += 1
            name_col, weight_col, count_col = (("Y", "AP", "AS") if location == "bag1" else ("B", "S", "V"))
            backpack[f"{name_col}{row}"] = item["name"]
            backpack[f"{weight_col}{row}"] = item["unit_weight"]
            backpack[f"{count_col}{row}"] = item["quantity"]
    spellbook: dict[str, str | int] = {}
    for i, spell in enumerate(names(plan, "known_spells")):
        if i >= 78: raise PlanError("5R 法术书最多放 78 道法术")
        spellbook[f"X{3+i}"] = spell
    free_slots = [f"Q{row}" for row in range(66, 74)]
    prepared_slots = ([f"{col}{row}" for row in range(66, 74) for col in ("Y", "AG", "AO")] +
                      ["AG74", "AO74"])
    main.update((slot, spell["name"]) for slot, spell in zip(free_slots, valid["free_cast_spells"]))
    main.update((slot, spell["name"]) for slot, spell in zip(prepared_slots, valid["prepared_spells"]))
    cantrips = names(plan, "cantrips")
    cantrip_slots = [f"{col}{row}" for row in range(77, 81) for col in ("Q", "Y")]
    if len(cantrips) > len(cantrip_slots): raise PlanError("cantrips 超出主卡空间")
    main.update(zip(cantrip_slots, cantrips))
    combat = valid["combat"]
    main["G22"] = combat["initiative_bonus"]
    main["G23"] = combat["ac_bonus"]
    shield = combat.get("shield", {})
    if shield.get("name"):
        main["AP40"] = str(shield["name"])
        main["AS40"] = "是" if shield.get("equipped") else "否"
    for tier, remaining in combat["spell_slots_current"].items():
        main[f"E{71+int(tier)}"] = remaining
    resources = list(combat["resources"])
    resources += [{"name": f"{spell['name']}（免费）", "description": spell["source"],
                   "current": spell["uses_remaining"], "max": spell["uses_max"],
                   "recharge": spell["recharge"]}
                  for spell in valid["free_cast_spells"] if spell["uses_max"] != "at_will"]
    for i, resource in enumerate(resources):
        row = 26 + i
        main[f"B{row}"] = str(resource["name"])
        put_optional(main, f"F{row}", resource.get("description"))
        main[f"J{row}"] = resource["current"]
        main[f"M{row}"] = resource["max"]
        main[f"O{row}"] = str(resource["recharge"])
    for key, ref in {"gp":"AI59", "pp":"AP59", "ep":"AI60", "sp":"AI61", "cp":"AI62"}.items():
        main[ref] = combat["currency"][key]
    return {"主要": main, "起源": origin, "背包": backpack, "法术书": spellbook}


def build_5e(plan: dict[str, Any], valid: dict[str, Any]) -> dict[str, dict[str, str | int]]:
    basic = valid["basic"]
    hit_die = basic.get("hit_die")
    if hit_die not in (6, 8, 10, 12):
        raise PlanError("5E 计划需提供职业命中骰 basic.hit_die（6/8/10/12）")
    hp_gains = plan.get("hp_gains")
    if hp_gains is None:
        hp_gains = [hit_die // 2 + 1] * (valid["level"] - 1)
    if not isinstance(hp_gains, list) or len(hp_gains) != valid["level"]-1 or any(
        isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= hit_die for x in hp_gains
    ):
        raise PlanError("hp_gains 应为等级 2 起每级的命中骰结果，长度为 level-1")
    constitution_modifier = (valid["final"]["CON"] - 10) // 2
    if hit_die + constitution_modifier < 1 or any(gain + constitution_modifier < 1 for gain in hp_gains):
        raise PlanError("此角色的每级 HP 最低为 1，模板的线性 HP 公式不适用；请单独核对")
    current_hp = hit_die + sum(hp_gains) + constitution_modifier * valid["level"]
    cells: dict[str, str | int | bool] = {"E3": str(basic["name"]), "E4": str(basic.get("player", "")),
                                         "S3": str(basic["class"]), "Y3": valid["level"],
                                         "E6": str(basic["species"]), "AW4": hit_die,
                                         "M29": current_hp, "L32": valid["level"]}
    for i, gain in enumerate(hp_gains):
        hp_cols = ("AY", "BA", "BC", "BE", "BG", "BI", "BK", "BM", "BO", "AW", "AY", "BA", "BC", "BE", "BG", "BI", "BK", "BM", "BO")
        cells[f"{hp_cols[i]}{4 if i < 9 else 7}"] = gain
    for ref, key in {"E7":"subspecies", "M6":"gender", "M7":"age", "E9":"height",
                     "E10":"weight", "L9":"alignment", "L10":"faith", "L38":"size",
                     "R38":"speed", "L45":"armor_type", "P45":"armor"}.items():
        put_optional(cells, ref, basic.get(key))
    for i, ability in enumerate(ABILITIES):
        row = 14+2*i
        cells[f"I{row}"] = valid["base"][ability]
        if valid["bonus"][ability]: cells[f"K{row}"] = valid["bonus"][ability]
        if valid["growth"][ability] or valid["other"][ability]:
            cells[f"M{row}"] = valid["growth"][ability]
            cells[f"O{row}"] = valid["other"][ability]
        if ability in valid["saves"]: cells[f"A{row}"] = True
    proficiency = 2+(valid["level"]-1)//4
    skill_rows = {"运动":45,"特技":47,"巧手":48,"隐匿":49,"调查":51,"奥秘":52,
                  "历史":53,"自然":54,"宗教":55,"察觉":57,"洞悉":58,"驯兽":59,
                  "医药":60,"求生":61,"游说":63,"欺瞒":64,"威吓":65,"表演":66}
    for name in valid["skills"]:
        row = skill_rows[name]
        cells[f"A{row}"] = True
        if name in valid["expertise"]: cells[f"F{row}"] = proficiency
    background: dict[str, str | int] = {"E3": str(basic["name"]),
                                        "E4": str(basic.get("player", "")),
                                        "M5": str(basic["background"])}
    for ref, key in {"E5":"hometown", "E7":"hair_style", "M7":"hair_color",
                     "E8":"eye_color", "M8":"skin_color", "U3":"personality",
                     "U5":"ideal", "U6":"bond", "U7":"flaw", "U9":"appearance",
                     "U18":"story"}.items():
        put_optional(background, ref, basic.get(key))
    put_optional(background, "U12", basic.get("background_feature"))
    for i, language in enumerate(names(plan, "languages")):
        if i >= 8: raise PlanError("5E 背景页最多放 8 门语言")
        background[f"{'C' if i % 2 == 0 else 'J'}{32+i//2}"] = language
    for i, tool in enumerate(names(plan, "tools")):
        if i >= 8: raise PlanError("5E 背景页最多放 8 项工具")
        background[f"{'C' if i % 2 == 0 else 'J'}{37+i//2}"] = tool
    features = ([{"name": f"子职：{basic['subclass']}"}] if basic.get("subclass") else [])
    features += plan.get("class_features", []) + plan.get("feats", [])
    if len(features) > 26: raise PlanError("5E 主卡最多放 26 项职业特性/专长")
    for i, feature in enumerate(features):
        cells[f"C{90+i}"] = str(feature["name"])
        put_optional(cells, f"H{90+i}", card_summary(feature))
    for i, trait in enumerate(plan.get("species_traits", [])):
        if i >= 26: raise PlanError("5E 主卡最多放 26 项种族特性")
        cells[f"Z{90+i}"] = str(trait["name"])
        put_optional(cells, f"AE{90+i}", card_summary(trait))
    backpack: dict[str, str | int] = {}
    items = names(plan, "inventory")
    bag_rows = list(range(5,15))+list(range(16,26))
    if len(items) > 40: raise PlanError("5E 前两个背包最多放 40 项物品")
    for i, item in enumerate(items):
        backpack[f"{'B' if i < 20 else 'Y'}{bag_rows[i % 20]}"] = item
    weapons = names(plan, "weapons")
    if len(weapons) > 5: raise PlanError("5E 主卡最多放 5 件武器")
    for i, weapon in enumerate(weapons): cells[f"P{47+i}"] = weapon
    spells = names(plan, "cantrips") + names(plan, "known_spells") + names(plan, "prepared_spells")
    spells = list(dict.fromkeys(spells))
    if len(spells) > 51: raise PlanError("5E 主卡法术概览最多放 51 道")
    if spells:
        cells["B70"] = "已知/已准备法术" if plan.get("known_spells") and plan.get("prepared_spells") else (
            "已知法术" if plan.get("known_spells") else "已准备法术")
    for i, spell in enumerate(spells): cells[f"{('C','J','Q')[i%3]}{72+i//3}"] = spell
    return {"主要": cells, "背景": background, "背包": backpack}


def output_path(plan: dict[str, Any], requested: Path | None) -> Path:
    basic = plan["basic"]
    if requested is not None and requested.suffix.lower() == ".xlsx": return requested
    directory = requested or ROOT / "outputs"
    if not basic.get("group_name"):
        raise PlanError("缺少 basic.group_name；请从公告确认团名，或明确指定完整 .xlsx 输出文件名")
    filename = f"{basic['name']}-{basic['group_name']}.xlsx"
    for char in '<>:"/\\|?*': filename = filename.replace(char, "-")
    return directory / filename


def combat_reference(plan: dict[str, Any], valid: dict[str, Any]) -> str:
    basic = valid["basic"]
    lines = [f"# {basic['name']} · 战斗速查", "", f"规则：DND {valid['ruleset'].upper()}；等级：{valid['level']}", ""]
    if valid["ruleset"] == "5r":
        combat = valid["combat"]
        lines += ["## 卡面计算输入", "",
                  f"先攻额外加值：{combat['initiative_bonus']}；来源：{combat.get('initiative_bonus_source', '无')}",
                  f"AC 额外加值：{combat['ac_bonus']}；来源：{combat.get('ac_bonus_source', '无')}",
                  f"盾牌：{combat.get('shield', {}).get('name') or '无'}；装备：{'是' if combat.get('shield', {}).get('equipped') else '否'}",
                  "当前法术位：" + ("、".join(f"{tier}环 {count}" for tier, count in combat["spell_slots_current"].items()) or "无"),
                  "随身钱币：" + "、".join(f"{key.upper()} {combat['currency'][key]}" for key in ("pp", "gp", "ep", "sp", "cp")), ""]
        if combat["resources"]:
            lines += ["## 有限次数资源", ""]
            lines += [f"- {x['name']}：{x['current']}/{x['max']}，{x['recharge']}。{x.get('description', '')}" for x in combat["resources"]]
            lines.append("")
        lines += ["## 携带物品", ""]
        for item in valid["inventory"]:
            lines.append(f"- {item['name']} ×{item['quantity']}；每件 {item['unit_weight']} lb；"
                         f"位置 {item['location']}；合计 {item['quantity'] * item['unit_weight']:g} lb")
        lines += ["", "背包重量按数量 × 单件重量写入模板；已装备物品和弹药由主卡单独计重。", ""]
    for title, key in (("职业特性", "class_features"), ("种族特性", "species_traits"), ("专长", "feats")):
        entries = plan.get(key, [])
        if entries:
            lines += [f"## {title}", ""]
            for entry in entries:
                detail = str(entry.get("description") or entry.get("summary") or "未提供说明")
                suffix = (f"（{entry['acquired_level']}级，来源：{entry['source']}）" if key == "feats" and valid["ruleset"] == "5r" else "")
                lines.append(f"- {entry['name']}{suffix}：{detail}")
            lines.append("")
    if valid["ruleset"] == "5r":
        for title, spells in (("无消耗法术", valid["free_cast_spells"]), ("准备法术", valid["prepared_spells"])):
            if spells:
                lines += [f"## {title}", ""]
                for spell in spells:
                    uses = ("；无限次" if spell.get("uses_max") == "at_will" else
                            f"；剩余 {spell['uses_remaining']}/{spell['uses_max']}，{spell['recharge']}") if title == "无消耗法术" else ""
                    description = f"；{spell['description']}" if spell.get("description") else ""
                    lines.append(f"- {spell['name']}：来源 {spell['source']}{uses}{description}")
                lines.append("")
    for title, key in (("戏法", "cantrips"), ("已知法术", "known_spells"),
                       ("准备法术", "prepared_spells")):
        if valid["ruleset"] == "5r" and key == "prepared_spells":
            continue
        spells = names(plan, key)
        if spells:
            lines += [f"## {title}", "", "、".join(spells), ""]
    return "\n".join(lines).rstrip() + "\n"


def fill(plan: dict[str, Any], destination: Path | None, template_override: Path | None) -> Path:
    valid = validate_plan(plan)
    ruleset = valid["ruleset"]
    template = template_override or ROOT / "assets" / f"dnd{ruleset}-blank.xlsx"
    if not template.is_file(): raise PlanError(f"缺少 {ruleset.upper()} 模板：{template}")
    if ruleset == "5e" and "5R" in template.name.upper():
        raise PlanError("禁止用 5R 模板生成 2014 年 5E 人物卡")
    changes = build_5r(plan, valid) if ruleset == "5r" else build_5e(plan, valid)
    destination = output_path(plan, destination)
    patch(template, destination, changes)
    reference = destination.with_name(destination.stem + "-战斗速查.md")
    reference.write_text(combat_reference(plan, valid), encoding="utf-8")
    report = {"ruleset": ruleset, "workbook": str(destination), "scores_final": valid["final"],
              "level": valid["level"], "skill_proficiencies": valid["skills"],
              "skill_expertise": valid["expertise"], "changed_cells": {k: len(v) for k,v in changes.items()},
              "combat_reference": str(reference), "native_recalculation": "pending",
              "note": "请用 WPS 或 Excel 原生重算并核对核心页；兼容渲染结果不可覆盖原卡。"}
    if ruleset == "5r":
        report["bag_weight_lb"] = {location: sum(item["quantity"] * item["unit_weight"]
                                                  for item in valid["inventory"] if item["location"] == location)
                                   for location in ("bag1", "bag2")}
    destination.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="D&D 5E (2014) / 5R (2024) character card filler")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--template", type=Path)
    args = parser.parse_args()
    try:
        plan = json.loads(args.input.read_text(encoding="utf-8"))
        print(fill(plan, args.output, args.template))
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as error:
        raise SystemExit(f"建卡失败：{error}") from error


if __name__ == "__main__":
    main()
