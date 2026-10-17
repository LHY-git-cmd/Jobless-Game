"""将用户提供的扫雷九宫格素材切成实际棋盘使用的 WebP 格子，不修改原图。

在项目任意目录运行本脚本即可重新生成 frontend/assets/minesweeper/。
需要 Pillow。原图只包含数字 1、2、3，其余数字由前端文字补齐。
"""

from pathlib import Path

from PIL import Image


def extract_tiles():
    """按原图中三行三列的格子边界切图，保留原有灰色底和立体边缘。"""
    source_dir = Path(__file__).resolve().parent
    output_dir = source_dir.parents[1] / "frontend" / "assets" / "minesweeper"
    output_dir.mkdir(parents=True, exist_ok=True)
    # 每格 272px；排除整张图外围的蓝色背景与圆角装饰。
    tiles = {
        "flag": (104, 104, 376, 376),
        "number-3": (376, 104, 648, 376),
        "mine": (648, 104, 920, 376),
        "number-1": (104, 376, 376, 648),
        "exploded": (376, 376, 648, 648),
        "covered": (648, 376, 920, 648),
        "number-2": (376, 648, 648, 920),
    }
    with Image.open(source_dir / "扫雷.jpeg") as image:
        for name, bounds in tiles.items():
            tile = image.crop(bounds).resize((96, 96), Image.Resampling.LANCZOS)
            tile.save(output_dir / f"{name}.webp", "WEBP", lossless=True, method=6)
        # 原图没有翻开的空格：取数字格中不含图案的灰色底，生成同色空格。
        blank = image.crop((400, 120, 420, 140)).resize((96, 96))
        blank.save(output_dir / "open.webp", "WEBP", lossless=True, method=6)
    print(f"已生成 {len(tiles) + 1} 张扫雷格子素材：{output_dir}")


if __name__ == "__main__":
    extract_tiles()
