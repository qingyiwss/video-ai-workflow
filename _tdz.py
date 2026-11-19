# -*- coding: utf-8 -*-
"""
TDZ 检查器 —— 找「在声明之前使用 const/let」的变量

为什么需要：
  scenes.js 的场景函数是模板字符串拼 HTML，变量必须在拼之前声明。
  这个错误在 `node --check` 里发现不了（语法合法），只在运行时抛
  ReferenceError: Cannot access 'x' before initialization。

  一轮一轮试太慢。这个脚本一次找全。

用法：
  python _tdz.py canvas/scenes.js
  python _tdz.py canvas/*.js
"""
import re
import sys
from pathlib import Path

# 这些是函数参数或外层作用域的，不算
EXTERNAL = {
    "sc", "L", "data", "hit", "t0", "t1", "fg", "sub", "bg", "fs", "theme",
    "FF", "FF_SERIF", "FF_SANS", "C", "O", "land", "n", "i", "j", "k", "y", "x",
    "it", "f", "v", "e", "el", "cur", "prev", "si", "time", "Math", "String",
    "Number", "Array", "Object", "JSON", "parseInt", "parseFloat", "console",
    "window", "document", "requestAnimationFrame",
}


def check_file(path):
    t = Path(path).read_text(encoding="utf-8")
    problems = []

    # 找到每个 BUILDER.xxx = (...) => { ... } 的边界
    starts = [(m.group(1) or m.group(2), m.start())
              for m in re.finditer(
                  r"^BUILDER(?:\.([\w-]+)|\[['\"]([\w-]+)['\"]\])\s*=", t, re.M)]

    for idx, (name, pos) in enumerate(starts):
        end = starts[idx + 1][1] if idx + 1 < len(starts) else len(t)
        body = t[pos:end]
        base_line = t[:pos].count("\n") + 1

        # 找模板字符串的起点（拼 HTML 的地方）
        m = re.search(r"(?:const\s+\w+\s*=\s*items\.map|const\s+html\s*=|"
                      r"sc\.innerHTML\s*=|const\s+inner\s*=\s*`|sc\.innerHTML\s*\+=)", body)
        if not m:
            continue
        tmpl_start = m.start()

        # 模板里用到 ${xxx}
        tmpl_end = body.find("}).join('');", tmpl_start)
        if tmpl_end < 0:
            tmpl_end = body.find("`;", tmpl_start)
        if tmpl_end < 0:
            tmpl_end = min(tmpl_start + 3000, len(body))
        tmpl = body[tmpl_start:tmpl_end]

        used = set(re.findall(r"\$\{(\w+)", tmpl))
        used -= EXTERNAL

        # 声明位置
        declared = {}
        # const x = ...
        for mm in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=", body):
            if mm.group(1) not in declared:
                declared[mm.group(1)] = mm.start()
        # const { a, b, c } = ...  解构
        for mm in re.finditer(r"(?:const|let|var)\s*\{([^}]*)\}", body):
            for name in re.split(r"[,:]", mm.group(1)):
                name = name.strip().split("=")[0].strip()
                if name and re.match(r"^\w+$", name) and name not in declared:
                    declared[name] = mm.start()

        for v in used:
            if v not in declared:
                # 可能是箭头函数的参数，如 (it, i) =>，忽略
                if re.search(rf"\(\s*[^)]*\b{v}\b[^)]*\)\s*=>", body):
                    continue
                problems.append((name, base_line, v, "未声明"))
            elif declared[v] > tmpl_start:
                line = base_line + body[:declared[v]].count("\n")
                problems.append((name, line, v, "声明在使用之后"))

    return problems


def main():
    files = sys.argv[1:] or ["canvas/scenes.js"]
    total = 0
    for f in files:
        p = Path(f)
        if not p.exists():
            print(f"找不到 {f}")
            continue
        probs = check_file(p)
        if probs:
            print(f"\n{p}:  {len(probs)} 处问题")
            for name, line, var, why in probs:
                print(f"  {name:<14} 行{line:>5}  {var:<12} {why}")
            total += len(probs)
        else:
            print(f"{p}:  OK")

    if total:
        print(f"\n合计 {total} 处。修完再跑。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
