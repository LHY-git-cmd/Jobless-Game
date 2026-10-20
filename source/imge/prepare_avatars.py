"""作用：在开发机将 25 张原始头像转为 128px WebP，生成共用清单，可选输出视觉检查联系表。

运行 python source/imge/prepare_avatars.py --preview；仅需开发机 Pillow，不修改原始 PNG。
内容变更时应发布新版本目录，避免服务器七天静态缓存继续使用旧图片。
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent / "avatar"
OUTPUT = ROOT / "frontend/assets/avatars/v1"


def prepare(preview=False):
    """先检查素材齐全，再按稳定编号生成成品；中心裁剪保留接近方形的原图主体。"""
    paths = [SOURCE / f"{number:03}.png" for number in range(1, 26)]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise ValueError("头像素材缺失：" + ", ".join(missing))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGB", (5 * 160, 5 * 180), "#17384d") if preview else None
    entries = []
    for number, path in enumerate(paths, 1):
        with Image.open(path) as original:
            image = ImageOps.fit(ImageOps.exif_transpose(original).convert("RGBA"), (128, 128), method=Image.Resampling.LANCZOS)
            image.save(OUTPUT / f"{number:03}.webp", format="WEBP", quality=82, method=6)
            if sheet is not None:
                x, y = ((number - 1) % 5) * 160 + 16, ((number - 1) // 5) * 180 + 12
                sheet.paste(image, (x, y), image)
                ImageDraw.Draw(sheet).text((x + 50, y + 138), f"{number:03}", fill="#f0d49a")
        entries.append({"id": number, "src": f"/assets/avatars/v1/{number:03}.webp"})
    (OUTPUT / "catalog.json").write_text(json.dumps({"default_id": 1, "avatars": entries}, indent=2) + "\n", encoding="utf-8")
    if sheet is not None:
        destination = ROOT / "artifacts/frontend/avatar-contact-sheet.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(destination)
    total = sum((OUTPUT / f"{number:03}.webp").stat().st_size for number in range(1, 26))
    print(f"生成 {len(entries)} 张 128x128 WebP，图片合计 {total} 字节（{total / 1024:.1f} KiB）。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="另存联系表至 artifacts/frontend，供视觉检查")
    prepare(parser.parse_args().preview)
