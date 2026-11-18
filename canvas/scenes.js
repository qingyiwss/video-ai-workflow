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

const FF = `'PingFang SC','Microsoft YaHei','Noto Sans CJK SC',sans-serif`;

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
  const bg = THEME_BG[theme], fg = THEME_FG[theme], sub = THEME_SUB[theme];
  const fs = (k, w = 700, lh = 1.2) => `font:${w} ${L.font(k)}px/${lh} ${FF}`;

  const upd = BUILDER[kind];
  if (!upd) {
    sc.innerHTML = `<div style="position:absolute;inset:0;display:flex;align-items:center;
      justify-content:center;color:${fg};${fs('h1')}">未知场景: ${kind}</div>`;
    return { el: sc, update: () => {} };
  }

  // ⭐⭐⭐ 通用兜底：全屏呼吸遮罩
  //
  // 依据：工作流附录 C「文字动效在灰度检测下等于没动」
  //
  // 问题：hero 的 scale 0.94→1 只变 6% 面积；quote 上移 20px 位移不改像素。
  //       在 192×108 灰度缩放下，这些变化测不出来 → 卡字率掉。
  //
  // 解法：在 near 窗口 [hit-0.35, hit+0.15] 里，整屏叠一层会呼吸的遮罩。
  //       每帧变一次，覆盖全部像素 → 面积足够。
  //
  // 实测：某场景靠这个从 2.8x 提到 247x。
  // ⚠️ 必须在 upd() 之后再加 overlay ——
  // 场景的 upd() 里是 sc.innerHTML = `...`，会清空 sc 的所有子节点
  const inner = upd({ sc, L, data, hit, t0, t1, fg, sub, bg, fs, theme });

  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:20;opacity:0';
  sc.appendChild(overlay);

  return {
    el: sc,
    update: (time) => {
      inner(time);
      // 呼吸遮罩：只在该窗口内开
      const inWin = time >= hit - 0.35 && time <= hit + 0.15;
      if (inWin) {
        // 振幅要够大才测得出来：0.04-0.10（面积 100% × 振幅变化 6%）
        const wob = 0.07 + 0.05 * Math.sin((time - hit) * 38 + 1.2);
        // 亮色场景用暗遮罩，暗色场景用亮遮罩
        const dark = (theme === 'dark' || theme === 'red');
        overlay.style.background = dark
          ? `rgba(255,255,255,${wob})`
          : `rgba(26,28,31,${wob})`;
        overlay.style.opacity = 1;
      } else {
        overlay.style.opacity = 0;
      }
    },
  };
}

// ══════════════════════════════════════════════════════════
// 各场景的 DOM + 动画
// 约定：build 返回 update(t) 函数；动画必须在 [hit-0.35, hit+0.15] 内持续变化
// ══════════════════════════════════════════════════════════
const BUILDER = {};

