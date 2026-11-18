# -*- coding: utf-8 -*-
"""
逐字对齐 → timeline.json（卡字第三步）

用法：
  python align_v6.py                 # 默认 v6
  python align_v6.py <项目目录>       # 指定项目

做法：
  1. 对每条选中音频用 Whisper 取 word_timestamps
  2. 和原文做字符级对齐（同音字允许多对一）
  3. 得到每个汉字的起止时间
  4. 换算成整条旁白里的绝对时间
  5. 输出卡字格式的 timeline.json
"""
import json
import re
import os
import tempfile
import difflib
import numpy as np
import subprocess
from pathlib import Path

from paths import P
FF = P.ffmpeg
MODEL_W = P.whisper
import sys

if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
    print("用法: python align.py <项目目录>")
    print("  项目目录需含 selection.json / narration.wav / lines/")
    sys.exit(1)
BASE = Path(sys.argv[1]).resolve()

UNITS = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-']*|[\u3400-\u9fff]")


def split_units(s):
    """按念法单位切：一个汉字，或一个英文/数字词"""
    return UNITS.findall(s)


def tidy(s):
    return re.sub(r'[，。：；「」、？！*\s]', '', s)


def load_pcm(path, sr=16000):
    tmp = os.path.join(tempfile.gettempdir(), "t_%d.raw" % np.random.randint(1e9))
    subprocess.run([FF, "-y", "-v", "error", "-i", str(path), "-ar", str(sr), "-ac", "1", "-f", "s16le", tmp],
                   check=True, capture_output=True)
    d = np.fromfile(tmp, dtype=np.int16).astype(np.float32)/32768.0
    os.remove(tmp)
    return d


def word_times(wm, audio):
    """Whisper 逐词时间（相对该音频起点）"""
    segs, _ = wm.transcribe(audio, language="zh", beam_size=5,
                             word_timestamps=True, vad_filter=False,
                             condition_on_previous_text=False)
    out = []
    for s in segs:
        if not s.words:
            continue
        for w in s.words:
            if w.end > w.start:
                out.append((w.start, w.end, w.word))
    return out


def align_chars(orig_units, timed_words):
    """
    把 Whisper 的词时间分配给原文的每个单位。
    做法：
      - Whisper 词按字符拆开，每个字符拿它所在词的线性插值时间
      - 再用 difflib 把「识别字符序列」和「原文单位序列」对齐
      - 原文单位从匹配上的识别字符取时间
    """
    # 1. 识别字符 → 时间
    heard_chars = []   # (char, s, e)
    for s, e, wtext in timed_words:
        cs = [c for c in tidy(wtext)]
        if not cs:
            continue
        n = len(cs)
        dur = (e - s) / n
        for i, c in enumerate(cs):
            heard_chars.append((c, s + i*dur, s + (i+1)*dur))

    heard_seq = [c for c, _, _ in heard_chars]
    orig_seq = orig_units

    # 2. difflib 对齐
    sm = difflib.SequenceMatcher(None, heard_seq, orig_seq, autojunk=False)
    times = [None] * len(orig_seq)
    last_e = 0.0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                _, s, e = heard_chars[i1 + k]
                times[j1 + k] = (s, e)
                last_e = e
        elif tag == "replace":
            # 识别有字但不同（同音/近音）：按长度比例分配识别段的时间
            if i2 > i1 and j2 > j1:
                seg_s = heard_chars[i1][1]
                seg_e = heard_chars[i2-1][2]
                span = max(seg_e - seg_s, 1e-3)
                m = j2 - j1
                for k in range(m):
                    times[j1 + k] = (seg_s + span*k/m, seg_s + span*(k+1)/m)
                last_e = seg_e
            else:
                # 有原文没识别（漏字）：给一个零宽时间点，后续插值补
                pass
        elif tag == "delete":
            # 识别多了（幻觉）：忽略
            pass
        # insert 留空，后面插值

    # 3. 插值补未匹配的
    n = len(orig_seq)
    i = 0
    while i < n:
        if times[i] is None:
            j = i
            while j < n and times[j] is None:
                j += 1
            prev_e = times[i-1][1] if i > 0 and times[i-1] else 0.0
            next_s = times[j][0] if j < n and times[j] else prev_e + 0.15*(j-i)
            span = max(next_s - prev_e, 0.05)
            cnt = j - i
            for k in range(cnt):
                times[i+k] = (prev_e + span*k/cnt, prev_e + span*(k+1)/cnt)
            i = j
        else:
            i += 1

    return times


