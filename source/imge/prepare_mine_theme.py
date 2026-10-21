"""作用：从用户指定的扫雷主题原图切出版本化WebP棋格与入口图，保留原图不覆盖旧素材。

在项目任意目录运行，需要Pillow；数字4～8使用同色底及前端文字补齐。
"""
from pathlib import Path
from PIL import Image


def prepare_theme():
    """906×862原图按实际三列三行边界裁切，避开外围蓝色与圆角装饰。"""
    source=Path(__file__).resolve().parent
    output=source.parents[1]/'frontend/assets/minesweeper/v2'
    output.mkdir(parents=True,exist_ok=True)
    # 边界包含每格本身的高光/阴影，保留用户素材的立体边缘。
    tiles={'flag':(56,53,317,311),'number-3':(317,53,576,311),'mine':(576,53,835,311),
           'number-1':(56,311,317,569),'exploded':(317,311,576,569),'covered':(576,311,835,569),
           'number-2':(317,569,576,829)}
    with Image.open(source/'minesweeper-theme.png') as image:
        image=image.convert('RGB')
        for name,bounds in tiles.items():
            image.crop(bounds).resize((96,96),Image.Resampling.LANCZOS).save(output/f'{name}.webp','WEBP',lossless=True,method=6)
        # 无数字的已揭格采用数字格内的同色灰底，不生成新的美术风格。
        Image.new('RGB',(96,96),image.getpixel((350,85))).save(output/'open.webp','WEBP',lossless=True,method=6)
        image.resize((256,244),Image.Resampling.LANCZOS).save(output/'theme.webp','WEBP',lossless=True,method=6)
    print('扫雷主题：9张版本化WebP已生成')


if __name__=='__main__':
    prepare_theme()
