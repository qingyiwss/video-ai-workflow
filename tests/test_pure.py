# -*- coding: utf-8 -*-
"""
纯函数单元测试 —— 不启动浏览器、不读音频

跑法：
  pip install -r requirements-dev.txt
  pytest tests/ -q

覆盖：
  gate1.check()      关键词距段首过近 / pause 全相同 / 关键词少于 2 字
  align_chars()      漏字插值 / 多字 / 同音替换
  fitFont()          长文本缩到下限 / 短文本不缩 / 中英混排（走 Node 侧，跳过）
  gridX()            12 栏端点 / span(0,12) 等于内容宽（走 Node 侧，跳过）

浏览器相关的两个（fitFont / gridX）需要 puppeteer，不在这个文件里测。
它们由 _assert.py 覆盖，那个脚本本来就是为「需要真实渲染」的断言准备的。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


# ══════════════════════════════════════════════════════════
# gate1.check()
# ══════════════════════════════════════════════════════════

def make_tl(sections, keywords, lines=None):
    """构造一个最小 timeline.json 结构"""
    return {
        "fps": 60, "total": 90, "lead": 0,
        "sections": sections,
        "keywords": keywords,
        "lines": lines or [],
    }


def test_gate1_keyword_too_close_to_head():
    """关键词距段首太近 → 必须报错"""
    from gate1 import check

    tl = make_tl(
        sections={"01": {"start": 10.0, "end": 30.0}},
        keywords=[{"tag": "01_01", "word": "卡字", "t": 10.8}],   # 距段首 0.8s
    )
    bad, tips = check(tl)
    assert any("距段首" in b for b in bad), f"应报「距段首」，实际: {bad}"


def test_gate1_keyword_position_ok():
    """关键词距段首 ≥1.65s → 不报错"""
    from gate1 import MIN_HEAD, check

    tl = make_tl(
        sections={"01": {"start": 10.0, "end": 30.0}},
        keywords=[{"tag": "01_01", "word": "卡字", "t": 10.0 + MIN_HEAD + 0.2}],
    )
    bad, _ = check(tl)
    assert not any("距段首" in b for b in bad), f"不该报「距段首」，实际: {bad}"


def test_gate1_keyword_too_short():
    """关键词单字 → 必须报错"""
    from gate1 import check

    tl = make_tl(
        sections={"01": {"start": 10.0, "end": 30.0}},
        keywords=[{"tag": "01_01", "word": "卡", "t": 12.0}],
    )
    bad, _ = check(tl)
    assert any("只有 1 个字" in b or "个字" in b for b in bad), f"应报字数不足: {bad}"


def test_gate1_keyword_count_mismatch():
    """关键词数 ≠ 段落数 → 必须报错"""
    from gate1 import check

    tl = make_tl(
        sections={"01": {"start": 10.0, "end": 30.0},
                  "02": {"start": 30.0, "end": 50.0}},
        keywords=[{"tag": "01_01", "word": "卡字", "t": 12.0}],   # 只有 1 个
    )
    bad, _ = check(tl)
    assert any("关键词" in b and "段落" in b for b in bad), f"应报数量不符: {bad}"


# ══════════════════════════════════════════════════════════
# align_chars()
# ══════════════════════════════════════════════════════════

def test_align_chars_exact_match():
    """单位数和识别词数相同 → 一一对应"""
    from align import align_chars

    units = ["它", "念", "到", "哪"]
    wts = [(0.0, 0.2, "它"),
           (0.2, 0.4, "念"),
           (0.4, 0.6, "到"),
           (0.6, 0.8, "哪")]
    times = align_chars(units, wts)
    assert len(times) == 4
    assert times[0][0] == pytest.approx(0.0, abs=0.01)
    assert times[-1][1] == pytest.approx(0.8, abs=0.01)


def test_align_chars_missing_word():
    """识别漏了字 → 插值补上，总数不变"""
    from align import align_chars

    units = ["它", "念", "到", "哪", "个"]
    wts = [(0.0, 0.2, "它"),
           (0.2, 0.4, "念"),
           # 「到」漏识别
           (0.6, 0.8, "哪"),
           (0.8, 1.0, "个")]
    times = align_chars(units, wts)
    assert len(times) == 5, f"单位 5 个，应返回 5 个时间，实际 {len(times)}"
    # 时间必须单调不减
    for a, b in zip(times, times[1:]):
        assert b[0] >= a[0] - 0.001, f"时间倒退: {a} → {b}"


def test_align_chars_extra_word():
    """识别多出字 → 仍然返回单位数个，且单调"""
    from align import align_chars

    units = ["它", "念", "到"]
    wts = [(0.0, 0.2, "它"),
           (0.2, 0.4, "念"),
           (0.4, 0.6, "到"),
           (0.6, 0.8, "多")]
    times = align_chars(units, wts)
    assert len(times) == 3
    for a, b in zip(times, times[1:]):
        assert b[0] >= a[0] - 0.001


def test_align_chars_homophone():
    """同音替换 → 按位置对齐，不因字面不同而崩溃"""
    from align import align_chars

    units = ["在", "这", "里"]
    wts = [(0.0, 0.2, "再"),   # 同音不同字
           (0.2, 0.4, "这"),
           (0.4, 0.6, "里")]
    times = align_chars(units, wts)
    assert len(times) == 3
    assert times[0][0] == pytest.approx(0.0, abs=0.01)


def test_align_chars_empty():
    """空输入 → 返回空，不崩溃"""
    from align import align_chars
    assert align_chars([], []) == []


# ══════════════════════════════════════════════════════════
# font_check 的字符收集
# ══════════════════════════════════════════════════════════

def test_font_check_collects_from_script(tmp_path):
    """script.md 的正文字符能被收集，注释和语法标记不算"""
    from font_check import chars_from_script

    p = tmp_path / "script.md"
    p.write_text(
        "＃ 这是注释，不该被收集\n"
        "[01 段落名]\n"
        "正文里的字会被收集。 | 0.5\n",
        encoding="utf-8")
    got = chars_from_script(p)
    chars = {c for c, _, _ in got}
    assert "正" in chars
    assert "文" in chars
    # 注释和段落名不该进来
    assert "注" not in chars, f"注释被收集了: {chars}"
    # 语法标记不该进来
    assert "|" not in chars


def test_font_check_collects_from_json(tmp_path):
    """scene-def.json 所有字符串值都被收集"""
    from font_check import chars_from_json

    p = tmp_path / "scene-def.json"
    p.write_text('{"sid":"01","data":{"title":"标题","note":"注释"}}',
                 encoding="utf-8")
    got = chars_from_json(p, "scene-def.json")
    chars = {c for c, _, _ in got}
    assert "标" in chars
    assert "题" in chars
    assert "注" in chars
    assert "释" in chars
