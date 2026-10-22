"""作用：先验证数独题库唯一性、推理分级及错误候选排除反例。"""
import json
from pathlib import Path
from unittest import TestCase
from backend.sudoku_content import solve, solutions, grade, verify_trace, canonical

ROOT = Path(__file__).resolve().parents[1]


class SudokuContent(TestCase):
    """离线搜索与逻辑求解分别验证，不能以答案或回溯代替技巧证明。"""

    def test_invalid_and_ambiguous(self):
        """无解、多解、错误尺寸及非法给定数不得作为唯一题发布。"""
        self.assertEqual(solutions([1,1]+[0]*14, 4), [])
        self.assertEqual(len(solutions([0]*16, 4)), 2)
        self.assertRaises(ValueError, solutions, [0]*15, 4)
        self.assertRaises(ValueError, solutions, [True]+[0]*15, 4)

    def test_published_unique_and_real_difficulty(self):
        """四档各三题，逐题验证低档停滞、完整推理合法及题目不互为变换。"""
        catalog = json.loads((ROOT/'content/sudoku-catalog-v2.json').read_text(encoding='utf-8'))['levels']
        audit = json.loads((ROOT/'content/sudoku-audit-v2.json').read_text(encoding='utf-8'))
        self.assertEqual(len(catalog), 13)
        identities = set()
        chains = 0
        for level in catalog:
            puzzle = level['puzzle']; size = puzzle['rows']; values = puzzle['values']
            answers = solutions(values, size)
            self.assertEqual(len(answers), 1, level['level_id'])
            record = audit[level['level_id']]
            result = solve(values, size, 4)
            self.assertEqual(result['values'], answers[0])
            self.assertTrue(verify_trace(values, size, record['trace']))
            if size == 9:
                self.assertEqual(grade(values), level['difficulty'])
                identity = canonical(values)
                self.assertNotIn(identity, identities); identities.add(identity)
                chains += any(v['technique'] == 'coloring' for v in record['trace'])
        self.assertGreaterEqual(chains, 1)

    def test_forged_trace_is_rejected(self):
        """伪造的填数或把真实答案从候选中删掉必须被审计拒绝。"""
        values = [1,0,0,4,0,4,1,0,0,1,4,0,4,0,0,1]
        self.assertFalse(verify_trace(values, 4, [{'technique':'single','place':[1,1]}]))
        self.assertFalse(verify_trace(values, 4, [{'technique':'pair','remove':[[1,2]]}]))
