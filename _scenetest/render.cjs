// 通用渲染器 —— 支持任意比例
// 用法：
//   node render-generic.cjs <项目目录> <比例> [起始秒] [结束秒]
//   node render-generic.cjs . 16:9            全片
//   node render-generic.cjs . 9:16 0 12       前 12 秒
//   node render-generic.cjs . 16:9 still 3.5 out.png   静帧
//
// 比例：9:16 / 16:9 / 4:3 / 1:1
//
// 依据：工作流 0.00 闸门 2（局部渲 3 处）+ 7.7（分段渲染）

const puppeteer = require(process.env.KAZI_PUPPETEER || 'puppeteer-core');
const fs = require('fs');
const path = require('path');

const RATIO_INFO = {
  '9:16': { w: 1080, h: 1920 },
  '16:9': { w: 1920, h: 1080 },
  '4:3':  { w: 1440, h: 1080 },
  '1:1':  { w: 1080, h: 1080 },
};

const [,, BASE_ARG, RATIO, A3, A4] = process.argv;
if (!BASE_ARG || !RATIO) {
  console.error('用法: node render-generic.cjs <项目目录> <9:16|16:9|4:3|1:1> [起] [止 | still 秒 输出]');
  process.exit(1);
}
const BASE = path.resolve(BASE_ARG);
const R = RATIO_INFO[RATIO];
if (!R) {
  console.error(`未知比例 ${RATIO}，可选：${Object.keys(RATIO_INFO).join(' / ')}`);
  process.exit(1);
}

const FPS = 60;
const CANVAS = process.env.KAZI_CANVAS || 'canvas.html';
const OUT = path.join(BASE, 'frames');

(async () => {
  // 读 timeline 和场景定义
  const tlPath = path.join(BASE, 'timeline.json');
  const defPath = path.join(BASE, 'scene-def.json');
  if (!fs.existsSync(tlPath)) { console.error('找不到 timeline.json'); process.exit(1); }
  if (!fs.existsSync(defPath)) { console.error('找不到 scene-def.json'); process.exit(1); }

  const tl = JSON.parse(fs.readFileSync(tlPath, 'utf8'));
  const def = JSON.parse(fs.readFileSync(defPath, 'utf8'));

  const browser = await puppeteer.launch({
    executablePath: process.env.KAZI_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--hide-scrollbars', '--force-device-scale-factor=1',
           '--allow-file-access-from-files', '--font-render-hinting=none'],
    protocolTimeout: 1800000,
  });

  async function newPage() {
    const p = await browser.newPage();
    await p.setViewport({ width: R.w, height: R.h, deviceScaleFactor: 1 });
    const errs = [];
    p.on('pageerror', e => errs.push(String(e)));
    p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
    await p.evaluateOnNewDocument((k, d) => {
      window.__KIT__ = k; window.__DEF__ = d;
    }, tl, def);
    await p.goto('file:///' + path.join(BASE, CANVAS).replace(/\\/g, '/') + '?ratio=' + RATIO,
                 { waitUntil: 'networkidle0', timeout: 60000 });
    await new Promise(r => setTimeout(r, 1200));
    const ok = await p.evaluate(() => {
      if (typeof window.initScene !== 'function') return 'no initScene';
      const r = window.initScene();
      return r ? 'ok:' + (window.__S__ ? window.__S__.length : 0) : 'initScene false';
    });
    return { p, errs, ok };
  }

  // ── 静帧模式 ──
  if (A3 === 'still') {
    const t = parseFloat(A4 || '3');
    const out = process.argv[6] || path.join(BASE, `still-${RATIO.replace(':','x')}.png`);
    const { p, errs, ok } = await newPage();
    if (!String(ok).startsWith('ok')) {
      console.error('初始化失败: ' + ok);
      if (errs.length) console.error(errs.slice(0, 5));
      await browser.close(); process.exit(1);
    }
    console.log('初始化 ' + ok);
    await p.evaluate((tt) => window.renderFrame(tt), t);
    await new Promise(r => setTimeout(r, 300));
    await p.screenshot({ path: out, type: 'png' });
    console.log(`静帧 ${t}s → ${out}`);
    if (errs.length) console.log('JS 错误: ' + errs.slice(0, 3).join(' | '));
    await browser.close();
    return;
  }

  // ── 视频模式 ──
  fs.mkdirSync(OUT, { recursive: true });
  const START = parseFloat(A3 || '0');
  const END = parseFloat(A4 || (tl.total || 100));
  const i0 = Math.round(START * FPS), i1 = Math.round(END * FPS);
  console.log(`${RATIO} ${R.w}x${R.h}  渲染 ${START}-${END}s = ${i1-i0} 帧`);

  const { p, errs, ok } = await newPage();
  if (!String(ok).startsWith('ok')) {
    console.error('初始化失败: ' + ok);
    if (errs.length) console.error(errs.slice(0, 5));
    await browser.close(); process.exit(1);
  }
  console.log('初始化 ' + ok);

  const t0 = Date.now();
  for (let i = i0; i < i1; i++) {
    await p.evaluate((tt) => window.renderFrame(tt), i / FPS);
    await p.screenshot({
      path: path.join(OUT, `f${String(i).padStart(5,'0')}.png`),
      type: 'png', optimizeForSpeed: true,
    });
    if ((i - i0) % 300 === 0) {
      console.log(`  ${i-i0}/${i1-i0}  ${((Date.now()-t0)/1000).toFixed(0)}s`);
    }
  }
  console.log(`完成 ${i1-i0} 帧，${((Date.now()-t0)/1000).toFixed(0)}s`);
  console.log(errs.length ? `JS 错误: ${errs.slice(0,5).join(' | ')}` : '无 JS 错误');
  await browser.close();
})();
