(function(){
'use strict';
// 缓动和小工具 —— 全部是时间的纯函数，任意一帧都能单独算出来
// 依据：同领域开源缓动库（移植为 JS）

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const inv = (a, b, x) => (b !== a ? clamp((x - a) / (b - a)) : (x >= b ? 1 : 0));

// 三次贝塞尔（与 CSS cubic-bezier 相同），牛顿迭代求解
function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = t => ((ax * t + bx) * t + cx) * t;
  const sy = t => ((ay * t + by) * t + cy) * t;
  const dx = t => (3 * ax * t + 2 * bx) * t + cx;
  return x => {
    x = clamp(x);
    let t = x;
    for (let i = 0; i < 8; i++) {
      const e = sx(t) - x, d = dx(t);
      if (Math.abs(e) < 1e-6 || Math.abs(d) < 1e-6) break;
      t -= e / d;
    }
    return sy(clamp(t));
  };
}

// 曲线族 —— 四条曲线的职责不能混用
const E = {
  linear: x => clamp(x),
  standard: bezier(0.2, 0, 0, 1),      // 位置移动、镜头
  enter:    bezier(0.05, 0.7, 0.1, 1), // 进场：快出慢停
  exit:     bezier(0.3, 0, 0.8, 0.15), // 退场：慢起快走
  inOut:    bezier(0.65, 0, 0.35, 1),
  smooth: x => { x = clamp(x); return x * x * x * (x * (x * 6 - 15) + 10); }, // 透明度、颜色
};

// 有阻尼的弹簧（解析解）。zeta 越小越弹。默认 0.75，过冲约 3%
function spring(t, freq = 2.2, zeta = 0.75) {
  if (t <= 0) return 0;
  const w = 2 * Math.PI * freq;
  const wd = w * Math.sqrt(1 - zeta * zeta);
  return 1 - Math.exp(-zeta * w * t) * (Math.cos(wd * t) + ((zeta * w) / wd) * Math.sin(wd * t));
}

// ⭐ 卡字最常用的一个：从 t0 开始动，在 t1 这一刻「第一次到位」（之后轻微过冲再停稳）
// 把 t1 设成 hit(关键词)，动作就正好落在关键词上
function springTo(t, t0, t1, zeta = 0.75) {
  const dur = Math.max(1e-3, t1 - t0);
  const freq = (Math.PI - Math.acos(zeta)) / (2 * Math.PI * Math.sqrt(1 - zeta * zeta) * dur);
  return spring(t - t0, freq, zeta);
}

// 在时刻 at 开始、持续 dur 秒的进度
const ramp = (t, at, dur, ease = E.standard) => ease(inv(at, at + dur, t));

// 进场 + 停留 + 退场的可见度（一个函数搞定三段）
const life = (t, a, b, fin = 0.35, fout = 0.3) =>
  Math.min(E.smooth(inv(a, a + fin, t)), 1 - E.smooth(inv(b - fout, b, t)));

// 可复现的伪随机（同 seed 每次渲染一致）
const hash = n => { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };
function noise1(x, seed = 0) {
  const i = Math.floor(x), f = x - i;
  const u = f * f * (3 - 2 * f);
  return lerp(hash(i + seed * 101), hash(i + 1 + seed * 101), u) * 2 - 1;
}

// ⭐ 通用技巧：sin(π·p) —— 两端为 0、中途最大。任何瞬态变形都用它
const bell = p => Math.sin(Math.PI * Math.min(1, Math.max(0, p)));

// 导出
window.Anim = {
  clamp, lerp, inv, bezier, E, spring, springTo, ramp, life, hash, noise1, bell,
};

})();
