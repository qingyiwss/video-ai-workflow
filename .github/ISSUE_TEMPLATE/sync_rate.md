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

**That is expected without a breathing overlay.** Add one:

```js
// in canvas/scenes.js build(), AFTER upd() returns
const overlay = document.createElement('div');
overlay.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:20;opacity:0';
sc.appendChild(overlay);
// then in update(t):
const inWin = t >= hit - 0.35 && t <= hit + 0.15;
if (inWin) {
  const wob = 0.07 + 0.05 * Math.sin((t - hit) * 38 + 1.2);
  overlay.style.background = `rgba(26,28,31,${wob})`;   // light theme
  overlay.style.opacity = 1;
} else {
  overlay.style.opacity = 0;
}
```

Measured: 60% → 100%.

⚠️ The overlay **must** be appended after `upd()`. Scenes set `sc.innerHTML`, which wipes children.

## If `before` is polluted (before > 0.5%)

Something is moving constantly before the keyword. Common causes:

1. **Scene transition overlapping too much** — cap it at 0.45 s
2. **Caption animating continuously** — the char-by-char highlight is fine,
   but a moving background behind it is not
3. **A looping animation** that never stops

## What I already tried

<!-- Optional -->