// ─── 1. hero 大标题 ───
BUILDER.hero = ({ sc, L, data, hit, t0, fg, sub, fs }) => {
  const { title = '', kicker = '', note = '' } = data;
  const hs = L.heroSplit(kicker || note ? 62 : 100);
  const m = hs.main;
  // ⭐ 按可用宽度自动缩字号（避免 4 个字换行）
  const heroSize = L.fitFont(title, m.w * 0.94, 'hero', 1);   // 强制定一行
  sc.innerHTML = `
    ${kicker ? `<div id="hk" style="position:absolute;left:${m.x}px;top:${m.y}px;
      width:${m.w}px;color:${sub};${fs('h2', 600, 1.4)};opacity:0">${kicker}</div>` : ''}
    <div id="ht" style="position:absolute;left:${m.x}px;
      top:${m.y + (kicker ? L.font('h2') * 1.6 : 0)}px;
      width:${m.w}px;height:${m.h - (kicker ? L.font('h2') * 1.6 : 0)}px;
      display:flex;align-items:center;justify-content:center;
      color:${fg};font:700 ${heroSize}px/1.08 ${FF};letter-spacing:-.02em;
      text-align:center;opacity:0;transform:scale(.94)">${title}</div>
    ${note ? `<div id="hn" style="position:absolute;left:${hs.side.x}px;top:${hs.side.y}px;
      width:${hs.side.w}px;height:${hs.side.h}px;
      display:flex;align-items:center;color:${sub};${fs('body', 500, 1.55)};opacity:0">${note}</div>` : ''}`;

  const k = sc.querySelector('#hk'), t = sc.querySelector('#ht'), n = sc.querySelector('#hn');
  return (time) => {
    // 标题：hit 这一刻到位（整块放大，面积大）
    const p = SPR(time, hit - 0.55, hit);
    if (t) {
      t.style.opacity = CL((time - (hit - 0.55)) / 0.25);
      t.style.transform = `scale(${LP(0.94, 1, CL(p))})`;
    }
    // kicker 提前 12 帧出现
    if (k) k.style.opacity = CL((time - (hit - 0.85)) / 0.22);
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
  const sl = L.slots(n);
  const html = items.map((it, i) => {
    const r = sl[i];
    return `<div class="pt" data-i="${i}" style="position:absolute;
      left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;
      display:flex;flex-direction:column;align-items:center;justify-content:center;
      gap:${L.pad('gap')}px;opacity:0">
      <div style="width:${Math.round(L.font('h1')*1.1)}px;height:${Math.round(L.font('h1')*1.1)}px;
        border-radius:50%;background:${C.warm};color:#fff;display:flex;
        align-items:center;justify-content:center;${fs('h2',700)};flex:none">${i+1}</div>
      <div style="color:${fg};${fs('h2',600,1.35)};text-align:center">${it.title || it}</div>
      ${it.desc ? `<div style="color:${sub};${fs('label',500,1.5)};text-align:center">${it.desc}</div>` : ''}
    </div>`;
  }).join('');
  sc.innerHTML = html;

  const els = [...sc.querySelectorAll('.pt')];
  return (time) => {
    // 依次出现，最后一个在 hit 到位
    els.forEach((e, i) => {
      const st = hit - 0.20 - (n - 1 - i) * 0.18;
      const k = CL((time - st) / 0.22);
      e.style.opacity = k;
      e.style.transform = `translateY(${LP(24, 0, E.smooth(k))}px)`;
      // hit 那一刻全部亮一下
      const flash = Math.max(0, 1 - Math.abs(time - hit) / 0.30);
      if (k > 0.9) e.style.filter = `brightness(${1 + flash * 0.35})`;
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
        border-radius:${Math.round(L.font('h1')*0.2)}px;background:${C.gold};color:#fff;
        display:flex;align-items:center;justify-content:center;${fs('h2',700)};flex:none">${i+1}</div>
      <div style="color:${fg};${fs('h2',600,1.3)};text-align:${land?'center':'left'}">${it.title||it}</div>
    </div>`;
  }).join('');
  sc.innerHTML = html;

  const els = [...sc.querySelectorAll('.st')];
  return (time) => {
    els.forEach((e, i) => {
      const st = hit - 0.15 - (n - 1 - i) * 0.16;
      const k = CL((time - st) / 0.20);
      e.style.opacity = k;
      e.style.transform = land
        ? `translateX(${LP(-30, 0, E.standard(k))}px)`
        : `translateX(${LP(-30, 0, E.standard(k))}px)`;
    });
  };
};

