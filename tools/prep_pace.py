# -*- coding: utf-8 -*-
"""
把项目目录转成 pace.py 要的输入格式

为什么需要：
  pace.py 要的是 kazi 老格式（lines/L0001.wav + L0001.json + align/<sha1>.json），
  而 gen_voice.py 输出的是 lines/<段>_<序>.wav。
  格式不通，直接传会报「没有 L*.json」。

用法：
  python tools/prep_pace.py <项目目录>
  python tools/prep_pace.py <项目目录> --out pace-in

产出：
  <项目>/pace-in/
  ├── lines/
  │   ├── L0001.wav
  │   └── L0001.json    {"say": "...", "dur": 3.2, "tag": "01_01"}
  └── align/
      └── <sha1:16>.json   [{"t":"字","s":0.0,"e":0.18}, ...]

之后跑：
  python tools/pace.py pace-in pace-out --report pace.tsv
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import wave
import contextlib
from pathlib import Path

# pace.py 里用的同一个正则（必须一致，否则 align 文件名对不上）
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9\.\-']*|[\u3400-\u9fff]")


def key(s):
    """pace.py 的 key() —— sha1(去标点的 say)[:16]"""
    return hashlib.sha1("".join(WORD.findall(s)).encode("utf-8")).hexdigest()[:16]


def dur(p):
    with contextlib.closing(wave.open(str(p), "rb")) as w:
        return w.getnframes() / w.getframerate()


def main():
    ap = argparse.ArgumentParser(description="转成 pace 输入格式")
    ap.add_argument("base", help="项目目录（含 lines/ selection.json）")
    ap.add_argument("--out", default="pace-in", help="输出目录名")
    ap.add_argument("--timeline", default="timeline.json",
                    help="对齐结果（有就一起转 align/）")
    a = ap.parse_args()

    BASE = Path(a.base).resolve()
    SRC = BASE / a.out

    sel_p = BASE / "selection.json"
    if not sel_p.exists():
        print(f"✗ 找不到 {sel_p}")
        print("  先跑 gen_voice.py")
        return 1

    sel = json.loads(sel_p.read_text(encoding="utf-8"))
    if isinstance(sel, dict):
        sel = sel.get("lines") or []

    LINES = SRC / "lines"
    ALIGN = SRC / "align"
    if SRC.exists():
        shutil.rmtree(SRC)
    LINES.mkdir(parents=True)
    ALIGN.mkdir(parents=True)

    # timeline（可选，用来生成 align/*.json）
    tl = None
    tp = BASE / a.timeline
    if tp.exists():
        try:
            tl = json.loads(tp.read_text(encoding="utf-8"))
        except Exception:
            tl = None

    n_wav = n_align = 0
    for i, s in enumerate(sel, 1):
        tag = s.get("tag") or f"{s.get('sec','00')}_{i:02d}"
        src = BASE / "lines" / f"{tag}.wav"
        if not src.exists():
            print(f"  ⚠ 缺 {tag}.wav")
            continue

        # ① 复制音频
        dst = LINES / f"L{i:04d}.wav"
        shutil.copy2(src, dst)
        n_wav += 1

        # ② 写 meta
        say = (s.get("text") or "").replace("*", "")
        meta = {"say": say, "dur": round(dur(dst), 3), "tag": tag}
        (LINES / f"L{i:04d}.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")

        # ③ align（从 timeline 的 words 转）
        if tl:
            line = next((x for x in tl.get("lines", []) if x.get("tag") == tag), None)
            if line and line.get("words"):
                st = line["start"]
                words = [{"t": w["u"],
                          "s": round(w["s"] - st, 3),
                          "e": round(w["e"] - st, 3)}
                         for w in line["words"]]
                (ALIGN / f"{key(say)}.json").write_text(
                    json.dumps(words, ensure_ascii=False), encoding="utf-8")
                n_align += 1

    print(f"✓ {SRC}")
    print(f"  lines/  {n_wav} 句")
    print(f"  align/  {n_align} 个{'（没 timeline.json 就为空，不影响跑）' if n_align==0 else ''}")
    print(f"\n下一步：")
    print(f"  python tools/pace.py \"{SRC}\" \"{BASE/'pace-out'}\" --report \"{BASE/'pace.tsv'}\"")

    if n_align == 0 and not tl:
        print(f"\n  ℹ️ 没找到 {a.timeline}，align/ 是空的。")
        print(f"     可以先跑 align.py 再执行本脚本，字级时间会更准。")
        print(f"     不过 pace 只剪静音，没有 align 也能工作。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
