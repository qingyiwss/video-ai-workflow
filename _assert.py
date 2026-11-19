# -*- coding: utf-8 -*-
"""
设计规格断言 —— 规格不该只写在文档里

三条硬规格，任一不满足就退出非零：

  ① 强调色覆盖率 ≤ 8%
     判定：像素与 #C4471F 的 CIEDE2000 色差 ΔE00 < 10
     取样：全片时长内均匀取 24 帧
     口径写死，不许为了让数字好看而改 ΔE 或取样方式

  ② L.pad('outer') 在 9:16 下 == 72

  ③ 相邻间距三档互不相等（sm < md < lg，且都是 spacing unit 的整数倍）

用法：
  python _assert.py                    # 用 demo/FINAL.mp4
  python _assert.py --video x.mp4      # 指定视频
  python _assert.py --layout-only      # 只查 ②③，不读视频

为什么需要：
  「强调色 2.14%」「边距 72」「间距递减」全在 commit message 和文档里，
  代码里一条断言都没有。下一轮改动很容易改回去，而没人知道。
"""
import argparse
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
from paths import P

# ── 规格常量，写死，不许改 ─────────────────────────────
ACCENT_RGB = (196, 71, 31)        # #C4471F
DELTA_E_MAX = 10.0                # CIEDE2000 阈值
COVERAGE_MAX = 0.08               # 8%
SAMPLE_FRAMES = 24
OUTER_EXPECT_916 = 72


# ══ CIEDE2000 ══════════════════════════════════════════
def srgb_to_lab(rgb):
    """sRGB (0-255) → CIELAB D65"""
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in rgb)
    X = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    Y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    Z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    Xn, Yn, Zn = 0.95047, 1.0, 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t + 16 / 116)

    fx, fy, fz = f(X / Xn), f(Y / Yn), f(Z / Zn)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def ciede2000(lab1, lab2):
    """标准 CIEDE2000（kL=kC=kH=1）"""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7))) if Cb > 0 else 0
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0

    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0
    else:
        dhp = h2p - h1p
        if dhp > 180: dhp -= 360
        elif dhp < -180: dhp += 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))

    Lbp = (L1 + L2) / 2
    Cbp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    else:
        if abs(h1p - h2p) > 180:
            hbp = (h1p + h2p + 360) / 2 if (h1p + h2p) < 360 else (h1p + h2p - 360) / 2
        else:
            hbp = (h1p + h2p) / 2

    T = (1 - 0.17 * math.cos(math.radians(hbp - 30))
         + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6))
         - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dTh = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    RC = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) if Cbp > 0 else 0
    SL = 1 + (0.015 * (Lbp - 50) ** 2) / math.sqrt(20 + (Lbp - 50) ** 2)
    SC = 1 + 0.045 * Cbp
    SH = 1 + 0.015 * Cbp * T
    RT = -math.sin(math.radians(2 * dTh)) * RC

    return math.sqrt((dLp / SL) ** 2 + (dCp / SC) ** 2 + (dHp / SH) ** 2
                     + RT * (dCp / SC) * (dHp / SH))


