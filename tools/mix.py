# -*- coding: utf-8 -*-
"""
混音：旁白 + BGM（让位）+ 音效

依据：工作流 6.1（BGM 让位）+ 6.3（音效四层）+ 6.5（响度标准）
     参数全部来自 mix_v6.py 的实测值

BGM 让位逻辑（这是核心）：
  1. 先算旁白的包络（每 10ms 的 RMS）
  2. 说话时 BGM 压到 人声 -15 dB
  3. 空当（>=0.55 秒）抬高 +6 dB（即 人声 -9 dB）
  4. 提前 0.20 秒开始压（人声起之前就压好）
  5. 平滑核 0.06 秒
  6. 1-4kHz 压 2-2.5 dB（给人声让路）
  7. 停乐 2-4 次（在章节卡上）

音效：
  · 落点峰值 = 人声峰值 - 5.5 dB（⚠️ 按峰值不按 RMS）
  · 时长拉伸 ×1.6
  · 高通提亮 diff(s)*0.72 + s*0.28
  · 5ms 入 / 45ms 出

用法：
  python mix.py <项目目录> [--bgm 路径] [--no-sfx]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000
from paths import P
FF = P.ffmpeg

# ── 工作流 6.1 的参数 ──
DUCK_DB = -15.0       # 说话时（相对人声）
RISE_DB = +6.0        # 空当抬高
RISE_TH = 0.55        # 空当最短时长（秒）
PRE_DUCK = 0.20       # 提前压
SMOOTH = 0.06         # 平滑核
EQ_HZ = [1000, 2500, 4000]
EQ_DB = -2.2

# ── 工作流 6.3 的参数 ──
# ⚠️ 工作流写「落点峰值 = 人声峰值 - 5.5 dB」，但那隐含前提是「人声峰值约 -4.5」
#    （v6 的混音已经归一化过）。旁白峰值是 0 dB 时，-5.5 会和人声一样响。
#    改成按「人声 RMS - 8 dB」校准，不受峰值影响。实测残差落在 -10 dB 以内。
SFX_RMS_BELOW = -8.0  # 落点（相对人声 RMS）
SFX_STRETCH = 1.6
FADE_IN, FADE_OUT = 0.005, 0.045

from paths import P
KENNEY = Path(P.sfx) if P.sfx else Path("assets/sfx")


def load(path, sr=SR):
    y, s0 = sf.read(str(path), dtype="float32", always_2d=True)
    y = y.mean(1)
    if s0 != sr:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(s0, sr)
        y = resample_poly(y, sr // g, s0 // g).astype(np.float32)
    return y


def rms_db(y):
    r = float(np.sqrt(np.mean(y ** 2) + 1e-12))
    return 20 * np.log10(max(r, 1e-9))


def peak_db(y):
    return 20 * np.log10(max(float(np.abs(y).max()), 1e-9))


def envelope(y, sr=SR, win=0.01):
    """每 10ms 的 RMS（dB，相对峰值）"""
    h = int(win * sr)
    n = len(y) // h
    if n < 1:
        return np.array([-99.0])
    r = np.sqrt(np.mean(y[:n * h].reshape(n, h) ** 2, axis=1) + 1e-12)
    ref = np.percentile(r, 95) + 1e-9
    return 20 * np.log10(r / ref), win


def duck_curve(y_voice, sr=SR):
    """算 BGM 该压多少（dB 包络）"""
    env, hop = envelope(y_voice, sr)
    n = len(env)
    voiced = env > -22.0          # 说话

    # 找空当（连续不说话的段，>= RISE_TH）
    gain = np.full(n, DUCK_DB, np.float32)   # 默认说话
    i = 0
    gaps = []
    while i < n:
        if not voiced[i]:
            j = i
            while j < n and not voiced[j]:
                j += 1
            if (j - i) * hop >= RISE_TH:
                gaps.append((i, j))
                gain[i:j] = DUCK_DB + RISE_DB
            i = j
        else:
            i += 1

    # 提前 PRE_DUCK 秒压下去
    pre = int(PRE_DUCK / hop)
    voiced_shift = np.zeros(n, bool)
    for k in range(n):
        if voiced[k]:
            a = max(0, k - pre)
            voiced_shift[a:k + 1] = True
    gain[voiced_shift] = np.minimum(gain[voiced_shift], DUCK_DB)

    # 平滑（高斯核）
    k = max(1, int(SMOOTH / hop))
    ker = np.hanning(k * 2 + 1)
    ker /= ker.sum()
    gain = np.convolve(gain, ker, "same")

    return gain, hop, gaps, n


def apply_duck(bgm, gain, hop, n_target, sr=SR):
    """把 gain 包络应用到 BGM（逐样本线性插值）"""
    n_bgm = len(bgm)
    t = np.arange(n_bgm) / sr
    idx = t / hop
    g = np.interp(idx, np.arange(len(gain)), gain, left=gain[0], right=gain[-1])
    return bgm * (10 ** (g / 20.0)).astype(np.float32)


def load_sfx(kind):
    """从 Kenney 库里找一类音效，随机挑一个"""
    import random
    cands = sorted(KENNEY.glob(f"{kind}_*.ogg"))
    if not cands:
        cands = sorted(KENNEY.glob(f"{kind}*.ogg"))
    if not cands:
        return None
    return random.choice(cands)


def process_sfx(path, target_peak_db, sr=SR):
    """载入音效：拉伸 ×1.6 + 高通提亮 + 归一化到目标峰值"""
    y = load(path, sr)
    # 拉伸
    if SFX_STRETCH != 1.0:
        n_out = int(len(y) * SFX_STRETCH)
        x_old = np.linspace(0, 1, len(y))
        x_new = np.linspace(0, 1, n_out)
        y = np.interp(x_new, x_old, y).astype(np.float32)
    # 高通提亮：diff(s)*0.72 + s*0.28
    d = np.diff(y, prepend=y[0])
    y = (d * 0.72 + y * 0.28).astype(np.float32)
    # 峰值归一化
    cur = peak_db(y)
    y = y * (10 ** ((target_peak_db - cur) / 20.0))
    # 淡入淡出
    fi, fo = int(FADE_IN * sr), int(FADE_OUT * sr)
    if len(y) > fi:
        y[:fi] *= np.linspace(0, 1, fi)
    if len(y) > fo:
        y[-fo:] *= np.linspace(1, 0, fo)
    return y


def main():
    ap = argparse.ArgumentParser(description="混音：旁白 + BGM 让位 + 音效")
    ap.add_argument("base")
    ap.add_argument("--bgm", default="")
    ap.add_argument("--no-sfx", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--dump-sfx", default="", help="把音效层单独存出来（验证用）")
    ap.add_argument("--dump-bgm", default="", help="把 BGM 层单独存出来（验证用）")
    a = ap.parse_args()

    B = Path(a.base)
    out = Path(a.out) if a.out else B / "mix.wav"

    # ── 旁白 ──
    voice = load(B / "narration.wav")
    v_peak = peak_db(voice)
    v_rms = rms_db(voice)
    total = len(voice) / SR
    print(f"旁白  {total:.2f}s  RMS {v_rms:.1f} dB  峰 {v_peak:.1f} dB")

    mix = voice.copy()

    # ── 音效（先加，再和 BGM 一起让位）──
    if not a.no_sfx:
        tl_path = B / "timeline.json"
        kwfile = B / "kw-sfx.json"
        if tl_path.exists() and kwfile.exists():
            tl = json.loads(tl_path.read_text("utf-8"))
            kwsfx = json.loads(kwfile.read_text("utf-8"))
            target_pk = v_rms + SFX_RMS_BELOW
            n_ok = n_miss = 0
            for k in tl.get("keywords", []):
                kind = kwsfx.get(k["word"])
                if not kind:
                    n_miss += 1
                    continue
                src = load_sfx(kind)
                if src is None:
                    print(f"  ⚠ 没找到音效 {kind}")
                    n_miss += 1
                    continue
                s = process_sfx(src, target_pk)
                # 落点放在关键词开始那一刻（hit = t - 3 帧）
                at = max(0.0, k["t"] - 3 / 60)
                i0 = int(at * SR)
                i1 = min(len(mix), i0 + len(s))
                if i1 > i0:
                    mix[i0:i1] += s[:i1 - i0]
                    n_ok += 1
            print(f"音效  落点 {n_ok} 个（目标峰值 {target_pk:.1f} dB）"
                  + (f"  缺 {n_miss}" if n_miss else ""))
        else:
            print("音效  跳过（没有 timeline.json 或 kw-sfx.json）")

    # ── BGM 让位 ──
    if a.bgm:
        bgm = load(a.bgm)
        # 循环到足够长
        reps = int(np.ceil(len(voice) / len(bgm))) + 1
        bgm = np.tile(bgm, reps)[:len(voice)]
        print(f"BGM   {a.bgm.name if hasattr(a.bgm,'name') else a.bgm}  {len(bgm)/SR:.1f}s")

        gain, hop, gaps, n = duck_curve(voice)
        print(f"  让位：说话 {DUCK_DB:.0f} dB / 空当 {DUCK_DB+RISE_DB:.0f} dB")
        print(f"  空当 {len(gaps)} 处：" +
              "、".join(f"{g[0]*hop:.1f}s({(g[1]-g[0])*hop:.2f}s)" for g in gaps[:6]))

        # 基准增益：把 BGM 抬到与人声同 RMS
        b_rms = rms_db(bgm)
        base_gain = 10 ** ((v_rms - b_rms) / 20.0)
        bgm2 = apply_duck(bgm, gain, hop, len(voice))
        bgm2 = bgm2 * base_gain

        # 简单 1-4k 压（用 FFT 做一次）
        S = np.fft.rfft(bgm2)
        f = np.fft.rfftfreq(len(bgm2), 1 / SR)
        mask = np.ones_like(f)
        for hz in EQ_HZ:
            band = (f > hz * 0.7) & (f < hz * 1.4)
            mask[band] = 10 ** (EQ_DB / 20.0)
        bgm2 = np.fft.irfft(S * mask, len(bgm2)).astype(np.float32)

        mix = mix + bgm2
    else:
        print("BGM   跳过（没指定 --bgm）")

    # ── 可选：把各层单独存出来（验证用）──
    if a.dump_sfx:
        only = mix - voice
        if a.bgm:
            only = only - bgm2
        sf.write(str(a.dump_sfx), only, SR, subtype="PCM_16")
        print(f"音效层 → {a.dump_sfx}  峰 {peak_db(only):.1f} dB")
    if a.dump_bgm and a.bgm:
        sf.write(str(a.dump_bgm), bgm2, SR, subtype="PCM_16")
        print(f"BGM层  → {a.dump_bgm}  RMS {rms_db(bgm2):.1f} dB"
              f"  （人声 RMS {v_rms:.1f}，差 {rms_db(bgm2)-v_rms:+.1f}）")

    # ── 归一化到 -14 LUFS 附近（简单峰值保护）──
    pk = peak_db(mix)
    if pk > -1.5:
        mix = mix * (10 ** ((-1.5 - pk) / 20.0))
        print(f"峰值保护：{pk:.1f} → -1.5 dB")

    sf.write(str(out), mix, SR, subtype="PCM_16")
    print(f"\n→ {out}")
    print(f"  时长 {len(mix)/SR:.2f}s  峰 {peak_db(mix):.1f} dB  RMS {rms_db(mix):.1f} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
