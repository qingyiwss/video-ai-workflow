# -*- coding: utf-8 -*-
"""
字幕和配音对不对得上 —— 拿真实音频量，不看代码

依据：同领域开源字幕检查实现（103 行，逐行对照移植）

为什么要量：
  字幕时间来自对齐表，可对齐表在句首常常不准（把句首静音算进第一个字），
  配音模型每句前后的静音也长短不一，结果字幕会比声音早出现、字比声音先亮。

量什么（都和音频里实际开口、收声比，音量比全片响的部分低 32 dB 以下算没声音）：
  1. 出现：字幕出现时刻 - 它第一个字实际开口。**建议 -0.15 到 0 秒**
  2. 逐字变亮：每条第一个字，对齐表开始 - 实际开口。**±0.08 秒以内**
  3. 停留：字幕消失 - 最后一个字收声。太短来不及读，太长压到下一句空白
  4. 太短的字幕：显示不到 0.8 秒

用法：
  python caption_check.py timeline.json narration.wav [--show -0.1] [--hold 0.7] [--maxc 16]

--show / --hold / --maxc 必须和画面里字幕组件的设置一致。
"""
import argparse
import json
import re

import numpy as np
import soundfile as sf

BREAK = set("，。？！；：、,.?!;:")


def width(cs):
    """字符宽度：英文/数字算 0.55，标点算 0，汉字算 1"""
    w = 0.0
    for c in cs:
        ch = c["c"] if isinstance(c, dict) else c
        if ch in BREAK:
            continue
        w += 0.55 if re.match(r"[A-Za-z0-9 .\-']", ch) else 1
    return w


def build_chunks(T, maxc):
    """按字幕组件的切分规则，把 cap[] 切成一条条字幕

    规矩（工作流 5.14）：
      1. **按标点切** —— 标点处是天然断点
      2. 相邻短段能合并就合并（合并后 <= maxc）
      3. 只有单个标点段自己就超过 maxc，才硬切

    ⚠️ 之前实现成「一律按 16 字硬切」，会把「这事没那么简单眼睛和耳朵不是一个」
       切成 16 字 + 「速度」2 字 0.34 秒 —— 观众根本来不及看。
    """
    chunks = []
    for l in T["lines"]:
        if not l.get("real", True):
            continue
        if not l.get("cap"):
            continue

        # ① 按标点切成 phrases（标点留在段尾，用来算断点）
        phrases, cur = [], []
        for c in l["cap"]:
            cur.append(c)
            if c["c"] in BREAK:
                phrases.append(cur)
                cur = []
        if cur:
            phrases.append(cur)

        # ② 贪心合并：能塞进 maxc 就合，塞不下就起新条
        acc = []

        def flush():
            nonlocal acc
            real = [c for c in acc if c["c"] not in BREAK]
            if real:
                chunks.append({"i": l.get("i", l.get("tag", "?")),
                               "chars": real})
            acc = []

        for p_ in phrases:
            w = width(p_)
            if width(acc) + w <= maxc:
                acc = acc + p_                 # 合得下，继续合
                continue
            flush()                            # 合不下，先把前面的收掉
            if w <= maxc:
                acc = p_                       # 这一段自己放得下
            else:
                # ③ 单段超长：按 width 硬切（不是按元素个数）
                cur2 = []
                for c in p_:
                    if width(cur2) + width([c]) > maxc and cur2:
                        acc = cur2
                        flush()
                        cur2 = []
                    cur2.append(c)
                if cur2:
                    acc = cur2
                    flush()
        flush()

    # ④ 尾条太短就并进上一条（≤4 字且上一条有空间）
    merged = []
    for c in chunks:
        if merged and len(c["chars"]) <= 4:
            prev = merged[-1]
            if width([{"c": x["c"]} for x in prev["chars"]] +
                     [{"c": x["c"]} for x in c["chars"]]) <= maxc + 2:
                prev["chars"] = prev["chars"] + c["chars"]
                continue
        merged.append(c)
    return merged


