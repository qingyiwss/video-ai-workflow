(function(){
'use strict';
// 时间查表 —— 画面里每一个和旁白有关的时刻都从这里查，不手写秒数
// 依据：同领域开源时间查表实现
//
// 两条设计原则：
//   1. 找不到词直接报错，不会悄悄给一个假时间
//   2. 稿子改了重跑 timeline，画面自动跟着动

const FPS = 60;
const LEAD = 3 / FPS;    // 动作该到位的提前量（ITU-R BT.1359）
const APPEAR = 12 / FPS; // 新元素最晚出现的提前量

let TL = null;
let LINES = {};

// 归一化：只留字母数字和撇号，便于比较
const norm = s => String(s).toLowerCase().replace(/[^0-9a-z\u3400-\u9fff']/g, "");

/**
 * 初始化
 * @param {object} timeline  timeline.json
 */
function init(timeline) {
  TL = timeline;
  LINES = {};
  for (const l of TL.lines) {
    LINES[l.i !== undefined ? l.i : l.tag] = l;
  }
}

/** 含某句的 line 对象。支持行号或 tag，或按内容查找 */
function line(sel) {
  if (typeof sel === "number" || /^\d+$/.test(String(sel))) {
    const k = Number(sel);
    if (!LINES[k]) throw new Error(`line ${k} 不存在`);
    return LINES[k];
  }
  // 按 tag 或文本内容找
  for (const k in LINES) {
    const l = LINES[k];
    if (l.tag === sel) return l;
    if (l.text && l.text.includes(sel)) return l;
  }
  throw new Error(`line 找不到: ${sel}`);
}

/**
 * 第 n 次出现 `word` 的开始（或结束）秒数
 * @param {string} word  一个或多个字/词，空格分隔
 * @param {number} n     第几次出现（从 0 开始）
 * @param {"s"|"e"} edge 取开始还是结束
 * @param {number|string|null} lineSel 只在某一句里找
 */
function at(word, n = 0, edge = "s", lineSel = null) {
  if (!TL) throw new Error("先 init(timeline)");
  const target = String(word).split(/\s+/).map(norm);
  let k = 0;
  for (const key in LINES) {
    const l = LINES[key];
    if (lineSel !== null && l.i !== lineSel && l.tag !== lineSel) continue;
    const units = (l.words || []).map(w => norm(w.u));
    for (let i = 0; i <= units.length - target.length; i++) {
      let hit = true;
      for (let j = 0; j < target.length; j++) {
        if (units[i + j] !== target[j]) { hit = false; break; }
      }
      if (hit) {
        if (k === n) {
          const w = l.words[i + target.length - 1];
          return edge === "s" ? l.words[i].s : w.e;
        }
        k++;
      }
    }
  }
  throw new Error(`at: 找不到 "${word}" 第 ${n} 次` + (lineSel !== null ? ` line=${lineSel}` : ""));
}

/** 在某一句里找（at 的简写） */
function atIn(l, word, n = 0, edge = "s") {
  return at(word, n, edge, l.i !== undefined ? l.i : l.tag);
}

/** 关键词时刻。找不到直接报错 */
function kwT(word) {
  if (!TL || !TL.keywords) throw new Error("timeline 没有 keywords");
  const w = norm(word);
  for (const k of TL.keywords) {
    const kk = norm(k.word);
    if (kk.startsWith(w) || kk.includes(w)) return k.t;
  }
  throw new Error(`kw: 找不到关键词 "${word}"`);
}

/** ⭐ 动作该到位的时刻 = 关键词 - 3 帧 */
function hit(word) {
  return kwT(word) - LEAD;
}

/** ⭐ 新元素最晚出现的时刻 = 关键词 - 12 帧 */
function appearBy(word) {
  return kwT(word) - APPEAR;
}

/** 全部关键词（按时间排序） */
function keywords() {
  return (TL && TL.keywords ? TL.keywords.slice() : []).sort((a, b) => a.t - b.t);
}

/**
 * 段落表（章节卡 / 进度条 / 发布章节 都从这里取）
 *
 * ⚠️ 返回**按开始时间排序的数组**，不是对象。
 * 原因：JS 对象的数字键会排到前面（「10」「11」会跑到「01」前面），
 * 直接 Object.entries() 遍历会得到错乱的章节顺序。
 * 返回数组，顺序就是时间顺序，直接用于章节卡和发布章节。
 */
function sections() {
  const s = TL && TL.sections ? TL.sections : {};
  return Object.entries(s)
    .map(([name, v]) => ({ name, ...v }))
    .sort((a, b) => a.start - b.start);
}

/** 空当表（@gap 定义的无旁白区段） */
function gaps() {
  return TL && TL.gaps ? TL.gaps : [];
}

/** 总时长 */
function total() {
  return TL ? TL.total : 0;
}

window.Time = {
  FPS, LEAD, APPEAR,
  init, line, at, atIn, kwT, hit, appearBy, keywords, sections, gaps, total, norm,
};

})();
