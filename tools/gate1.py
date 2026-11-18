# -*- coding: utf-8 -*-
"""
闸门 1：时间表定稿检查（画画面之前必跑）

依据：工作流 0.00 闸门 1 + 4.2b

为什么要有这一步：
  这条片子的 8 个关键词都在段落第一句的第 0.3-0.8 秒处。
  卡字要求「关键词前 1.35 秒画面安静」，场景进场有 0.30 秒淡入，
  所以进场时刻必须 ≤ kwT - 1.65 —— 结果落到上一段里，和「上一段还没退场」冲突。
  无解，只能回稿子改。

  如果这一关在画画面之前跑，能省 2 小时。

用法：
  python tools/gate1.py <项目目录>
  python tools/gate1.py <项目目录> --fix-hint    # 额外给改稿建议
"""
import argparse
import json
import sys
from pathlib import Path

# ── 阈值（工作流 0.00 / 2.1）──
MIN_KW_LEN = 2         # 关键词至少 2 个字
MIN_HEAD = 1.65        # 关键词距段首 ≥ 1.65 秒
MIN_TAIL = 0.50        # 关键词距段尾 ≥ 0.5 秒
FADE = 0.30            # 场景淡入时长
QUIET = 1.35           # 卡字要求的前置安静期


def check(tl, hint=False):
    """返回 (问题列表, 提示列表)"""
    bad, tips = [], []
    secs = tl.get("sections") or {}
    lines = tl.get("lines") or []
    kws = tl.get("keywords") or []

    # ── ① 关键词数 = 段落数 ──
    if len(kws) != len(secs):
        bad.append(f"关键词 {len(kws)} 个 ≠ 段落 {len(secs)} 段")

    # ── ② 每个关键词 ≥2 字 ──
    for k in kws:
        w = k.get("word", "")
        if len(w) < MIN_KW_LEN:
            bad.append(f"关键词「{w}」只有 {len(w)} 个字（需 ≥{MIN_KW_LEN}）")

    # ── ③ 关键词距段首 / 段尾 ──
    order = sorted(secs.items(), key=lambda kv: kv[1]["start"])
    for sid, v in order:
        kw = next((k for k in kws if v["start"] <= k["t"] <= v["end"]), None)
        if not kw:
            bad.append(f"段 {sid} 没有关键词")
            continue
        off_head = kw["t"] - v["start"]
        off_tail = v["end"] - kw["t"]

        if off_head < MIN_HEAD:
            bad.append(
                f"段 {sid}「{kw['word']}」距段首只有 {off_head:.2f}s"
                f"（需 ≥{MIN_HEAD}）→ 进场时刻 {kw['t']-MIN_HEAD:.2f}s "
                f"早于段首 {v['start']:.2f}s")
            if hint:
                # 算需要往后退多少
                need = MIN_HEAD - off_head
                tips.append(
                    f"段 {sid}：把「{kw['word']}」往后挪 {need:.2f}s —— "
                    f"或在它前面加一句 ≥{need:.1f} 秒的铺垫")
        if off_tail < MIN_TAIL:
            bad.append(
                f"段 {sid}「{kw['word']}」距段尾只有 {off_tail:.2f}s（需 ≥{MIN_TAIL}）")

    # ── ④ pause 不能全一样 ──
    pauses = [l.get("pause", 0) for l in lines]
    if pauses:
        uniq = set(round(p, 2) for p in pauses)
        if len(uniq) == 1:
            bad.append(
                f"所有 pause 都是 {pauses[0]:.2f}s —— 稿子没写 `| 0.6` 这类标注"
                f"（工作流 2.13c）")

    # ── ⑤ 三项质量 ──
    for L in lines:
        tag = L.get("tag", "?")
        for w in L.get("words", []):
            d = w["e"] - w["s"]
            if d <= 0.001:
                bad.append(f"{tag}「{w['u']}」零/负时长 {d:.4f}s")
            if w["e"] < w["s"]:
                bad.append(f"{tag}「{w['u']}」e < s")
            if w["s"] < L["start"] - 0.01 or w["e"] > L["end"] + 0.01:
                bad.append(
                    f"{tag}「{w['u']}」超出句边界 "
                    f"（起 {w['s']-L['start']:+.3f} 终 {w['e']-L['end']:+.3f}）")

    # ── ⑥ 句间衔接 ──
    for i in range(len(lines) - 1):
        a, b = lines[i], lines[i+1]
        gap = b["start"] - a["end"]
        if abs(gap - a.get("pause", 0)) > 0.05:
            bad.append(
                f"{a['tag']}→{b['tag']} 实际间隙 {gap:.3f}s "
                f"≠ 声明 pause {a.get('pause',0):.3f}s")

    return bad, tips


def main():
    ap = argparse.ArgumentParser(description="闸门 1：时间表定稿检查")
    ap.add_argument("base", help="项目目录（含 timeline.json）")
    ap.add_argument("--timeline", default="", help="指定 timeline 路径")
    ap.add_argument("--fix-hint", action="store_true", help="给出改稿建议")
    a = ap.parse_args()

    p = Path(a.timeline) if a.timeline else Path(a.base) / "timeline.json"
    if not p.exists():
        print(f"✗ 找不到 {p}")
        return 1
    tl = json.loads(p.read_text(encoding="utf-8"))

    print("=" * 66)
    print("闸门 1：时间表定稿检查")
    print("=" * 66)
    print(f"  {len(tl['lines'])} 句 / {len(tl.get('keywords') or [])} 关键词 / "
          f"{len(tl.get('sections') or {})} 段 / 总长 {tl['total']:.2f}s")
    print()

    bad, tips = check(tl, a.fix_hint)

    if not bad:
        print("✓ 全部通过，可以去画画面")
        return 0

    print(f"✗ 未通过（{len(bad)} 项）\n")
    for i, b in enumerate(bad, 1):
        print(f"  {i}. {b}")

    if tips:
        print(f"\n改稿建议：")
        for t in tips:
            print(f"  · {t}")

    print(f"\n{'='*66}")
    print("不要往下走。改稿 → 重配 → 重对齐 → 再跑这一关。")
    print("在画画面之前拦住，能省 2 小时返工。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
