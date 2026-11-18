# -*- coding: utf-8 -*-
"""
通用配音 —— 多种 TTS 后端，按硬件自动选

支持后端：
  local-gpu   本地 audiocpp（Vulkan/CUDA）  ★ 最优，能克隆音色
  local-cpu   本地 audiocpp（CPU）          慢 48 倍，能克隆音色
  edge-tts    微软在线（免费）              快，不能克隆，用通用音色
  cloud-api   在线 API（需 Key）            快，音色受服务商限制

用法：
  python tools/gen_voice.py <项目目录>
  python tools/gen_voice.py <项目目录> --backend edge-tts --voice zh-CN-YunxiNeural
  python tools/gen_voice.py <项目目录> --rounds 2

依据：工作流 3.1-3.10 + docs/TTS-PLANS.md

产出：
  <项目>/lines/<段>_<序>.wav
  <项目>/narration.wav
  <项目>/selection.json      （数组格式，align 要用）
  <项目>/selection-meta.json
  <项目>/report.txt
"""
import argparse
import asyncio
import difflib
import json
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 16000

# ── edge-tts 音色（实测 8/8 可用，2026-11-18）──
# 平均 cps 4.58，生成 1.7 秒/句
EDGE_VOICES = {
    "zh-CN-YunxiNeural": "男 · 年轻口语（最接近口播）",
    "zh-CN-YunjianNeural": "男 · 成熟解说",
    "zh-CN-YunyangNeural": "男 · 新闻播报（cps 5.1 最快）",
    "zh-CN-YunxiaNeural": "男 · 少年",
    "zh-CN-XiaoxiaoNeural": "女 · 温柔",
    "zh-CN-XiaoyiNeural": "女 · 活泼",
    "zh-CN-liaoning-XiaobeiNeural": "女 · 东北话",
    "zh-CN-shaanxi-XiaoniNeural": "女 · 陕西话",
}
DEFAULT_EDGE = "zh-CN-YunxiNeural"


# ══════════════════════════════════════════════════════════
# 稿子解析（工作流 2.13）
# ══════════════════════════════════════════════════════════

def parse_script(path, default_pause=0.34):
    """→ [(sec, text_with_kw, pause), ...]"""
    text = Path(path).read_text(encoding="utf-8-sig")
    out, sec = [], None
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        m = re.match(r"^\[([^\]]+)\]$", ln)
        if m:
            name = m.group(1)
            mn = re.match(r"^(\d+)", name)
            sec = mn.group(1).zfill(2) if mn else name[:8]
            continue
        m = re.match(r"^##\s*段\s*(\d+)", ln)
        if m:
            sec = m.group(1).zfill(2)
            continue
        if ln.startswith(("＃", "#", ">", "---", "@gap", "```")):
            continue
        body = re.sub(r"^[-*+]\s+", "", ln)
        pause = default_pause
        pm = re.search(r"\|\s*([\d.]+)\s*$", body)
        if pm:
            pause = float(pm.group(1))
            body = body[:pm.start()].strip()
        for sent in re.split(r"(?<=[。！？])", body):
            sent = sent.strip()
            if len(sent) >= 2 and sec is not None:
                out.append((sec, sent, pause))
    return out


# ══════════════════════════════════════════════════════════
# 数字归一化（工作流 3.9b）
# ══════════════════════════════════════════════════════════

_CN_DIGIT = {"零":0,"〇":0,"一":1,"二":2,"两":2,"三":3,"四":4,
             "五":5,"六":6,"七":7,"八":8,"九":9}
_CN_UNIT = {"十":10,"百":100,"千":1000,"万":10000}


def _cn2num(s):
    if not s: return None
    if "点" in s:
        a, b = s.split("点", 1)
        ai = _cn2num(a) if a else 0
        bd = "".join(str(_CN_DIGIT.get(c,"")) for c in b if c in _CN_DIGIT)
        return float(f"{ai}.{bd}") if bd else None
    total = cur = 0; last_unit = 1
    for c in s:
        if c in _CN_DIGIT: cur = _CN_DIGIT[c]
        elif c in _CN_UNIT:
            u = _CN_UNIT[c]
            if u >= 10000: total += (cur or 1)*u; cur = 0
            else: total += (cur if cur else 1)*u; cur = 0
            last_unit = u
        else: return None
    if cur and last_unit >= 100: cur *= last_unit // 10
    return total + cur


