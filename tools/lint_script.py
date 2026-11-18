# -*- coding: utf-8 -*-
"""
稿子体检（通用版）：检查任意 script.md
  用法: python lint_script.py script-new.md

查四项（卡字方法论的硬指标）：
  1. 碎句占比（≤4 字）  目标 18-22%
  2. 最长分句           目标 ≤16 字
  3. 平均分句           目标 7-8 字
  4. 段尾「漂亮总结」    目标 0 个
  5. 每句关键词         目标恰好 1 个
"""
import re
import sys
from pathlib import Path

CLAUSE_SPLIT = re.compile(r"[，。！？；：、,;:]|(?<![0-9])\.(?![0-9])")
END_PUNCT = "。！？!?"

# 「漂亮总结」的句式特征
SUMMARY_PATTERNS = [
    (r"^(所以|因此|总之|综上|这就是|这便是|原来|说到底)", "套话开头"),
    (r"(才是|就是|正是|关键在于|本质上|说白了就是)$", "下定义收尾"),
    (r"(的意义|的价值|的真相|的本质)$", "抽象名词收尾"),
    (r"(这么简单|就这么简单|没那么复杂)$", "轻巧收尾"),
    (r"^(这|那)(就是|才是|正是)", "指认式收尾"),
]


# ── 禁用清单（工作流 2.5）──
BANNED = ["最强", "颠覆", "一键", "零门槛", "总结一下", "赋能", "干货满满", "保姆级"]
END_ONLY = ["最后", "总之"]          # 只允许出现在结尾段
# 「不是……而是」句式（工作流 2.5）
NOT_BUT = re.compile(r"不是[^，。？！]{0,14}[，,]?(而是|是)")


def check_banned(paras):
    """禁用词 / 破折号 / 「不是…而是」/「最后」「总之」
    依据：工作流 2.5 禁用清单
    """
    hits = []
    last_idx = len(paras) - 1
    for pi, para in enumerate(paras):
        for sent, _ in para:
            if "—" in sent or "——" in sent:
                hits.append((pi + 1, "破折号", sent[:24]))
            m = NOT_BUT.search(sent)
            if m:
                hits.append((pi + 1, "「不是…而是」", sent[:24]))
            for w in BANNED:
                if w in sent:
                    hits.append((pi + 1, f"禁用词「{w}」", sent[:24]))
            for w in END_ONLY:
                if w in sent and pi != last_idx:
                    hits.append((pi + 1, f"「{w}」只在结尾段", sent[:24]))
    return hits


def parse(path):
    """解析稿子：段 → 句 → 分句。支持 *关键词* 标记和 {念法=>字幕}"""
    # utf-8-sig 会吃掉 BOM（否则 # 前面的 \ufeff 会让 startswith 失败）
    text = Path(path).read_text(encoding="utf-8-sig")
    paras = []
    cur = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            if cur:
                paras.append(cur); cur = []
            continue
        # 跳过 [段落名] 这种章节标记（工作流 2.13 稿子格式）
        if re.match(r"^\[[^\]]+\]$", line):
            if cur:
                paras.append(cur); cur = []   # 段落标记 = 段落边界
            continue
        # 跳过 @gap 行
        if line.startswith("@gap"):
            continue
        # 跳过 Markdown 结构行
        if line.startswith("#") or line.startswith("＃") or line.startswith(">") or line.startswith("|"):
            continue
        if re.match(r"^[-=]{3,}$", line):      # --- / ===
            continue
        # 去掉列表符
        line = re.sub(r"^[-*+]\s+", "", line)
        if not line or line.startswith("```"):
            continue
        # 跳过 Markdown 加粗主打句行（**...**），它只是摘要不是正文
        if re.match(r"^\*\*.+\*\*$", line):
            continue
        # 去掉句末停顿标注 `| 0.5`（工作流 2.13，它不是正文）
        line = re.sub(r"\s*\|\s*[\d.]+\s*$", "", line)
        # 去掉念法标注，保留字幕
        line = re.sub(r"\{(.+?)=>.*?\}", r"\1", line)
        # 按句切之前，先记下每句有没有关键词
        # （不能整行算一个数，否则一行切成多句时会重复计数）
        raw_sents = [x.strip() for x in re.split(r"(?<=[。！？!?])", line)]
        for raw_sent in raw_sents:
            if len(raw_sent) < 2:
                continue
            n_kw = len(re.findall(r"\*[^*]+\*", raw_sent))
            sent = raw_sent.replace("*", "")
            cur.append((sent, n_kw))
    if cur:
        paras.append(cur)
    return paras


def analyze(paras):
    all_lens = []
    short = 0
    rows = []
    for pi, para in enumerate(paras):
        lens = []
        for sent, _ in para:
            for cl in CLAUSE_SPLIT.split(sent):
                cl = cl.strip()
                if not cl:
                    continue
                lens.append(len(cl))
                all_lens.append(len(cl))
                if len(cl) <= 4:
                    short += 1
        if not lens:
            continue
        rows.append({
            "p": pi + 1,
            "n": len(lens),
            "short": sum(1 for x in lens if x <= 4),
            "ratio": sum(1 for x in lens if x <= 4) / len(lens),
            "max": max(lens),
            "mean": sum(lens) / len(lens),
        })
    # 句子层面（口播规则：一句约 20 字）
    sent_lens = []
    for para in paras:
        for sent, _ in para:
            s = re.sub(r"[，。！？；：、,;:]|(?<![0-9])\.(?![0-9])", "", sent).strip()
            if s:
                sent_lens.append(len(s))

    total = len(all_lens)
    return rows, {
        "clauses": total,
        "short": short,
        "ratio": short / total if total else 0,
        "max": max(all_lens) if all_lens else 0,
        "mean": sum(all_lens) / total if total else 0,
        "n_sent": len(sent_lens),
        "sent_mean": sum(sent_lens) / len(sent_lens) if sent_lens else 0,
        "sent_max": max(sent_lens) if sent_lens else 0,
        "sent_min": min(sent_lens) if sent_lens else 0,
    }