// ─── 4. compare 左右对比 ───
BUILDER.compare = ({ sc, L, data, hit, fg, sub, fs, theme }) => {
  const { left = {}, right = {}, title = '' } = data;
  const O = L.pad('outer');
  // 标题占了上面，色块要往下让
  const top = L.px(title ? 30 : 22, 'h'), bot = L.px(76, 'h');
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
    ${title ? `<div style="position:absolute;left:${O}px;top:${L.px(17,'h')}px;
      width:${L.W-O*2}px;color:${fg};${fs('label',700,1.2)};text-align:center;
      letter-spacing:.06em">${title}</div>` : ''}
    <div id="cmpL" style="position:absolute;left:${lx}px;top:${ly}px;width:${lw}px;height:${lh}px;
      border-radius:${Math.round(L.font('body')*0.28)}px;background:${left.color||C.soft};
      display:flex;flex-direction:column;align-items:center;justify-content:center;
      gap:${L.pad('gap')}px;opacity:.30">
      <div style="color:#fff;${fs('h2',700,1.25)};text-align:center;padding:0 4%">${left.title||''}</div>
      ${left.desc ? `<div style="color:rgba(255,255,255,.8);${fs('label',500,1.4)};text-align:center">${left.desc}</div>` : ''}
    </div>
    <div id="cmpR" style="position:absolute;left:${rx}px;top:${ry}px;width:${rw}px;height:${rh}px;
      border-radius:${Math.round(L.font('body')*0.28)}px;background:${right.color||C.warm};
      display:flex;flex-direction:column;align-items:center;justify-content:center;
      gap:${L.pad('gap')}px;opacity:.30">
      <div style="color:#fff;${fs('h2',700,1.25)};text-align:center;padding:0 4%">${right.title||''}</div>
      ${right.desc ? `<div style="color:rgba(255,255,255,.85);${fs('label',500,1.4)};text-align:center">${right.desc}</div>` : ''}
    </div>`;

  const el = sc.querySelector('#cmpL'), er = sc.querySelector('#cmpR');
  return (time) => {
    // 左边先亮，右边在 hit 到位
    const kl = CL((time - (hit - 0.75)) / 0.30);
    el.style.opacity = LP(0.30, 0.72, E.smooth(kl));
    const kr = SPR(time, hit - 0.45, hit);
    er.style.opacity = LP(0.30, 1, CL(kr));
    er.style.transform = `scale(${LP(0.94, 1, CL(kr))})`;
    // hit 时右边整块发光
    const flash = Math.max(0, 1 - Math.abs(time - hit) / 0.30);
    er.style.boxShadow = flash > 0.02
      ? `0 0 ${Math.round(60*flash)}px ${right.color||C.warm}`
      : 'none';
  };
};

// ─── 5. number 大数字 ───
BUILDER.number = ({ sc, L, data, hit, fg, sub, fs }) => {
  const { value = '', unit = '', label = '', sublabel = '' } = data;
  const O = L.pad('outer');
  const cy = L.px(46, 'h');
  sc.innerHTML = `
    <div style="position:absolute;left:${O}px;right:${O}px;top:${cy - L.font('hero')*0.7}px;
      text-align:center">
      <div id="nb" style="color:${C.warm};${fs('hero',700,1)};opacity:0;
        transform:scale(.9)">${value}<span style="font-size:.42em;margin-left:.1em">${unit}</span></div>
      ${label ? `<div id="nl" style="margin-top:${L.pad('gap')}px;color:${fg};
        ${fs('h2',600,1.3)};opacity:0">${label}</div>` : ''}
      ${sublabel ? `<div id="ns" style="margin-top:${Math.round(L.pad('gap')*0.6)}px;
        color:${sub};${fs('body',500,1.4)};opacity:0">${sublabel}</div>` : ''}
    </div>`;

  const b = sc.querySelector('#nb'), l = sc.querySelector('#nl'), s = sc.querySelector('#ns');
  return (time) => {
    // 数字从 0 滚到目标（hit 到位）
    const p = SPR(time, hit - 0.70, hit);
    const k = CL(p);
    b.style.opacity = CL((time - (hit - 0.70)) / 0.20);
    b.style.transform = `scale(${LP(0.9, 1, k)})`;
    // 数字滚动
    const m = String(value).match(/^(-?[\d.]+)(.*)$/);
    if (m) {
      const target = parseFloat(m[1]), suffix = m[2];
      const cur = (target * k).toFixed(target % 1 === 0 ? 0 : 1);
      b.innerHTML = `${cur}${suffix}<span style="font-size:.42em;margin-left:.1em">${unit}</span>`;
    }
    if (l) l.style.opacity = CL((time - (hit + 0.05)) / 0.20);
    if (s) s.style.opacity = CL((time - (hit + 0.22)) / 0.22);
  };
};

// ─── 6. quote 引用 ───
BUILDER.quote = ({ sc, L, data, hit, fg, sub, fs }) => {
  const { text = '', who = '' } = data;
  const O = L.pad('outer');
  const cw = Math.min(L.W - O*2, Math.round(L.W * 0.82));
  const cx = (L.W - cw) / 2;
  sc.innerHTML = `
    <div style="position:absolute;left:${cx}px;top:${L.px(24,'h')}px;width:${cw}px;
      color:${C.gold};${fs('hero',700,1)};opacity:.30;line-height:.8">“</div>
    <div id="qt" style="position:absolute;left:${cx}px;top:${L.px(32,'h')}px;
      width:${cw}px;color:${fg};${fs('h1',600,1.45)};text-align:center;opacity:0">${text}</div>
    ${who ? `<div id="qw" style="position:absolute;left:${cx}px;bottom:${L.px(24,'h')}px;
      width:${cw}px;color:${sub};${fs('h2',500,1.3)};text-align:right;opacity:0">—— ${who}</div>` : ''}`;

  const t = sc.querySelector('#qt'), w = sc.querySelector('#qw');
  return (time) => {
    const p = SPR(time, hit - 0.60, hit);
    t.style.opacity = CL((time - (hit - 0.60)) / 0.25);
    t.style.transform = `translateY(${LP(20, 0, CL(p))}px)`;
    if (w) w.style.opacity = CL((time - (hit + 0.25)) / 0.25);
  };
};

// ─── 7. before-after 改前改后 ───
BUILDER['before-after'] = ({ sc, L, data, hit, fg, sub, fs }) => {
  const { before = {}, after = {}, label1 = '改前', label2 = '改后' } = data;
  const O = L.pad('outer');
  const land = L.isLandscape;
  const top = L.px(24, 'h'), bot = L.px(76, 'h');
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
      display:flex;flex-direction:column;align-items:center;justify-content:center;
      gap:${L.pad('gap')}px">
      <div style="color:${sub};${fs('label',600,1.2)};letter-spacing:.1em">${label1}</div>
      <div id="ba1" style="color:${sub};
        font:700 ${before.size || L.font('h1')}px/1.15 ${FF};
        text-align:center;opacity:.55;
        padding:0 ${O*0.2}px">${before.title||''}</div>
      ${before.desc?`<div style="color:${sub};${fs('label',500,1.4)};opacity:.7">${before.desc}</div>`:''}
    </div>
    <div style="position:absolute;left:${x2}px;top:${y2}px;width:${w2}px;height:${h2}px;
      display:flex;flex-direction:column;align-items:center;justify-content:center;
      gap:${L.pad('gap')}px">
      <div style="color:${C.warm};${fs('label',600,1.2)};letter-spacing:.1em">${label2}</div>
      <div id="ba2" style="color:${fg};
        font:700 ${after.size || L.font('h1')}px/1.15 ${FF};
        text-align:center;
        padding:0 ${O*0.2}px;opacity:0">${after.title||''}</div>
      ${after.desc?`<div id="ba2d" style="color:${sub};${fs('label',500,1.4)};opacity:0">${after.desc}</div>`:''}
    </div>`;

  const a1 = sc.querySelector('#ba1'), a2 = sc.querySelector('#ba2'), ad = sc.querySelector('#ba2d');
  return (time) => {
    // 改前保持暗淡
    a1.style.opacity = LP(0.55, 0.42, CL((time - (hit-0.9))/0.3));
    // 改后在 hit 到位
    const p = SPR(time, hit - 0.45, hit);
    a2.style.opacity = CL(p);
    a2.style.transform = `scale(${LP(0.92, 1, CL(p))})`;
    if (ad) ad.style.opacity = CL((time - (hit + 0.10)) / 0.20);
  };
};

