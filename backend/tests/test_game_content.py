"""离线题库验收：独立约束搜索验证唯一解、规则和无死锁解锁。"""

from unittest import TestCase
from backend.app.services.game_rules import validate_akari, validate_sudoku, stars_for, xp_for
from backend.app.common.game_catalog import LEVELS, PK_PUZZLES, POLICY
from backend.content_check import akari_solutions, sudoku_solutions


class ContentTests(TestCase):
    """正式题目必须有唯一合法解，时间门槛与成长策略必须一致。"""

    def test_ten_campaign_and_independent_pk_puzzles(self):
        """十关及独立PK池都通过离线搜索，不能把随机棋盘直接发布。"""
        campaign = [v for v in LEVELS.values() if v['game_id'] == 'akari']
        self.assertEqual(len(campaign), 10)
        self.assertTrue(PK_PUZZLES)
        for level in campaign + PK_PUZZLES:
            with self.subTest(level=level['level_id']):
                answers = akari_solutions(level['puzzle']['map'])
                self.assertEqual(len(answers), 1)
                self.assertTrue(validate_akari(level['puzzle'], answers[0]))
                self.assertLess(level['t3_ms'], level['t2_ms'])
        self.assertFalse({v['puzzle']['checksum'] for v in campaign} &
                         {v['puzzle']['checksum'] for v in PK_PUZZLES})

    def test_beginner_sudoku_unique_and_clues_immutable(self):
        """初级数独只能靠单候选/唯一候选解出，终盘不许修改已给数字。"""
        puzzle = LEVELS['sudoku-beginner-001']['puzzle']
        answers = sudoku_solutions(puzzle['values'])
        self.assertEqual(len(answers), 1)
        self.assertTrue(validate_sudoku(puzzle, answers[0]))
        changed = answers[0][:]
        changed[0] = 1
        self.assertFalse(validate_sudoku(puzzle, changed))
        from backend.content_check import sudoku_singles
        self.assertEqual(sudoku_singles(puzzle['values']), answers[0])

    def test_millisecond_boundaries_and_milestone_equivalence(self):
        """在阈值毫秒边界判星；先一星再三星与直接三星经验一致。"""
        level = LEVELS['akari-001']
        self.assertEqual([stars_for(level, t) for t in
                          (level['t3_ms'], level['t3_ms'] + 1, level['t2_ms'], level['t2_ms'] + 1)], [3, 2, 2, 1])
        self.assertEqual(xp_for(0, 3), 80)
        self.assertEqual(xp_for(0, 1) + xp_for(1, 3), xp_for(0, 3))
        self.assertEqual(xp_for(3, 3), 0)
        for count, required in ((3, 2), (6, 3), (9, 4)):
            self.assertGreaterEqual(count * xp_for(0, 1), POLICY['level_xp'][required - 1])

    def test_invalid_akari_layouts(self):
        """拒绝重复、越界、墙上放灯、布尔坐标及互照。"""
        puzzle = {'map': ['.1.', '...', '.#.'], 'rows': 3, 'cols': 3}
        for bulbs in ([0, 0], [-1], [9], [1], [True], [0, 2]):
            self.assertFalse(validate_akari(puzzle, bulbs))

    def test_elapsed_time_has_no_float_rounding_at_millisecond_boundary(self):
        """1001ms不能因浮点乘法变成1000ms，微秒尾数向下取整。"""
        from datetime import datetime, timedelta
        from backend.app.services.game_rules import elapsed_ms
        start = datetime(2026, 1, 1)
        self.assertEqual(elapsed_ms(start, start+timedelta(milliseconds=1001)), 1001)
        self.assertEqual(elapsed_ms(start, start+timedelta(days=1, milliseconds=1001, microseconds=999)), 86401001)