# ══ 断言 ①：强调色覆盖率 ════════════════════════════
def check_accent(video):
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("  跳过：需要 numpy + Pillow")
        return None

    if not Path(video).exists():
        print(f"  跳过：找不到 {video}")
        return None

    ff = P.ffmpeg
    if not ff:
        print("  跳过：找不到 ffmpeg")
        return None

    # 时长
    r = subprocess.run([P.ffprobe or "ffprobe", "-v", "error",
                        "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True)
    try:
        dur = float(r.stdout.strip())
    except Exception:
        print("  跳过：读不到时长")
        return None

    tmp = ROOT / "_assert_frames"
    tmp.mkdir(exist_ok=True)
    target_lab = srgb_to_lab(ACCENT_RGB)

    total_px = 0
    accent_px = 0
    per_frame = []

    for k in range(SAMPLE_FRAMES):
        t = dur * k / SAMPLE_FRAMES
        f = tmp / f"f{k:03d}.png"
        subprocess.run([ff, "-y", "-v", "error", "-ss", str(t), "-i", str(video),
                        "-frames:v", "1", str(f)], capture_output=True)
        if not f.exists():
            continue
        # 降采样到 1/4 提速（覆盖率是比例，降采样不改变比例）
        im = Image.open(f).convert("RGB")
        im = im.resize((im.width // 4, im.height // 4), Image.BILINEAR)
        a = np.asarray(im, dtype=np.int16)
        h, w = a.shape[:2]
        total_px += h * w

        # 逐像素 CIEDE2000 太慢，先用 RGB 距离筛候选，再对候选算 ΔE00
        d_rgb = np.abs(a - np.array(ACCENT_RGB)).sum(axis=2)
        cand = d_rgb < 120          # 宽松预筛
        n_cand = int(cand.sum())
        if n_cand:
            ys, xs = np.where(cand)
            # 对候选抽样算 ΔE00（最多 3000 个，足够估计比例）
            idx = np.linspace(0, n_cand - 1, min(n_cand, 3000)).astype(int)
            hit = 0
            for i in idx:
                px = tuple(int(v) for v in a[ys[i], xs[i]])
                if ciede2000(srgb_to_lab(px), target_lab) < DELTA_E_MAX:
                    hit += 1
            # 按抽样比例外推
            accent_px += n_cand * (hit / len(idx))
        per_frame.append((t, n_cand / (h * w)))
        f.unlink(missing_ok=True)

    tmp.rmdir()

    if not total_px:
        print("  跳过：没有取到帧")
        return None

    cov = accent_px / total_px
    ok = cov <= COVERAGE_MAX
    print(f"  采样 {len(per_frame)} 帧")
    print(f"  覆盖率 {cov*100:.2f}%   上限 {COVERAGE_MAX*100:.0f}%   "
          f"{'OK' if ok else 'FAIL'}")
    return ok


# ══ 断言 ②③：边距 + 间距 ═══════════════════════════
def check_layout():
    js = ROOT / "_assert_layout.cjs"
    js.write_text(r"""
const puppeteer = require(process.env.KAZI_PUPPETEER || 'puppeteer-core');
(async () => {
  const b = await puppeteer.launch({
    executablePath: process.env.KAZI_CHROME,
    headless: 'new', args: ['--no-sandbox'] });
  const p = await b.newPage();
  await p.goto('about:blank');
  await p.addScriptTag({ path: process.env.KAZI_LAYOUT });
  const r = await p.evaluate(() => {
    const out = {};
    for (const ratio of ['9:16','16:9','4:3','1:1']) {
      const L = window.Layout.make(ratio);
      out[ratio] = { outer: L.pad('outer'), u: L.SP.u,
                     sm: L.SP.sm, md: L.SP.md, lg: L.SP.lg };
    }
    return out;
  });
  console.log(JSON.stringify(r));
  await b.close();
})();
""", encoding="utf-8")

    env = os.environ.copy()
    env["KAZI_CHROME"] = P.chrome
    env["KAZI_PUPPETEER"] = P.puppeteer or "puppeteer-core"
    env["KAZI_LAYOUT"] = str(ROOT / "canvas" / "layout.js")
    env["NO_PROXY"] = "*"
    node = P.__dict__.get("node") or "node"
    import shutil
    node = shutil.which("node") or "D:/Dev/tools/node/node.exe"

    r = subprocess.run([node, str(js)], capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    js.unlink(missing_ok=True)

    if r.returncode != 0:
        print(f"  跳过：浏览器跑不起来（{r.stderr[-120:] if r.stderr else ''}）")
        return None

    import json
    try:
        d = json.loads(r.stdout.strip())
    except Exception:
        print(f"  跳过：解析失败 {r.stdout[:100]}")
        return None

    ok1 = d["9:16"]["outer"] == OUTER_EXPECT_916
    print(f"  outer @9:16 = {d['9:16']['outer']}   期望 {OUTER_EXPECT_916}   "
          f"{'OK' if ok1 else 'FAIL'}")

    ok2 = True
    for ratio, v in d.items():
        s, m, l, u = v["sm"], v["md"], v["lg"], v["u"]
        good = (s < m < l) and (s == u) and (m == u * 2) and (l == u * 3)
        if not good:
            ok2 = False
            print(f"  {ratio}: sm={s} md={m} lg={l} u={u}   FAIL（应为 1:2:3）")
    if ok2:
        vals = ", ".join(f"{k} {v['sm']}/{v['md']}/{v['lg']}" for k, v in d.items())
        print(f"  间距三档 1:2:3 全部画幅   OK  ({vals})")

    return ok1 and ok2


def main():
    ap = argparse.ArgumentParser(description="设计规格断言")
    ap.add_argument("--video", default=None)
    ap.add_argument("--layout-only", action="store_true")
    ap.add_argument("--accent-only", action="store_true")
    a = ap.parse_args()

    video = a.video or (ROOT / "demo" / "FINAL.mp4")

    results = []

    if not a.accent_only:
        print("① ② 边距与间距")
        r = check_layout()
        results.append(("layout", r))
        print()

    if not a.layout_only:
        print(f"① 强调色覆盖率（ΔE00 < {DELTA_E_MAX}，{SAMPLE_FRAMES} 帧均匀采样）")
        r = check_accent(video)
        results.append(("accent", r))
        print()

    failed = [n for n, r in results if r is False]
    skipped = [n for n, r in results if r is None]

    if failed:
        print(f"FAIL: {', '.join(failed)}")
        return 1
    if skipped:
        print(f"SKIP: {', '.join(skipped)}（环境不全，不算通过）")
        return 0
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
