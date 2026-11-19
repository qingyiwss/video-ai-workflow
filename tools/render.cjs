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

// ═══════════════════════════════════════════════════════════
// 两种 CLI 形式都接受：
//
//   ① 简式（和 canvas/render.cjs 兼容，make_demo.py 用这个）
//      node tools/render.cjs <项目目录> <比例>
//      时长从 timeline.json 的 total 自动读
//
//   ② 全式（保留旧用法，向后兼容）
//      node tools/render.cjs <项目目录> <画布文件> <总时长秒> [每段秒] [并发] [比例]
//
// 第二种里 CANVAS 是画布文件名，第一种里第二个参数是比例。
// 用「是不是 xx:xx 的形式」区分。
// ═══════════════════════════════════════════════════════════
const RATIO_INFO = {
  '9:16': { w: 1080, h: 1920 },
  '16:9': { w: 1920, h: 1080 },
  '4:3':  { w: 1440, h: 1080 },
  '1:1':  { w: 1080, h: 1080 },
};
const IS_RATIO = s => typeof s === 'string' && /^\d+:\d+$/.test(s);

let [,, BASE, A2, A3, A4, A5, A6] = process.argv;
let CANVAS, TOTAL_S, SEG_S, JOBS, RATIO;

if (IS_RATIO(A2)) {
  // 简式：<dir> <ratio> [seg_s] [jobs]
  CANVAS = process.env.KAZI_CANVAS || 'canvas.html';
  RATIO = A2;
  SEG_S = A3; JOBS = A4;
  TOTAL_S = null;                      // 稍后从 timeline.json 读
} else {
  // 全式：<dir> <canvas> <total_s> [seg] [jobs] [ratio]
  CANVAS = A2; TOTAL_S = A3; SEG_S = A4; JOBS = A5; RATIO = A6;
}

const RAT = RATIO_INFO[RATIO || '9:16'] || RATIO_INFO['9:16'];
if (!BASE || !CANVAS) {
  console.error('用法:');
  console.error('  node tools/render.cjs <项目目录> <比例> [每段秒数] [并发数]');
  console.error('  node tools/render.cjs <项目目录> <画布文件> <总时长秒> [每段秒] [并发] [比例]');
  console.error('例: node tools/render.cjs ./my-video 9:16');
  process.exit(1);
}

const FPS = 60;
const SEG = parseFloat(SEG_S || '30');
const CONCURRENCY = Math.max(1, parseInt(JOBS || '1', 10));
const OUT = path.join(BASE, 'frames');
const LOG = path.join(BASE, 'render.log');

fs.mkdirSync(OUT, { recursive: true });

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

// 时长：参数优先，否则从 kit.total 读（简式）
const TOTAL = TOTAL_S != null ? parseFloat(TOTAL_S)
            : parseFloat(kit.total || kit.duration || 0);
if (!TOTAL || !isFinite(TOTAL) || TOTAL <= 0) {
  console.error('✗ 读不到总时长。参数没给，timeline.json 里也没有 total 字段');
  process.exit(1);
}
console.log(`时长 ${TOTAL.toFixed(2)}s  比例 ${RATIO || '9:16'}  ${RAT.w}x${RAT.h}`);

const NFRAMES = Math.ceil(TOTAL * FPS);
const SEG_FRAMES = Math.ceil(SEG * FPS);

// ─── 检查已有帧，算出哪些段要做 ───
function segRange(i) {
  const a = i * SEG_FRAMES;
  return [a, Math.min(NFRAMES, a + SEG_FRAMES)];
}
const nSegs = Math.ceil(NFRAMES / SEG_FRAMES);

// 返回该段从第几帧开始缺（-1 = 全有）
//
// ⚠️ 不能只判「整段是否完成」：
//    中断时往往渲染到一半（比如 1200 帧的段渲了 222 帧），
//    整段判会认为未完成而从头重渲，已渲的 222 帧白费。
//    段内逐帧找第一个缺失处，从那里续。
function segStartFrom(i) {
  const [a, b] = segRange(i);
  for (let f = a; f < b; f++) {
    const p = path.join(OUT, `f${String(f).padStart(5, '0')}.png`);
    if (!fs.existsSync(p) || fs.statSync(p).size < 1000) return f;
  }
  return -1;
}

const todo = [];
let reusedFrames = 0;
for (let i = 0; i < nSegs; i++) {
  const from = segStartFrom(i);
  if (from >= 0) {
    todo.push({ seg: i, from });
    const [a] = segRange(i);
    reusedFrames += (from - a);
  }
}

console.log(`总 ${NFRAMES} 帧 = ${nSegs} 段（每段 ${SEG}s = ${SEG_FRAMES} 帧）`);
console.log(`已完成 ${nSegs - todo.length} 段，待渲染 ${todo.length} 段`);
if (reusedFrames) console.log(`复用已有 ${reusedFrames} 帧（段内断点续跑）`);

if (!todo.length) {
  console.log('✓ 全部已完成');
  process.exit(0);
}

// ─── 渲染一段 ───
async function renderSeg(segIdx, fromFrame) {
  const [a0, b] = segRange(segIdx);
  const a = (fromFrame != null) ? fromFrame : a0;
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
  const queue = todo.slice();   // [{seg, from}, ...]

  async function worker() {
    while (queue.length) {
      const job = queue.shift();          // {seg, from}
      try {
        await renderSeg(job.seg, job.from);
        done++;
        console.log(`  [${done}/${todo.length}]`);
      } catch (e) {
        console.error(`  ✗ 段 ${job.seg} 失败: ${e.message}`);
        failed.push(job.seg);
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
