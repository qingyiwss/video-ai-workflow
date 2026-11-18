import sys
# -*- coding: utf-8 -*-
"""
重配语调怪异的两句，按 f0 跨度筛选
  · 「但那个像我的感觉」原 f0 -62 Hz（像叹气）
  · 「早很多」原 f0 +23 Hz（句尾上翘）

期望：
  · 「但那个像我的感觉」→ 跨度 -30 ~ -10 Hz
  · 「早很多」→ 跨度 -25 ~ -5 Hz（降调收尾）
"""
from paths import P
import subprocess
import re
import os
import tempfile
import wave
import json
import numpy as np
from pathlib import Path

CPP = P.audiocpp
MODEL = P.model
REF = P.ref
REF_TEXT = "我最近在想一个问题为什么有些工具用起来很顺手有些用两次就放下了后来发现差别不在共同多少而在它有没有替你省掉那些真正凡人的步骤这点想明白以后我挑东西的标准就变了现在拿到一个新工具我第一反应不是马上打开试用而是先问自己它到底解决了我哪一个具体的问题"

FF = P.ffmpeg
MODEL_W = P.whisper
if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
    print("用法: python retake_tone.py <项目目录>")
    sys.exit(1)
BASE = Path(sys.argv[1]).resolve()
RETAKES = BASE / "retakes"
RETAKES.mkdir(exist_ok=True)

TARGETS = [
    # (tag, text, 期望跨度范围 min, max)
    ("09_49", "但那个像我的感觉。", -30, -8),
    ("11_59", "早很多。", -28, -4),
]

N_TAKES = 8


def tidy(s):
    return re.sub(r'[，。：；「」、？！*\s]', '', s)


def gen(text, out, seed):
    cmd = [CPP, "--task", "tts", "--family", "cosyvoice3",
           "--model", MODEL, "--backend", "vulkan", "--device", "0", "--threads", "12",
           "--text", text, "--voice-ref", REF, "--out", str(out),
           "--request-option", "template_name=zero_shot",
           "--request-option", f"reference_text={REF_TEXT}",
           "--request-option", f"seed={seed}", "--metrics"]
    subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return out.exists() and out.stat().st_size > 3000


def load(path, sr=16000):
    tmp = os.path.join(tempfile.gettempdir(), "rt_%d.wav" % np.random.randint(1e9))
    subprocess.run([FF, "-y", "-v", "error", "-i", str(path), "-ar", str(sr),
                    "-ac", "1", tmp], check=True, capture_output=True)
    with wave.open(tmp, "rb") as w:
        d = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)/32768.0
    os.remove(tmp)
    return d, sr


def f0_span(x, sr, win=512, hop=160):
    """返回 (中位, 首, 尾, 跨度, CV)"""
    vals = []
    for i in range(0, len(x)-win, hop):
        fr = x[i:i+win]
        if np.sqrt(np.mean(fr**2)) < 0.01:
            continue
        fr = fr - fr.mean()
        c = np.correlate(fr, fr, mode="full")[win-1:]
        lo, hi = sr//400, sr//60
        if hi >= len(c):
            continue
        seg = c[lo:hi]
        if len(seg) == 0 or seg.max() <= 0:
            continue
        pk = np.argmax(seg) + lo
        f = sr/pk if pk > 0 else 0
        if 60 < f < 400:
            vals.append(f)
    v = np.array(vals)
    if len(v) < 5:
        return None
    n = len(v)
    head = np.median(v[:max(1, n//5)])
    tail = np.median(v[-max(1, n//5):])
    return float(np.median(v)), float(head), float(tail), float(tail-head), float(v.std()/max(v.mean(), 1e-9))


def main():
    from faster_whisper import WhisperModel
    wm = WhisperModel(MODEL_W, device="cpu", compute_type="int8", cpu_threads=6)

    results = {}
    for tag, text, lo, hi in TARGETS:
        print(f"\n{'='*70}")
        print(f"{tag}  「{text}」  期望 f0 跨度 {lo} ~ {hi} Hz")
        print('='*70)

        target = tidy(text)
        cands = []
        for t in range(N_TAKES):
            wav = RETAKES / f"{tag}_t{t}.wav"
            if not wav.exists() or wav.stat().st_size < 3000:
                gen(text, wav, seed=3000 + t*173 + hash(tag) % 1000)
            if not wav.exists():
                continue
            x, sr = load(wav)
            rms = float(np.sqrt(np.mean(x**2)))
            pk = float(np.abs(x).max())
            rms_db = 20*np.log10(max(rms, 1e-9))
            pk_db = 20*np.log10(max(pk, 1e-9))
            if pk_db < -20 or rms_db < -35:
                print(f"  t{t}  静音（峰 {pk_db:.1f}dB）")
                continue

            # 吻合度
            segs, _ = wm.transcribe(x, language="zh", beam_size=5,
                                     condition_on_previous_text=False)
            heard = "".join(s.text for s in segs)
            h = tidy(heard)
            overlap = sum(1 for c in set(target) if c in h) / max(len(set(target)), 1)

            sp = f0_span(x, sr)
            if sp is None:
                continue
            med, head, tail, span, cv = sp

            # 评分：跨度落在期望范围中心最好；吻合度必须 ≥0.95
            mid = (lo + hi) / 2
            span_score = -abs(span - mid) / 20.0
            ok_overlap = overlap >= 0.95
            ok_span = lo <= span <= hi

            cands.append({
                "t": t, "path": str(wav), "dur": len(x)/sr,
                "heard": heard, "overlap": overlap,
                "med": med, "head": head, "tail": tail,
                "span": span, "cv": cv,
                "score": span_score if ok_overlap else -999,
                "ok_span": ok_span, "ok_overlap": ok_overlap,
            })
            mark = "✓" if (ok_span and ok_overlap) else ""
            print(f"  t{t}  {len(x)/sr:.2f}s  f0 中位{med:.0f} 跨度{span:+.0f}  "
                  f"CV{cv*100:.0f}%  吻合{overlap*100:.0f}%  {mark}")

        if not cands:
            print("  ✗ 无可用候选")
            continue

        # 优先：跨度达标 + 吻合度达标；其次按 score
        good = [c for c in cands if c["ok_span"] and c["ok_overlap"]]
        if good:
            good.sort(key=lambda x: abs(x["span"] - (lo+hi)/2))
            best = good[0]
        else:
            cands.sort(key=lambda x: -x["score"])
            best = cands[0]

        print(f"\n  → 选中 t{best['t']}  f0跨度 {best['span']:+.0f} Hz（期望 {lo}~{hi}）"
              f"  吻合 {best['overlap']*100:.0f}%")
        results[tag] = best

    (RETAKES / "selected.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {RETAKES/'selected.json'}")


if __name__ == "__main__":
    main()
