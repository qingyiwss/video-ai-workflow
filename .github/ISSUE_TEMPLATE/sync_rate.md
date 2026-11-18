---
name: Sync rate too low
about: kazi_check.py reports less than 80% — the picture does not land on the keyword
title: "[sync] "
labels: sync-rate
assignees: ''
---

**This is the most common problem. 90% of the time it is one of two things.**

Before filing, run Gate 1:

```bash
python tools/gate1.py .
```

If it fails, that is the cause — fix the script, do not come back here yet.

---

## Your numbers

Paste the full table from `kazi_check.py`:

```
卡字率 X/Y = Z%
判定  时刻  关键词  这一下  前一秒  倍数
...
```

## Checklist

- [ ] `gate1.py` passes
- [ ] I checked whether the failing scenes use subtle motions
      (`scale 0.94→1`, 20 px shifts, opacity fades) — see
      [PITFALLS 坑 20](../../docs/PITFALLS.md)
- [ ] I checked whether `before` is polluted (before > 0.5%)
      — see [PITFALLS 坑 11](../../docs/PITFALLS.md)

## If the failing scenes are "subtle motion" types

**Do not add a full-screen brightness overlay.** We did that, then removed it.

It lifted the metric from 60% to 100% while the frame-internal spatial deviation
stayed flat (31.03 → 29.20). Nothing in the picture moved — it was pure
whole-screen flicker at 6 Hz, and it only ran inside the detection window.

**Instead, make the motion real.** Example from `hero`:

```js
// ❌ old: scale only — 6% of pixels
t.style.transform = `scale(${LP(0.94, 1, k01)})`;

// ✓ new: rise 35% of the glyph height + a rule sweeps to full width
t.style.transform = `translateY(${LP(heroSize * 0.35, 0, k01)}px)`;
l.style.width = (E.standard(lp) * m.w) + 'px';
```

| version | near | ratio | spatial structure |
|---|---|---|---|
| `scale 0.94→1` | 0.22% | 0.5× | — |
| ✗ brightness overlay | 11.61% | ~5× | **unchanged (fake)** |
| ✓ real motion | **1.33%** | **2.1×** | **changed (real)** |

The real motion scores 8× lower and is the only one a viewer can see.

See [PITFALLS 坑 20](../../docs/PITFALLS.md) for the full comparison per scene.

## If `before` is polluted (before > 0.5%)

Something is moving constantly before the keyword. Common causes:

1. **Scene transition overlapping too much** — cap it at 0.45 s
2. **Caption animating continuously** — the char-by-char highlight is fine,
   but a moving background behind it is not
3. **A looping animation** that never stops

## What I already tried

<!-- Optional -->
