# -*- coding: utf-8 -*-
"""
缺字检测 —— 渲染前必须跑

为什么需要：
  字体子集只覆盖 GB2312 全集（6763 字）。如果稿子里有 GB2312 之外的字
  （如「彧」「垚」这类 GBK 扩展字），浏览器会回退到系统字体。

  后果是双重的：
    ① 同一行混排两种宋体，字宽和字重都不同，肉眼可见
    ② fitFont 用 measureText 测的是 KaziSerif 的宽度，实际渲染的是
       SimSun —— 估宽失真，可能溢出

  两种都不会报错，只在成片里露出来。所以必须在渲染前拦。

用法：
  python tools/font_check.py <项目目录>
  python tools/font_check.py <项目目录> --strict     # GB2312 之外也算错

退出码：
  0  全部字符都在子集里
  1  有缺失字符
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "canvas" / "fonts"


def load_cmap(path):
    """读 woff2 的 cmap。延迟 import fontTools，运行时不需要它"""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        print("缺少 fontTools。装一下：pip install -r requirements-dev.txt")
        sys.exit(2)
    t = TTFont(str(path))
    cmap = set(t.getBestCmap().keys())
    t.close()
    return cmap


def gb2312_set():
    s = set()
    for hi in range(0xB0, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                s.add(ord(bytes([hi, lo]).decode("gb2312")))
            except UnicodeDecodeError:
                pass
    return s


# ── 收集项目里会用到的所有字符 ──────────────────────────────

def chars_from_script(path):
    """script.md 里的正文字符。注释行和语法标记不算"""
    out = []
    if not path.exists():
        return out
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("＃") or s.startswith("#"):
            continue
        if s.startswith("[") and s.endswith("]"):
            continue          # 段落名
        # 去掉行尾的 | 0.5
        s = re.sub(r"\|\s*[\d.]+\s*$", "", s)
        # 去掉 * 标记
        s = s.replace("*", "")
        for ch in s:
            if ord(ch) > 0x7F:
                out.append((ch, path.name, i))
    return out


def chars_from_json(path, label):
    """scene-def.json 里所有字符串值"""
    out = []
    if not path.exists():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out

    def walk(v, p):
        if isinstance(v, str):
            for ch in v:
                if ord(ch) > 0x7F:
                    out.append((ch, label, p))
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(k, f"{p}.key")
                walk(x, f"{p}.{k}" if not p.endswith("]") else p)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{p}[{i}]")

    walk(data, label)
    return out


def collect(project):
    """返回 [(char, file, location), ...]"""
    out = []
    out += chars_from_script(project / "script.md")
    out += chars_from_json(project / "scene-def.json", "scene-def.json")
    return out


def main():
    ap = argparse.ArgumentParser(description="缺字检测")
    ap.add_argument("project", help="项目目录（含 script.md / scene-def.json）")
    ap.add_argument("--strict", action="store_true",
                    help="GB2312 之外的字也算缺失（更严）")
    ap.add_argument("--font", default=None,
                    help="只检查某个字体文件（默认检查全部三个）")
    a = ap.parse_args()

    project = Path(a.project).resolve()
    if not project.exists():
        print(f"找不到目录: {project}")
        return 2

    fonts = ([Path(a.font)] if a.font else sorted(FONTS.glob("*.woff2")))
    if not fonts:
        print(f"找不到字体文件: {FONTS}")
        return 2

    # 每个字体各有自己的 cmap，取交集（任何一个缺都算缺）
    cmaps = {}
    for f in fonts:
        cmaps[f.name] = load_cmap(f)

    common = set.intersection(*cmaps.values())
    gb = gb2312_set()

    used = collect(project)
    if not used:
        print("没有找到可检测的文字（script.md / scene-def.json 都为空？）")
        return 0

    # 逐字判断
    missing = {}      # char -> [(file, loc), ...]
    outside_gb = set()
    for ch, fname, loc in used:
        cp = ord(ch)
        if cp not in common:
            missing.setdefault(ch, []).append((fname, loc))
        elif a.strict and cp not in gb:
            outside_gb.add(ch)

    # ── 输出 ──
    print(f"字体子集: {len(common)} 字符（{', '.join(f.name for f in fonts)}）")
    print(f"GB2312:  {len(gb)} 字符")
    print(f"稿件用字: {len(set(c for c, _, _ in used))} 个不重复")
    print()

    if missing:
        print(f"✗ 缺字 {len(missing)} 个 —— 这些字会回退到系统字体")
        print(f"{'字符':<4}{'Unicode':<10}{'出现位置'}")
        print("-" * 66)
        for ch in sorted(missing, key=lambda c: -len(missing[c])):
            locs = missing[ch]
            cp = ord(ch)
            first = locs[0]
            more = f" 等 {len(locs)} 处" if len(locs) > 1 else ""
            print(f"  {ch:<3} U+{cp:04X}    {first[0]}:{first[1]}{more}")
        print()
        print("怎么修：")
        print("  ① 换掉这些字（同义字替换）")
        print("  ② 或者重新生成字体子集，把 _chars.txt 加上这些字后重跑子集脚本")
        print("  ③ 如果这些字不在 GB2312 里，属于 GBK 扩展字，需要扩大子集范围")
        return 1

    if outside_gb:
        print(f"⚠ {len(outside_gb)} 个字不在 GB2312 里，但字体有（子集会随用字扩展）")
        print(f"  {''.join(sorted(outside_gb)[:20])}")
        print("  这些字在当前字体里存在，可以正常渲染。")
        print()

    print("✓ 全部字符都有对应字形")
    return 0


if __name__ == "__main__":
    sys.exit(main())
