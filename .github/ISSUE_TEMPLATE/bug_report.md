---
name: Bug report
about: Something is broken or produces wrong output
title: "[bug] "
labels: bug
assignees: ''
---

## What happened

<!-- One sentence. What did you expect, what did you get. -->

## Which step

- [ ] `setup.py` — environment detection / install
- [ ] `lint_script.py` — script health check
- [ ] `gen_voice.py` — voice generation
- [ ] `align.py` — word-level alignment
- [ ] `gate1.py` — timeline sign-off
- [ ] render — canvas / frames
- [ ] `mix.py` — audio mixing
- [ ] `kazi_check.py` — sync rate measurement
- [ ] `gen_cover.cjs` — covers
- [ ] other: 

## Environment

Run this and paste the output:

```bash
python tools/detect_env.py --json
```

<details>
<summary>Click to expand</summary>

```json
paste here
```

</details>

## Full error

<details>
<summary>Click to expand</summary>

```
paste the whole traceback, not just the last line
```

</details>

## What you already tried

<!-- Optional but speeds things up a lot -->

---

**Before filing, please check:**

- [ ] Read [docs/PITFALLS.md](../../docs/PITFALLS.md) — 36 pitfalls with symptom → cause → fix
- [ ] Searched existing issues
- [ ] This is not a "how do I write a script" question (that goes in Discussions)
