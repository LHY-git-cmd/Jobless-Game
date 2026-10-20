"""公共头像清单：前后端共用发布目录中的清单，进程内仅缓存少量编号，不读取图片内容。"""

from functools import lru_cache
import json
from pathlib import Path

DEFAULT_AVATAR_ID = 1
CATALOG_PATH = Path(__file__).resolve().parents[3] / "frontend/assets/avatars/v1/catalog.json"


@lru_cache(maxsize=1)
def avatar_ids() -> frozenset[int]:
    """首次使用时检查编号、固定站内路径和成品存在性；后续验证无需扫描硬盘。"""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    entries = catalog["avatars"]
    identifiers = frozenset(entry["id"] for entry in entries)
    if catalog["default_id"] != DEFAULT_AVATAR_ID or DEFAULT_AVATAR_ID not in identifiers or len(identifiers) != len(entries):
        raise ValueError("头像清单默认值或编号无效。")
    for entry in entries:
        number = entry["id"]
        if type(number) is not int or not 1 <= number <= 255 or entry["src"] != f"/assets/avatars/v1/{number:03}.webp":
            raise ValueError("头像清单路径无效。")
        if not (CATALOG_PATH.parent / f"{number:03}.webp").is_file():
            raise ValueError("头像成品缺失。")
    return identifiers
