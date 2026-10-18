#!/usr/bin/env python3
"""Fill a version-specific D&D character workbook without rewriting its OOXML features."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import stat
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
    shield_ac = shield.get("ac", 2)
    if isinstance(shield_ac, bool) or not isinstance(shield_ac, int) or not 2 <= shield_ac <= 5:
        raise PlanError("combat.shield.ac 须为盾牌提供的总 AC（通常 2，+1盾牌为3），范围2–5")
    if shield_ac != 2 and not str(shield.get("ac_source", "")).strip():
        raise PlanError("魔法盾牌的额外 AC 须注明 combat.shield.ac_source")
    save_bonuses = combat.get("save_bonuses", {})
    if not isinstance(save_bonuses, dict) or set(save_bonuses) - set(ABILITIES) or any(
        isinstance(v, bool) or not isinstance(v, int) or not -20 <= v <= 20 for v in save_bonuses.values()
    ):
        raise PlanError("combat.save_bonuses 须为 STR/DEX/CON/INT/WIS/CHA 到整数加值的对象")
    if any(save_bonuses.values()) and not str(combat.get("save_bonuses_source", "")).strip():
        raise PlanError("豁免额外加值须注明 combat.save_bonuses_source")
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

    if "prepared_spells" in plan:
        raise PlanError("5R 请将 prepared_spells 拆为 selected_prepared_spells 与 always_prepared_spells")
    selected = plan.get("selected_prepared_spells", [])
    always = plan.get("always_prepared_spells", [])
    if not isinstance(selected, list) or not isinstance(always, list):
        raise PlanError("5R 准备法术须分为两个数组")
    prepared = selected + always
    free = plan.get("free_cast_spells", [])
    for key, spells in (("selected_prepared_spells", selected), ("always_prepared_spells", always), ("free_cast_spells", free)):
        if not isinstance(spells, list) or any(not isinstance(spell, dict) or
            not isinstance(spell.get("name"), str) or not spell["name"].strip() or
            not isinstance(spell.get("source"), str) or not spell["source"].strip() or
            isinstance(spell.get("level"), bool) or not isinstance(spell.get("level"), int) or
            not (0 if key == "free_cast_spells" else 1) <= spell["level"] <= 9 for spell in spells):
            raise PlanError(f"5R {key} 每项须有 name、source 和环阶 level")
        if len({spell["name"] for spell in spells}) != len(spells):
            raise PlanError(f"5R {key} 有重复法术")
    if len([spell for spell in free if spell["name"] not in {x["name"] for x in prepared}]) > 8 or len(prepared) > 26:
        raise PlanError("5R 无消耗法术最多 8 道，主卡准备法术最多 26 道")
    if len({x["name"] for x in prepared}) != len(prepared):
        raise PlanError("自选与额外常备法术不可重复")
    levels_by_name = {x["name"]: x["level"] for x in prepared}
    if any(x["name"] in levels_by_name and levels_by_name[x["name"]] != x["level"] for x in free):
        raise PlanError("免费施放与准备法术的同名条目环阶必须一致")
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
    for feature in plan.get("class_features", []):
        acquired = feature.get("acquired_level")
        if feature.get("source") not in {"class", "subclass"} or isinstance(acquired, bool) or not isinstance(acquired, int) or not 1 <= acquired <= level:
            raise PlanError(f"职业特性 {feature['name']} 须注明 source=class/subclass 和取得等级")

    for key in ("initiative_bonus", "ac_bonus", "hp_bonus_flat"):
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
    effects = plan.get("mechanical_effects", [])
    if not isinstance(effects, list) or any(not isinstance(x, dict) or
        not str(x.get("source", "")).strip() or x.get("target") not in
        {"initiative_bonus", "ac_bonus", "hp_bonus_flat"} or
        isinstance(x.get("amount"), bool) or not isinstance(x.get("amount"), int) for x in effects):
        raise PlanError("mechanical_effects 须逐项列出 source、target、amount")
    for target in ("initiative_bonus", "ac_bonus", "hp_bonus_flat"):
        if sum(x["amount"] for x in effects if x["target"] == target) != combat[target]:
            raise PlanError(f"mechanical_effects 与 combat.{target} 不一致")
    required_effects = {"警觉": "initiative_bonus", "防御": "ac_bonus", "健壮": "hp_bonus_flat"}
    for feat in plan.get("feats", []):
        target = required_effects.get(feat["name"])
        if target and not any(x["source"] == feat["name"] and x["target"] == target for x in effects):
            raise PlanError(f"专长 {feat['name']} 的数值效果须列入 mechanical_effects.{target}")
    audit = plan.get("level_audit")
    if not isinstance(audit, dict):
        raise PlanError("5R 须先提供 level_audit 等级—资源—特性核对表")
    for key, actual in (("selected_prepared_count", len(selected)), ("always_prepared_count", len(always)),
                        ("cantrip_count", len(plan.get("cantrips", [])))):
        if audit.get(key) != actual:
            raise PlanError(f"level_audit.{key} 与计划数量不符")
    maximum = audit.get("spell_slots_max")
    if not isinstance(maximum, dict) or any(str(k) not in {str(x) for x in range(1,10)} or
        isinstance(v, bool) or not isinstance(v, int) or v < 0 for k,v in maximum.items()):
        raise PlanError("level_audit.spell_slots_max 须为环阶到最大法术位的对象")
    if any(slots.get(k, 0) > maximum.get(k, 0) for k in slots):
        raise PlanError("当前法术位超过 level_audit.spell_slots_max")
    highest = max((int(k) for k,v in maximum.items() if v), default=0)
    if audit.get("max_spell_level") != highest:
        raise PlanError("level_audit.max_spell_level 与最大法术位环阶不符")
    if any(x["level"] > highest for x in prepared):
        raise PlanError("准备法术环阶高于当前最高法术位")
    for source in ("class", "subclass"):
        key = source + "_features"
        expected = names(audit, key)
        actual = [x["name"] for x in plan.get("class_features", []) if x.get("source") == source]
        if expected != actual:
            raise PlanError(f"level_audit.{key} 与职业特性列表不符")
    expected_resources = audit.get("resources")
    actual_resources = {x["name"]: x["max"] for x in resources}
    actual_resources.update({x["name"]: x["uses_max"] for x in free if x["uses_max"] != "at_will"})
    if expected_resources != actual_resources:
        raise PlanError("level_audit.resources 与资源上限不符")
    totals = audit.get("expected_totals")
    if not isinstance(totals, dict) or set(totals) != {"initiative", "ac", "hp"} or any(
        isinstance(v, bool) or not isinstance(v, int) for v in totals.values()
    ):
        raise PlanError("level_audit.expected_totals 须提供先攻、AC、HP 三项预期整数")
    expected_saves = audit.get("expected_save_totals")
    if expected_saves is not None or any(save_bonuses.values()):
        if not isinstance(expected_saves, dict) or set(expected_saves) != set(ABILITIES) or any(
            isinstance(v, bool) or not isinstance(v, int) for v in expected_saves.values()
        ):
            raise PlanError("有豁免额外加值时，level_audit.expected_save_totals 须提供六项最终豁免整数")
    return {"inventory": inventory, "selected_prepared_spells": selected,
            "always_prepared_spells": always,
            "prepared_spells": sorted(prepared, key=lambda spell: spell["level"]),
            "free_cast_spells": free, "combat": combat, "level_audit": audit}


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


def template_feature_catalog(template: Path, class_name: str, subclass_name: str = "") -> tuple[dict[str, int], dict[str, int]]:
    """Read literal feature names from the template's class data; never use cached formula output."""
    with zipfile.ZipFile(template) as archive:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(n.text or "" for n in si.iter(f"{{{NS}}}t"))
                       for si in root.findall(f"{{{NS}}}si")]
        root = ET.fromstring(archive.read(sheet_path(archive, "职业")))
        values: dict[str, str] = {}
        for cell in root.iter(f"{{{NS}}}c"):
            ref = cell.get("r", "")
            # Class/subclass option cells may be conditional formulas; use their
            # cached displayed names only for option discovery, not feature data.
            if cell.find(f"{{{NS}}}f") is not None and not re.fullmatch(r"[B-Z](?:[3-9]|1\d|2[0-2])", ref):
                continue
            raw = cell.findtext(f"{{{NS}}}v")
            if cell.get("t") == "s" and raw is not None:
                value = strings[int(raw)]
            elif cell.get("t") == "inlineStr":
                value = "".join(n.text or "" for n in cell.iter(f"{{{NS}}}t"))
            else:
                value = raw or ""
            if value:
                values[ref] = value.strip()
    class_row = next((row for row in range(2, 23) if values.get(f"CH{row}") == class_name), None)
    if class_row is None:
        raise PlanError(f"5R 模板职业表没有 {class_name}；请核对职业名称或模板版本")
    name_col = int(values[f"CK{class_row}"])
    level_col = int(values[f"CJ{class_row}"])
    def column(number: int) -> str:
        result = ""
        while number:
            number, digit = divmod(number - 1, 26)
            result = chr(65 + digit) + result
        return result
    subclass_rows = [(row, values[f"CH{row}"], int(values[f"CI{row}"]))
                     for row in range(30, 285) if values.get(f"CH{row}") and
                     values.get(f"CI{row}", "").isdigit()]
    selected = next(((row, index) for row, name, index in subclass_rows if name == subclass_name), None)
    if subclass_name and selected is None:
        raise PlanError(f"5R 模板子职表没有 {subclass_name}")
    # The class table starts at row 34. B:Z lists subclasses for each class;
    # CH:CI gives each subclass's first data row relative to row 34.
    option_row = next((row for row in range(3, 23) if values.get(f"B{row}") == class_name), None)
    if option_row is None:
        raise PlanError(f"模板子职索引没有主职业 {class_name}")
    option_names = {values.get(f"{column(col)}{option_row}") for col in range(3, 27)}
    starts = [index for _, name, index in subclass_rows if name in option_names]
    if not starts:
        raise PlanError(f"模板未找到 {class_name} 的子职数据边界")
    class_end = 32 + min(starts)
    if subclass_name and subclass_name not in option_names:
        raise PlanError(f"{subclass_name} 不在 {class_name} 的模板子职选项中")
    def collect(start_row: int, end_row: int) -> dict[str, int]:
        found: dict[str, int] = {}
        last_level = 1
        for row in range(start_row, end_row + 1):
            raw_level = values.get(f"{column(level_col)}{row}", "")
            if raw_level.isdigit():
                last_level = int(raw_level)
            name = values.get(f"{column(name_col)}{row}", "")
            if name and len(name) <= 40:
                found[name] = last_level
        return found
    class_names = collect(40, class_end)
    subclass_names: dict[str, int] = {}
    if selected:
        selected_row, selected_index = selected
        next_entry = None
        for row, _, index in subclass_rows:
            if row <= selected_row:
                continue
            if index <= selected_index:
                break
            next_entry = index
            break
        first_data_row = 33 + selected_index
        if next_entry is not None:
            last_data_row = 32 + next_entry
        else:
            last_data_row = first_data_row
            while values.get(f"{column(name_col)}{last_data_row+1}") and last_data_row < 262:
                last_data_row += 1
        subclass_names = collect(first_data_row, last_data_row)
    return class_names, subclass_names


