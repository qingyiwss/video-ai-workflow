# -*- coding: utf-8 -*-
"""
停顿规整（pace）—— 只动静音，不动念出来的声音

依据：同领域开源实现（155 行，逐行对照移植）

为什么需要：
  配音模型每句开头结尾自带的静音长短不一（0 到 0.5 秒），句子里的逗号
  有时一口气念过去，有时又拖很久。稿子里写"这句后面停 0.4 秒"，实际听到的
  空白可能是 0.2 秒，也可能是 1 秒：有的段落连得太紧，有的又太松。

做三件事，都只动静音：
  1. 句首句尾：按音量找真正开口和收声的位置，前留 0.04 秒、后留 0.08 秒
  2. 句内标点：量出实际静音，短了在最深处补，长了从中间剪
  3. 补/剪多少，后面的字对齐时间跟着加减，不用重新对齐

用法：
  python pace.py <输入目录> <输出目录> [--report 报告.tsv]

输入目录需有：
  lines/L*.wav   每句音频
  lines/L*.json  {"say": 念法, "dur": 时长, ...}
  align/<key>.json  [{"t": 字, "s": 开始, "e": 结束}, ...]  （可选）

输出目录：
  lines/*.wav + *.json（含 head/tail/paced）
  align/*.json（修正后）
"""
import argparse
import os
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf

# ══════════════════════════════════════════════════════════════════
# 参数（全部照抄 同领域开源实现）
# ══════════════════════════════════════════════════════════════════

# 句内标点处的静音（秒）：最短，最长
RULE = {
    "，": (0.14, 0.32), ",": (0.14, 0.32),
    "、": (0.06, 0.18),
    "：": (0.16, 0.36),
    "；": (0.24, 0.42),
    "。": (0.30, 0.48), "？": (0.30, 0.48), "！": (0.30, 0.48),
}

HOP = 0.01          # 分析帧长
THR_IN = -36.0      # 句内停顿门槛：换气声听起来也是"停"，所以比响的部分低 36 dB 就算
THR = -40.0         # 比全句响的部分（95 分位）低 40 dB 以下算静音
FADE = 0.008        # 接口淡入淡出

WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9\.\-']*|[\u3400-\u9fff]")


