# -*- coding: utf-8 -*-
"""
场景改造的批量验证器

改造一个场景后跑一次，一次性给出：
  ① 四画幅静帧（并排成一张图）
  ② 卡字率对比（与上一次记录比）
  ③ 布局溢出检查（元素是否超出内容区）

用法：
  python _verify.py --still 3.0 --label hero-v4
  python _verify.py --no-sync                 # 只出图，不跑卡字率
  python _verify.py --sync                     # 只跑卡字率
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
from paths import P

WORK = ROOT / "_verify"
CACHE = ROOT / "_verify" / "history.json"


def find_node():
    """找 node.exe —— 与 paths.py 同逻辑"""
    w = shutil.which("node")
    if w:
        return w
    for c in [r"D:\Dev\tools\node\node.exe",
              r"C:\Program Files\nodejs\node.exe"]:
        if Path(c).exists():
            return c
    return "node"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore", **kw)


def prep():
    """复制 canvas 到工作目录"""
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    for f in ["anim.js", "time.js", "layout.js", "scenes.js",
              "canvas.html", "render.cjs"]:
        src = ROOT / "canvas" / f
        if src.exists():
            shutil.copy2(src, WORK / f)
    for f in ["scene-def.json", "timeline.json"]:
        src = ROOT / "demo" / f
        if src.exists():
            shutil.copy2(src, WORK / f)

    # render.cjs 要 require('puppeteer-core')，从 _verify/ 往上找
    # 建一个 node_modules 指向 puppeteer 所在目录
    nm = WORK / "node_modules"
    if not nm.exists():
        pptr = Path(P.puppeteer)
        if pptr.exists():
            # pptr = .../node_modules/puppeteer-core
            target = pptr.parent
            try:
                if os.name == "nt":
                    subprocess.run(["cmd", "/c", "mklink", "/J",
                                    str(nm), str(target)],
                                   capture_output=True)
                else:
                    nm.symlink_to(target, target_is_directory=True)
            except Exception:
                pass


def stills(t):
    """四画幅静帧 → 拼成一张"""
    node = find_node()
    ff = P.ffmpeg
    out = []
    env = os.environ.copy()
    env["KAZI_CHROME"] = P.chrome
    env["KAZI_PUPPETEER"] = P.puppeteer
    env["NO_PROXY"] = "*"

    if not hasattr(stills, "_shown"):
        print(f"  node: {node}")
        stills._shown = True

    for ratio, tag in [("9:16", "p"), ("16:9", "l"),
                       ("4:3", "f"), ("1:1", "s")]:
        png = WORK / f"{tag}.png"
        r = run([node, str(WORK / "render.cjs"), str(WORK), ratio,
                 "still", str(t), str(png)], env=env)
        if not png.exists():
            print(f"  ✗ {ratio} 渲染失败: {r.stderr[-200:] if r.stderr else ''}")
            continue
        sm = WORK / f"_{tag}.png"
        run([ff, "-y", "-v", "error", "-i", str(png), "-vf",
             "scale=-2:560:force_original_aspect_ratio=decrease,"
             "pad=iw:560:(ow-iw)/2:(oh-ih)/2:color=0x2A2A2A", str(sm)])
        out.append((ratio, sm))

    if len(out) == 4:
        dest = ROOT / "_stills.png"
        args = [ff, "-y", "-v", "error"]
        for _, f in out:
            args += ["-i", str(f)]
        args += ["-filter_complex", "[0][1][2][3]hstack=inputs=4", str(dest)]
        run(args)
        print(f"  ✓ 四画幅 → _stills.png  {dest.stat().st_size//1024} KB")
    return len(out)


def overflow_check(t):
    """溢出检查 —— 复用 render.cjs 的初始化流程（注入 KIT/DEF + 正确 viewport）

    不自己实现浏览器初始化：canvas.html 依赖 window.__KIT__ / __DEF__，
    还要等 initScene()。抄错一步就得到 stage 0x0。
    """
    node = find_node()
    js = ROOT / "_verify" / "check.cjs"
    js.write_text(r"""
const puppeteer = require(process.env.KAZI_PUPPETEER);
const fs = require('fs');
const path = require('path');

const RATIOS = {
  '9:16': { w: 1080, h: 1920 },
  '16:9': { w: 1920, h: 1080 },
  '4:3':  { w: 1440, h: 1080 },
  '1:1':  { w: 1080, h: 1080 },
};