def check_summary(paras):
    """找段尾的漂亮总结"""
    hits = []
    for pi, para in enumerate(paras):
        if not para:
            continue
        last = para[-1][0].rstrip("。！？!? ")
        for pat, name in SUMMARY_PATTERNS:
            if re.search(pat, last):
                hits.append((pi + 1, last, name))
                break
    return hits


def check_keywords(paras):
    """每段（= 一个场景）恰好一个关键词。
    参考：上条片子 59 句 / 21 关键词 ≈ 2.8 句一个落点。"""
    bad = []
    for pi, para in enumerate(paras):
        n = sum(k for _, k in para)
        if n != 1:
            # 找出该段里的句子，便于定位
            txt = " / ".join(s[:12] for s, _ in para)
            bad.append((pi + 1, txt, n))
    return bad


def main():
    if len(sys.argv) < 2:
        print("用法: python lint_script.py script.md")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"找不到 {path}")
        sys.exit(1)

    paras = parse(path)
    rows, tot = analyze(paras)
    kws = check_keywords(paras)
    sums = check_summary(paras)
    banned = check_banned(paras)

    n_sent = sum(len(p) for p in paras)
    print("=" * 78)
    print(f"稿子体检：{path.name}")
    print("=" * 78)
    print(f"\n段 {len(paras)} · 句 {n_sent} · 分句 {tot['clauses']} · 总字数 "
          f"{sum(len(s) for p in paras for s, _ in p)}")
    print(f"预计时长（6.13 cps 净）{sum(len(s) for p in paras for s, _ in p)/6.13:.0f} 秒")

    print(f"\n【句子层面】口播规则：一句约 20 字")
    print(f"  句数 {tot['n_sent']}   平均 {tot['sent_mean']:.1f} 字   "
          f"最长 {tot['sent_max']}   最短 {tot['sent_min']}")
    sp = "✓" if 15 <= tot['sent_mean'] <= 24 else ("⚠ 太短（停顿会累积）" if tot['sent_mean'] < 15 else "⚠ 太长")
    print(f"  平均句长 {tot['sent_mean']:.1f} 字  目标 15-24   {sp}")

    print(f"\n【分句层面】{'段':<4}{'分句':>5}{'≤4字':>6}{'占比':>8}{'最长':>6}{'均长':>6}")
    print("-" * 78)
    for r in rows:
        flag = ""
        if r["ratio"] > 0.28:
            flag = " ⚠ 太碎"
        elif r["ratio"] < 0.14:
            flag = " ⚠ 太整"
        if r["max"] > 16:
            flag += " ⚠ 有长句"
        print(f"{r['p']:<4}{r['n']:>5}{r['short']:>6}{r['ratio']*100:>7.0f}%"
              f"{r['max']:>6}{r['mean']:>6.1f}{flag}")
    print("-" * 78)
    print(f"{'合计':<4}{tot['clauses']:>5}{tot['short']:>6}{tot['ratio']*100:>7.0f}%"
          f"{tot['max']:>6}{tot['mean']:>6.1f}")

    # 判分
    print("\n" + "=" * 78)
    print("四项硬指标")
    print("=" * 78)
    ok = True

    r4 = tot["ratio"] * 100
    m4 = "✓" if 18 <= r4 <= 22 else ("⚠ 偏高" if r4 > 22 else "⚠ 偏低")
    if not (18 <= r4 <= 22):
        ok = False
    print(f"  碎句占比   {r4:>5.1f}%   目标 18-22   {m4}")

    m1 = "✓" if tot["max"] <= 16 else "✗"
    if tot["max"] > 16:
        ok = False
    print(f"  最长分句   {tot['max']:>5} 字   目标 ≤16    {m1}")

    m2 = "✓" if 6.5 <= tot["mean"] <= 8.5 else "⚠"
    if not (6.5 <= tot["mean"] <= 8.5):
        ok = False
    print(f"  平均分句   {tot['mean']:>5.1f} 字   目标 7-8    {m2}")

    m3 = "✓" if not sums else "✗"
    if sums:
        ok = False
    m0 = "✓" if 15 <= tot['sent_mean'] <= 24 else "✗"
    print(f"  平均句长   {tot['sent_mean']:>5.1f} 字   目标 15-24  {m0}")

    print(f"  段尾总结   {len(sums):>5} 个   目标 0      {m3}")
    for pi, last, name in sums:
        print(f"      段{pi}: 「{last}」 ← {name}")

    if not (15 <= tot['sent_mean'] <= 24):
        ok = False

    m4b = "✓" if not banned else "✗"
    if banned:
        ok = False
    print(f"  禁用清单   {len(banned):>5} 处   目标 0      {m4b}")
    for pi, what, sent in banned[:8]:
        print(f"      段{pi}: {what}  「{sent}」")

    m5 = "✓" if not kws else "✗"
    if kws:
        ok = False
    print(f"  每段关键词 {'✓' if not kws else str(len(kws))+' 段不合规'}  目标恰好 1")
    for pi, txt, n in kws[:8]:
        print(f"      段{pi}: 有 {n} 个  「{txt[:40]}」")

    print("\n" + "=" * 78)
    print("✓ 全部达标，可以拿去配音" if ok else "✗ 有项目未达标，先改")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