def key(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def frames_db(y, sr):
    """逐 10ms 的 dB（相对 95 分位）"""
    h = int(HOP * sr)
    n = len(y) // h
    if n < 1:
        return np.array([-99.0])
    r = np.sqrt(np.mean(y[:n * h].reshape(n, h) ** 2, axis=1) + 1e-12)
    ref = np.percentile(r, 95) + 1e-9
    return 20 * np.log10(r / ref)


def nd_quiet(db, cs, ce):
    """静音段里最安静那一帧的位置"""
    i0 = int(cs / HOP)
    i1 = max(i0 + 1, int(np.ceil(ce / HOP)))
    if i1 <= len(db):
        return (i0 + int(np.argmin(db[i0:i1]))) * HOP + HOP / 2
    return (cs + ce) / 2


def silent_run(db, t0, t1, thr=THR, bridge=8):
    """t0..t1 之间最长的一段静音：(开始秒, 结束秒)；没有静音返回音量最低那一帧（长度 0）

    ⚠️ bridge：把时长 < bridge 帧（默认 8 帧 = 80ms）的「有声缝隙」合并回静音。
    为什么：换气声、齿音只有 -30dB 左右，单看会判成「有声」，
    把一个 550ms 的真停顿切成 420ms + 100ms 两段。
    「说话」应该按「有没有在念字」算，不是按「有没有任何响声」。
    """
    i0, i1 = max(0, int(t0 / HOP)), min(len(db), int(np.ceil(t1 / HOP)))
    if i1 <= i0:
        return (t0, t0)
    seg = (db[i0:i1] < thr).copy()

    # 合并短有声缝隙
    if bridge > 0:
        k = 0
        n = len(seg)
        while k < n:
            if not seg[k]:                       # 有声
                j = k
                while j < n and not seg[j]:
                    j += 1
                if (j - k) < bridge:             # 太短，当静音
                    seg[k:j] = True
                k = j
            else:
                k += 1

    best, cur, bs = (0, 0), 0, 0
    for k, s in enumerate(seg):
        if s:
            if cur == 0:
                bs = k
            cur += 1
            if cur > best[1] - best[0]:
                best = (bs, k + 1)
        else:
            cur = 0
    if best[1] > best[0]:
        return ((i0 + best[0]) * HOP, (i0 + best[1]) * HOP)
    m = i0 + int(np.argmin(db[i0:i1]))
    return (m * HOP + HOP / 2, m * HOP + HOP / 2)


def fade_join(y, cut_s, cut_e, insert, sr):
    """把 y 的 [cut_s, cut_e) 换成 insert 长度的静音，接口做短淡入淡出避免咔哒"""
    a_, b_ = int(cut_s * sr), int(cut_e * sr)
    f = int(FADE * sr)
    left, right = y[:a_].copy(), y[b_:].copy()
    if len(left) > f:
        left[-f:] *= np.linspace(1, 0, f)
    if len(right) > f:
        right[:f] *= np.linspace(0, 1, f)
    return np.concatenate([left, np.zeros(int(round(insert * sr)), np.float32), right])


def process_one(wav_path, meta_path, align_path, out_dir, head=0.04, tail=0.08):
    """处理一句，返回 (补长次数, 剪短次数, 行记录)"""
    d = json.loads(Path(meta_path).read_text("utf-8"))
    y, sr = sf.read(str(wav_path), dtype="float32")
    if y.ndim > 1:
        y = y[:, 0]
    al = json.loads(Path(align_path).read_text("utf-8")) if Path(align_path).exists() else []
    say = d.get("say", "")

    db = frames_db(y, sr)
    edits = []
    rows = []

    # ─── 句内标点 ───
    us = [(m.group(0), m.start(), m.end()) for m in WORD.finditer(say)]
    times = [None] * len(us)
    j = 0
    for q, (u, _, _) in enumerate(us):
        for jj in range(j, min(j + 4, len(al))):
            if str(al[jj].get("t", "")).lower().strip() == u.lower():
                times[q] = jj
                j = jj + 1
                break

    # ⭐⭐⭐ 按「全句扫所有长静音」处理，不依赖逐字
    # 为什么：对齐器会把某段静音算进某个字（实测「了」标成 1.14 秒），
    # 逐字检查会漏或重复。直接扫整句的所有长静音更可靠。
    #
    # 规矩：
    #   · 句首/句尾的静音不剪（交给 head/tail 处理）
    #   · 句中的长静音，按最近的那个标点定上限
    #   · 没标点的位置，上限 MAX_INNER = 0.25 秒
    MAX_INNER = 0.25
    dur_all = len(y) / sr
    # 找出该句所有「标点位置」，用于判断某个静音该按哪个上限
    punct_pts = []      # [(时间, 标点字符)]
    for q in range(len(us) - 1):
        bt = say[us[q][2]:us[q + 1][1]].strip()
        pp = next((ch for ch in bt if ch in RULE), None)
        if pp and times[q] is not None and times[q + 1] is not None:
            mid = (al[times[q]]["e"] + al[times[q + 1]]["s"]) / 2
            punct_pts.append((mid, pp))

    # 扫描整句：把静音按「>= 0.28 秒」切出来（0.28 是句号下限附近）
    scan_thr = 0.28
    step = HOP
    sil_flags = (db < THR_IN)
    # 合并短杂音
    k2 = 0
    while k2 < len(sil_flags):
        if not sil_flags[k2]:
            j2 = k2
            while j2 < len(sil_flags) and not sil_flags[j2]:
                j2 += 1
            if (j2 - k2) < 8:
                sil_flags[k2:j2] = True
            k2 = j2
        else:
            k2 += 1

    runs = []
    k3 = 0
    while k3 < len(sil_flags):
        if sil_flags[k3]:
            j3 = k3
            while j3 < len(sil_flags) and sil_flags[j3]:
                j3 += 1
            if (j3 - k3) * step >= scan_thr:
                runs.append((k3 * step, j3 * step))
            k3 = j3
        else:
            k3 += 1

    seen_inner = []
    for cs2, ce2 in runs:
        # 句首不管（head 会处理）；句尾要管（可能是 align 没算的尾巴）
        if cs2 < 0.10:
            continue
        # 句尾的长静音：剪到 tail 长度
        if ce2 > dur_all - 0.10:
            inner = ce2 - cs2
            if inner > 0.20:
                cut = inner - 0.08      # 留 0.08 给 tail
                c0_ = nd_quiet(db, cs2, ce2)
                edits.append((c0_, c0_ + cut, 0.0, inner, "尾"))
            continue
        # 这个静音该按什么上限？
        near_p = min(punct_pts, key=lambda x: abs(x[0] - (cs2 + ce2) / 2), default=None)
        if near_p and abs(near_p[0] - (cs2 + ce2) / 2) < 0.60:
            lo_, hi_ = RULE[near_p[1]]
            cap, tag_ = hi_, near_p[1]
        else:
            cap, tag_ = MAX_INNER, "内"
        inner = ce2 - cs2
        if inner <= cap + 0.04:
            continue
        def _ov(a1, b1, a2, b2):
            return (min(b1, b2) - max(a1, a2)) > 0.5 * min(b1 - a1, b2 - a2)
        if any(_ov(cs2, ce2, x, y2) for x, y2 in seen_inner):
            continue
        seen_inner.append((cs2, ce2))

        cut = inner - cap
        c0_ = nd_quiet(db, cs2, ce2)
        # ⚠️ 剪的范围必须在静音段内：[c0_, c0_+cut] ⊆ [cs2, ce2]
        #    否则会把后面「有声的字」剪掉（实测把「是切屏」整段剪没了）
        c0_ = max(cs2, min(c0_, ce2 - cut))
        # 再确认这段真的是静音（允许 ±1 帧误差）
        i_a, i_b = int(c0_ / HOP), int(np.ceil((c0_ + cut) / HOP))
        if i_a < 0 or i_b > len(db):
            continue
        if (db[i_a:i_b] > THR_IN).sum() > 2:
            # 这段里有响声，不能剪，改到最安静的位置
            best_k = i_a + int(np.argmin(db[i_a:i_b])) - (i_b - i_a) // 2
            c0_ = max(cs2, min(best_k * HOP, ce2 - cut))
        edits.append((c0_, c0_ + cut, 0.0, inner, tag_))

    for q in range(len(us) - 1):
        between = say[us[q][2]:us[q + 1][1]].strip()
        # ⚠️ 不能只看第一个字符：稿子里 `*定了个算法*，` 中间的 `法→关` 之间是 `*，`
        #    首字符是星号 → 被静默跳过。必须在这一小段里「找有没有标点」。
        p = next((ch for ch in between if ch in RULE), None)
        if p is None or times[q] is None or times[q + 1] is None:
            continue
        lo, hi = RULE[p]
        e0, s1 = al[times[q]]["e"], al[times[q + 1]]["s"]

        # align 会在字尾多算静音（实测「到」标到 2.88s，实际 2.46s 就收声了）。
        # 所以区间要往两边放开，让 silent_run 自己找最长的静音段。
        # 区间：从上一字结束前 0.40s 到下一字开始后 0.40s（足够覆盖 align 误差）
        cs, ce = silent_run(db, max(0, e0 - 0.40), s1 + 0.40, thr=THR_IN)
        sil = ce - cs
        # 补和剪都落在最安静那一帧附近，换气声尽量不被切开
        quiet = nd_quiet(db, cs, ce)
        if sil < lo - 0.02:
            edits.append((quiet, quiet, lo - sil, sil, p))
        elif sil > hi + 0.02:
            cut = sil - hi
            c0_ = min(max(cs, quiet - cut / 2), ce - cut)
            edits.append((c0_, c0_ + cut, 0.0, sil, p))

    # 从后往前改，前面的位置不受影响
    shifts = []
    for cs, ce, ins, sil, p in sorted(edits, key=lambda x: -x[0]):
        y = fade_join(y, cs, ce, ins, sr)
        shifts.append((cs, ins - (ce - cs)))
        rows.append((Path(meta_path).stem, p, round(sil, 3), round(sil + ins - (ce - cs), 3)))

    def moved(t):
        return t + sum(dl for at, dl in shifts if t > at + 1e-4)

    al2 = [{**x, "s": round(moved(x["s"]), 3), "e": round(moved(x["e"]), 3)} for x in al]

    # 对齐器把标点处的静音算进下一个字 → 按实际静音修正（否则字幕先亮）
    db2 = frames_db(y, sr)
    for q in range(len(us) - 1):
        _bt = say[us[q][2]:us[q + 1][1]].strip()
        if not any(ch in RULE for ch in _bt) or times[q] is None or times[q + 1] is None:
            continue
        A, B = al2[times[q]], al2[times[q + 1]]
        cs, ce = silent_run(db2, min(A["e"], B["s"]) - 0.15, max(A["e"], B["s"]) + 0.15, thr=THR_IN)
        if ce - cs < 0.06:
            continue
        B["s"] = round(min(max(B["s"], ce - 0.02), B["e"] - 0.03), 3)
        A["e"] = round(max(min(A["e"], cs + 0.02), A["s"] + 0.03), 3)

    # ─── 句首句尾 ───
    db = frames_db(y, sr)
    loud = db > THR
    run = np.convolve(loud, np.ones(3), "same") >= 3   # 连续 3 帧都响才算开口，免被咔哒声骗
    on = np.nonzero(run)[0]
    off = np.nonzero(loud)[0]
    s_on = max(0, on[0] - 1) * HOP if len(on) else 0.0
    s_off = (off[-1] + 1) * HOP if len(off) else len(y) / sr
    c0 = max(0.0, s_on - head)
    c1 = min(len(y) / sr, s_off + tail)
    y = y[int(c0 * sr):int(c1 * sr)].copy()
    f = int(0.005 * sr)
    if f > 0 and len(y) > f:
        y[:f] *= np.linspace(0, 1, f)
    f = int(min(0.05, c1 - s_off) * sr)
    if f > 0 and len(y) > f:
        y[-f:] *= np.linspace(1, 0, f)
    al2 = [{"t": x["t"], "s": round(max(0, x["s"] - c0), 3), "e": round(max(0, x["e"] - c0), 3)} for x in al2]
    head_len = round(s_on - c0, 3)
    tail_len = round(c1 - s_off, 3)

    # 第一个字从真正开口算起；最后一个字同理
    if al2:
        dbt = frames_db(y, sr)
        run32 = np.nonzero(np.convolve(dbt > THR_IN, np.ones(3), "same") >= 3)[0]
        on32 = max(0, run32[0] - 1) * HOP if len(run32) else head_len
        al2[0]["s"] = round(on32 if abs(al2[0]["s"] - on32) > 0.04 else max(al2[0]["s"], head_len), 3)
        al2[0]["s"] = round(min(al2[0]["s"], al2[0]["e"] - 0.03), 3)
        al2[-1]["e"] = round(min(al2[-1]["e"], len(y) / sr - tail_len), 3)

    # ─── 写出 ───
    out_wav = out_dir / "lines" / Path(meta_path).with_suffix(".wav").name
    sf.write(str(out_wav), y, sr, subtype="PCM_16")
    d2 = {**d, "dur": round(len(y) / sr, 3), "head": head_len, "tail": tail_len, "paced": len(edits)}
    (out_dir / "lines" / Path(meta_path).name).write_text(
        json.dumps(d2, ensure_ascii=False), "utf-8")
    if al:
        (out_dir / "align" / Path(align_path).name).write_text(
            json.dumps(al2, ensure_ascii=False), "utf-8")

    if os.environ.get("PACE_DEBUG"):
        import sys as _s
        print(f"[DBG {Path(meta_path).stem}] edits={len(edits)} rows={len(rows)}",
              file=_s.stderr)
        for r in rows:
            print(f"    row: {r}", file=_s.stderr)

    n_short = sum(1 for r in rows if r[3] > r[2])
    n_long = len(rows) - n_short
    return n_short, n_long, rows


def main():
    ap = argparse.ArgumentParser(description="停顿规整：只动静音")
    ap.add_argument("src", help="输入目录（含 lines/ 和 align/）")
    ap.add_argument("dst", help="输出目录")
    ap.add_argument("--report", default="", help="写一份 tsv 报告")
    ap.add_argument("--head", type=float, default=0.04, help="句首保留静音（秒），默认 0.04")
    ap.add_argument("--tail", type=float, default=0.08, help="句尾保留静音（秒），默认 0.08")
    a = ap.parse_args()

    SRC, DST = Path(a.src), Path(a.dst)
    for sub in ("lines", "align"):
        (DST / sub).mkdir(parents=True, exist_ok=True)

    metas = sorted((SRC / "lines").glob("L*.json"))
    if not metas:
        print(f"✗ {SRC}/lines 下没有 L*.json")
        return 1

    all_rows = []
    total_short = total_long = 0
    n = 0
    for meta in metas:
        d = json.loads(meta.read_text("utf-8"))
        k = key(d.get("say", ""))
        wav = meta.with_suffix(".wav")
        if not wav.exists():
            print(f"  ⚠ 缺 {wav.name}")
            continue
        alp = SRC / "align" / f"{k}.json"
        ns, nl, rows = process_one(wav, meta, alp, DST, a.head, a.tail)
        total_short += ns
        total_long += nl
        all_rows.extend(rows)
        n += 1

    # 清掉多余的旧文件
    have = {m.name for m in (SRC / "lines").glob("L*.*")}
    for m in (DST / "lines").glob("L*.*"):
        if m.name not in have:
            m.unlink()

    if a.report:
        with open(a.report, "w", encoding="utf-8-sig") as fo:
            fo.write("句\t标点\t原来静音\t改后静音\n")
            for r in all_rows:
                fo.write("\t".join(map(str, r)) + "\n")

    print(f"{n} 句；句内停顿补长 {total_short} 处，剪短 {total_long} 处")
    if all_rows:
        saved = sum(abs(r[3] - r[2]) for r in all_rows)
        print(f"  静音总变化 {saved:.2f} 秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
