# -*- coding: utf-8 -*-
"""
生成 15 秒示例片 —— 验证环境能不能跑通全流程

它会做完整九步里的六步（跳过写稿和发布物料）：
  配音 → 对齐 → 闸门1 → 渲染 → 混音 → 卡字率检查

用法：
  python make_demo.py
  python make_demo.py --backend edge-tts
  python make_demo.py --ratio 16:9 --keep     # 保留中间文件

产出：
  demo/FINAL.mp4        成片
  demo/narration.wav    旁白
  demo/timeline.json    时间表
  demo/check.txt        检查报告
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))

DEMO_SCRIPT = """＃ 示例稿 · 15 秒 · 3 段
＃ 关键词用 *星号* 包起来，画面会卡在这些词上
＃ | 0.5 是这句话收声到下一句开口的空白

[01 开场]
先说一个词，叫*卡字*，就是画面动的那一下，正好跟字对上。 | 0.4
它念到哪个字，画面同时也到，一秒都不差，听着很自然。 | 0.5

[02 原理]
声音比画面早四十五毫秒，人的耳朵就能察觉到，很明显。 | 0.4
画面得提前一帧*到位*，不能等声音出来再动，那就晚了。 | 0.5

[03 结果]
这套方法能跑到百分之百*卡上*，一个都没有漏掉。 | 0.5
收藏下来，下次做视频少走弯路。 | 1.0
"""

DEMO_SCENES = [
    {
        "sid": "01", "kind": "hero", "theme": "paper",
        "first": "01_01", "last": "01_02",
        "data": {"title": "卡字", "kicker": "先说个词",
                 "note": "画面动的那一下，正好跟字对上"},
        "chap": {"num": "01", "cn": "开场", "en": "WHAT"}
    },
    {
        "sid": "02", "kind": "compare", "theme": "dark",
        "first": "02_03", "last": "02_04",
        "data": {"title": "为什么是 45 毫秒",
                 "left": {"title": "看见", "desc": "125 ms", "color": "#7A8971"},
                 "right": {"title": "听见", "desc": "45 ms", "color": "#C99B3F"}},
        "chap": {"num": "02", "cn": "原理", "en": "WHY"}
    },
    {
        "sid": "03", "kind": "number", "theme": "paper",
        "first": "03_05", "last": "03_06",
        "data": {"value": "100", "unit": "%", "label": "卡字率",
                 "sublabel": "15 个关键词全卡上"},
        "chap": {"num": "03", "cn": "结果", "en": "RESULT"}
    },
]


def hr(t=""):
    print("\n" + "=" * 62)
    if t:
        print(t)
        print("=" * 62)


def run(cmd, cwd=None, timeout=1800, label=""):
    if label:
        print(f"\n  ▶ {label}")
    r = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", timeout=timeout)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    for line in out.splitlines():
        if any(k in line for k in ["✓", "✗", "完成", "失败", "句", "cps",
                                   "卡字率", "响度", "问题", "关键词"]):
            print(f"    {line.strip()[:95]}")
    return r.returncode == 0, out


def main():
    ap = argparse.ArgumentParser(description="生成示例片")
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--ratio", default="9:16",
                    choices=["9:16", "16:9", "4:3", "1:1"])
    ap.add_argument("--keep", action="store_true", help="保留中间文件")
    ap.add_argument("--dir", default="demo")
    a = ap.parse_args()

    from paths import P

    DEMO = ROOT / a.dir
    if DEMO.exists() and not a.keep:
        shutil.rmtree(DEMO)
    DEMO.mkdir(exist_ok=True)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  生成示例片  {a.ratio}  后端 {a.backend:<22}║
╚══════════════════════════════════════════════════════════╝""")

    t0 = time.time()

    # ── 0. 准备 ──
    hr("0. 准备文件")
    (DEMO / "script.md").write_text(DEMO_SCRIPT, encoding="utf-8")
    (DEMO / "scene-def.json").write_text(
        json.dumps(DEMO_SCENES, ensure_ascii=False, indent=1), encoding="utf-8")

    # 画布运行时依赖
    for f in ["anim.js", "time.js", "layout.js", "scenes.js", "canvas.html"]:
        src = ROOT / "canvas" / f
        if src.exists():
            shutil.copy2(src, DEMO / f)
    shutil.copy2(ROOT / "canvas" / "render.cjs", DEMO / "render.cjs")
    print(f"  ✓ script.md / scene-def.json / 6 个运行时")

    # ── 1. 稿子体检 ──
    hr("1. 稿子体检")
    lint_ok, _ = run([sys.executable, str(ROOT/"tools/lint_script.py"),
                      str(DEMO/"script.md")], label="lint_script.py")
    if not lint_ok:
        print("""
  ℹ️ 示例稿只有 6 句，三项句长指标在这么短的样本下
     本来就难同时满足（碎句率和句长互相拉扯）。
     真正写稿时要过，但示例片以「跑通流程」为主。""")

    # ── 2. 配音 ──
    hr("2. 配音")
    ok, out = run([sys.executable, str(ROOT/"tools/gen_voice.py"), str(DEMO),
                   "--backend", a.backend], timeout=3600, label="gen_voice.py")
    if not (DEMO / "narration.wav").exists():
        print("\n✗ 配音失败，停下来")
        print(out[-800:])
        return 1

    # ── 3. 对齐 ──
    hr("3. 逐字对齐")
    ok, out = run([sys.executable, str(ROOT/"tools/align.py"), str(DEMO)],
                  timeout=900, label="align.py")
    if not (DEMO / "timeline.json").exists():
        print("\n✗ 对齐失败")
        print(out[-800:])
        return 1

    # ── 4. 闸门 1 ──
    hr("4. 闸门 1：时间表定稿")
    g1_ok, out = run([sys.executable, str(ROOT/"tools/gate1.py"), str(DEMO)],
                     label="gate1.py")
    if not g1_ok:
        print("\n  ⚠ 闸门 1 没过 —— 示例稿是按规则写的，不应该发生")
        print("    如果这是你自己的稿子，回去改，别往下走")

    # ── 5. 缺字检测（P0-1）──
    hr("5. 缺字检测")
    font_ok, fout = run([sys.executable, str(ROOT/"tools/font_check.py"), str(DEMO)],
                        label="font_check.py")
    if not font_ok:
        print("\n  ✗ 稿子里有字体子集没有的字，会在渲染时回退到系统字体")
        print("    换字，或扩展 canvas/fonts/ 的子集后重跑")
        print("    不要让缺字进渲染 —— 它不报错，只在成片里露出来")
        return 1
    print("  ✓ 全部字符都有字形")

    # ── 6. 渲染 ──
    hr("6. 渲染画面")
    tl = json.loads((DEMO / "timeline.json").read_text(encoding="utf-8"))
    total = tl.get("total", 15)
    print(f"  总长 {total:.2f}s  比例 {a.ratio}")

    node = shutil.which("node")
    if not node:
        print("  ✗ 没有 Node.js，跳过渲染")
        print(f"    装 Node 后手动跑：")
        print(f"    node render.cjs {DEMO} {a.ratio}")
        return 1

    env = os.environ.copy()
    env["KAZI_CHROME"] = P.chrome
    env["KAZI_PUPPETEER"] = P.puppeteer

    ok, out = run([node, str(DEMO/"render.cjs"), str(DEMO), a.ratio],
                  timeout=1800, label=f"render.cjs {a.ratio}")
    frames = list((DEMO / "frames").glob("*.png")) if (DEMO/"frames").exists() else []
    print(f"  {len(frames)} 帧")
    if not frames:
        print("\n✗ 渲染失败")
        print(out[-800:])
        return 1

    # ── 7. 混音 ──
    hr("7. 混音")
    # ⚠️ 归一化的源永远是 mix.wav / narration.wav，不能是 mix-final.wav
    #    否则重跑会叠加增益，越跑越小声（实测 -18.3 → -23.3）
    bgm = P.bgm
    if bgm and Path(bgm).exists():
        ok, out = run([sys.executable, str(ROOT/"tools/mix.py"), str(DEMO),
                       "--bgm", bgm, "--out", str(DEMO/"mix.wav")],
                      label="mix.py（带 BGM）")
        audio = DEMO / "mix.wav"
    else:
        print("  （没有 BGM，直接归一化旁白）")
        audio = DEMO / "narration.wav"

    # 归一化
    ffm = P.ffmpeg
    if not ffm:
        print("  ✗ 没有 ffmpeg")
        return 1

    final_audio = DEMO / "mix-final.wav"
    if final_audio.exists():
        final_audio.unlink()      # 必须删，否则下次读到自己

    # 归一化三步走（工作流 6.5，2026-11-18 实测）
    #
    # edge-tts / CosyVoice3 输出：峰值高（-1.2）但 RMS 低（-23）
    #   动态 20 dB，直接加增益会撞峰值
    #
    # ❌ loudnorm 两遍法 → 只能到 -16.4（LRA 太大，线性模式受限）
    # ✓ 压缩 + 限幅 + 精确增益 → -14.0 / -2.4
    import re as _re

    def probe(path):
        r = subprocess.run([ffm, "-i", str(path),
                            "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="ignore")
        mi = _re.search(r'"input_i"\s*:\s*"(-?[\d.]+)"', r.stderr or "")
        mt = _re.search(r'"input_tp"\s*:\s*"(-?[\d.]+)"', r.stderr or "")
        return (float(mi.group(1)) if mi else -18.0,
                float(mt.group(1)) if mt else -2.0)

    cur_i, cur_tp = probe(audio)
    print(f"  压缩前  {cur_i:.1f} LUFS / {cur_tp:.1f} dBTP")

    # ① 压缩（阈值 -24，比例 4，makeup 14）→ 动态从 20 dB 压到 ~11 dB
    tmp_c = DEMO / "_norm_c.wav"
    subprocess.run([ffm, "-y", "-v", "error", "-i", str(audio),
                    "-af", "acompressor=threshold=-24dB:ratio=4:attack=5:release=150:makeup=14",
                    "-ar", "48000", str(tmp_c)],
                   capture_output=True, text=True)

    # ② 硬限幅（0.87 = -1.2 dBFS）
    tmp_l = DEMO / "_norm_l.wav"
    subprocess.run([ffm, "-y", "-v", "error", "-i", str(tmp_c),
                    "-af", "alimiter=limit=0.87:attack=2:release=30:level=0",
                    "-ar", "48000", str(tmp_l)],
                   capture_output=True, text=True)
    li, ltp = probe(tmp_l)
    print(f"  限幅后  {li:.1f} LUFS / {ltp:.1f} dBTP")

    # ③ 精确增益（目标 -14，峰值不超 -1.2）
    gain = round(min(-14.0 - li, -1.2 - ltp), 1)
    print(f"  加 {gain:+.1f} dB")
    subprocess.run([ffm, "-y", "-v", "error", "-i", str(tmp_l),
                    "-af", f"volume={gain}dB,aresample=48000",
                    "-ar", "48000", str(final_audio)],
                   capture_output=True, text=True)
    tmp_c.unlink(missing_ok=True)
    tmp_l.unlink(missing_ok=True)

    fi, ftp = probe(final_audio)
    ok = -15.5 <= fi <= -12.5 and ftp <= -1.0
    print(f"  最终    {fi:.1f} LUFS / {ftp:.1f} dBTP  {'✓ 达标' if ok else '⚠ 偏差'}")

    # ── 8. 合成 ──
    hr("8. 合成视频")
    out_mp4 = DEMO / "FINAL.mp4"
    r = subprocess.run([ffm, "-y", "-v", "error",
                        "-framerate", "60", "-i", str(DEMO/"frames"/"f%05d.png"),
                        "-i", str(final_audio),
                        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                        "-shortest", "-movflags", "+faststart", str(out_mp4)],
                       capture_output=True, text=True)
    if out_mp4.exists():
        print(f"  ✓ FINAL.mp4  {out_mp4.stat().st_size/1024/1024:.1f} MB")
    else:
        print(f"  ✗ 失败：{r.stderr[:300]}")
        return 1

    # ── 9. 卡字率 ──
    hr("9. 卡字率检查")
    ok, out = run([sys.executable, str(ROOT/"tools/kazi_check.py"),
                   str(out_mp4), "--timeline", str(DEMO/"timeline.json")],
                  timeout=900, label="kazi_check.py")
    (DEMO / "check.txt").write_text(out, encoding="utf-8")

    # ── 10. 清理 ──
    if not a.keep:
        shutil.rmtree(DEMO / "frames", ignore_errors=True)
        shutil.rmtree(DEMO / "batch", ignore_errors=True)
        for f in ["pace-in", "pace-out", "_bgm_flat.wav"]:
            p = DEMO / f
            if p.exists():
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()

    # ── 汇总 ──
    elapsed = time.time() - t0
    hr("完成")
    print(f"""
  用时 {elapsed/60:.1f} 分钟
  成片 {out_mp4}
  旁白 {DEMO/'narration.wav'}
  时间表 {DEMO/'timeline.json'}
  报告 {DEMO/'check.txt'}

  下一步：
    · 听一下成片，卡字对不对
    · 看 工作流.md 学怎么写自己的稿
    · 改 demo/script.md 和 scene-def.json，重跑这一步
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