(async () => {
  const base = path.resolve(process.argv[2]);
  const t = parseFloat(process.argv[3]);
  const tl = JSON.parse(fs.readFileSync(path.join(base, 'timeline.json'), 'utf8'));
  const def = JSON.parse(fs.readFileSync(path.join(base, 'scene-def.json'), 'utf8'));

  const browser = await puppeteer.launch({
    executablePath: process.env.KAZI_CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--hide-scrollbars', '--force-device-scale-factor=1',
           '--allow-file-access-from-files'],
    protocolTimeout: 600000,
  });

  for (const ratio of Object.keys(RATIOS)) {
    const R = RATIOS[ratio];
    const p = await browser.newPage();
    await p.setViewport({ width: R.w, height: R.h, deviceScaleFactor: 1 });
    await p.evaluateOnNewDocument((k, d) => {
      window.__KIT__ = k; window.__DEF__ = d;
    }, tl, def);
    await p.goto('file:///' + path.join(base, 'canvas.html').replace(/\\/g, '/') +
                 '?ratio=' + ratio, { waitUntil: 'networkidle0', timeout: 60000 });
    await new Promise(r => setTimeout(r, 1000));
    const ok = await p.evaluate(() => {
      if (typeof window.initScene !== 'function') return 'no initScene';
      const r = window.initScene();
      return r ? 'ok' : 'initScene false';
    });
    if (ok !== 'ok') {
      console.log(`  ${ratio.padEnd(5)} 初始化失败: ${ok}`);
      await p.close();
      continue;
    }
    await p.evaluate((tt) => window.renderFrame(tt), t);
    await new Promise(r => setTimeout(r, 200));

    const r = await p.evaluate(() => {
      const stage = document.getElementById('stage');
      const sr = stage.getBoundingClientRect();
      const bad = [];
      const seen = new Set();
      stage.querySelectorAll('*').forEach(el => {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') return;
        if (parseFloat(cs.opacity) < 0.01) return;
        const b = el.getBoundingClientRect();
        if (b.width < 2 || b.height < 2) return;
        if (sr.left - 1 <= b.left && b.right <= sr.right + 1 &&
            sr.top - 1 <= b.top && b.bottom <= sr.bottom + 1) return;
        const key = el.tagName + '|' + Math.round(b.left) + ',' + Math.round(b.top);
        if (seen.has(key)) return;
        seen.add(key);
        bad.push({
          tag: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
          l: Math.round(b.left - sr.left), tp: Math.round(b.top - sr.top),
          rt: Math.round(b.right - sr.left), bt: Math.round(b.bottom - sr.top),
          text: (el.textContent || '').trim().slice(0, 12)
        });
      });
      return { sw: Math.round(sr.width), sh: Math.round(sr.height), bad };
    });

    if (r.bad.length === 0) {
      console.log(`  ${ratio.padEnd(5)} ${r.sw}x${r.sh}  no overflow OK`);
    } else {
      console.log(`  ${ratio.padEnd(5)} ${r.sw}x${r.sh}  ${r.bad.length} overflows`);
      r.bad.slice(0, 6).forEach(x =>
        console.log(`        ${x.tag} [${x.l},${x.tp} - ${x.rt},${x.bt}] "${x.text}"`));
    }
    await p.close();
  }
  await browser.close();
})();
""", encoding="utf-8")

    env = os.environ.copy()
    env["KAZI_CHROME"] = P.chrome
    env["KAZI_PUPPETEER"] = P.puppeteer
    env["NO_PROXY"] = "*"
    if not P.puppeteer:
        print("  ✗ P.puppeteer 为空 —— 设 KAZI_PUPPETEER 或 npm install")
        return
    r = run([node, str(js), str(WORK), str(t)], env=env)
    print(r.stdout.strip() or "  (无输出)")
    if r.returncode != 0 and r.stderr:
        print("  " + r.stderr.strip().splitlines()[-1][:160])


def sync_rate(label):
    """跑卡字率，与历史对比"""
    ff = P.ffmpeg
    mp4 = WORK / "check.mp4"
    if not mp4.exists():
        # 合成
        r = run([ff, "-y", "-v", "error", "-framerate", "60",
                 "-i", str(WORK / "frames" / "f%05d.png"),
                 "-i", str(ROOT / "demo" / "narration.wav"),
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                 "-shortest", str(mp4)])
    if not mp4.exists():
        print("  ✗ 没有 check.mp4，先全片渲染")
        return

    r = run([sys.executable, str(ROOT / "tools" / "kazi_check.py"),
             str(mp4), "--timeline", str(WORK / "timeline.json")])
    out = r.stdout + r.stderr

    rows = []
    for line in out.splitlines():
        if "卡上" in line and ("✓" in line or "✗" in line):
            rows.append(line.strip())
    rate = next((l.strip() for l in out.splitlines() if "卡字率" in l), "")

    print(f"  {rate}")
    for l in rows:
        print(f"    {l}")

    # 存历史
    hist = {}
    if CACHE.exists():
        try:
            hist = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            hist = {}
    hist[label] = {"rate": rate, "rows": rows}
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(hist, ensure_ascii=False, indent=1),
                     encoding="utf-8")

    # 与上一个对比
    keys = list(hist.keys())
    if len(keys) >= 2:
        prev = hist[keys[-2]]
        print(f"\n  对比 {keys[-2]} → {label}")
        print(f"    {prev['rate']}  →  {rate}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--still", type=float, default=3.0)
    ap.add_argument("--label", default="current")
    ap.add_argument("--no-sync", action="store_true")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--no-prep", action="store_true")
    a = ap.parse_args()

    if not a.no_prep:
        prep()
        print("✓ 准备完成")
        # 缺字检测：挂在 prep 之后，渲染之前
        r = run([sys.executable, str(ROOT/"tools/font_check.py"), str(WORK)])
        fo = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            print("  ✗ 缺字：")
            for line in fo.splitlines():
                if line.strip().startswith("  ") or "缺" in line:
                    print(f"    {line.strip()}")
            print("  停下来，不要进渲染")
            return
        print("  ✓ 无缺字")

    if not a.sync:
        print(f"\n=== 四画幅静帧 @ {a.still}s ===")
        stills(a.still)
        print(f"\n=== 溢出检查 ===")
        overflow_check(a.still)

    if not a.no_sync:
        print(f"\n=== 卡字率 ===")
        sync_rate(a.label)


if __name__ == "__main__":
    main()