def validate_template_features(plan: dict[str, Any], template: Path) -> None:
    class_names, subclass_names = template_feature_catalog(template, str(plan["basic"]["class"]),
                                                           str(plan["basic"].get("subclass", "")))
    for feature in plan.get("class_features", []):
        name, source, level = feature["name"], feature["source"], feature["acquired_level"]
        if source == "class" and name not in class_names:
            raise PlanError(f"职业特性名称不在该职业模板中：{name}")
        if source == "class" and class_names[name] != level:
            raise PlanError(f"{name} 的取得等级应为模板中的 {class_names[name]} 级")
        if source == "subclass" and name not in subclass_names:
            raise PlanError(f"子职特性名称不在该子职模板中：{name}")
        if source == "subclass" and not plan["basic"].get("subclass"):
            raise PlanError(f"子职特性 {name} 缺少 basic.subclass")
        if source == "subclass" and subclass_names[name] != level:
            raise PlanError(f"{name} 的取得等级应为模板中的 {subclass_names[name]} 级")
    current_level = plan["basic"].get("level", 1)
    for source, catalog in (("class", class_names), ("subclass", subclass_names)):
        expected = {name for name, level in catalog.items() if level <= current_level}
        actual = {x["name"] for x in plan.get("class_features", []) if x["source"] == source}
        if expected != actual:
            missing = expected - actual
            extra = actual - expected
            raise PlanError(f"{source} 当前等级特性不完整：缺少 {', '.join(sorted(missing)) or '无'}；多出 {', '.join(sorted(extra)) or '无'}")


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
    if output.exists() and not (output.stat().st_mode & stat.S_IWRITE):
        raise PlanError(f"目标人物卡为只读，未写入：{output}")
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


