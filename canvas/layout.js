// 布局引擎 —— 让同一套场景代码适配 9:16 竖屏 / 16:9 横屏 / 4:3 / 1:1
// 依据：工作流 5.14 字号表 + 5.9 场景架构
//
// 核心思想：
//   场景代码只写「语义」（标题在哪、内容区多大），
//   具体的像素由布局引擎按比例算出来。
//
// 用法：
//   const L = Layout.make('16:9');
//   L.W / L.H                画布尺寸
//   L.font('h1')             字号
//   L.pad('outer')           外边距
//   L.area('content')        内容区 {x,y,w,h}
//   L.stack('v', 3)          纵向三等分的高度

(function () {
'use strict';

// ── 三套基准设计 ──
// 所有数字都是「1080 宽」为基准的设计值，横屏按宽度等比放大，
// 但字号用「高度」算，免得横屏字太大。
const RATIOS = {
  '9:16':  { w: 1080, h: 1920, name: '竖屏' },
  '16:9':  { w: 1920, h: 1080, name: '横屏' },
  '4:3':   { w: 1440, h: 1080, name: '4:3' },
  '1:1':   { w: 1080, h: 1080, name: '方形' },
};

// ── 字号基准表（竖屏 1080×1920 实测，见工作流 5.14）──
// key: 用途  value: [竖屏 px, 缩放参考轴]
//   参考轴 'w' = 按宽度等比（横屏字会变大）
//         'h' = 按高度等比（横屏字保持）★ 推荐
//         'm' = 按 min(w,h) 等比（最保守）
// 参考轴：
//   'd' = 对角线等比（推荐）—— 字占屏幕的视觉比例一致，横屏和竖屏观感统一
//   'h' = 高度等比 —— 横屏字会显得小
//   'w' = 宽度等比 —— 横屏字会显得大
//
// 实测（2026-11-17）：
//   按 'h'：16:9 下 hero 只有 146px，在 1920 宽的屏幕里显得很小
//   按 'd'：16:9 下 hero 约 271px，视觉比例和竖屏一致
const FONT_BASE = {
  hero:   [260, 'd'],   // 主视觉大字（一屏两三个字）
  h1:     [136, 'd'],   // 标题
  h2:     [ 96, 'd'],   // 小标题
  body:   [ 64, 'd'],   // 正文
  label:  [ 44, 'd'],   // 标签
  cap:    [ 46, 'd'],   // 字幕
  micro:  [ 26, 'd'],   // 角标（章节号、时间码）
};

// ── 间距基准（竖屏 1080×1920）──
const SPACE_BASE = {
  outer:  [ 64, 'd'],   // 外边距
  gap:    [ 24, 'd'],   // 元素间距
  // 字幕距底：竖屏要避开手机底部手势区，横屏不需要那么多
  capBot: [190, 'h'],   // 字幕距底（按高度算，横屏自然变小）
};

function make(ratioKey) {
  const R = RATIOS[ratioKey] || RATIOS['9:16'];
  const W = R.w, H = R.h;

  // 竖屏基准
  const BW = 1080, BH = 1920;

  // 对角线（几何平均 w 和 h，比算术平均更稳）
  const DIAG_BASE = Math.sqrt(BW * BH);
  const DIAG_OUT = Math.sqrt(W * H);

  const sc = ref => {
    if (ref === 'w') return W / BW;
    if (ref === 'h') return H / BH;
    if (ref === 'd') return DIAG_OUT / DIAG_BASE;   // ★ 推荐
    return Math.min(W / BW, H / BH);   // 'm'
  };

  /** 字号：返回 px */
  const font = key => {
    const [base, ref] = FONT_BASE[key] || FONT_BASE.body;
    return Math.round(base * sc(ref));
  };

  /** 间距：返回 px */
  const pad = key => {
    const [base, ref] = SPACE_BASE[key] || SPACE_BASE.gap;
    return Math.round(base * sc(ref));
  };

  /** 百分比 → px */
  const px = (pct, axis) => Math.round((axis === 'w' ? W : H) * pct / 100);

  /**
   * 分区：把画布切成几个区域
   * area('head')  = 顶部 18%
   * area('body')  = 中间 64%
   * area('foot')  = 底部 18%
   */
  const AREAS = {
    head:  { y: 0,    h: 18 },
    body:  { y: 18,   h: 64 },
    foot:  { y: 82,   h: 18 },
    // 横屏专用：左右分栏
    left:  { x: 0,    w: 50 },
    right: { x: 50,   w: 50 },
  };

  const area = name => {
    const a = AREAS[name];
    if (!a) throw new Error('未知区域: ' + name);
    if (a.w != null) {
      return { x: px(a.x, 'w'), y: 0, w: px(a.w, 'w'), h: H };
    }
    return { x: 0, y: px(a.y, 'h'), w: W, h: px(a.h, 'h') };
  };

  /** 纵向 n 等分，返回第 i 份的 y 和 h */
  const rows = (n, from = 0, to = 100) => {
    const top = px(from, 'h'), bot = px(to, 'h');
    const total = bot - top;
    const each = total / n;
    return i => ({ y: Math.round(top + each * i), h: Math.round(each) });
  };

  /** 横向 n 等分 */
  const cols = (n, from = 0, to = 100) => {
    const l = px(from, 'w'), r = px(to, 'w');
    const total = r - l;
    const each = total / n;
    return i => ({ x: Math.round(l + each * i), w: Math.round(each) });
  };

  /** 是否横屏（宽 > 高） */
  const isLandscape = W > H;

  /** 内容区最大宽度（横屏时可以更宽，但要留边） */
  const contentW = () => Math.min(W - pad('outer') * 2, isLandscape ? 1600 : 940);

  /**
   * ⭐ 场景布局：竖屏上下堆叠，横屏左右分栏
   *
   * 返回一组「槽位」，场景代码只关心有几个槽、每个槽多大，
   * 不用管是竖屏还是横屏。
   *
   * @param n     要几个槽
   * @param mode  'auto' = 竖屏纵向、横屏横向
   *              'v' / 'h' = 强制
   */
  const slots = (n, mode = 'auto') => {
    const horiz = mode === 'h' || (mode === 'auto' && isLandscape);
    const O = pad('outer');
    const out = [];
    if (horiz) {
      // 横向 n 栏
      const usable = W - O * 2;
      const gap = pad('gap') * (n - 1);
      const each = (usable - gap) / n;
      const top = px(20, 'h');            // 上留 20%
      const bot = px(78, 'h');            // 下留 22%（给字幕）
      for (let i = 0; i < n; i++) {
        out.push({
          x: Math.round(O + i * (each + pad('gap'))),
          y: Math.round(top),
          w: Math.round(each),
          h: Math.round(bot - top),
        });
      }
    } else {
      // 纵向 n 行
      const top = px(18, 'h');
      const bot = px(80, 'h');
      const usable = bot - top;
      const gap = pad('gap') * (n - 1);
      const each = (usable - gap) / n;
      for (let i = 0; i < n; i++) {
        out.push({
          x: O,
          y: Math.round(top + i * (each + pad('gap'))),
          w: Math.round(W - O * 2),
          h: Math.round(each),
        });
      }
    }
    return out;
  };

  /**
   * ⭐ 主视觉 + 说明：横屏左图右文，竖屏上图下文
   */
  const heroSplit = (splitPct = 55) => {
    const O = pad('outer');
    const top = px(18, 'h');
    const bot = px(78, 'h');
    if (isLandscape) {
      const usable = W - O * 2;
      const lw = Math.round(usable * splitPct / 100);
      const rw = usable - lw - pad('gap');
      return {
        main: { x: O, y: top, w: lw, h: bot - top },
        side: { x: O + lw + pad('gap'), y: top, w: rw, h: bot - top },
        dir: 'h',
      };
    } else {
      const usable = bot - top;
      const mh = Math.round(usable * splitPct / 100);
      return {
        main: { x: O, y: top, w: W - O * 2, h: mh },
        side: { x: O, y: top + mh + pad('gap'), w: W - O * 2, h: usable - mh - pad('gap') },
        dir: 'v',
      };
    }
  };

  /**
   * ⭐ 文字自适应：按可用宽度算字号，避免 hero 换行
   *
   * 一个汉字宽度 ≈ 字号；英文字符 ≈ 0.55 字号
   *
   * @param text    文字
   * @param maxW    可用宽度 px
   * @param key     基准字号档（hero/h1/h2/...）
   * @param maxLines 允许几行（默认 1）
   */
  const fitFont = (text, maxW, key = 'hero', maxLines = 1) => {
    const base = font(key);
    const str = String(text);
    // 估算宽度（汉字 1.0，英文数字 0.55）
    const measure = (px_) => {
      let w = 0;
      for (const ch of str) {
        w += /[\u3400-\u9fff\uff00-\uffef]/.test(ch) ? px_ : px_ * 0.55;
      }
      return w;
    };
    let size = base;
    // 最多缩到 55%
    const minSize = Math.round(base * 0.38);   // 最多缩到 38%
    for (let i = 0; i < 40 && size > minSize; i++) {
      const w = measure(size);
      // 允许的行数
      const lines = Math.ceil(w / maxW);
      if (lines <= maxLines) break;
      size = Math.round(size * 0.94);
    }
    return Math.max(size, minSize);
  };

  return {
    ratio: ratioKey, name: R.name,
    W, H, isLandscape,
    font, pad, px, area, rows, cols, contentW, slots, heroSplit, fitFont,
    // 便捷：返回 CSS 字符串
    css: {
      font: (key, weight = 700) => `font:${weight} ${font(key)}px/1.2 "PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif`,
      fontLH: (key, weight, lh) => `font:${weight} ${font(key)}px/${lh} "PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif`,
    },
  };
}

/** 从 URL 参数读比例 */
function fromURL() {
  const p = new URLSearchParams(location.search);
  return make(p.get('ratio') || '9:16');
}

window.Layout = { make, fromURL, RATIOS, FONT_BASE, SPACE_BASE };

})();