def _numstr(v):
    if v is None: return ""
    return str(int(v)) if float(v).is_integer() else str(v)


def norm_numbers(s):
    s = re.sub(r"百分之([零〇一二两三四五六七八九十百千万点]+)",
               lambda m: _numstr(_cn2num(m.group(1))) + "%", s)
    return re.sub(r"[零〇一二两三四五六七八九十百千万点]+",
                  lambda m: _numstr(_cn2num(m.group(0))) or m.group(0), s)


def tidy(s):
    return re.sub(r"[，。？！；：、「」（）\s,.?!;:%]", "", norm_numbers(s))


# ══════════════════════════════════════════════════════════
# 音频读写
# ══════════════════════════════════════════════════════════

def load_pcm(path, sr=SR):
    with wave.open(str(path), "rb") as w:
        n, ch, sw, fr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        buf = w.readframes(n)
    if sw != 2:
        raise ValueError(f"{path} 不是 16bit")
    x = np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    if fr != sr:
        idx = np.linspace(0, len(x)-1, int(len(x)*sr/fr))
        x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    return x


def save_wav(x, path, sr=SR):
    y = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((y*32767).astype("<i2").tobytes())


def any_to_wav(src, sr=SR):
    """mp3/m4a/任意 → 16k 单声道 wav 的 float 数组"""
    from paths import P
    ff = P.ffmpeg
    tmp = Path(src).with_suffix(".tmp.wav")
    r = subprocess.run([ff, "-y", "-v", "error", "-i", str(src),
                        "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(tmp)],
                       capture_output=True, text=True)
    if not tmp.exists():
        raise RuntimeError(f"转换失败 {src}: {r.stderr[:200]}")
    x = load_pcm(tmp, sr)
    tmp.unlink(missing_ok=True)
    return x


def normalize_rms(x, target_db=-23.0, sr=SR):
    """把一句音频的 RMS 拉到目标值（不改峰值形状）

    为什么逐句归一化：
      edge-tts / CosyVoice3 每一句输出音量不一致（实测差 10-12 dB）。
      只对整段做 loudnorm，后面小声的句子还是小声。
    """
    if len(x) == 0:
        return x
    rms = float(np.sqrt(np.mean(x ** 2)))
    if rms < 1e-6:
        return x
    cur_db = 20 * np.log10(rms)
    gain = 10 ** ((target_db - cur_db) / 20)
    y = x * gain
    # 峰值上限 -3 dBFS（留 1.5 dB 给后续压缩留余量）
    pk = float(np.abs(y).max())
    LIMIT = 10 ** (-3.0 / 20)
    if pk > LIMIT:
        y = y * (LIMIT / pk)
    return y


def trim_and_pad(x, sr=SR, head=0.04, tail=0.08, thr_db=-40):
    if len(x) == 0: return x
    fl = int(0.02*sr)
    nf = len(x)//fl
    if nf == 0: return x
    e = np.array([np.sqrt(np.mean(x[i*fl:(i+1)*fl]**2)) for i in range(nf)])
    edb = 20*np.log10(np.maximum(e, 1e-9))
    loud = np.where(edb > thr_db)[0]
    if len(loud) == 0: return x
    a = max(0, loud[0]*fl - int(head*sr))
    b = min(len(x), (loud[-1]+1)*fl + int(tail*sr))
    return x[a:b]


# ══════════════════════════════════════════════════════════
# 后端：edge-tts
# ══════════════════════════════════════════════════════════

async def edge_batch(plan, outdir, voice, rate="+0%"):
    import edge_tts
    outdir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(4)     # 并发 4，别把微软惹毛

    async def one(i, text):
        f = outdir/f"line_{i+1}.wav"
        async with sem:
            for attempt in range(3):
                try:
                    mp3 = outdir/f"_t{i+1}.mp3"
                    txt = text.replace("*", "")
                    comm = edge_tts.Communicate(txt, voice, rate=rate)
                    await comm.save(str(mp3))
                    if mp3.exists() and mp3.stat().st_size > 500:
                        x = any_to_wav(mp3)
                        save_wav(x, f)
                        mp3.unlink(missing_ok=True)
                        return True
                except Exception:
                    pass
                await asyncio.sleep(1.5 * (attempt+1))
        return False

    tasks = [one(i, t) for i, (_, t, _) in enumerate(plan)]
    res = await asyncio.gather(*tasks)
    return sum(1 for r in res if r)


# ══════════════════════════════════════════════════════════
# 后端：本地 audiocpp
# ══════════════════════════════════════════════════════════

REF_TEXT_DEFAULT = (
    "我最近在想一个问题为什么有些工具用起来很顺手有些用两次就放下了"
    "后来发现差别不在共同多少而在它有没有替你省掉那些真正凡人的步骤"
    "这点想明白以后我挑东西的标准就变了现在拿到一个新工具"
    "我第一反应不是马上打开试用而是先问自己它到底解决了我哪一个具体的问题"
)


def local_batch(plan, outdir, cfg, seed):
    outdir.mkdir(parents=True, exist_ok=True)
    txt = outdir/"_texts.txt"
    txt.write_text("\n".join(p[1].replace("*","") for p in plan), encoding="utf-8")
    cmd = [cfg["exe"], "--task","tts","--family","cosyvoice3",
           "--model", cfg["model"], "--backend", cfg["backend"],
           "--device", str(cfg.get("device",0)), "--threads", str(cfg.get("threads",12)),
           "--voice-ref", cfg["ref"],
           "--request-option","template_name=zero_shot",
           "--request-option", f"reference_text={cfg.get('ref_text') or REF_TEXT_DEFAULT}",
           "--request-option", f"seed={seed}",
           "--batch-text-file", str(txt), "--out-dir", str(outdir)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", timeout=7200)
    files = sorted(outdir.glob("line_*.wav"),
                   key=lambda p: int(re.search(r"line_(\d+)", p.name).group(1))
                   if re.search(r"line_(\d+)", p.name) else 0)
    return files, r.returncode != 0


def local_single(text, out, cfg, seed):
    cmd = [cfg["exe"], "--task","tts","--family","cosyvoice3",
           "--model", cfg["model"], "--backend", cfg["backend"],
           "--device", str(cfg.get("device",0)), "--threads", str(cfg.get("threads",12)),
           "--text", text.replace("*",""), "--voice-ref", cfg["ref"], "--out", str(out),
           "--request-option","template_name=zero_shot",
           "--request-option", f"reference_text={cfg.get('ref_text') or REF_TEXT_DEFAULT}",
           "--request-option", f"seed={seed}"]
    subprocess.run(cmd, capture_output=True, text=True,
                   encoding="utf-8", errors="ignore", timeout=1800)


# ══════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════

SEEDS = [7011, 7157, 7283, 7399]


def main():
    ap = argparse.ArgumentParser(description="通用配音（多后端）")
    ap.add_argument("base")
    ap.add_argument("--script", default="script.md")
    ap.add_argument("--backend", default="auto",
                    choices=["auto","local-gpu","local-cpu","edge-tts","cloud-api"],
                    help="auto=自动检测")
    ap.add_argument("--voice", default="", help="edge-tts 音色")
    ap.add_argument("--rate", default="+0%", help="edge-tts 语速，如 +10%%")
    ap.add_argument("--rounds", type=int, default=0, help="候选轮数（0=按后端定）")
    ap.add_argument("--exe", default="", help="audiocpp_cli 路径")
    ap.add_argument("--model", default="", help="模型 .gguf 路径")
    ap.add_argument("--ref", default="", help="参考音 wav")
    ap.add_argument("--ref-text", default="", help="参考音文本")
    ap.add_argument("--lead", type=float, default=1.6)
    ap.add_argument("--tail", type=float, default=1.5)
    a = ap.parse_args()

    BASE = Path(a.base).resolve()
    SCRIPT = BASE/a.script
    if not SCRIPT.exists():
        print(f"✗ 找不到 {SCRIPT}")
        return 1

    plan = parse_script(SCRIPT)
    if not plan:
        print("✗ 稿子解析出 0 句")
        return 1

    # ── 决定后端 ──
    backend = a.backend
    if backend == "auto":
        sys.path.insert(0, str(Path(__file__).parent))
        try:
            from detect_env import (candidates, detect_cpu, detect_ram_gb,
                                    detect_vulkan_devices, detect_api_keys, detect_tools)
            c = candidates(detect_cpu(), detect_ram_gb(),
                           detect_vulkan_devices(a.exe or None),
                           detect_api_keys(), detect_tools())
            backend = c[0][0]
        except Exception as e:
            print(f"  ⚠ 检测失败（{e}），回退 edge-tts")
            backend = "edge-tts"

    # 归一化后端名
    if backend in ("local-gpu", "local-igpu", "local-cpu"):
        mode = "local"
        btype = "gpu" if backend == "local-gpu" else ("cpu" if backend == "local-cpu" else "vulkan")
    elif backend == "edge-tts":
        mode, btype = "edge", ""
    else:
        print(f"✗ 后端 {backend} 还没实现")
        return 1

    total_chars = sum(len(re.sub(r"[*，。？！；：、]","",t)) for _,t,_ in plan)
    rounds = a.rounds or (4 if mode == "local" else 1)

    print("="*72)
    print(f"配音：{len(plan)} 句  {total_chars} 字  后端 {backend}  {rounds} 轮")
    print("="*72)

    LINES = BASE/"lines"
    LINES.mkdir(exist_ok=True)
    BATCH = BASE/"batch"

    # ── 生成 ──
    if mode == "edge":
        voice = a.voice or DEFAULT_EDGE
        print(f"\n音色：{voice}  （{EDGE_VOICES.get(voice,'自定义')}）")
        print(f"语速：{a.rate}")
        outdir = BATCH/"edge"
        t0 = __import__("time").time()
        ok = asyncio.run(edge_batch(plan, outdir, voice, a.rate))
        print(f"  {ok}/{len(plan)} 句  {__import__('time').time()-t0:.0f}s")
        rounds_files = [[outdir/f"line_{i+1}.wav" for i in range(len(plan))]]
    else:
        cfg = {
            "exe": a.exe or P.audiocpp,
            "model": a.model or P.model,
            "ref": a.ref or P.ref,
            "ref_text": a.ref_text or P.ref_text,
            "backend": btype,
            "device": 0, "threads": 12,
        }
        for k in ("exe","model","ref"):
            if not Path(cfg[k]).exists():
                print(f"✗ {k} 不存在：{cfg[k]}")
                print(f"  提示：先跑 python tools/detect_env.py 看用哪个方案")
                return 1

        rounds_files = []
        for ri, seed in enumerate(SEEDS[:rounds]):
            print(f"\n[第 {ri+1}/{rounds} 轮] seed={seed}")
            outdir = BATCH/f"r{ri}"
            files, crashed = local_batch(plan, outdir, cfg, seed)
            print(f"  {len(files)}/{len(plan)} 句" + ("  ⚠ 崩溃" if crashed else ""))
            if len(files) < len(plan):
                for si, (sec, text, pause) in enumerate(plan):
                    one = outdir/f"line_{si+1}.wav"
                    if one.exists() and one.stat().st_size > 3000: continue
                    local_single(text, one, cfg, seed+1000)
                files = sorted(outdir.glob("line_*.wav"))
                print(f"  补跑后 {len(files)}/{len(plan)}")
            rounds_files.append(files)

    # ── 筛选 ──
    print("\n" + "="*72)
    print("筛选")
    print("="*72)

    if mode == "edge":
        # edge 只跑 1 轮，没得选。但仍要检查音量
        selected = []
        for si, (sec, text, pause) in enumerate(plan):
            tag = f"{sec}_{si+1:02d}"
            f = rounds_files[0][si]
            if not f.exists() or f.stat().st_size < 1000:
                print(f"  [{si+1:>2}] {tag}  ✗ 无音频")
                continue
            x = normalize_rms(trim_and_pad(load_pcm(f)))
            save_wav(x, LINES/f"{tag}.wav")
            dur = len(x)/SR
            chars = len(re.sub(r"[*，。？！；：、]","",text))
            selected.append({"tag":tag,"sec":sec,"text":text,"pause":pause,
                             "dur":round(dur,3),"round":0,"overlap":1.0,
                             "cps":round(chars/dur,2) if dur else 0,"pk_db":0})
            print(f"  [{si+1:>2}] {tag}  {dur:>5.2f}s  cps {chars/dur:>4.1f}")
    else:
        from faster_whisper import WhisperModel
        W = P.whisper
        wm = WhisperModel(W, device="cpu", compute_type="int8", cpu_threads=6)
        selected = []
        for si, (sec, text, pause) in enumerate(plan):
            tag = f"{sec}_{si+1:02d}"
            target = tidy(text)
            cands = []
            for ri, files in enumerate(rounds_files):
                if si >= len(files): continue
                p = files[si]
                if not p.exists() or p.stat().st_size < 3000: continue
                try: x = load_pcm(p)
                except Exception: continue
                if len(x) == 0: continue
                rms = 20*np.log10(max(float(np.sqrt(np.mean(x**2))),1e-9))
                pk = 20*np.log10(max(float(np.abs(x).max()),1e-9))
                if pk < -20 or rms < -35: continue
                segs,_ = wm.transcribe(x, language="zh", beam_size=5,
                                       condition_on_previous_text=False)
                heard = "".join(s.text for s in segs)
                ov = difflib.SequenceMatcher(None, tidy(heard), target).ratio()
                dur = len(x)/SR
                cps = len(target)/dur if dur else 0
                score = ov*100 - (20 if cps>10 else 0) - (10 if cps<2.5 else 0)
                cands.append((score,ri,p,ov,dur,cps,pk))
            if not cands:
                print(f"  [{si+1:>2}] {tag}  ⚠ 无有效候选")
                continue
            best = max(cands, key=lambda c: c[0])
            x = normalize_rms(trim_and_pad(load_pcm(best[2])))
            save_wav(x, LINES/f"{tag}.wav")
            selected.append({"tag":tag,"sec":sec,"text":text,"pause":pause,
                             "dur":round(len(x)/SR,3),"round":best[1],
                             "overlap":round(best[3],3),"cps":round(best[5],2),
                             "pk_db":round(best[6],1)})
            flag = "✓" if best[3]>=0.95 else ("△" if best[3]>=0.7 else "✗")
            print(f"  [{si+1:>2}] {tag}  {len(x)/SR:>5.2f}s  第{best[1]+1}轮  "
                  f"吻{best[3]*100:>5.1f}%  cps{best[5]:>4.1f}  {flag}")

    # ── 拼接 ──
    print("\n" + "="*72)
    print("拼接旁白")
    print("="*72)
    parts = [np.zeros(int(a.lead*SR), dtype=np.float32)]
    t = float(a.lead)
    timeline = []
    for s in selected:
        x = load_pcm(LINES/f"{s['tag']}.wav")
        start = t; parts.append(x); t += len(x)/SR; end = t
        timeline.append({"tag":s["tag"],"sec":s["sec"],"text":s["text"],
                         "start":round(start,3),"end":round(end,3),"pause":s["pause"]})
        parts.append(np.zeros(int(s["pause"]*SR), dtype=np.float32)); t += s["pause"]
    parts.append(np.zeros(int(a.tail*SR), dtype=np.float32))
    total = sum(len(p) for p in parts)/SR
    save_wav(np.concatenate(parts), BASE/"narration.wav")
    print(f"  narration.wav  {total:.2f}s  {len(selected)} 句")

    # ── 存档 ──
    (BASE/"selection.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=1), encoding="utf-8")
    (BASE/"selection-meta.json").write_text(
        json.dumps({"lead":a.lead,"tail":a.tail,"total":round(total,3),
                    "backend":backend,"voice":a.voice or (DEFAULT_EDGE if mode=="edge" else "")},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (BASE/"timeline_draft.json").write_text(
        json.dumps({"lead":a.lead,"total":round(total,3),"lines":timeline,"gaps":[]},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    with (BASE/"report.txt").open("w", encoding="utf-8") as f:
        f.write(f"配音报告  后端 {backend}\n{'='*60}\n")
        f.write(f"句数 {len(selected)}/{len(plan)}   总长 {total:.2f}s\n\n")
        for s in selected:
            f.write(f"{s['tag']}  {s['dur']:>6.2f}s  cps{s['cps']:>4.1f}\n")

    speech = sum(s["dur"] for s in selected)
    chars = sum(len(re.sub(r"[*，。？！；：、]","",s["text"])) for s in selected)
    print(f"\n  实测净 cps = {chars}/{speech:.2f}s = {chars/speech:.2f}")
    print(f"  片长 {total:.2f}s")
    print(f"\n✓ 完成　后端 {backend}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
