"""读取冻结的版本化目录；公开元数据由同一内容源生成，不泄漏未开始题目。"""

import json
from copy import deepcopy
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[2] / 'content/game-catalog-v1.json').read_text(encoding='utf-8'))
POLICY = CATALOG['policy']
LEVELS = {level['level_id']: level for level in CATALOG['levels']}
PK_PUZZLES = CATALOG['pk_puzzles']
QUALIFICATIONS = ('mine-beginner-001', 'akari-001', 'sudoku-beginner-001')


def metadata(level):
    """开始前只提供尺寸和版本，不提供地图、数独给定盘及隐藏答案。"""
    result = {k: deepcopy(v) for k, v in level.items() if k != 'puzzle'}
    result.update({k: level['puzzle'][k] for k in ('rows', 'cols', 'checksum')})
    result['links'] = {'self': f"/api/v1/levels/{level['level_id']}", 'attempts': '/api/v1/attempts'}
    return result
