import copy
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fill_character import PlanError, fill, validate_plan  # noqa: E402


BASE = {
    "kind": "dnd-character-plan", "schema_version": 1,
    "basic": {"name": "测试角色", "class": "战士", "species": "人类", "background": "士兵",
              "level": 1, "group_name": "单元测试", "story": "来自边境村落，受训后加入巡逻队。"},
    "scores_base": {"STR": 15, "DEX": 13, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8},
    "save_proficiencies": ["STR", "CON"], "skill_proficiencies": ["运动", "察觉"],
    "inventory": ["背包", "火把"], "weapons": ["长剑"], "languages": ["通用语"],
}


class CharacterFillTests(unittest.TestCase):
    def test_5r_preserves_template_structure_and_writes_origin(self):
        plan = copy.deepcopy(BASE)
        plan.update(ruleset="5r", background_bonus={"STR": 2, "CON": 1},
                    feats=[{"name": "起源专长测试", "type": "origin"}],
                    class_features=[{"name": "战斗风格", "description": "测试描述"}],
                    species_traits=[{"name": "人类特性", "description": "测试特性"}],
                    known_spells=["测试法术"], prepared_spells=["测试法术"], cantrips=["测试戏法"])
        with tempfile.TemporaryDirectory() as temporary:
            destination = fill(plan, Path(temporary), None)
            source = ROOT / "assets" / "dnd5r-blank.xlsx"
            with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination) as result:
                self.assertIsNone(result.testzip())
                self.assertEqual(original.namelist(), result.namelist())
                self.assertEqual(original.read("xl/worksheets/sheet3.xml"), result.read("xl/worksheets/sheet3.xml"))
            wb = openpyxl.load_workbook(destination, read_only=True)
            self.assertEqual(wb["主要"]["E3"].value, "测试角色")
            self.assertEqual(wb["主要"]["K13"].value, 2)
            self.assertEqual(wb["主要"]["K15"].value, 1)
            self.assertEqual(wb["主要"]["B41"].value, "O")
            self.assertEqual(wb["起源"]["S17"].value, plan["basic"]["story"])
            self.assertEqual(wb["主要"]["AX17"].value, "战斗风格")
            self.assertEqual(wb["主要"]["BT6"].value, "人类特性")
            self.assertEqual(wb["主要"]["Q66"].value, "测试法术")
            self.assertEqual(wb["主要"]["Q77"].value, "测试戏法")
            self.assertEqual(wb["法术书"]["X3"].value, "测试法术")
            self.assertEqual(wb["主要"]["BF7"].data_type, "f")
            source_wb = openpyxl.load_workbook(source, read_only=True)
            self.assertEqual(wb.sheetnames, source_wb.sheetnames)
            source_wb.close()
            wb.close()

    def test_5e_has_distinct_racial_bonus_fields(self):
        plan = copy.deepcopy(BASE)
        plan.update(ruleset="5e", racial_bonus={"STR": 1})
        plan["basic"].update(hit_die=10, armor_type="重甲", armor="锁子甲", speed="30尺",
                             background_feature="军旅身份")
        with tempfile.TemporaryDirectory() as temporary:
            destination = fill(plan, Path(temporary), None)
            with zipfile.ZipFile(destination) as archive:
                self.assertIsNone(archive.testzip())
            wb = openpyxl.load_workbook(destination, read_only=True)
            sh = wb["主要"]
            self.assertEqual(sh["K14"].value, 1)
            self.assertEqual(sh["AW4"].value, 10)
            self.assertEqual(sh["A14"].value, True)
            self.assertEqual(sh["F14"].data_type, "f")
            self.assertEqual(wb["背景"]["U12"].value, "军旅身份")
            self.assertEqual(wb["背景"]["U18"].value, plan["basic"]["story"])
            self.assertEqual(len(wb.sheetnames), 19)
            wb.close()

    def test_rejects_mixed_edition_ability_bonus(self):
        plan = copy.deepcopy(BASE)
        plan.update(ruleset="5r", racial_bonus={"STR": 2},
                    background_bonus={"STR": 2, "CON": 1},
                    feats=[{"name": "起源专长测试", "type": "origin"}])
        with self.assertRaisesRegex(PlanError, "不使用 racial_bonus"):
            validate_plan(plan)

    def test_5e_features_spells_and_level_hp(self):
        plan = copy.deepcopy(BASE)
        plan.update(ruleset="5e", racial_bonus={"STR": 1},
                    class_features=[{"name": "战斗风格", "description": "测试描述"}],
                    species_traits=[{"name": "额外熟练", "description": "测试种族特性"}],
                    known_spells=["测试法术"])
        plan["basic"].update(level=4, hit_die=10, subclass="勇士")
        with tempfile.TemporaryDirectory() as temporary:
            destination = fill(plan, Path(temporary), None)
            wb = openpyxl.load_workbook(destination, read_only=True)
            sh = wb["主要"]
            self.assertEqual(sh["M29"].value, 36)
            self.assertEqual(sh["L32"].value, 4)
            self.assertEqual(sh["C90"].value, "子职：勇士")
            self.assertEqual(sh["C91"].value, "战斗风格")
            self.assertEqual(sh["Z90"].value, "额外熟练")
            self.assertEqual(sh["C72"].value, "测试法术")
            self.assertEqual(sh["B70"].value, "已知法术")
            self.assertEqual(wb["背包"]["B5"].value, "背包")
            wb.close()


if __name__ == "__main__":
    unittest.main()
