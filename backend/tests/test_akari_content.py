"""作用：先验证16关唯一解、逻辑可解、实际递进及冻结迁移一致性。"""
import json
from pathlib import Path
from unittest import TestCase
from backend.content_check import akari_solutions, checksum
from backend.app.services.game_rules import validate_akari
from backend.akari_content import solve

ROOT = Path(__file__).resolve().parents[1]


class AkariContent(TestCase):
    """独立搜索不依赖题库答案，逻辑工具不得以成功猜测冒充推理。"""

    def test_all_sixteen_unique_logical_and_progressive(self):
        """逐题核对唯一性、完整逻辑终盘、预定尺寸及审计记录。"""
        levels = json.loads((ROOT/'content/akari-catalog-v2.json').read_text(encoding='utf-8'))['levels']
        audit = json.loads((ROOT/'content/akari-audit-v2.json').read_text(encoding='utf-8'))
        self.assertEqual(len(levels), 16)
        self.assertEqual([v['puzzle']['rows'] for v in levels], [4,4,5,5,6,6,6,7,7,7,8,8,8,9,9,10])
        identities = set()
        scores = []
        for number, level in enumerate(levels):
            with self.subTest(level=level['level_id']):
                puzzle = level['puzzle']; grid = puzzle['map']
                answers = akari_solutions(grid)
                self.assertEqual(len(answers), 1)
                self.assertTrue(validate_akari(puzzle, answers[0]))
                logical = solve(grid)
                self.assertTrue(logical['solved'])
                self.assertEqual(logical['bulbs'], answers[0])
                if number >= 7:
                    self.assertFalse(solve(grid, 0 if number < 13 else 1)['solved'])
                record = audit[level['level_id']]
                self.assertEqual(logical, record)
                scores.append(record['score'])
                self.assertTrue(record['trace'])
                self.assertEqual(level['number'], number)
                self.assertEqual(level['name'], '入门' if number == 0 else f'第{number}关')
                self.assertNotIn(tuple(grid), identities); identities.add(tuple(grid))
                self.assertEqual(puzzle['checksum'], checksum({k:v for k,v in puzzle.items() if k!='checksum'}))
        self.assertEqual(scores, sorted(set(scores)))
        self.assertIn('0', ''.join(levels[2]['puzzle']['map']))
        self.assertIn('1', ''.join(levels[3]['puzzle']['map']))
        self.assertIn('2', ''.join(levels[4]['puzzle']['map']))
        self.assertTrue(set('34') & set(''.join(levels[5]['puzzle']['map'])))

    def test_logic_rejects_impossible_and_does_not_guess_ambiguous(self):
        """矛盾和多解盘不能被逻辑工具标为已解。"""
        self.assertFalse(solve(['.0'])['solved'])
        self.assertFalse(solve(['..', '..'])['solved'])

    def test_migration_matches_catalog_and_keeps_legacy(self):
        """迁移冻结完全相同的定义，不修改已发布的旧题目。"""
        catalog = json.loads((ROOT/'content/akari-catalog-v2.json').read_text(encoding='utf-8'))['levels']
        sql = (ROOT/'migrations/V13__publish_akari_levels.sql').read_text(encoding='utf-8')
        self.assertNotIn('UPDATE ', sql)
        for level in catalog:
            self.assertIn(json.dumps(level, ensure_ascii=False, separators=(',', ':')), sql)