def main():
    from faster_whisper import WhisperModel
    wm = WhisperModel(MODEL_W, device="cpu", compute_type="int8", cpu_threads=6)

    sel = json.loads((BASE/"selection.json").read_text(encoding="utf-8"))
    draft = json.loads((BASE/"timeline_draft.json").read_text(encoding="utf-8"))

    print(f"=== v6 逐字对齐：{len(sel)} 句 ===\n")

    lines_out = []
    keywords = []
    total_lead = draft["lead"]
    kw_idx = 0

    for s, d in zip(sel, draft["lines"]):
        tag = s["tag"]
        text = s["text"]
        pause = s["pause"] if "pause" in s else 0.4
        abs_start = d["start"]
        abs_end = d["end"]

        # selection 里可能没有 path，按 tag 找
        ap = s.get("path")
        if not ap:
            for cand in [BASE/"lines"/f"{tag}.wav", BASE/"lines"/f"{tag}.mp3"]:
                if cand.exists():
                    ap = str(cand); break
        if not ap:
            raise FileNotFoundError(f"{tag}.wav 不在 {BASE/'lines'}")
        audio = load_pcm(ap)
        wts = word_times(wm, audio)

        # 原文单位（去标点，保留英文词）
        say_units = split_units(tidy(text))
        show_units = split_units(tidy(text))

        # 关键词位置（原文里用 * 标记的）
        kw_pos = []
        raw = text
        # 找 *...* 在原串里的字符位置 → 换算成 tidy 后的单位索引
        for m in re.finditer(r"\*([^*]+)\*", raw):
            kw_text = m.group(1)
            # 在 tidy 后的串里找它
            pre = tidy(raw[:m.start()])
            start_idx = len(split_units(pre))
            kw_len = len(split_units(kw_text))
            for kk in range(kw_len):
                if start_idx + kk < len(say_units):
                    kw_pos.append((start_idx + kk, kw_text))
            break  # 每句只取第一个关键词

        times = align_chars(say_units, wts)

        # ⚠️ 对齐器可能把最后一个字的结束时间算到句尾之外
        #    （实测：「然」超出句边界 0.13 秒）
        #    修法：把超出的部分并回最后一个字，不改句子边界
        if times:
            last_te = max(te for _, te in times)
            if last_te > (abs_end - abs_start) + 0.005:
                # 只保留到句尾
                clamped = []
                for ts, te in times:
                    clamped.append((min(ts, abs_end - abs_start - 0.01),
                                    min(te, abs_end - abs_start)))
                times = clamped

        words = []
        for u, (ts, te) in zip(say_units, times):
            words.append({"u": u, "s": round(abs_start + ts, 3),
                          "e": round(abs_start + te, 3)})

        caps = []
        kw_flags = {p for p, _ in kw_pos}
        for k, (u, (ts, te)) in enumerate(zip(show_units, times)):
            c = {"c": u, "s": round(abs_start + ts, 3), "e": round(abs_start + te, 3)}
            if k in kw_flags:
                c["k"] = 1
            caps.append(c)

        # 关键词时间
        if kw_pos:
            p, kt = kw_pos[0]
            if p < len(times):
                keywords.append({"tag": tag, "line": len(lines_out), "word": kt,
                                 "t": round(abs_start + times[p][0], 3),
                                 "e": round(abs_start + times[p][1], 3)})

        lines_out.append({
            "i": len(lines_out), "tag": tag, "sid": s.get("sid") or s.get("sec"),
            "text": text, "say": "".join(say_units), "show": "".join(show_units),
            "start": round(abs_start, 3), "end": round(abs_end, 3),
            "pause": pause,
            "words": words, "cap": caps,
        })

        nk = len(kw_pos)
        print(f"  {tag}  {len(say_units):>2}单位  {abs_start:>6.2f}-{abs_end:>6.2f}s  "
              f"识出{len(wts)}词  关键词{nk}")

    # ─── sections：按段落聚合 ───
    # sections 是章节卡 / 进度条 / 发布章节的唯一来源，必须真算，不能留空
    sections = {}
    for l in lines_out:
        sec_name = l["sid"]
        if sec_name not in sections:
            sections[sec_name] = {"start": l["start"], "end": l["end"],
                                  "first": l["i"], "last": l["i"]}
        sections[sec_name]["end"] = l["end"]
        sections[sec_name]["last"] = l["i"]

    # ─── gaps：@gap 定义的无旁白区段 ───
    # 优先级：draft 里已算好的 > 从稿子文件解析 > 空
    gaps = draft.get("gaps")
    if gaps is None:
        gaps = []
        script_file = BASE / "script.txt"
        if script_file.exists():
            # 解析 @gap 秒数 名字，算它落在第几句之后
            import re as _re
            n_line = 0
            for raw in script_file.read_text(encoding="utf-8").splitlines():
                ln = raw.strip()
                if not ln or ln.startswith("#") or ln.startswith("["):
                    continue
                m = _re.match(r"@gap\s+([\d.]+)(?:\s+(\S+))?", ln)
                if m:
                    gaps.append({"after": n_line,
                                 "dur": float(m.group(1)),
                                 "name": m.group(2) if m.group(2) else None})
                    continue
                n_line += 1

    tl = {
        "fps": 60,
        "total": draft["total"],
        "lead": total_lead,
        "lines": lines_out,
        "keywords": keywords,
        "sections": sections,
        "gaps": gaps,
    }

    out = BASE / "timeline.json"
    out.write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n=== 汇总 ===")
    print(f"  句数 {len(lines_out)}  关键词 {len(keywords)}  总长 {draft['total']:.2f}s")
    print(f"  字数 {sum(len(l['words']) for l in lines_out)}")
    print(f"→ {out}")

    # 关键词清单
    print(f"\n=== 关键词（画面要卡的点）===")
    for k in keywords:
        print(f"  {k['tag']}  {k['word']:<6} @ {k['t']:>6.2f}s")


if __name__ == "__main__":
    main()
