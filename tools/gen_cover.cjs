// 封面静帧 —— 复用画布出图，不用 PS
//
// 依据：工作流 8.2
//   「封面：一个主体、一句话、能在手机小图上看清。
//    B 站要 16:9 和 4:3 两张，字放在正中间，16:9 那张从中间裁成 4:3 也切不到字。」
//
// 用法：
//   node gen_cover.cjs <项目目录> <画布文件> <封面帧时间> [输出目录] [片源比例]
//
//   片源比例：9:16（默认）/ 16:9 / 4:3 / 1:1
//
// 例：
//   node gen_cover.cjs ./proj canvas.html 7.3 ./cover 16:9
//
// 输出（按片源比例决定主版本）：
//   片源 9:16 → cover-1080x1920.png 主版本 + cover-1920x1080.png（裁，字在中间）
//   片源 16:9 → cover-1920x1080.png 主版本 + cover-1440x1080.png（裁）
//   片源 4:3  → cover-1440x1080.png 主版本
//   片源 1:1  → cover-1080x1080.png 主版本
//
//   总是输出 cover-check.png（安全区检查图）
//
// ⚠️ 关键改动（2026-11-17）：
//   旧版是把竖屏画布 scale(0.5625) 塞进 16:9 —— 字会很小、两边全空。
//   新版是让画布自己按目标比例渲染（?ratio=16:9），布局引擎负责重排。

const puppeteer = require(process.env.KAZI_PUPPETEER || 'puppeteer-core');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const [,, BASE, CANVAS, T, OUTDIR, RATIO_ARG] = process.argv;
if (!BASE || !CANVAS || T === undefined) {
  console.error('用法: node gen_cover.cjs <项目目录> <画布文件> <封面帧时间> [输出目录] [9:16|16:9|4:3|1:1]');
  process.exit(1);
}

// 从环境变量或 config 读，回退 'ffmpeg'
const FF = process.env.KAZI_FFMPEG || 'ffmpeg';

const DIMS = {
  '9:16': { w: 1080, h: 1920, tag: '1080x1920' },
  '16:9': { w: 1920, h: 1080, tag: '1920x1080' },
  '4:3':  { w: 1440, h: 1080, tag: '1440x1080' },
  '1:1':  { w: 1080, h: 1080, tag: '1080x1080' },
};

// 片源比例 → 要出哪些封面
const PLAN = {
  '9:16': ['9:16', '16:9'],           // 竖屏主 + B站横屏（裁）
  '16:9': ['16:9', '4:3'],            // 横屏主 + B站 4:3（裁）
  '4:3':  ['4:3', '16:9'],
  '1:1':  ['1:1', '16:9'],
};

const SRC_RATIO = RATIO_ARG || '9:16';
if (!DIMS[SRC_RATIO]) {
  console.error(`未知片源比例 ${SRC_RATIO}，可选：${Object.keys(DIMS).join(' / ')}`);
  process.exit(1);
}

const OUT = path.resolve(OUTDIR || path.join(BASE, 'cover'));
fs.mkdirSync(OUT, { recursive: true });
const T_FRAME = parseFloat(T);

async function shoot(browser, ratio) {
  const D = DIMS[ratio];
  const p = await browser.newPage();
  await p.setViewport({ width: D.w, height: D.h, deviceScaleFactor: 1 });
  const errs = [];
  p.on('pageerror', e => errs.push(String(e)));

  const readJson = f => {
    const fp = path.join(BASE, f);
    return fs.existsSync(fp) ? JSON.parse(fs.readFileSync(fp, 'utf8')) : null;
  };
  const kit = readJson('full-kit.json') || readJson('timeline.json');
  const def = readJson('scene-def.json');

  if (kit) {
    await p.evaluateOnNewDocument((k, d) => {
      window.__KIT__ = k; if (d) window.__DEF__ = d;
    }, kit, def);
  }

  await p.goto('file:///' + path.join(BASE, CANVAS).replace(/\\/g, '/') + '?ratio=' + ratio,
               { waitUntil: 'networkidle0', timeout: 60000 });
  await new Promise(r => setTimeout(r, 1200));

  await p.evaluate((t) => {
    if (typeof window.initScene === 'function') window.initScene();
    if (typeof window.renderFrame === 'function') window.renderFrame(t);
  }, T_FRAME);
  await new Promise(r => setTimeout(r, 500));

  const file = path.join(OUT, `cover-${D.tag}.png`);
  await p.screenshot({ path: file, type: 'png' });
  await p.close();
  return { file, errs, dim: D };
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: process.env.KAZI_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--hide-scrollbars', '--force-device-scale-factor=1',
           '--allow-file-access-from-files', '--font-render-hinting=none'],
    protocolTimeout: 600000,
  });

  const plan = PLAN[SRC_RATIO];
  console.log(`片源 ${SRC_RATIO} ${DIMS[SRC_RATIO].w}x${DIMS[SRC_RATIO].h}  出 ${plan.length} 张`);

  const made = {};
  for (const ratio of plan) {
    const r = await shoot(browser, ratio);
    made[ratio] = r.file;
    const note = r.errs.length ? `  ⚠ ${r.errs[0].slice(0, 60)}` : '';
    console.log(`  ✓ cover-${DIMS[ratio].tag}.png${note}`);
  }

  // ── 4:3 从 16:9 裁（如果 16:9 有、4:3 没有）──
  if (made['16:9'] && !made['4:3']) {
    const src = made['16:9'];
    const dst = path.join(OUT, 'cover-1440x1080.png');
    try {
      execSync(`"${FF}" -y -v error -i "${src}" -vf "crop=1440:1080:240:0" "${dst}"`);
      made['4:3'] = dst;
      console.log('  ✓ cover-1440x1080.png（从 16:9 裁）');
    } catch (e) {
      console.log('  ✗ 4:3 裁剪失败: ' + e.message.slice(0, 80));
    }
  }

  // ── 16:9 从 4:3 补边（如果 4:3 有、16:9 没有）──
  if (made['4:3'] && !made['16:9']) {
    const src = made['4:3'];
    const dst = path.join(OUT, 'cover-1920x1080.png');
    try {
      execSync(`"${FF}" -y -v error -i "${src}" -vf "scale=1920:1080" "${dst}"`);
      made['16:9'] = dst;
      console.log('  ✓ cover-1920x1080.png（从 4:3 缩放）');
    } catch (e) {
      console.log('  ✗ 16:9 缩放失败: ' + e.message.slice(0, 80));
    }
  }

  // ── 安全区检查图：红区 = 4:3 裁 16:9 时会被切掉的部分 ──
  // ⚠️ ffmpeg 不能解 SVG（no decoder found），用 drawbox 滤镜画
  if (made['16:9']) {
    const src = made['16:9'];
    const dst = path.join(OUT, 'cover-check.png');
    try {
      // 两侧 240px 涂红 28%，中间 1440 描红边
      execSync(
        `"${FF}" -y -v error -i "${src}" -vf "` +
        `drawbox=x=0:y=0:w=240:h=1080:color=red@0.28:t=fill,` +
        `drawbox=x=1680:y=0:w=240:h=1080:color=red@0.28:t=fill,` +
        `drawbox=x=240:y=0:w=1440:h=1080:color=red@1:t=6` +
        `" "${dst}"`);
      console.log('  ✓ cover-check.png（红色区域会被 4:3 裁掉，字不能落在这里）');
    } catch (e) {
      console.log('  ✗ 检查图失败: ' + e.message.slice(0, 80));
    }
  }

  await browser.close();
  console.log(`\n输出目录：${OUT}`);
})();
