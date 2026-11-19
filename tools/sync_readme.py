# -*- coding: utf-8 -*-
"""
从 demo/check.txt 同步实测数字到两版 README

为什么需要：
  README 里的「卡字率 / 响度 / 真峰值 / 分辨率 / 帧率」是手写的。
  三轮提交、动了三百多行 README，这张表一个字没改，数字早就过期了。
  两版 README 还互相不一致（英文版写理想值，中文版写旧片子值）。

  手写的数字一定会漂。让它自动生成。

用法：
  python tools/sync_readme.py              # 同步 demo/check.txt → 两版 README
  python tools/sync_readme.py --check      # 只检查是否一致，不改（CI 用）
  python tools/sync_readme.py --src x.txt  # 指定别的 check.txt

README 里用标记包住的区域会被替换：

  <!-- AUTO:metrics:start -->
  ... 自动生成，勿手改 ...
  <!-- AUTO:metrics:end -->

make_demo.py 结束时会自动调一次。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BEGIN = "<!-- AUTO:metrics:start -->"
END = "<!-- AUTO:metrics:end -->"


def parse_check(path):
    """从 check.txt 解析实测值"""
    if not path.exists():
        return None
    t = path.read_text(encoding="utf-8")
    out = {}

    # 分辨率 / 帧率 / 时长
    m = re.search(r"(\d+)x(\d+)\s+([\d.]+)fps\s+([\d.]+)s", t)
    if m:
        out["width"] = int(m.group(1))
        out["height"] = int(m.group(2))
        out["fps"] = float(m.group(3))
        out["duration"] = float(m.group(4))

    # 卡字率
    m = re.search(r"卡字率\s*(\d+)\s*/\s*(\d+)\s*=\s*([\d.]+)\s*%", t)
    if m:
        out["hits"] = int(m.group(1))
        out["total"] = int(m.group(2))
        out["rate"] = float(m.group(3))

    # 高出随机
    m = re.search(r"高出随机\s*\+?\s*([\d.]+)\s*%", t)
    if m:
        out["lift"] = float(m.group(1))

    # 响度 / 真峰值
    m = re.search(r"响度\s*(-?[\d.]+)\s*LUFS\s*真峰值\s*(-?[\d.]+)\s*dBTP", t)
    if m:
        out["lufs"] = float(m.group(1))
        out["dbtp"] = float(m.group(2))

    return out if out else None


def build_table(d, lang="en"):
    """生成 markdown 表格行"""
    if lang == "zh":
        rows = [
            ("**卡字率**（画面动作和关键词的同步率）",
             f"**{d['hits']}/{d['total']} = {d['rate']:.0f}%**"),
            ("响度", f"{d['lufs']:.1f} LUFS"),
            ("真峰值", f"{d['dbtp']:.1f} dBTP"),
            ("分辨率", "1080×1920 / 1920×1080 / 1440×1080 / 1080×1080"),
            ("帧率", f"{d.get('fps',60):.0f}fps"),
        ]
    else:
        rows = [
            ("**Kayzi rate** (visual action synced to keyword)",
             f"**{d['hits']}/{d['total']} = {d['rate']:.0f}%**"),
            ("Loudness", f"{d['lufs']:.1f} LUFS"),
            ("True peak", f"{d['dbtp']:.1f} dBTP"),
            ("Resolutions", "1080×1920 / 1920×1080 / 1440×1080 / 1080×1080"),
            ("Frame rate", f"{d.get('fps',60):.0f}fps"),
        ]

    lines = ["| " + ("Metric" if lang != "zh" else "指标") + " | " +
             ("Value" if lang != "zh" else "数值") + " |",
             "|---|---|"]
    for k, v in rows:
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def inject(text, table):
    """替换标记之间的内容。没有标记就返回 None"""
    if BEGIN not in text or END not in text:
        return None
    i = text.find(BEGIN) + len(BEGIN)
    j = text.find(END)
    return text[:i] + "\n" + table + "\n" + text[j:]


def main():
    ap = argparse.ArgumentParser(description="从 check.txt 同步数字到 README")
    ap.add_argument("--src", default=None, help="check.txt 路径")
    ap.add_argument("--check", action="store_true", help="只检查不改")
    a = ap.parse_args()

    src = Path(a.src) if a.src else ROOT / "demo" / "check.txt"
    d = parse_check(src)
    if not d:
        print(f"解析失败或文件不存在: {src}")
        print("  先跑 make_demo.py 生成 demo/check.txt")
        return 2

    print(f"从 {src.name} 读到：")
    for k in ["hits", "total", "rate", "lufs", "dbtp", "fps"]:
        if k in d:
            print(f"  {k:<8} {d[k]}")
    print()

    targets = [("README.md", "en"), ("README.zh-CN.md", "zh")]
    changed = 0
    missing_marker = []

    for name, lang in targets:
        p = ROOT / name
        if not p.exists():
            continue
        old = p.read_text(encoding="utf-8")
        # 缺关键字段就拒绝写，不要输出 ?/? = 0%
        need = ["hits", "total", "rate", "lufs", "dbtp"]
        miss = [k for k in need if k not in d]
        if miss:
            print(f"  ✗ {name}  跳过：check.txt 缺字段 {miss}")
            continue

        table = build_table(d, lang)
        new = inject(old, table)

        if new is None:
            missing_marker.append(name)
            continue

        if new == old:
            print(f"  = {name}  已是最新")
        else:
            if a.check:
                print(f"  ✗ {name}  数字不一致")
                changed += 1
            else:
                p.write_text(new, encoding="utf-8")
                print(f"  ✓ {name}  已更新")
                changed += 1

    if missing_marker:
        print(f"\n⚠ 这些文件没有 AUTO:metrics 标记，无法自动同步：")
        for m in missing_marker:
            print(f"    {m}")
        print(f"  在这张表的上下各加一行：")
        print(f"    {BEGIN}")
        print(f"    {END}")

    if a.check and changed:
        print(f"\n✗ {changed} 个文件与 check.txt 不一致")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
