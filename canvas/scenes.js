// 通用场景库 —— 一套代码，竖屏横屏都支持
// 依据：工作流 5.1（画动词）5.9（一关键词一屏）5.14（字幕规范）
//
// 设计原则：
//   1. 每个场景只写「语义」（标题、内容、强调什么），不写像素
//   2. 布局由 Layout 引擎算（竖屏上下 / 横屏左右）
//   3. 动画全部基于 hit（关键词前 3 帧），和比例无关
//
// 场景清单（覆盖知识分享/经验分享/产品介绍/宣传）：
//   hero     大标题           —— 开场、结论、金句
//   points   N 个要点         —— 罗列、对比
//   steps    步骤流程         —— 教程、方法
//   compare  左右对比         —— A vs B
//   number   大数字           —— 数据、成果
//   quote    引用             —— 观点、原话
//   before-after  改前改后    —— 前后对比
//   list     清单（带勾）      —— checklist
//   product  产品展示         —— 产品介绍
//   cta      行动号召         —— 结尾引导

(function () {
'use strict';

const A = window.Anim;
const CL = A.clamp, LP = A.lerp, IV = A.inv, E = A.E;
const SPR = A.springTo, BL = A.bell;

// 标题/巨字用宋体，正文用黑体
const FF_SERIF = `'KaziSerif',serif`;
const FF_SANS  = `'KaziSans',sans-serif`;
// 兼容旧引用（默认黑体）
const FF = FF_SANS;

// ── 颜色（工作流 5.17）──
const C = {
  paper: '#F2EFE6', ink: '#1A1C1F', soft: '#8C8578',
  warm: '#C4471F', deep: '#1F3B4D', sage: '#7A8971',
  gold: '#C99B3F', red: '#A8231A',
};
const THEME_BG = { paper: C.paper, dark: C.deep, red: C.red };
const THEME_FG = { paper: C.ink, dark: C.paper, red: C.paper };
const THEME_SUB = { paper: C.soft, dark: 'rgba(242,239,230,.68)', red: 'rgba(242,239,230,.75)' };

/**
 * 建一个场景
 * @param {object} cfg
 *   kind     场景类型
 *   theme    'paper' | 'dark' | 'red'
 *   data     内容（各 kind 不同）
 *   L        Layout 对象
 *   hit      关键词成交时刻（秒）
 *   t0/t1    场景起止（秒）
 */
function build(cfg) {
  const { kind, theme = 'paper', data, L, hit, t0, t1 } = cfg;
  const sc = document.createElement('div');
  sc.className = 'scene';
  // 微推容器：包住场景内容，只做 scale，不影响场景自己的 transform
  const zoom = document.createElement('div');
  zoom.style.cssText = 'position:absolute;inset:0;transform-origin:50% 46%;will-change:transform';
  sc.appendChild(zoom);
  sc.__zoom = zoom;
  const bg = THEME_BG[theme], fg = THEME_FG[theme], sub = THEME_SUB[theme];
  const fs = (k, w = 700, lh = 1.2) => `font:${w} ${L.font(k)}px/${lh} ${FF}`;

  const upd = BUILDER[kind];
  if (!upd) {
    sc.innerHTML = `<div style="position:absolute;inset:0;display:flex;align-items:center;
      justify-content:center;color:${fg};${fs('h1')}">未知场景: ${kind}</div>`;
    return { el: sc, update: () => {} };
  }

  // ⛔ 已禁用：全屏呼吸遮罩
  //
  // 曾经在这里加过一层全屏 alpha 波动，把卡字率从 60% 拉到 100%。
  // 但实测证明它只是「制造了亮度抖动」，不是内容在动：
  //
  //   每像素时间标准差  0.26 → 7.75 灰阶   （涨 30 倍）
  //   帧内空间标准差   31.03 → 29.20      （几乎不变）
  //   → 全屏同相位亮暗波动，没有任何「内容在动」的信息
  //
  // 23.7 灰阶 / 6 Hz 的全屏闪动，人眼能看到，但那是闪烁不是动画。
  // 而且它只在检测窗口里打开 —— 纯粹为了过指标。
  //
  // 正确的做法：让场景动画本身够大、够真实。
  // 指标上不去，说明动画真的不够，那就去改动画。
  // 场景写进 zoom（内层），微推加在 sc（外层），互不覆盖
  const inner = upd({ sc: zoom, L, data, hit, t0, t1, fg, sub, bg, fs, theme });

  // ═══════════════════════════════════════════════════════
  // 微推：整段 scale 1.000 → 1.035
  //
  // 「活着」的底噪。但有一条硬约束（PITFALLS 37）：
  //   before 窗口 = [hit-1.35, hit-0.45]
  //   摄像机运动必须在 hit-1.4s 之前收住，否则污染 before
  //
  // 所以曲线不是「整段线性」，而是：
  //   t0            → 1.000
  //   hit-1.40      → 1.035   （大部分推镜在 before 之前完成）
  //   hit-1.40 之后 → 冻结在 1.035，不再变化
  //
  // 这样 hit 附近的画面是绝对静止的，before 窗口内也没有变化。
  // 实测 before 从 0.05-0.07 未受影响。
  // ═══════════════════════════════════════════════════════
  const SCALE_FROM = 1.000;
  const SCALE_TO   = 1.035;
  const freezeAt   = hit - 1.40;         // 之后冻结
  const pushEnd    = Math.max(t0 + 0.35, freezeAt);

  return {
    el: sc,
    update: (time) => {
      inner(time);
      // 线性推镜，到 freezeAt 停住
      const k = CL((time - t0) / Math.max(0.01, pushEnd - t0));
      const sc_ = SCALE_FROM + (SCALE_TO - SCALE_FROM) * k;
      // 用 transform 会覆盖场景自己的 transform，改用独立的 zoom 层
      if (sc.__zoom) {
        sc.__zoom.style.transform = `scale(${sc_})`;
      }
    },
  };
}

// ══════════════════════════════════════════════════════════
// 各场景的 DOM + 动画
// 约定：build 返回 update(t) 函数；动画必须在 [hit - 0.40, hit+0.15] 内持续变化
// ══════════════════════════════════════════════════════════
const BUILDER = {};

// ─── 1. hero 大标题 ───
BUILDER.hero = ({ sc, L, data, hit, t0, fg, sub, fs }) => {
  const { title = '', kicker = '', note = '' } = data;
  const G = L.G;
  const land = L.isLandscape;
  const O = L.pad('outer');

  // ═══════════════════════════════════════════════════════
  // 网格排版：先定字号，再让文字和底线都吸附到「文字实际占几栏」
  //
  // 之前错在「先定 10 栏，再按 10 栏缩字号」→ 字只占 4 栏，右侧空 6 栏。
  // 正确顺序：
  //   ① 用满宽（横屏 7 栏 / 竖屏 10 栏）算字号
  //   ② 量文字实际宽度，换算成占几栏
  //   ③ 底线宽度 = 文字实际宽度（不是栏宽）
  // ═══════════════════════════════════════════════════════
  const maxW = land ? G.col(0, 7).w : G.col(0, 10).w;
  const heroSize = L.fitFont(title, maxW, 'hero', 1);
  const textW = L.measureText(title, heroSize, 700);

  // 底线：比文字略短（85%），视觉上像「压住」而不是「框住」
  const ruleW = Math.round(textW * 0.85);

  // ═══ 纵向：整块在 [区顶, 字幕顶] 之间垂直居中 ═══
  // 之前固定 22% 起点，导致下方空 60%。改为算完总高再居中。
  const RULE_H = Math.max(2, Math.round(L.H / 640));
  const GAP = L.pad('gap');
  const kickerH = kicker ? Math.round(L.font('h2') * 1.4) : 0;
  const titleH = Math.round(heroSize * 1.08);
  const noteH = note ? Math.round(L.font('body') * 1.7 * 2) : 0;   // 预留 2 行

  // 竖屏：kicker → title → rule → note 纵向堆叠
  // 横屏：kicker → title → rule 在左，note 在右（与 title 顶对齐），总高取两者较大
  const stackH = kickerH + (kicker ? GAP : 0) + titleH + Math.round(GAP * 0.5)
                 + RULE_H + (note && !land ? Math.round(GAP * 1.4) + noteH : 0);
  const blockH = land ? Math.max(stackH, titleH + noteH) : stackH;

  const zoneTop = L.px(14, 'h');
  const zoneBot = L.px(land ? 76 : 82, 'h');
  const topY = L.snap4(zoneTop + Math.max(0, (zoneBot - zoneTop - blockH) / 2));

  const titleTop = L.snap4(topY + (kicker ? kickerH + GAP : 0));
  const ruleY = L.snap4(titleTop + titleH + Math.round(GAP * 0.5));

  // note：竖屏在底线下方、跨 8 栏；横屏在右 4 栏、与巨字顶对齐
  const noteCol = land ? G.col(8, 4) : G.col(0, 8);
  const noteTop = land ? titleTop : L.snap4(ruleY + Math.round(GAP * 1.4));

  sc.innerHTML = `
    ${kicker ? `<div id="hk" style="position:absolute;left:${G.x(0)}px;top:${topY}px;
      width:${maxW}px;color:${sub};${fs('h2', 600, 1.4)};letter-spacing:.02em;
      opacity:0">${kicker}</div>` : ''}
    <div id="ht" style="position:absolute;left:${G.x(0)}px;top:${titleTop}px;
      width:${maxW}px;
      color:${fg};font:600 ${heroSize}px/1.10 ${FF_SERIF};letter-spacing:-.01em;
      text-align:left;opacity:0;overflow:visible">${title}</div>
    <div id="hl" style="position:absolute;left:${G.x(0)}px;top:${ruleY}px;
      width:0;height:${RULE_H}px;background:${fg};opacity:0"></div>
    ${note ? `<div id="hn" style="position:absolute;left:${noteCol.x}px;top:${noteTop}px;
      width:${noteCol.w}px;color:${sub};${fs('body', 500, 1.7)};
      text-wrap:balance;opacity:0">${note}</div>` : ''}`;

  const k = sc.querySelector('#hk'), t = sc.querySelector('#ht'),
        n = sc.querySelector('#hn'), l = sc.querySelector('#hl');
  return (time) => {
    // ⭐ 标题：从下方「顶上来」并压到底线，同时底部横线从左到右长出来。
    //    这两个都是真实位移 + 真实面积变化，不靠亮度波动。
    //    位移距离 = 字高的 35%（约 90px），横线从 0 长到 100% 宽。
    const p = SPR(time, hit - 0.40, hit);
    const k01 = CL(p);
    if (t) {
      t.style.opacity = CL((time - (hit - 0.40)) / 0.20);
      // 从下方 35% 字高升到位
      t.style.transform = `translateY(${LP(heroSize * 0.35, 0, k01)}px)`;
    }
    // 底线：hit 时刻正好铺满
    if (l) {
      const lp = CL((time - (hit - 0.40)) / 0.52);
      l.style.opacity = CL((time - (hit - 0.40)) / 0.16);
      l.style.width = (E.standard(lp) * ruleW) + 'px';
    }
    // kicker 提前 12 帧出现
    if (k) k.style.opacity = CL((time - (hit - 2.50)) / 0.20);
    // ⚠️ note 用「进场后 1.0 秒」而不是「hit+0.3」
    // 因为 hit 可能很晚（段01 的关键词在 3.62s，note 就永远不显示）
    if (n) n.style.opacity = CL((time - (t0 + 1.0)) / 0.30);
  };
};

// ─── 2. points N 个要点 ───
BUILDER.points = ({ sc, L, data, hit, fg, sub, fs }) => {
  const items = data.items || [];
  const n = items.length;
  const O = L.pad('outer');
  // 横屏：N 栏；竖屏：N 行
  // 竖屏用 10 栏宽、横屏用满宽
  const sl = L.slots(n).map(s => L.isLandscape ? s : Object.assign({}, s, { w: L.G.col(0, 10).w }));
  const html = items.map((it, i) => {
    const r = sl[i];
    // ⭐ 左对齐：气泡和文字都从容器左边缘开始（align-items:flex-start）
    //    竖屏时把整块推到栏线，横屏时每栏各占一段
    const gapY = Math.round(L.pad('gap') * 0.55);
    return `<div class="pt" data-i="${i}" style="position:absolute;
      left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;
      display:flex;flex-direction:column;align-items:flex-start;justify-content:center;
      gap:${gapY}px;opacity:0">
      <div style="width:${Math.round(L.font('h1')*0.92)}px;height:${Math.round(L.font('h1')*0.92)}px;
        border-radius:50%;background:transparent;border:2px solid ${fg};color:${fg};display:flex;
        align-items:center;justify-content:center;${fs('h2',700)};flex:none;
        margin-bottom:${Math.round(L.pad('gap')*0.30)}px">${i+1}</div>
      <div style="width:100%;color:${fg};font-family:${FF_SERIF};font-size:${Math.round(L.font('h2')*1.05)}px;font-weight:600;line-height:1.35;text-align:left">${it.title || it}</div>
      ${it.desc ? `<div style="width:100%;color:${sub};${fs('label',500,1.5)};text-align:left">${it.desc}</div>` : ''}
    </div>`;
  }).join('');
  sc.innerHTML = html;

  const els = [...sc.querySelectorAll('.pt')];
  return (time) => {
    els.forEach((e, i) => {
      const isKw = (i === n - 1);
      // 非关键词项：在 hit-2.0s 前依次出现完（不污染 before）
      // 关键词项：在 hit 时刻从下方升起 40% 行高（大位移）
      const st = isKw ? hit - 0.40 : (hit - 2.00 + i * 0.13);
      const k = CL((time - st) / (isKw ? 0.58 : 0.18));
      e.style.opacity = isKw ? CL((time - (hit - 0.40)) / 0.24) : k;
      const dist = isKw ? sl[i].h * 1.4 : 24;
      e.style.transform = `translateY(${LP(dist, 0, isKw ? E.standard(k) : E.smooth(k))}px)`;
    });
  };
};

// ─── 3. steps 步骤流程 ───
BUILDER.steps = ({ sc, L, data, hit, fg, sub, fs }) => {
  const items = data.items || [];
  const n = items.length;
  const land = L.isLandscape;
  const O = L.pad('outer');
  const top = L.px(22, 'h'), bot = L.px(76, 'h');
  const gap = L.pad('gap');
  // 横屏横向排，竖屏纵向排
  const each = land
    ? (L.W - O*2 - gap*(n-1)) / n
    : (bot - top - gap*(n-1)) / n;

  const html = items.map((it, i) => {
    const x = land ? Math.round(O + i*(each+gap)) : O;
    const y = land ? top : Math.round(top + i*(each+gap));
    const w = land ? Math.round(each) : Math.round(L.W - O*2);
    const h = land ? Math.round(bot - top) : Math.round(each);
    return `<div class="st" data-i="${i}" style="position:absolute;
      left:${x}px;top:${y}px;width:${w}px;height:${h}px;
      display:flex;${land?'flex-direction:column':'flex-direction:row'};
      align-items:center;justify-content:center;gap:${gap}px;opacity:0">
      <div style="width:${Math.round(L.font('h1')*0.95)}px;height:${Math.round(L.font('h1')*0.95)}px;
        border-radius:${Math.round(L.font('h1')*0.2)}px;background:transparent;border:2px solid ${fg};color:${fg};
        display:flex;align-items:center;justify-content:center;${fs('h2',700)};flex:none">${i+1}</div>
      <div style="color:${fg};font-family:${FF_SERIF};font-size:${Math.round(L.font('h2')*1.05)}px;font-weight:600;line-height:1.3;text-align:left">${it.title||it}</div>
    </div>`;
  }).join('');
  sc.innerHTML = html;

  const els = [...sc.querySelectorAll('.st')];
  return (time) => {
    els.forEach((e, i) => {
      const isKw = (i === n - 1);
      const st = isKw ? hit - 0.40 : (hit - 1.90 + i * 0.12);
      const k = CL((time - st) / (isKw ? 0.58 : 0.18));
      e.style.opacity = isKw ? CL((time - (hit - 0.40)) / 0.24) : k;
      // 关键词项：横向推入 40% 可用宽度（大位移）
      const dist = isKw ? (land ? L.W * 0.22 : L.W * 0.40) : 30;
      e.style.transform = `translateX(${LP(-dist, 0, E.standard(k))}px)`;
    });
  };
};

// ─── 4. compare 左右对比 ───
BUILDER.compare = ({ sc, L, data, hit, fg, sub, fs, theme }) => {
  const { left = {}, right = {}, title = '' } = data;
  const G = L.G;
  const O = L.pad('outer');
  // 标题占了上面，色块要往下让
  const top = L.px(title ? 26 : 18, 'h'), bot = L.px(78, 'h');
  const land = L.isLandscape;
  const gap = L.pad('gap') * 1.2;

  let lx, ly, lw, lh, rx, ry, rw, rh;
  if (land) {
    const ew = (L.W - O*2 - gap) / 2;
    lx = O; ly = top; lw = Math.round(ew); lh = Math.round(bot - top);
    rx = Math.round(O + ew + gap); ry = top; rw = Math.round(ew); rh = Math.round(bot - top);
  } else {
    const eh = (bot - top - gap) / 2;
    lx = O; ly = top; lw = Math.round(L.W - O*2); lh = Math.round(eh);
    rx = O; ry = Math.round(top + eh + gap); rw = Math.round(L.W - O*2); rh = Math.round(eh);
  }

  sc.innerHTML = `
    ${title ? `<div style="position:absolute;left:${O}px;top:${L.px(15,'h')}px;
      width:${L.W-O*2}px;color:${fg};${fs('label',700,1.2)};text-align:left;
      letter-spacing:.10em;
      letter-spacing:.06em">${title}</div>` : ''}
    <div id="cmpL" style="position:absolute;left:${lx}px;top:${ly}px;width:${lw}px;height:${lh}px;
      border-radius:${Math.round(L.font('body')*0.28)}px;background:${left.color||C.soft};
      display:flex;flex-direction:column;align-items:flex-start;justify-content:center;
      gap:${Math.round(L.pad('gap')*0.5)}px;opacity:.30;box-sizing:border-box;padding:0 6%;overflow:hidden">
      <div class="ht"></div>
      <div style="color:#fff;${fs('h2',700,1.25)};text-align:left;font-family:${FF_SERIF};font-weight:600">${left.title||''}</div>
      ${left.desc ? `<div style="color:rgba(255,255,255,.8);${fs('label',500,1.4)};text-align:left">${left.desc}</div>` : ''}
    </div>
    <div id="cmpR" style="position:absolute;left:${rx}px;top:${ry}px;width:${rw}px;height:${rh}px;
      border-radius:${Math.round(L.font('body')*0.28)}px;background:${right.color||C.warm};
      display:flex;flex-direction:column;align-items:flex-start;justify-content:center;
      gap:${Math.round(L.pad('gap')*0.5)}px;opacity:.30;box-sizing:border-box;padding:0 6%;overflow:hidden">
      <div class="ht"></div>
      <div style="color:#fff;${fs('h2',700,1.25)};text-align:left;font-family:${FF_SERIF};font-weight:600">${right.title||''}</div>
      ${right.desc ? `<div style="color:rgba(255,255,255,.85);${fs('label',500,1.4)};text-align:left">${right.desc}</div>` : ''}
    </div>`;

  const el = sc.querySelector('#cmpL'), er = sc.querySelector('#cmpR');
  return (time) => {
    // 左边：铺垫，在 hit-2.4s 前就位（不进 before 窗口）
    const kl = CL((time - (hit - 2.4)) / 0.30);
    el.style.opacity = LP(0.30, 0.72, E.smooth(kl));

    // 右边（关键词）：整块从右侧推入 1.2 栏宽 + 底色由浅到满
    // ⛔ 不用 boxShadow 发光（规格禁止，且是给检测器喂信号）
    // ⛔ 不动 width —— 会压扁 flex 容器把文字挤成竖排（实测踩过）
    const kr = CL(E.standard(CL((time - (hit - 0.40)) / 0.52)));
    er.style.opacity = LP(0.30, 1, CL((time - (hit - 0.40)) / 0.20));
    er.style.transform = `translateX(${LP(G.col(0, 1.2).w, 0, kr)}px)`;
    // 底色从半透明到不透明（真实面积感知，不改布局）
    er.style.filter = 'none';   // 显式清除（防止旧版本残留）
  };
};

// ─── 5. number 大数字 ───
BUILDER.number = ({ sc, L, data, hit, fg, sub, fs }) => {
  const { value = '', unit = '', label = '', sublabel = '' } = data;
  const O = L.pad('outer');
  const col = L.G.col(0, 11);
  const heroSize = L.fitFont(value + unit, col.w, 'hero', 1);
  const labelSize = L.font('h2');
  const subSize = L.font('body');

  // 纵向：数字、标签、副标、底线 依次排，整块在 18%~78% 之间居中
  const RULE_H = Math.max(2, Math.round(L.H / 640));
  const GAP = L.pad('gap');
  const numH = Math.round(heroSize * 1.08);
  const blockH = numH + (label ? Math.round(GAP * 1.6) + Math.round(labelSize * 1.3) : 0)
               + (sublabel ? Math.round(GAP * 0.6) + Math.round(subSize * 1.4) : 0)
               + Math.round(GAP * 0.9) + RULE_H;
  const zoneTop = L.px(20, 'h'), zoneBot = L.px(72, 'h');
  const topY = L.snap4(zoneTop + Math.max(0, (zoneBot - zoneTop - blockH) / 2));

  let cy = topY;
  const numTop = cy; cy += numH + Math.round(GAP * 1.6);
  const labelTop = cy; if (label) cy += Math.round(labelSize * 1.3) + Math.round(GAP * 0.9);
  const subTop = cy; if (sublabel) cy += Math.round(subSize * 1.4);
  // 底线在整块下方 1.2 个间距
  const ruleTop = cy + Math.round(GAP * 0.9);

  sc.innerHTML = `
    <div id="nb" style="position:absolute;left:${col.x}px;top:${numTop}px;
      width:${col.w}px;color:${C.warm};
      font:600 ${heroSize}px/1.02 ${FF_SERIF};letter-spacing:-.01em;
      text-align:left;opacity:0;transform:scale(.9)">${value}<span style="font-size:.42em;margin-left:.06em">${unit}</span></div>
    ${label ? `<div id="nl" style="position:absolute;left:${col.x}px;top:${labelTop}px;
      width:${col.w}px;color:${fg};font:600 ${labelSize}px/1.3 ${FF};
      letter-spacing:.02em;text-align:left;opacity:0">${label}</div>` : ''}
    ${sublabel ? `<div id="ns" style="position:absolute;left:${col.x}px;top:${subTop}px;
      width:${col.w}px;color:${sub};font:500 ${subSize}px/1.4 ${FF};
      text-align:left;opacity:0">${sublabel}</div>` : ''}
    <div id="nline" style="position:absolute;left:${col.x}px;top:${ruleTop}px;
      width:0;height:${RULE_H}px;background:${fg};opacity:0"></div>`;

  const b = sc.querySelector('#nb'), l = sc.querySelector('#nl'), s = sc.querySelector('#ns');
  return (time) => {
    // ⭐ 数字滚动 + 底线展开（真实动作，不靠亮度）
    // 起点 = 目标值的 70%，避免「0 → 100」这种夸张滚程
    const p = SPR(time, hit - 0.40, hit);
    const k = CL(p);
    b.style.opacity = CL((time - (hit - 0.40)) / 0.18);
    // 数字滚动
    const m = String(value).match(/^(-?[\d.]+)(.*)$/);
    if (m) {
      const target = parseFloat(m[1]), suffix = m[2];
      const from = target * 0.70;
      const cur = (from + (target - from) * k).toFixed(target % 1 === 0 ? 0 : 1);
      b.innerHTML = `${cur}${suffix}<span style="font-size:.42em;margin-left:.1em">${unit}</span>`;
    }
    // 底线从 0 展开到 60% 宽
    if (sc.querySelector('#nline')) {
      const nl = sc.querySelector('#nline');
      nl.style.opacity = CL((time - (hit - 0.40)) / 0.16);
      nl.style.width = (E.standard(CL((time - (hit - 0.40)) / 0.52)) * (L.W - O*2) * 0.30) + 'px';
    }
    if (l) l.style.opacity = CL((time - (hit + 0.05)) / 0.20);
    if (s) s.style.opacity = CL((time - (hit + 0.22)) / 0.22);
  };
};

// ─── 6. quote 引用 ───
BUILDER.quote = ({ sc, L, data, hit, fg, sub, fs }) => {
  const { text = '', who = '' } = data;
  const G = L.G;
  const land = L.isLandscape;

  // ═══════════════════════════════════════════════════════
  // 编辑排版：引号占第 0 栏，正文从第 1 栏起跨 9 栏（左对齐）
  //          署名右对齐到第 12 栏 —— 不是居中卡片
  // ═══════════════════════════════════════════════════════
  const quoteCol = land ? G.col(1, 9) : G.col(1, 10);
  const whoCol = G.col(6, 6);

  // 正文：h1 档，最多 3 行
  const bodySize = L.fitFont(text, quoteCol.w, 'h1', land ? 2 : 3);
  const bodyW = L.measureText(text, bodySize, 600);
  const lines = Math.max(1, Math.ceil(bodyW / quoteCol.w));
  const bodyH = Math.round(bodySize * 1.45 * lines);

  const RULE_H = Math.max(2, Math.round(L.H / 640));
  const GAP = L.pad('gap');

  // 纵向居中：引号 + 正文 + 底线
  const blockH = bodyH + Math.round(GAP * 1.2) + RULE_H;
  const zoneTop = L.px(16, 'h');
  const zoneBot = L.px(78, 'h');
  const bodyTop = L.snap4(zoneTop + Math.max(0, (zoneBot - zoneTop - blockH) / 2));

  // 引号：在正文左上，字号比正文大 1.6 倍
  const markSize = Math.round(bodySize * 1.6);
  const markTop = L.snap4(bodyTop - markSize * 0.55);

  const ruleY = L.snap4(bodyTop + bodyH + Math.round(GAP * 0.75));
  const ruleW = Math.round(Math.min(bodyW, quoteCol.w) * 0.62);

  sc.innerHTML = `
    <div id="qm" style="position:absolute;left:${G.x(0)}px;top:${markTop}px;
      width:${G.col(0, 1).w}px;
      color:${fg};font:600 ${markSize}px/0.8 ${FF_SERIF};
      opacity:.10;transform-origin:left top">“</div>
    <div id="qt" style="position:absolute;left:${quoteCol.x}px;top:${bodyTop}px;
      width:${quoteCol.w}px;
      color:${fg};font:600 ${bodySize}px/1.55 ${FF_SERIF};
      letter-spacing:-.01em;text-align:left;opacity:0">${text}</div>
    <div id="qline" style="position:absolute;left:${quoteCol.x}px;top:${ruleY}px;
      width:0;height:${RULE_H}px;background:${fg};opacity:0"></div>
    ${who ? `<div id="qw" style="position:absolute;left:${whoCol.x}px;
      top:${L.snap4(ruleY + GAP * 0.8)}px;width:${whoCol.w}px;
      color:${sub};${fs('label', 500, 1.3)};letter-spacing:.06em;
      text-align:right;opacity:0">—— ${who}</div>` : ''}`;

  const t = sc.querySelector('#qt'), w = sc.querySelector('#qw'),
        qm = sc.querySelector('#qm'), ql = sc.querySelector('#qline');

  // ⚠️ 硬规则（PITFALLS 37）：关键词动作启动必须 >= hit-0.44（更晚）
  //    hit-0.46 / 0.48 / 0.50 都在 before 窗口内！用 hit-0.40 留 3 帧余量
  //    铺垫（署名、引号）在 hit-1.9s 前完成，不污染 before
  return (time) => {
    if (w) w.style.opacity = CL((time - (hit - 2.6)) / 0.20);
    if (qm) {
      const kq = CL((time - (hit - 2.6)) / 0.24);
      qm.style.opacity = LP(0.10, 0.26, kq);
      qm.style.transform = `scale(${LP(0.80, 1, E.standard(kq))})`;
    }
    // 关键词元素：正文从左侧滑入 1.5 栏宽（真实位移）
    const px_ = CL(E.standard(CL((time - (hit - 0.40)) / 0.62)));
    t.style.opacity = CL((time - (hit - 0.40)) / 0.20);
    t.style.transform = `translateX(${LP(-G.col(0, 2.4).w, 0, px_)}px)`;
    // 底线从正文左边缘扫出
    if (ql) {
      ql.style.opacity = CL((time - (hit - 0.40)) / 0.16);
      ql.style.width = (E.standard(CL((time - (hit - 0.40)) / 0.62)) * ruleW) + 'px';
    }
  };
};

// ─── 7. before-after 改前改后 ───
BUILDER['before-after'] = ({ sc, L, data, hit, fg, sub, fs }) => {
  const { before = {}, after = {}, label1 = '改前', label2 = '改后' } = data;
  const O = L.pad('outer');
  const land = L.isLandscape;
  const top = L.px(20, 'h'), bot = L.px(78, 'h');
  const gap = L.pad('gap');

  let x1,y1,w1,h1,x2,y2,w2,h2;
  if (land) {
    const ew = (L.W - O*2 - gap) / 2;
    x1=O; y1=top; w1=Math.round(ew); h1=Math.round(bot-top);
    x2=Math.round(O+ew+gap); y2=top; w2=Math.round(ew); h2=Math.round(bot-top);
  } else {
    const eh = (bot-top-gap)/2;
    x1=O; y1=top; w1=Math.round(L.W-O*2); h1=Math.round(eh);
    x2=O; y2=Math.round(top+eh+gap); w2=Math.round(L.W-O*2); h2=Math.round(eh);
  }

  sc.innerHTML = `
    <div style="position:absolute;left:${x1}px;top:${y1}px;width:${w1}px;height:${h1}px;
      display:flex;flex-direction:column;align-items:flex-start;justify-content:center;
      gap:${Math.round(L.pad('gap')*0.55)}px;box-sizing:border-box;padding:0 ${Math.round(O*0.55)}px">
      <div style="color:${sub};${fs('label',600,1.2)};letter-spacing:.12em">${label1}</div>
      <div id="ba1" style="color:${sub};
        font:600 ${before.size || L.font('h1')}px/1.20 ${FF_SERIF};
        text-align:left;opacity:.55;letter-spacing:-.01em">${before.title||''}</div>
      ${before.desc?`<div style="color:${sub};${fs('label',500,1.4)};opacity:.7">${before.desc}</div>`:''}
    </div>
    <div style="position:absolute;left:${x2}px;top:${y2}px;width:${w2}px;height:${h2}px;
      display:flex;flex-direction:column;align-items:flex-start;justify-content:center;
      gap:${Math.round(L.pad('gap')*0.55)}px;box-sizing:border-box;padding:0 ${Math.round(O*0.55)}px">
      <div style="color:${C.warm};${fs('label',600,1.2)};letter-spacing:.12em">${label2}</div>
      <div id="ba2" style="color:${fg};
        font:600 ${after.size || L.font('h1')}px/1.20 ${FF_SERIF};
        text-align:left;opacity:0">${after.title||''}</div>
      ${after.desc?`<div id="ba2d" style="color:${sub};${fs('label',500,1.4)};opacity:0">${after.desc}</div>`:''}
    </div>`;

  const a1 = sc.querySelector('#ba1'), a2 = sc.querySelector('#ba2'), ad = sc.querySelector('#ba2d');
  return (time) => {
    // 改前保持暗淡
    a1.style.opacity = LP(0.55, 0.42, CL((time - (hit - 2.4)) / 0.28));
    // 改后在 hit 到位
    // 关键词：a2 整块从下方升起 22% 行高（真实位移，不是 scale）
    const p = CL(E.standard(CL((time - (hit - 0.40)) / 0.52)));
    a2.style.opacity = CL((time - (hit - 0.40)) / 0.20);
    const rise = Math.round(L.font('h1') * 0.34);
    a2.style.transform = `translateY(${LP(rise, 0, p)}px)`;
    if (ad) ad.style.opacity = CL((time - (hit - 0.40)) / 0.24);
  };
};

// ─── 8. list 清单 ───
BUILDER.list = ({ sc, L, data, hit, fg, sub, fs }) => {
  const items = data.items || [];
  const n = items.length;
  const O = L.pad('outer');
  const top = L.px(17, 'h'), bot = L.px(79, 'h');
  const gap = L.pad('gap') * 0.7;
  const each = (bot - top - gap*(n-1)) / n;

  sc.innerHTML = items.map((it, i) => {
    const y = Math.round(top + i*(each+gap));
    return `<div class="li" data-i="${i}" style="position:absolute;
      left:${O}px;top:${y}px;width:${L.W-O*2}px;height:${Math.round(each)}px;
      display:flex;align-items:center;gap:${L.pad('gap')}px;opacity:0">
      <div style="width:${Math.round(L.font('label')*1.1)}px;height:${Math.round(L.font('label')*1.1)}px;
        border-radius:50%;border:3px solid ${C.sage};display:flex;align-items:center;
        justify-content:center;color:${C.sage};${fs('label',700)};flex:none">✓</div>
      <div style="color:${fg};${fs('body',500,1.35)}">${it.title||it}</div>
    </div>`;
  }).join('');

  const els = [...sc.querySelectorAll('.li')];
  // ⚠️ 所有条目在 hit-2.1s ~ hit-1.5s 之间出现完（留 0.6s 给 before 窗口保持安静）
  const T_START = hit - 2.10;
  const PER = n > 1 ? Math.min(0.16, 0.55 / (n - 1)) : 0;
  return (time) => {
    els.forEach((e, i) => {
      const st = T_START + i * PER;
      const k = CL((time - st) / 0.16);
      // 关键词元素：最后一条在 hit 时刻整块左移到位（大位移，30% 屏宽）
      const isKw = (i === n - 1);
      e.style.opacity = k;
      e.style.transform = isKw
        ? `translateX(${LP(-L.W * 0.30, 0, E.standard(CL((time - (hit - 0.40)) / 0.52)))}px)`
        : `translateX(${LP(-L.W * 0.30, 0, E.standard(k))}px)`;
    });
  };
};

// ─── 9. product 产品展示 ───
BUILDER.product = ({ sc, L, data, hit, fg, sub, fs }) => {
  const { name = '', tagline = '', features = [] } = data;
  const hs = L.heroSplit(58);
  const O = L.pad('outer');
  const nameSize = L.fitFont(name, hs.main.w * 0.90, 'hero', 1);

  sc.innerHTML = `
    <div style="position:absolute;left:${hs.main.x}px;top:${hs.main.y}px;
      width:${hs.main.w}px;height:${hs.main.h}px;
      display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:${L.pad('gap')}px">
      <div id="pn" style="color:${fg};font:600 ${nameSize}px/1.10 ${FF_SERIF};letter-spacing:-.01em;text-align:left;
        opacity:0">${name}</div>
      <div id="pline" style="width:0;height:${Math.max(3, Math.round(L.H/640))}px;
        background:${fg};opacity:0"></div>
      ${tagline ? `<div id="pt" style="color:${sub};${fs('h2',600,1.35)};
        text-align:left;opacity:0">${tagline}</div>` : ''}
    </div>
    <div style="position:absolute;left:${hs.side.x}px;top:${hs.side.y}px;
      width:${hs.side.w}px;height:${hs.side.h}px;
      display:flex;flex-direction:column;justify-content:center;gap:${L.pad('gap')}px">
      ${features.map((f,i)=>`<div class="pf" data-i="${i}" style="color:${sub};
        ${fs('body',500,1.4)};opacity:0">· ${f}</div>`).join('')}
    </div>`;

  const pn = sc.querySelector('#pn'), pt = sc.querySelector('#pt');
  const pfs = [...sc.querySelectorAll('.pf')];
  const pl = sc.querySelector('#pline');
  return (time) => {
    // 铺垫：特性全部在 hit-1.8s 前出现完，不污染 before
    pfs.forEach((e, i) => {
      e.style.opacity = CL((time - (hit - 2.90 + i * 0.11)) / 0.14);
    });
    if (pt) pt.style.opacity = CL((time - (hit - 2.50)) / 0.20);
    // 关键词元素：产品名从下方升起 30% 字高 + 底线展开
    const k01 = CL(E.standard(CL((time - (hit - 0.40)) / 0.52)));
    pn.style.opacity = CL((time - (hit - 0.40)) / 0.20);
    pn.style.transform = `translateY(${LP(nameSize * 0.42, 0, k01)}px)`;
    if (pl) {
      pl.style.opacity = CL((time - (hit - 0.40)) / 0.16);
      pl.style.width = (E.standard(CL((time - (hit - 0.40)) / 0.52)) * hs.main.w * 0.45) + 'px';
    }
  };
};

// ─── 10. cta 行动号召 ───
BUILDER.cta = ({ sc, L, data, hit, t0, fg, sub, fs }) => {
  const { main = '', subline = '', action = '' } = data;
  const O = L.pad('outer');
  const mainSize = L.fitFont(main, L.G.col(0, 11).w, 'h1', 1);
  sc.innerHTML = `
    <div style="position:absolute;left:${O}px;width:${L.G.col(0,11).w}px;
      top:${L.px(22,'h')}px;text-align:left">
      <div id="cm" style="color:${fg};font:600 ${mainSize}px/1.30 ${FF_SERIF};letter-spacing:-.01em;opacity:0">${main}</div>
      <div id="cline" style="display:inline-block;width:0;
        height:${Math.max(3, Math.round(L.H/640))}px;background:${fg};opacity:0;
        margin-top:${Math.round(L.pad('gap')*0.6)}px"></div>
      ${subline ? `<div id="cs" style="margin-top:${L.pad('gap')}px;color:${sub};
        ${fs('h2',500,1.4)};opacity:0">${subline}</div>` : ''}
      ${action ? `<div id="ca" style="margin-top:${Math.round(L.pad('gap')*1.4)}px;
        display:inline-block;padding:${Math.round(L.font('body')*0.5)}px ${Math.round(L.font('body')*1.2)}px;
        border-radius:${Math.round(L.font('body')*0.6)}px;background:${C.warm};color:#fff;position:relative;overflow:hidden;
        ${fs('h2',700,1.2)};opacity:0">${action}</div>` : ''}
    </div>`;
  const m = sc.querySelector('#cm'), s = sc.querySelector('#cs'), a = sc.querySelector('#ca');
  return (time) => {
    // 关键词元素：主标题从下方升起 32% 字高 + 底线展开
    const k01 = CL(E.standard(CL((time - (hit - 0.40)) / 0.52)));
    m.style.opacity = CL((time - (hit - 0.40))/0.18);
    m.style.transform = `translateY(${LP(mainSize * 0.44, 0, k01)}px)`;
    if (sc.querySelector('#cline')) {
      const cl = sc.querySelector('#cline');
      cl.style.opacity = CL((time - (hit - 0.40)) / 0.16);
      cl.style.width = (E.standard(CL((time - (hit - 0.40)) / 0.52)) * (L.W - O*2) * 0.30) + 'px';
    }
    // 铺垫：副标题和按钮在 hit-1.9s 前出现完（不污染 before）
    if (s) s.style.opacity = CL((time - (hit - 2.20))/0.28);
    if (a) {
      const q = CL((time - (hit - 1.90))/0.25);
      a.style.opacity = q;
      a.style.transform = `scale(${LP(0.9,1,E.standard(q))})`;
    }
  };
};

window.Scenes = { build, C, BUILDER, THEME_BG, THEME_FG, THEME_SUB };

})();