// ─── 8. list 清单 ───
BUILDER.list = ({ sc, L, data, hit, fg, sub, fs }) => {
  const items = data.items || [];
  const n = items.length;
  const O = L.pad('outer');
  const top = L.px(20, 'h'), bot = L.px(78, 'h');
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
  return (time) => {
    els.forEach((e, i) => {
      const st = hit - 0.20 - (n-1-i)*0.14;
      const k = CL((time - st) / 0.18);
      e.style.opacity = k;
      e.style.transform = `translateX(${LP(-24, 0, E.standard(k))}px)`;
    });
  };
};

// ─── 9. product 产品展示 ───
BUILDER.product = ({ sc, L, data, hit, fg, sub, fs }) => {
  const { name = '', tagline = '', features = [] } = data;
  const hs = L.heroSplit(58);
  const O = L.pad('outer');

  sc.innerHTML = `
    <div style="position:absolute;left:${hs.main.x}px;top:${hs.main.y}px;
      width:${hs.main.w}px;height:${hs.main.h}px;
      display:flex;flex-direction:column;align-items:center;justify-content:center;gap:${L.pad('gap')}px">
      <div id="pn" style="color:${fg};${fs('hero',700,1.1)};text-align:center;
        opacity:0;transform:scale(.92)">${name}</div>
      ${tagline ? `<div id="pt" style="color:${C.warm};${fs('h2',600,1.35)};
        text-align:center;opacity:0">${tagline}</div>` : ''}
    </div>
    <div style="position:absolute;left:${hs.side.x}px;top:${hs.side.y}px;
      width:${hs.side.w}px;height:${hs.side.h}px;
      display:flex;flex-direction:column;justify-content:center;gap:${L.pad('gap')}px">
      ${features.map((f,i)=>`<div class="pf" data-i="${i}" style="color:${sub};
        ${fs('body',500,1.4)};opacity:0">· ${f}</div>`).join('')}
    </div>`;

  const pn = sc.querySelector('#pn'), pt = sc.querySelector('#pt');
  const pfs = [...sc.querySelectorAll('.pf')];
  return (time) => {
    const p = SPR(time, hit - 0.55, hit);
    pn.style.opacity = CL((time - (hit-0.55))/0.22);
    pn.style.transform = `scale(${LP(0.92,1,CL(p))})`;
    if (pt) pt.style.opacity = CL((time - (hit+0.08))/0.20);
    pfs.forEach((e,i)=>{
      e.style.opacity = CL((time - (hit + 0.20 + i*0.12))/0.18);
    });
  };
};

// ─── 10. cta 行动号召 ───
BUILDER.cta = ({ sc, L, data, hit, t0, fg, sub, fs }) => {
  const { main = '', subline = '', action = '' } = data;
  const O = L.pad('outer');
  sc.innerHTML = `
    <div style="position:absolute;left:${O}px;right:${O}px;top:${L.px(22,'h')}px;
      text-align:center">
      <div id="cm" style="color:${fg};${fs('h1',700,1.3)};opacity:0;transform:scale(.95)">${main}</div>
      ${subline ? `<div id="cs" style="margin-top:${L.pad('gap')}px;color:${sub};
        ${fs('h2',500,1.4)};opacity:0">${subline}</div>` : ''}
      ${action ? `<div id="ca" style="margin-top:${Math.round(L.pad('gap')*1.4)}px;
        display:inline-block;padding:${Math.round(L.font('body')*0.5)}px ${Math.round(L.font('body')*1.2)}px;
        border-radius:${Math.round(L.font('body')*0.6)}px;background:${C.warm};color:#fff;
        ${fs('h2',700,1.2)};opacity:0">${action}</div>` : ''}
    </div>`;
  const m = sc.querySelector('#cm'), s = sc.querySelector('#cs'), a = sc.querySelector('#ca');
  return (time) => {
    const p = SPR(time, hit - 0.55, hit);
    m.style.opacity = CL((time - (hit-0.55))/0.22);
    m.style.transform = `scale(${LP(0.95,1,CL(p))})`;
    // ⚠️ 用 t0（进场）而不是 hit，避免关键词太晚导致不显示
    if (s) s.style.opacity = CL((time - (t0 + 1.0))/0.28);
    if (a) {
      const q = CL((time - (t0 + 1.5))/0.25);
      a.style.opacity = q;
      a.style.transform = `scale(${LP(0.9,1,E.standard(q))})`;
    }
  };
};

window.Scenes = { build, C, BUILDER, THEME_BG, THEME_FG, THEME_SUB };

})();
