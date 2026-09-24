from __future__ import annotations

import importlib.util
import json
import random
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fill_investigator", ROOT / "scripts" / "fill_investigator.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
TEMPLATE = ROOT / "assets" / "COC七版规则空白卡20.6.1.xlsx"


class InvestigatorSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = MODULE.workbook_catalog(TEMPLATE)

    def test_catalog_is_compact_by_default(self) -> None:
        result = MODULE.compact_catalog(self.catalog, "记者", None, None)
        self.assertIn("occupation_match", result)
        self.assertIn("skill_slots", result)
        self.assertIn("weapon_summary", result)
        self.assertNotIn("occupations", result)
        self.assertNotIn("weapons", result)
        self.assertLess(len(json.dumps(result, ensure_ascii=False)), 6000)
        only = MODULE.compact_catalog(self.catalog, "记者", "occupation", None)
        self.assertEqual(set(only), {"template", "occupation_match", "open_occupation_slots"})
        no_occupation = MODULE.compact_catalog(self.catalog, None, None, None)
        self.assertIn("skill_summary", no_occupation)
        self.assertNotIn("skill_slots", no_occupation)

    def test_skill_aliases_and_weapon_candidates(self) -> None:
        for name in ("艺术及手艺（摄影）", "艺术手艺 : 摄影", "艺术和手艺(摄影)", "艺术与手艺 ( 摄影 )"):
            skill, specialty = MODULE.resolve_skill(name, self.catalog["skills"], set())
            self.assertTrue(skill["primary"].startswith("技艺"))
            self.assertEqual(specialty, "摄影")
        self.assertEqual(MODULE.weapon_candidates("小刀", self.catalog["weapons"])[0], "小型刀具(弹簧折叠刀等)")
        for name in ("小刀", "折刀", "随身刀", "野外小刀"):
            self.assertEqual(MODULE.resolve_named(name, self.catalog["weapons"], "武器")["name"], "小型刀具(弹簧折叠刀等)")
        for name in ("砍刀", "柴刀", "开山刀"):
            self.assertIn("大型刀具", MODULE.resolve_named(name, self.catalog["weapons"], "武器")["name"])

    def test_open_occupation_slots(self) -> None:
        accountant = MODULE.resolve_named("会计师", self.catalog["occupations"], "职业")
        self.assertEqual(sum(x["count"] for x in MODULE.open_occupation_slots(accountant["skills"])), 2)
        student = MODULE.resolve_named("学生/实习生", self.catalog["occupations"], "职业")
        self.assertEqual(sum(x["count"] for x in MODULE.open_occupation_slots(student["skills"])), 5)
        candidates = MODULE.compact_catalog(self.catalog, "学生", "occupation", None)["occupation_candidates"]
        self.assertGreaterEqual(len(candidates), 3)
        self.assertLess(len(json.dumps(candidates, ensure_ascii=False)), 6000)

    def test_final_characteristics_skip_age_rolls(self) -> None:
        attributes = {"STR": 55, "CON": 60, "SIZ": 65, "DEX": 70, "APP": 55,
                      "INT": 75, "POW": 60, "EDU": 70, "LUCK": 50}
        final, log = MODULE.age_adjust(attributes, 45, random.Random(1), None, True)
        self.assertEqual(final, attributes)
        self.assertEqual(log["education_rolls"], [])
        self.assertEqual(log["mov_penalty"], 1)

    def test_fill_and_inspect_preserve_chinese(self) -> None:
        plan = json.loads((ROOT / "tests" / "sample-plan.json").read_text(encoding="utf-8"))
        plan["characteristics_are_final"] = True
        plan.pop("age_adjustment", None)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            request = directory / "plan.json"
            output = directory / "card.xlsx"
            request.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            report = MODULE.fill(TEMPLATE, request, output)
            observed = MODULE.inspect_cells(output, "人物卡", ["E3", "E5", "AA61", "AG5"])
            self.assertEqual(observed["cells"]["E3"]["value"], "林默")
            self.assertEqual(observed["cells"]["E5"]["value"], "会计师")
            self.assertIn("圆框眼镜", observed["cells"]["AA61"]["value"])
            self.assertEqual(observed["cells"]["AG5"]["value"], 70)
            self.assertEqual(report["age_adjustment"]["mode"], "supplied_final")
            self.assertEqual(sum(x["occupation_choice"] for x in report["skills"]), 2)
            self.assertEqual(report["selected_open_skills"], ["心理学", "历史"])
            self.assertEqual(MODULE.inspect_cells(output, "人物卡", ["BA18", "BA19"])["cells"]["BA18"]["value"], "心理学")
            self.assertNotIn("P16", report["written_cells"])
            self.assertTrue(output.with_suffix(".report.json").exists())
            self.assertFalse(output.with_suffix(".xlsx.report.json").exists())

            plan["skills"][7].pop("occupation_choice")
            request.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.PlanError, "开放技能名额"):
                MODULE.fill(TEMPLATE, request, output)

    def test_directory_output_and_packed_items(self) -> None:
        plan = json.loads((ROOT / "tests" / "sample-plan.json").read_text(encoding="utf-8"))
        plan["items"].append({"name": "雨布、干粮", "location": "背包侧袋", "status": "随身"})
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            request = directory / "plan.json"
            request.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            report = MODULE.fill(TEMPLATE, request, directory / "cards")
            output = Path(report["output"])
            self.assertEqual(output.name, "林默-旧货账目.xlsx")
            self.assertTrue(output.with_suffix(".report.json").exists())
            cells = MODULE.inspect_cells(output, "人物卡", ["N79", "N80", "N81", "F79", "F80", "F81"])["cells"]
            self.assertEqual([cells[f"N{row}"]["value"] for row in (79, 80, 81)], ["换洗衣物", "雨布", "干粮"])
            self.assertEqual([cells[f"F{row}"]["value"] for row in (79, 80)], ["钢笔与采访本", "袖珍手电筒"])
            self.assertIsNone(cells["F81"]["value"] if cells["F81"] else None)


if __name__ == "__main__":
    unittest.main()