def validate_build_strategy(plan: dict[str, Any]) -> None:
    """Check provenance consistency; rule legality and tactical merit remain Agent decisions."""
    if "build_strategy" not in plan:
        return
    strategy = plan["build_strategy"]
    if not isinstance(strategy, dict):
        raise PlanError("build_strategy 须为建卡决策对象")
    for key in ("primary_role", "party_context"):
        if not isinstance(strategy.get(key), str) or not strategy[key].strip():
            raise PlanError(f"build_strategy.{key} 须填写；队伍信息不明时明确写未知")
    if "secondary_role" in strategy and not isinstance(strategy["secondary_role"], str):
        raise PlanError("build_strategy.secondary_role 须为文字")
    for key, selected in (("skill_sources", "skill_proficiencies"),
                          ("expertise_sources", "skill_expertise"), ("tool_sources", "tools")):
        sources = strategy.get(key, {})
        if not isinstance(sources, dict) or any(not isinstance(v, str) or not v.strip() for v in sources.values()):
            raise PlanError(f"build_strategy.{key} 须为名称到非空来源说明的对象")
        if set(sources) != set(plan.get(selected, [])):
            raise PlanError(f"build_strategy.{key} 须逐项覆盖最终 {selected}，不得缺项或多项")
    choices = strategy.get("choices")
    if not isinstance(choices, list) or not choices:
        raise PlanError("build_strategy.choices 须记录至少一项实际代选的选择与理由")
    for choice in choices:
        if not isinstance(choice, dict) or any(not isinstance(choice.get(k), str) or not choice[k].strip()
                                               for k in ("choice", "reason")):
            raise PlanError("build_strategy.choices 每项须有非空 choice、reason")
        if any(k in choice and not isinstance(choice[k], str) for k in ("synergy", "tradeoff")):
            raise PlanError("选择的 synergy、tradeoff 须为文字；无配合或取舍时可省略")


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("kind") != "dnd-character-plan" or plan.get("schema_version") not in (1, 2):
        raise PlanError("需要 dnd-character-plan schema_version 1/2 计划")
    ruleset = require(plan, "ruleset")
    if ruleset not in {"5e", "5r"}:
        raise PlanError("ruleset 只能是 5e（2014）或 5r（2024）")
    if ruleset == "5r" and plan["schema_version"] != 2:
        raise PlanError("5R 现使用 schema_version 2；请拆分法术来源并填写等级核对表")
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
    validate_build_strategy(plan)
    details = validate_5r_details(plan, level) if ruleset == "5r" else {}
    return {"ruleset": ruleset, "basic": basic, "level": level, "base": base, "bonus": bonus,
            "growth": growth, "other": other, "final": final, "skills": skills,
            "expertise": expertise, "saves": saves, **details}


