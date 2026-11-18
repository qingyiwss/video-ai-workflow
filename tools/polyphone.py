# -*- coding: utf-8 -*-
"""
多音字检查（声学版）—— 用声母的频谱特征判断读音

依据：配音检查里的这段（原文）：
  「**声母不同的多音字，可以用声学比对来查。** 比如「卡」有 kǎ（卡字）和 qiǎ（卡住）
   两个读音，声母一个是 k、一个是 q，开头那几十毫秒的频谱差得很远。做法：把全片每个
   「卡」字开头那一小段的频谱特征算出来，再拿一批读音确定是 k 声母的字、一批确定是
   q 声母的字各算一份当参照，看每个「卡」离哪一组近。」

为什么不用 kazi 原版（Whisper logits 打分）：
  原版依赖 `mlx-whisper`（苹果芯片专用），且要**直接读 Whisper 的 token logits**。
  Windows 上的 `faster-whisper` 不暴露 logits（`generate_segments` 只吐文字）。

  实测确认：`initial_prompt` 换成不同的候选字，识别结果**完全一样** ——
  它是上下文提示，不影响声学判定。

  **所以改用 参考文档里提到的另一条路：声学比对。**

局限（kazi 原文）：
  「**声调不同、声母相同的（「数」shǔ 和 shù）这样分不出来，还得靠耳朵。**」
  → 本工具只查「声母不同」的多音字。声调差异不在范围内。

用法：
  python tools/polyphone.py timeline.json narration.wav --out polyphone
  python tools/polyphone.py timeline.json narration.wav --pair 卡:ka3,qia3

输出：
  <out>/report.tsv   每个多音字：第几句、上下文、声母特征、判给哪个读音、置信度
  <out>/flagged.wav  存疑的地方（置信度低或判给非预期读音），中间用提示音隔开
  <out>/flagged.txt  试听音频里每一处是什么
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

HAN = re.compile(r"[\u3400-\u9fff]")

# 声母 → 用来做参照的字（读音唯一、声母明确、日常常用）
# 只收「声母不同」就能区分的多音字
INITIAL_REFS = {
    "k": "看开可空苦口考快扩肯",
    "q": "去请前七千起气全且群",
    "z": "在走字总自早增最怎",
    "zh": "这中只真正张知道主站",
    "c": "从次才草村层参粗",
    "ch": "出长成吃车常场初程",
    "s": "三四是送色所死苏",
    "sh": "上说时手是水少山生",
    "j": "就家见几间叫机今结",
    "x": "下小想先学心西相信",
    "g": "个给过国感高工关",
    "h": "和会还后好回很活红",
    "l": "了来里老两理力量立",
    "n": "你那年能内南女难",
    "m": "们没面明么民美名母",
    "b": "不本把被别比百半",
    "p": "怕跑平片配品排盘",
    "d": "的大到得地对多点第",
    "t": "他太天同条头体提通",
    "f": "发分方反非放风法",
    "r": "人日然让如认热容",
    "y": "一有也又用要于样应",
    "w": "我为我问无外王往",
}

# 多音字 → (声母不同的两个读音, 对应的两个声母)
# 只收「声母不同」的；声调差异的不收（kazi 明说分不出来）
POLY_INITIAL = {
    "卡": (("ka3", "k"), ("qia3", "q")),
    "长": (("chang2", "ch"), ("zhang3", "zh")),
    "重": (("zhong4", "zh"), ("chong2", "ch")),
    "行": (("xing2", "x"),  ("hang2", "h")),
    "还": (("hai2", "h"),   ("huan2", "h")),   # 同声母，标注为不可查
    "差": (("cha4", "ch"),  ("chai1", "ch")),  # 同声母
    "调": (("diao4", "d"),  ("tiao2", "t")),
    "降": (("jiang4", "j"), ("xiang2", "x")),
    "处": (("chu4", "ch"),  ("chu3", "ch")),   # 同声母
    "种": (("zhong3", "zh"),("zhong4", "zh")), # 同声母
    "为": (("wei4", "w"),   ("wei2", "w")),    # 同声母
    "发": (("fa1", "f"),    ("fa4", "f")),     # 同声母
    "率": (("lv4", "l"),    ("shuai4", "sh")),
    "落": (("luo4", "l"),   ("la4", "l")),     # 同声母
    "没": (("mei2", "m"),   ("mo4", "m")),     # 同声母
    "弹": (("tan2", "t"),   ("dan4", "d")),
    "转": (("zhuan3", "zh"),("zhuan4", "zh")), # 同声母
    "看": (("kan4", "k"),   ("kan1", "k")),    # 同声母
    "相": (("xiang1", "x"), ("xiang4", "x")),  # 同声母
    "系": (("xi4", "x"),    ("ji4", "j")),
    "解": (("jie3", "j"),   ("xie4", "x")),
    "传": (("chuan2", "ch"),("zhuan4", "zh")),
    "尽": (("jin4", "j"),   ("jin3", "j")),    # 同声母
    "兴": (("xing1", "x"),  ("xing4", "x")),   # 同声母
    "将": (("jiang1", "j"), ("jiang4", "j")),  # 同声母
    "难": (("nan2", "n"),   ("nan4", "n")),    # 同声母
    "塞": (("sai1", "s"),   ("se4", "s")),     # 同声母
    "识": (("shi2", "sh"),  ("zhi4", "zh")),
    "铺": (("pu1", "p"),    ("pu4", "p")),     # 同声母
    "旋": (("xuan2", "x"),  ("xuan4", "x")),   # 同声母
    "折": (("zhe2", "zh"),  ("she2", "sh")),
    "横": (("heng2", "h"),  ("heng4", "h")),   # 同声母
    "划": (("hua2", "h"),   ("hua4", "h")),    # 同声母
    "会": (("hui4", "h"),   ("kuai4", "k")),
    "创": (("chuang4", "ch"),("chuang1", "ch")),# 同声母
    "恶": (("e4", ""),      ("wu4", "w")),
    "宿": (("su4", "s"),    ("xiu3", "x")),
    "冠": (("guan1", "g"),  ("guan4", "g")),   # 同声母
    "蒙": (("meng2", "m"),  ("meng3", "m")),   # 同声母
    "要": (("yao4", "y"),   ("yao1", "y")),    # 同声母
    "喝": (("he1", "h"),    ("he4", "h")),     # 同声母
    "盛": (("sheng4", "sh"),("cheng2", "ch")),
}

SR = 16000
WIN = int(0.045 * SR)   # 取开头 45ms（声母主要在这里）
N_MELS = 26
N_FFT = 512


def mel_filterbank(n_mels=N_MELS, n_fft=N_FFT, sr=SR, fmin=60, fmax=7000):
    """简单 mel 滤波器组"""
    def hz2mel(f):
        return 2595 * np.log10(1 + f / 700.0)

    def mel2hz(m):
        return 700 * (10 ** (m / 2595.0) - 1)

    mels = np.linspace(hz2mel(fmin), hz2mel(fmax), n_mels + 2)
    hz = mel2hz(mels)
    bins = np.floor((n_fft + 1) * hz / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for i in range(n_mels):
        l, c, r = bins[i], bins[i + 1], bins[i + 2]
        if c > l:
            fb[i, l:c] = (np.arange(l, c) - l) / (c - l)
        if r > c:
            fb[i, c:r] = (r - np.arange(c, r)) / (r - c)
    return fb


FB = mel_filterbank()


def onset_features(seg, sr=SR):
    """取这一小段开头 45ms 的 mel 谱，返回归一化后的向量"""
    if sr != SR:
        from math import gcd
        g = gcd(sr, SR)
        seg = resample_poly(seg, SR // g, sr // g).astype(np.float32)
    if len(seg) < WIN:
        seg = np.pad(seg, (0, WIN - len(seg)))
    # 找起点：段内最响的位置往前一点
    env = np.abs(seg)
    peak = int(np.argmax(np.convolve(env, np.ones(80) / 80, "same")))
    a = max(0, peak - int(0.01 * SR))
    w = seg[a:a + WIN]
    if len(w) < WIN:
        w = np.pad(w, (0, WIN - len(w)))
    w = w * np.hanning(WIN)
    spec = np.abs(np.fft.rfft(w, N_FFT)) ** 2
    mel = FB @ spec
    mel = np.log1p(mel)
    n = np.linalg.norm(mel)
    return mel / n if n > 1e-9 else mel


def build_refs(initial, wm_corpus, timeline, wav, sr=SR):
    """从本片里找该声母的参照字，算平均特征"""
    feats = []
    for L in timeline.get("lines", []):
        units = L.get("words") or []
        for k, u in enumerate(units):
            if u["u"] in wm_corpus:
                s0 = max(0, u["s"] - 0.02)
                s1 = u["e"] + 0.02
                seg = wav[int(s0 * sr):int(s1 * sr)]
                if len(seg) > WIN // 2:
                    feats.append(onset_features(seg, sr))
    if not feats:
        return None
    return np.mean(feats, axis=0)


def main():
    ap = argparse.ArgumentParser(description="多音字检查（声学版）")
    ap.add_argument("timeline")
    ap.add_argument("wav")
    ap.add_argument("--out", default="polyphone")
    ap.add_argument("--margin", type=float, default=0.04,
                    help="余弦距离差多少才判（默认 0.04）")
    ap.add_argument("--lines", default="")
    ap.add_argument("--expect", default="", help='JSON：{"往后数十句": {"数": "shu3"}}')
    args = ap.parse_args()

    tl = json.loads(Path(args.timeline).read_text("utf-8"))
    expect = json.loads(Path(args.expect).read_text("utf-8")) if args.expect else {}
    only = {int(x) for x in args.lines.split(",") if x.strip()}

    wav, sr = sf.read(args.wav, dtype="float32", always_2d=True)
    wav = wav.mean(1)
    if sr != SR:
        from math import gcd
        g = gcd(sr, SR)
        wav = resample_poly(wav, SR // g, sr // g).astype(np.float32)
        sr = SR

    # ─── 建参照：每个声母一组 ───
    print(" 建立参照（从本片找该声母的字）...")
    refs = {}
    for ini, chars in INITIAL_REFS.items():
        if len(ini) == 0:
            continue
        r = build_refs(ini, set(chars), tl, wav, sr)
        if r is not None:
            refs[ini] = r
    print(f" {len(refs)} 个声母有参照")

    # ─── 逐句找多音字 ───
    rows = []
    for L in tl.get("lines", []):
        units = L.get("words") or []
        if only and (L.get("i") not in only and L.get("tag") not in only):
            continue
        say = "".join(u["u"] for u in units)
        for k, u in enumerate(units):
            c = u["u"]
            if c not in POLY_INITIAL:
                continue
            (r1, i1), (r2, i2) = POLY_INITIAL[c]
            if not i1 or not i2 or i1 == i2:
                continue      # 同声母，本工具分不出来
            if i1 not in refs or i2 not in refs:
                continue
            s0 = max(0, u["s"] - 0.02)
            s1 = u["e"] + 0.02
            seg = wav[int(s0 * sr):int(s1 * sr)]
            if len(seg) < WIN // 2:
                continue
            f = onset_features(seg, sr)
            d1 = 1 - float(np.dot(f, refs[i1]))   # 余弦距离
            d2 = 1 - float(np.dot(f, refs[i2]))
            # 用户指定该念哪个
            want = r1
            for frag, fix in expect.items():
                if frag in say and c in fix:
                    want = fix[c]
            pred = r1 if d1 < d2 else r2
            margin = abs(d2 - d1)
            rows.append({
                "i": L.get("i", L.get("tag")), "t": round(u["s"], 2),
                "ctx": say[max(0, k - 3):k + 4], "ch": c,
                "want": want, "pred": pred, "margin": round(margin, 4),
                "d1": round(d1, 4), "d2": round(d2, 4),
                "r1": r1, "r2": r2, "s0": s0, "s1": s1,
            })
            flag = "" if pred == want else "  ⚠"
            print(f"  第 {rows[-1]['i']} 句 {rows[-1]['t']:>6.2f}s「{c}」"
                  f"想 {want} 判 {pred}  距离 {d1:.3f}/{d2:.3f} 差 {margin:.3f}{flag}")

    # ─── 输出 ───
    O = Path(args.out)
    O.mkdir(parents=True, exist_ok=True)

    with open(O / "report.tsv", "w", encoding="utf-8-sig") as f:
        f.write("句\t秒\t上下文\t字\t想读\t判给\t距离差\t声母1\t声母2\t距离1\t距离2\n")
        for r in rows:
            f.write(f"{r['i']}\t{r['t']}\t{r['ctx']}\t{r['ch']}\t{r['want']}\t{r['pred']}\t"
                    f"{r['margin']}\t{r['r1']}\t{r['r2']}\t{r['d1']}\t{r['d2']}\n")

    # 存疑：判给的不对，或者差距太小
    bad = [r for r in rows if r["pred"] != r["want"] and r["margin"] >= args.margin]
    unsure = [r for r in rows if r["margin"] < args.margin and r not in bad]

    beep = (0.15 * np.sin(2 * np.pi * 880 * np.arange(int(0.12 * sr)) / sr)).astype(np.float32)
    gap = np.zeros(int(0.25 * sr), np.float32)
    parts, notes = [], []
    for r in bad + unsure:
        a_, b_ = max(0, r["s0"] - 0.5), min(len(wav) / sr, r["s1"] + 0.5)
        parts += [beep, gap, wav[int(a_ * sr):int(b_ * sr)], gap]
        tag = "判错" if r in bad else "存疑"
        notes.append(f"[{tag}] 第 {r['i']} 句 {r['t']}s「{r['ctx']}」的「{r['ch']}」"
                     f"想读 {r['want']}，判给 {r['pred']}（距离差 {r['margin']:.3f}）")

    if parts:
        sf.write(str(O / "flagged.wav"), np.concatenate(parts), sr)
    (O / "flagged.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")

    print(f"\n查了 {len(rows)} 处（声母可分的多音字）")
    print(f"  判给非预期：{len(bad)} 处    差距不足：{len(unsure)} 处")
    for n in notes:
        print("  " + n)
    if not notes:
        print("  ✓ 没有发现问题")
    print(f"\n→ {O}/report.tsv")
    if parts:
        print(f"→ {O}/flagged.wav（听一遍）")

    print("\n⚠️ 本工具只查「声母不同」的多音字。")
    print("   声调不同的（数 shǔ / shù、还 hái / huán）分不出来，还得靠耳朵。")
    print("   kazi 原文：「没报出来」不等于「没读错」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
