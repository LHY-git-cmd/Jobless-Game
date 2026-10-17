"""从原始 FLAC 第一声爆炸裁出网页连锁爆炸音效，保留原文件。

依赖：pip install soundfile numpy scipy
执行：python source/audio/prepare_explosion.py
输出：1.4 秒、24kHz、单声道 PCM WAV，含 3ms 淡入和 250ms 淡出。
"""

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def prepare_explosion():
    """去除起始静音、后续重复爆炸和长尾，并预留声音叠加的音量空间。"""
    source = Path(__file__).resolve().parent
    samples, rate = sf.read(source / "爆炸声.flac", always_2d=True)
    # 波形中的第一声起爆约在 0.05 秒；1.445 秒后进入较长的低音量尾部。
    clip = samples[round(0.045 * rate):round(1.445 * rate)].mean(axis=1)
    clip *= 0.8 / max(float(np.abs(clip).max()), 1e-9)
    fade_in, fade_out = round(0.003 * rate), round(0.25 * rate)
    clip[:fade_in] *= np.linspace(0, 1, fade_in)
    clip[-fade_out:] *= np.linspace(1, 0, fade_out)
    clip = resample_poly(clip, 24000, rate)
    # 重采样可能产生瞬态过冲，写文件前再次限制峰值以免叠加时失真。
    clip *= min(1.0, 0.8 / max(float(np.abs(clip).max()), 1e-9))
    output = source.parents[1] / "frontend" / "assets" / "audio" / "explosion.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, clip, 24000, subtype="PCM_16")
    print(f"已裁剪：{len(clip) / 24000:.2f}s，{output.stat().st_size} bytes，{output}")


if __name__ == "__main__":
    prepare_explosion()
