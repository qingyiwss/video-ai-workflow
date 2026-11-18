// 分段渲染 —— 中断了重跑同一条命令，已经渲好的段会跳过
//
// 依据：kazi 06_检查和发布.md
//   「分段渲染，中断了重跑同一条命令，已经渲好的段会跳过。」
//
// 为什么要分段：
//   一条 6 分钟 4K 片子要渲几十分钟，中途崩一次就全白费。
//   分段之后，崩了只重渲那一段。
//
// 用法：
//   node render_segmented.cjs <项目目录> <画布文件> <总时长秒> [每段秒数] [并发数]
//
// 例：
//   node render.cjs ./my-video canvas.html 105.34 30 3
//
// 输出：
//   frames/f00000.png ... frames/NNNNN.png
//   render.log    每段的进度记录
//
// 中断后：直接再跑同一条命令，会检查已有帧数，从缺的地方继续。

const puppeteer = require(process.env.KAZI_PUPPETEER || 'puppeteer-core');
const fs = require('fs');
const path = require('path');

const [,, BASE, CANVAS, TOTAL_S, SEG_S, JOBS, RATIO] = process.argv;

// 比例 → 尺寸（默认竖屏，向后兼容）
const RATIO_INFO = {
  '9:16': { w: 1080, h: 1920 },
  '16:9': { w: 1920, h: 1080 },
  '4:3':  { w: 1440, h: 1080 },
  '1:1':  { w: 1080, h: 1080 },
};
const RAT = RATIO_INFO[RATIO || '9:16'] || RATIO_INFO['9:16'];
if (!BASE || !CANVAS || !TOTAL_S) {
  console.error('用法: node render_segmented.cjs <项目目录> <画布文件> <总时长秒> [每段秒数] [并发数]');
  process.exit(1);
}

const FPS = 60;
const TOTAL = parseFloat(TOTAL_S);
const SEG = parseFloat(SEG_S || '30');
const CONCURRENCY = Math.max(1, parseInt(JOBS || '1', 10));
const OUT = path.join(BASE, 'frames');
const LOG = path.join(BASE, 'render.log');

fs.mkdirSync(OUT, { recursive: true });

const NFRAMES = Math.ceil(TOTAL * FPS);
const SEG_FRAMES = Math.ceil(SEG * FPS);

// ─── 读 kit 和 scene-def ───
const readJson = f => {
  const p = path.join(BASE, f);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null;
};
const kit = readJson('full-kit.json') || readJson('timeline.json');
const def = readJson('scene-def.json');

if (!kit) {
  console.error('✗ 找不到 full-kit.json 或 timeline.json');
  process.exit(1);
}

// ─── 检查已有帧，算出哪些段要做 ───
function segRange(i) {
  const a = i * SEG_FRAMES;
  return [a, Math.min(NFRAMES, a + SEG_FRAMES)];
}
const nSegs = Math.ceil(NFRAMES / SEG_FRAMES);

function segDone(i) {
  const [a, b] = segRange(i);
  for (let f = a; f < b; f++) {
    const p = path.join(OUT, `f${String(f).padStart(5, '0')}.png`);
    if (!fs.existsSync(p) || fs.statSync(p).size < 1000) return false;
  }
  return true;
}

const todo = [];
for (let i = 0; i < nSegs; i++) if (!segDone(i)) todo.push(i);

console.log(`总 ${NFRAMES} 帧 = ${nSegs} 段（每段 ${SEG}s = ${SEG_FRAMES} 帧）`);
console.log(`已完成 ${nSegs - todo.length} 段，待渲染 ${todo.length} 段`);

if (!todo.length) {
  console.log('✓ 全部已完成');
  process.exit(0);
}

// ─── 渲染一段 ───
async function renderSeg(segIdx) {
  const [a, b] = segRange(segIdx);
  // ⚠️ 每段独立 browser 实例。
  //    共享一个 browser 开多个 page 并发渲染，puppeteer 的 CDP 会话会互相干扰
  //    （实测：Target closed / Session closed，611 秒只渲 6 帧）。
  const browser = await puppeteer.launch({
    executablePath: process.env.KAZI_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--hide-scrollbars', '--force-device-scale-factor=1',
           '--allow-file-access-from-files', '--font-render-hinting=none'],
    protocolTimeout: 1800000,
  });
  const p = await browser.newPage();
  await p.setViewport({ width: RAT.w, height: RAT.h, deviceScaleFactor: 1 });
  const errs = [];
  p.on('pageerror', e => errs.push(String(e)));

  await p.evaluateOnNewDocument((k, d) => {
    window.__KIT__ = k; if (d) window.__DEF__ = d;
  }, kit, def);
  await p.goto('file:///' + path.join(BASE, CANVAS).replace(/\\/g, '/') + '?ratio=' + (RATIO || '9:16'),
               { waitUntil: 'networkidle0', timeout: 60000 });
  await new Promise(r => setTimeout(r, 1200));

  const ok = await p.evaluate(() => {
    if (typeof window.initScene === 'function') {
      const r = window.initScene();
      if (r === false) return 'initScene false';
    }
    return typeof window.renderFrame === 'function' ? 'ok' : 'no renderFrame';
  });
  if (ok !== 'ok') {
    await p.close();
    throw new Error(`段 ${segIdx} 初始化失败: ${ok}`);
  }

  const t0 = Date.now();
  for (let f = a; f < b; f++) {
    await p.evaluate((t) => window.renderFrame(t), f / FPS);
    await p.screenshot({
      path: path.join(OUT, `f${String(f).padStart(5, '0')}.png`),
      type: 'png', optimizeForSpeed: true,
    });
  }
  const el = ((Date.now() - t0) / 1000).toFixed(0);
  await p.close();
  await browser.close();

  const line = `段 ${segIdx} [${a}-${b}) ${b-a} 帧 ${el}s` + (errs.length ? ` ⚠ ${errs[0].slice(0,60)}` : '');
  console.log('  ' + line);
  fs.appendFileSync(LOG, new Date().toISOString() + '  ' + line + '\n');
  return { segIdx, frames: b - a, seconds: +el, errs: errs.length };
}

// ─── 主循环：并发渲染 ───
(async () => {
  const t0 = Date.now();
  let done = 0, failed = [];
  const queue = todo.slice();

  async function worker() {
    while (queue.length) {
      const seg = queue.shift();
      try {
        await renderSeg(seg);
        done++;
        console.log(`  [${done}/${todo.length}]`);
      } catch (e) {
        console.error(`  ✗ 段 ${seg} 失败: ${e.message}`);
        failed.push(seg);
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, todo.length) }, worker));

  const el = ((Date.now() - t0) / 1000).toFixed(0);
  console.log(`\n完成 ${done}/${todo.length} 段，用时 ${el}s`);
  if (failed.length) {
    console.log(`✗ 失败 ${failed.length} 段: ${failed.join(', ')}`);
    console.log(`  重跑同一条命令会从这些段继续`);
    process.exit(1);
  }
  console.log('✓ 全部完成');
})();