def put_optional(cells: dict[str, str | int | float], ref: str, value: Any) -> None:
    if value is not None and value != "":
        cells[ref] = str(value) if not isinstance(value, int) else value


def card_summary(entry: dict[str, Any], *, include_source: bool = False, strict: bool = False) -> str:
    description = str(entry.get("summary") or entry.get("description") or "").strip()
    source = str(entry.get("source", "")).strip() if include_source else ""
    text = f"{source}｜{description}" if source and description else source or description
    if strict and len(text) > 32:
        raise PlanError(f"{entry['name']} 的卡面说明超过 32 字；请单独提供简短 summary，完整内容留在战斗速查")
    return text if len(text) <= 32 else text[:31] + "…"


def ordered_class_features(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(plan.get("class_features", []),
                  key=lambda feature: (feature["acquired_level"], feature["source"] != "class"))


def build_5r(plan: dict[str, Any], valid: dict[str, Any]) -> dict[str, dict[str, str | int | float]]:
    basic = valid["basic"]
    main: dict[str, str | int] = {"E3": str(basic["name"]), "E4": str(basic.get("player", "")),
                                  "E6": str(basic["class"]), "O6": valid["level"],
                                  "T6": str(basic["species"]), "AW9": str(basic["class"])}
    if basic.get("subclass"):
        main["BD9"] = str(basic["subclass"])
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
    for i, feat in enumerate(ordered_class_features(plan)):
        main[f"AX{17+i}"] = str(feat["name"])
        put_optional(main, f"BC{17+i}", card_summary(feat, strict=True))
    for i, trait in enumerate(plan.get("species_traits", [])):
        main[f"BT{6+i}"] = str(trait["name"])
        put_optional(main, f"BZ{6+i}", card_summary(trait, strict=True))
    for i, feat in enumerate(plan.get("feats", [])):
        main[f"BT{19+i}"] = feat["acquired_level"]
        main[f"BU{19+i}"] = str(feat["name"])
        put_optional(main, f"BZ{19+i}", card_summary(feat, include_source=True, strict=True))
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
    lookup_spells = list(dict.fromkeys(names(plan, "known_spells") + names(plan, "cantrips") +
                         [x["name"] for x in valid["prepared_spells"]] +
                         [x["name"] for x in valid["free_cast_spells"]]))
    if len(lookup_spells) > 78:
        raise PlanError("5R 法术书查询索引（已知、戏法、准备、免费合并去重）最多放78道法术")
    for i, spell in enumerate(lookup_spells):
        spellbook[f"X{3+i}"] = spell
    free_slots = [f"Q{row}" for row in range(66, 74)]
    prepared_slots = ([f"Y{row}" for row in range(66, 74)] +
                      [f"AG{row}" for row in range(66, 75)] +
                      [f"AO{row}" for row in range(66, 75)])
    displayed_free = sorted((spell for spell in valid["free_cast_spells"] if
                             spell["name"] not in {x["name"] for x in valid["prepared_spells"]}),
                            key=lambda spell: spell["level"])
    main.update((slot, spell["name"]) for slot, spell in zip(free_slots, displayed_free))
    main.update((slot, spell["name"]) for slot, spell in zip(prepared_slots, valid["prepared_spells"]))
    cantrips = names(plan, "cantrips")
    cantrip_slots = [f"{col}{row}" for row in range(77, 81) for col in ("Q", "Y")]
    if len(cantrips) > len(cantrip_slots): raise PlanError("cantrips 超出主卡空间")
    main.update(zip(cantrip_slots, cantrips))
    combat = valid["combat"]
    main["G22"] = combat["initiative_bonus"]
    main["G23"] = combat["ac_bonus"]
    main["BB7"] = combat["hp_bonus_flat"]
    for i, ability in enumerate(ABILITIES):
        main[f"W{13+i}"] = combat.get("save_bonuses", {}).get(ability, 0)
    shield = combat.get("shield", {})
    if shield.get("name"):
        main["AL40"] = str(shield["name"])
        main["AQ40"] = shield.get("ac", 2)
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
    strategy = plan.get("build_strategy")
    if strategy:
        roles = strategy["primary_role"] + (f"；辅助贡献：{strategy['secondary_role']}" if strategy.get("secondary_role") else "")
        lines += ["## 建卡取舍", "", f"主要定位：{roles}", f"队伍信息：{strategy['party_context']}", ""]
        for title, key in (("技能", "skill_sources"), ("专精", "expertise_sources"), ("工具", "tool_sources")):
            if strategy.get(key):
                lines.append(f"{title}来源：" + "；".join(f"{name}：{source}" for name, source in strategy[key].items()))
        lines.append("")
        for choice in strategy["choices"]:
            detail = f"- {choice['choice']}：{choice['reason']}"
            if choice.get("synergy"):
                detail += f" 配合：{choice['synergy']}"
            if choice.get("tradeoff"):
                detail += f" 取舍：{choice['tradeoff']}"
            lines.append(detail)
        lines.append("")
    if valid["ruleset"] == "5r":
        combat = valid["combat"]
        lines += ["## 卡面计算输入", "",
                  f"先攻额外加值：{combat['initiative_bonus']}；来源：{combat.get('initiative_bonus_source', '无')}",
                  f"AC 额外加值：{combat['ac_bonus']}；来源：{combat.get('ac_bonus_source', '无')}",
                  f"HP 固定额外加值：{combat['hp_bonus_flat']}；来源：{combat.get('hp_bonus_flat_source', '无')}",
                  f"盾牌：{combat.get('shield', {}).get('name') or '无'}；装备：{'是' if combat.get('shield', {}).get('equipped') else '否'}",
                  f"盾牌提供 AC：{combat.get('shield', {}).get('ac', 2)}（仅装备时计入；不重复加入额外AC）",
                  "豁免额外加值：" + "、".join(f"{a} {combat.get('save_bonuses', {}).get(a, 0):+d}" for a in ABILITIES)
                  + f"；来源：{combat.get('save_bonuses_source', '无')}",
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
        entries = ordered_class_features(plan) if key == "class_features" and valid["ruleset"] == "5r" else plan.get(key, [])
        if entries:
            lines += [f"## {title}", ""]
            for entry in entries:
                detail = str(entry.get("description") or entry.get("summary") or "未提供说明")
                suffix = (f"（{entry['acquired_level']}级，来源：{entry['source']}）" if key in ("feats", "class_features") and valid["ruleset"] == "5r" else "")
                lines.append(f"- {entry['name']}{suffix}：{detail}")
            lines.append("")
    if valid["ruleset"] == "5r":
        prepared_names = {spell["name"] for spell in valid["prepared_spells"]}
        free_by_name = {spell["name"]: spell for spell in valid["free_cast_spells"]}
        for title, spells in (("无消耗法术", sorted((spell for spell in valid["free_cast_spells"]
                                          if spell["name"] not in prepared_names), key=lambda spell: spell["level"])),
                              ("准备法术（按环阶）", valid["prepared_spells"])):
            if spells:
                lines += [f"## {title}", ""]
                for spell in spells:
                    free_spell = spell if title == "无消耗法术" else free_by_name.get(spell["name"])
                    uses = (("；无限次免费施放" if free_spell.get("uses_max") == "at_will" else
                             f"；免费施放剩余 {free_spell['uses_remaining']}/{free_spell['uses_max']}，{free_spell['recharge']}")
                            if free_spell else "")
                    description = f"；{spell['description']}" if spell.get("description") else ""
                    lines.append(f"- {spell['level']}环 {spell['name']}：来源 {spell['source']}{uses}{description}")
                lines.append("")
    for title, key in (("戏法", "cantrips"), ("已知法术", "known_spells"),
                       ("准备法术", "prepared_spells")):
        if valid["ruleset"] == "5r" and key == "prepared_spells":
            continue
        spells = names(plan, key)
        if spells:
            lines += [f"## {title}", "", "、".join(spells), ""]
    return "\n".join(lines).rstrip() + "\n"


def inspect_saved(template: Path, destination: Path, changes: dict[str, dict[str, Any]],
                  expected_totals: dict[str, int] | None = None, strict_parts: bool = True,
                  plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check the file on disk, never in-memory patch state. Formula caches require native save."""
    with zipfile.ZipFile(template) as source, zipfile.ZipFile(destination) as saved:
        if saved.testzip() is not None:
            raise PlanError("保存后的 XLSX ZIP 结构损坏")
        if strict_parts and source.namelist() != saved.namelist():
            raise PlanError("保存后的页签/部件集合与模板不同，请人工确认原生保存影响")
        def tabs(archive: zipfile.ZipFile) -> list[tuple[str | None, str]]:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            return [(sheet.get("name"), sheet.get("state", "visible"))
                    for sheet in workbook.findall(f"{{{NS}}}sheets/{{{NS}}}sheet")]
        if tabs(source) != tabs(saved):
            raise PlanError("保存后的页签名称、顺序或隐藏状态与模板不同")
        strings: list[str] = []
        if "xl/sharedStrings.xml" in saved.namelist():
            root = ET.fromstring(saved.read("xl/sharedStrings.xml"))
            strings = ["".join(n.text or "" for n in si.iter(f"{{{NS}}}t"))
                       for si in root.findall(f"{{{NS}}}si")]
        roots = {name: ET.fromstring(saved.read(sheet_path(saved, name))) for name in changes}
        for name, cells in changes.items():
            present = {c.get("r"): c for c in roots[name].iter(f"{{{NS}}}c")}
            for ref, expected in cells.items():
                cell = present.get(ref)
                if cell is None:
                    raise PlanError(f"保存后缺少 {name}!{ref}")
                if cell.get("t") == "inlineStr":
                    actual = "".join(n.text or "" for n in cell.iter(f"{{{NS}}}t"))
                elif cell.get("t") == "s":
                    actual = strings[int(cell.findtext(f"{{{NS}}}v"))]
                else:
                    actual = cell.findtext(f"{{{NS}}}v")
                if isinstance(expected, bool):
                    okay = actual == ("1" if expected else "0")
                elif isinstance(expected, (int, float)):
                    okay = actual is not None and math.isclose(float(actual), expected, abs_tol=0.0001)
                else:
                    okay = actual == str(expected)
                if not okay:
                    raise PlanError(f"保存后 {name}!{ref} 不一致：预期 {expected}，实际 {actual}")
        result: dict[str, Any] = {"input_cells": "passed", "sheet_states": "preserved",
                                  "zip_parts": "preserved" if strict_parts else "not_compared_after_native_save",
                                  "read_only": not bool(destination.stat().st_mode & stat.S_IWRITE)}
        if plan is not None and plan["ruleset"] == "5r":
            main = {c.get("r"): c for c in roots["主要"].iter(f"{{{NS}}}c")}
            def cell_text(ref: str) -> str:
                cell = main.get(ref)
                if cell is None:
                    return ""
                if cell.get("t") == "inlineStr":
                    return "".join(n.text or "" for n in cell.iter(f"{{{NS}}}t"))
                if cell.get("t") == "s":
                    return strings[int(cell.findtext(f"{{{NS}}}v"))]
                return cell.findtext(f"{{{NS}}}v") or ""
            features = ordered_class_features(plan)
            actual_features = [cell_text(f"AX{row}") for row in range(17, 65)]
            if [x for x in actual_features if x] != [x["name"] for x in features]:
                raise PlanError("保存后的职业能力名称或数量与计划不一致")
            prepared_slots = ([f"Y{row}" for row in range(66, 74)] +
                              [f"AG{row}" for row in range(66, 75)] +
                              [f"AO{row}" for row in range(66, 75)])
            actual_prepared = [cell_text(ref) for ref in prepared_slots if cell_text(ref)]
            planned_prepared = sorted(plan["selected_prepared_spells"] + plan["always_prepared_spells"],
                                      key=lambda spell: spell["level"])
            if actual_prepared != [spell["name"] for spell in planned_prepared]:
                raise PlanError("保存后的准备法术顺序或数量与计划不一致")
            actual_free = [cell_text(f"Q{row}") for row in range(66, 74) if cell_text(f"Q{row}")]
            expected_free = [x["name"] for x in sorted(plan["free_cast_spells"], key=lambda x: x["level"])
                             if x["name"] not in set(actual_prepared)]
            if actual_free != expected_free or len(set(actual_free + actual_prepared)) != len(actual_free + actual_prepared):
                raise PlanError("保存后的无消耗法术有重复、顺序或数量错误")
            cantrip_slots = [f"{col}{row}" for row in range(77, 81) for col in ("Q", "Y")]
            actual_cantrips = [cell_text(ref) for ref in cantrip_slots if cell_text(ref)]
            if actual_cantrips != plan.get("cantrips", []):
                raise PlanError("保存后的戏法顺序或数量与计划不一致")
            result["feature_count"] = len(features)
            result["prepared_spell_count"] = len(actual_prepared)
            result["free_spell_display_count"] = len(actual_free)
            result["cantrip_count"] = len(actual_cantrips)
            if expected_totals is not None:
                for i, feature in enumerate(features):
                    ref = f"AW{17+i}"
                    if main.get(ref) is None or main[ref].find(f"{{{NS}}}f") is None:
                        raise PlanError(f"保存后职业等级公式 {ref} 丢失")
                    raw = cell_text(ref)
                    if not raw or not math.isclose(float(raw), feature["acquired_level"], abs_tol=0.001):
                        raise PlanError(f"保存后职业能力等级 AW{17+i} 未计算正确：{feature['name']}，预期 {feature['acquired_level']}，实际 {raw}")
                result["feature_levels"] = "passed"
                for tier, maximum in plan["level_audit"]["spell_slots_max"].items():
                    ref = f"H{71+int(tier)}"
                    if main.get(ref) is None or main[ref].find(f"{{{NS}}}f") is None:
                        raise PlanError(f"保存后法术位上限公式 {ref} 丢失")
                    raw = cell_text(ref)
                    if (raw == "" and maximum != 0) or (raw != "" and not math.isclose(float(raw), maximum, abs_tol=0.001)):
                        raise PlanError(f"保存后法术位上限 {ref} 未计算正确：预期 {maximum}，实际 {raw}")
                result["spell_slot_maxima"] = "passed"
                expected_saves = plan["level_audit"].get("expected_save_totals")
                if expected_saves is not None:
                    actual_saves = {}
                    for i, ability in enumerate(ABILITIES):
                        ref = f"T{13+i}"
                        if main.get(ref) is None or main[ref].find(f"{{{NS}}}f") is None:
                            raise PlanError(f"保存后豁免公式 {ref} 丢失")
                        raw = cell_text(ref)
                        if not raw or not math.isclose(float(raw), expected_saves[ability], abs_tol=0.001):
                            raise PlanError(f"保存后 {ability} 豁免未通过：预期 {expected_saves[ability]}，实际 {raw}")
                        actual_saves[ability] = float(raw)
                    result["calculated_saves"] = actual_saves
        if expected_totals is not None:
            main = {c.get("r"): c for c in roots["主要"].iter(f"{{{NS}}}c")}
            actuals = {}
            for key, ref in (("initiative", "D22"), ("ac", "D23"), ("hp", "V22")):
                cell = main.get(ref)
                if cell is None or cell.find(f"{{{NS}}}f") is None:
                    raise PlanError(f"保存后关键公式 {ref} 丢失")
                raw = cell.findtext(f"{{{NS}}}v") if cell is not None else None
                if raw is None or not math.isclose(float(raw), expected_totals[key], abs_tol=0.001):
                    raise PlanError(f"保存后 {ref} 计算值未通过：预期 {expected_totals[key]}，实际 {raw}；请原生重算后保存")
                actuals[key] = float(raw)
            result["calculated_totals"] = actuals
        return result


def fill(plan: dict[str, Any], destination: Path | None, template_override: Path | None) -> Path:
    valid = validate_plan(plan)
    ruleset = valid["ruleset"]
    template = template_override or ROOT / "assets" / f"dnd{ruleset}-blank.xlsx"
    if not template.is_file(): raise PlanError(f"缺少 {ruleset.upper()} 模板：{template}")
    if ruleset == "5e" and "5R" in template.name.upper():
        raise PlanError("禁止用 5R 模板生成 2014 年 5E 人物卡")
    if ruleset == "5r":
        validate_template_features(plan, template)
    changes = build_5r(plan, valid) if ruleset == "5r" else build_5e(plan, valid)
    destination = output_path(plan, destination)
    if destination.exists() and not (destination.stat().st_mode & stat.S_IWRITE):
        raise PlanError(f"目标人物卡为只读，未写入：{destination}")
    if ruleset == "5r":
        checklist = destination.with_name(destination.stem + "-等级核对.json")
        checklist.parent.mkdir(parents=True, exist_ok=True)
        checklist.write_text(json.dumps({"ruleset": ruleset, "class": valid["basic"]["class"],
                                         "subclass": valid["basic"].get("subclass", ""),
                                         "level": valid["level"], **valid["level_audit"]},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
    patch(template, destination, changes)
    structural = inspect_saved(template, destination, changes, plan=plan)
    reference = destination.with_name(destination.stem + "-战斗速查.md")
    reference.write_text(combat_reference(plan, valid), encoding="utf-8")
    report = {"ruleset": ruleset, "workbook": str(destination), "scores_final": valid["final"],
              "level": valid["level"], "skill_proficiencies": valid["skills"],
              "skill_expertise": valid["expertise"], "changed_cells": {k: len(v) for k,v in changes.items()},
              "combat_reference": str(reference), "native_recalculation": "pending",
              "saved_file_check": structural, "visual_review": "pending",
              "note": "请用 WPS 或 Excel 原生重算并核对核心页；兼容渲染结果不可覆盖原卡。"}
    if ruleset == "5r":
        report["level_checklist"] = str(checklist)
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
    parser.add_argument("--verify-only", action="store_true", help="原生重算并关闭后，重新读取保存文件核对输入与关键计算值")
    args = parser.parse_args()
    try:
        plan = json.loads(args.input.read_text(encoding="utf-8"))
        if args.verify_only:
            valid = validate_plan(plan)
            template = args.template or ROOT / "assets" / f"dnd{valid['ruleset']}-blank.xlsx"
            if valid["ruleset"] == "5r":
                validate_template_features(plan, template)
            changes = build_5r(plan, valid) if valid["ruleset"] == "5r" else build_5e(plan, valid)
            destination = output_path(plan, args.output)
            result = inspect_saved(template, destination, changes,
                                   valid["level_audit"]["expected_totals"] if valid["ruleset"] == "5r" else None,
                                   strict_parts=False, plan=plan)
            report_path = destination.with_suffix(".report.json")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["post_save_verification"] = result
            report["native_recalculation"] = "verified_totals" if valid["ruleset"] == "5r" else "inputs_only"
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(fill(plan, args.output, args.template))
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as error:
        raise SystemExit(f"建卡失败：{error}") from error


if __name__ == "__main__":
    main()
