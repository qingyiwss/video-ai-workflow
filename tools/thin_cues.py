# -*- coding: utf-8 -*-
"""
音效打点筛选 —— 打点太多时先筛一遍

依据：同领域开源实现（53 行，逐行对照移植）

为什么要筛：
  画面里每个动作都打点很方便，可全放出来会吵。kazi 那条片子导出了 861 个，
  平均每分钟 58 个，听起来像一直在敲东西。筛完剩 346 个，每分钟 23 个上下。

筛选规则（按轻重缓急）：
  1. 优先级：重击/叮 > 嗖 > 弹出 > 点击/纸/笔 > 滴答
  2. 从高到低挑，一个点要同时满足：
     - 离已留的任何点 ≥ GAP 秒（默认 0.3）
     - 同种声音离上一个同类 ≥ 它自己的最小间隔
     - 前后 1.5 秒里最多 3 个
     - 前后 30 秒里不超过 per_min 个（默认 22）
     - 同种声音 30 秒里不超过 CAP

经验值：轻的每分钟 4-10 个，中等 1-3 个，重的全片 8-12 个。
加起来不该超过每分钟二三十个，再多就像一直在敲东西。

用法：
  python thin_cues.py cues.json cues_thin.json [--per-min 22] [--gap 0.3]
"""
import argparse
import json
from pathlib import Path

# 优先级（数越大越重要）
PRI = {
    "thud": 5, "chime": 5,           # 重击、叮 → 关键词、结论
    "whoosh": 4, "swoosh": 4,        # 嗖 → 镜头大移动
    "pop": 3,                        # 弹出
    "click": 2, "paper": 2, "pen": 2, "type": 2, "servo": 2, "beep": 2,
    "tick": 1, "soft_in": 1,         # 滴答、轻亮
}

# 每种声音 30 秒内最多几个（重的少、轻的多）
CAP = {
    "thud": 2, "chime": 2, "whoosh": 3, "swoosh": 3, "pop": 8,
    "click": 3, "paper": 2, "pen": 1, "type": 1, "servo": 1, "beep": 1,
    "tick": 3, "soft_in": 1,
}

# 每种声音自己离上一个同类的最小间隔（秒）
SPACING = {
    "thud": 0.5, "chime": 0.8, "whoosh": 0.8, "swoosh": 0.5, "pop": 0.25,
    "click": 0.3, "paper": 0.5, "pen": 0.8, "type": 0.4, "servo": 0.8,
    "beep": 0.5, "tick": 0.6, "soft_in": 1.0,
}


def thin(cues, per_min=22, gap=0.3):
    """返回筛后的 cues（按时间排序）+ 统计"""
    order = sorted(cues, key=lambda c: (-PRI.get(c["kind"], 1),
                                        -c.get("gain", -12), c["t"]))
    kept = []
    for c in order:
        t, k = c["t"], c["kind"]
        if any(abs(t - x["t"]) < gap for x in kept):
            continue
        if any(x["kind"] == k and abs(t - x["t"]) < SPACING.get(k, 0.4) for x in kept):
            continue
        if sum(abs(t - x["t"]) <= 1.5 for x in kept) >= 3:
            continue
        if sum(abs(t - x["t"]) <= 30 for x in kept) >= per_min:
            continue
        if sum(x["kind"] == k and abs(t - x["t"]) <= 30 for x in kept) >= CAP.get(k, 2):
            continue
        kept.append(c)
    kept.sort(key=lambda c: c["t"])
    return kept


def main():
    ap = argparse.ArgumentParser(description="音效打点筛选")
    ap.add_argument("cues", help="输入 cues.json")
    ap.add_argument("out", help="输出筛选后的 json")
    ap.add_argument("--per-min", type=int, default=22, help="每分钟上限，默认 22")
    ap.add_argument("--gap", type=float, default=0.3, help="任意两点最小间隔（秒），默认 0.3")
    a = ap.parse_args()

    cues = json.loads(Path(a.cues).read_text("utf-8"))
    if not cues:
        print("✗ cues 为空")
        return 1

    kept = thin(cues, a.per_min, a.gap)
    Path(a.out).write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")

    span = max(c["t"] for c in cues) / 60 if cues else 1
    print(f"{len(cues)} 个 → 留下 {len(kept)} 个（平均每分钟 {len(kept)/span:.1f} 个）")

    by = {}
    for c in kept:
        by[c["kind"]] = by.get(c["kind"], 0) + 1
    print("按种类：" + "，".join(
        f"{k} {by[k]}/{sum(x['kind'] == k for x in cues)}"
        for k in sorted(by, key=lambda k: -PRI.get(k, 1))))

    mins = [0] * (int(span) + 1)
    for c in kept:
        mins[int(c["t"] // 60)] += 1
    print("每分钟： " + " ".join(str(m) for m in mins))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