def main():
    ap = argparse.ArgumentParser(description="字幕和配音对不对得上")
    ap.add_argument("timeline")
    ap.add_argument("wav")
    ap.add_argument("--show", type=float, default=-0.1, help="字幕比第一个字早多少秒出现（负数提前），默认 -0.1")
    ap.add_argument("--hold", type=float, default=0.7, help="最后一个字念完后最多再停留多少秒，默认 0.7")
    ap.add_argument("--maxc", type=int, default=16, help="字幕每行最多几个字，默认 16")
    a = ap.parse_args()

    T = json.loads(open(a.timeline, encoding="utf-8").read())
    y, sr = sf.read(a.wav, dtype="float32", always_2d=True)
    y = y.mean(1)

    HOP = 0.01
    h = int(HOP * sr)
    n = len(y) // h
    if n < 1:
        print("✗ 音频太短")
        return 1
    r = np.sqrt(np.mean(y[:n * h].reshape(n, h) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(r / np.percentile(r, 95))
    loud = np.convolve(db > -32, np.ones(3), "same") >= 2

    chunks = build_chunks(T, a.maxc)
    if not chunks:
        print("✗ timeline 里没有可用的 cap[]")
        return 1

    # 算每条的出现/消失时刻
    for k, c in enumerate(chunks):
        if not c["chars"]:
            continue
        c["show"] = c["chars"][0]["s"] + a.show
        c["hide"] = c["chars"][-1]["e"] + a.hold

    # 和字幕组件一致：停顿很短时上一条等最后字念完再换，新一条最晚在开口前 0.02 秒
    for k in range(1, len(chunks)):
        prev, cur = chunks[k - 1], chunks[k]
        if not prev["chars"] or not cur["chars"]:
            continue
        if prev["chars"][-1]["e"] + 0.03 > cur["show"]:
            cur["show"] = min(prev["chars"][-1]["e"] + 0.03, cur["chars"][0]["s"] - 0.02)

    for c, d in zip(chunks, chunks[1:]):
        if not c["chars"] or not d["chars"]:
            continue
        c["hide"] = min(c["hide"], d["show"])
        if d["show"] - c["hide"] < 0.25:
            c["hide"] = d["show"]   # 两条之间空不到 0.25 秒：不闪空，直接接上

    def onset_near(t, back=0.25, fwd=0.25):
        """t 附近实际开口的时刻：从 t-back 往后找第一段持续有声"""
        i0, i1 = max(0, int((t - back) / HOP)), min(n, int((t + fwd) / HOP))
        k = i0
        while k < i1 and loud[k]:
            k += 1
        while k < i1 and not loud[k]:
            k += 1
        return k * HOP if k < i1 else None

    def offset_near(t, back=0.25, fwd=0.3):
        """t 附近实际收声的时刻：从 t+fwd 往回找最后一段有声"""
        i0, i1 = max(0, int((t - back) / HOP)), min(n, int((t + fwd) / HOP))
        k = i1 - 1
        while k > i0 and not loud[k]:
            k -= 1
        return (k + 1) * HOP if k > i0 else None

    show_d, hold_d, short, light = [], [], [], []
    for k, c in enumerate(chunks):
        if not c["chars"]:
            continue
        first = c["chars"][0]
        on = onset_near(first["s"])
        if on is not None:
            show_d.append((round(c["show"] - on, 3), c["i"],
                           "".join(x["c"] for x in c["chars"])[:8]))
        nxt = chunks[k + 1]["chars"][0]["s"] if k + 1 < len(chunks) and chunks[k + 1]["chars"] \
            else c["chars"][-1]["e"] + 1
        off = offset_near(c["chars"][-1]["e"],
                          fwd=max(0.02, min(0.3, nxt - 0.03 - c["chars"][-1]["e"])))
        if off is not None:
            hold_d.append((round(c["hide"] - off, 3), c["i"]))
        dur = c["hide"] - c["show"]
        if dur < 0.8:
            short.append((c["i"], "".join(x["c"] for x in c["chars"]), round(dur, 2)))
        on2 = onset_near(first["s"], back=0.15, fwd=0.15)
        if on2 is not None:
            light.append(first["s"] - on2)

    # ─── 报告 ───
    print(f"字幕 {len(chunks)} 条")
    ok = True

    if show_d:
        sd = np.array([x[0] for x in show_d])
        early = int((sd < -0.25).sum())
        late = int((sd > 0.02).sum())
        print(f"  出现 - 开口：中位 {np.median(sd):+.2f}s  "
              f"p10 {np.percentile(sd, 10):+.2f}  p90 {np.percentile(sd, 90):+.2f}")
        print(f"    早于 0.25 秒：{early} 条   晚于开口：{late} 条")
        if early or late:
            ok = False

    if light:
        ld = np.array(light)
        bad = int((np.abs(ld) > 0.08).sum())
        print(f"  逐字变亮（首个字）：中位 {np.median(ld):+.3f}s   |偏差|>0.08：{bad} 条")
        if bad:
            ok = False

    if hold_d:
        hd = np.array([x[0] for x in hold_d])
        cut = int((hd < 0).sum())
        print(f"  消失 - 收声：中位 {np.median(hd):+.2f}s  p10 {np.percentile(hd, 10):+.2f}")
        print(f"    收声前就消失：{cut} 条")
        if cut:
            ok = False
            print("    ", sorted([x for x in hold_d if x[0] < 0])[:10])

    print(f"  显示不到 0.8 秒：{len(short)} 条")
    if short:
        print("    ", short[:10])

    bad5 = sorted(show_d, key=lambda x: x[0])[:5] + sorted(show_d, key=lambda x: -x[0])[:5]
    if bad5:
        print(f"  出现时机最偏的：{bad5}")

    print("\n" + ("✓ 通过" if ok else "✗ 有项目未通过（先跑 pace 停顿规整）"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
