# -*- coding: utf-8 -*-
"""
kazi_check 复刻：量卡字率
  动量 = 每帧与上一帧相比、变化超过 6 个灰阶的像素占比（缩到 192x108 灰度）
  关键词窗口 [t0-0.35, t0+0.15]；对照窗口 [t0-1.35, t0-0.45]
  判定：near >= 1.5 * before + 0.001
  随机基线：同样的判断放到旁白里每一个时刻上
"""
from paths import P
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("video")
ap.add_argument("--timeline", default="")
ap.add_argument("--keywords", default="")
ap.add_argument("--early", type=float, default=0.35)
ap.add_argument("--late", type=float, default=0.15)
ap.add_argument("--offset", type=float, default=0.0,
                help="视频第 0 秒对应时间表里的第几秒（只渲染了一段时用）")
ap.add_argument("--json", default="")
ap.add_argument("--quiet", action="store_true")
a = ap.parse_args()

W, H = 192, 108


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def keywords_from_timeline(tl):
    if tl.get("keywords"):
        return [{"word": k["word"], "t": k["t"], "line": k.get("line")} for k in tl["keywords"]]
    out = []
    for l in tl["lines"]:
        run = []
        for c in l["cap"] + [{"c": "", "s": 0}]:
            if c.get("k"):
                run.append(c)
            elif run:
                out.append({"word": "".join(x["c"] for x in run), "t": run[0]["s"], "line": l["i"]})
                run = []
    return out


info = probe(a.video)
vs = next(s for s in info["streams"] if s["codec_type"] == "video")
num, den = map(int, vs.get("avg_frame_rate", vs["r_frame_rate"]).split("/"))
fps = num / den if den else 30.0
dur = float(info["format"].get("duration", vs.get("duration", 0)))
auds = [s for s in info["streams"] if s["codec_type"] == "audio"]

cmd = [P.ffmpeg, "-v", "error", "-i", a.video,
       "-vf", f"scale={W}:{H}:flags=area,format=gray",
       "-f", "rawvideo", "-pix_fmt", "gray", "-"]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
N = W * H
act, mad, lum, flash = [], [], [], []
prev = prev2 = None
while True:
    buf = proc.stdout.read(N)
    if len(buf) < N:
        break
    f = np.frombuffer(buf, np.uint8).astype(np.int16).reshape(H, W)
    lum.append(float(f.mean()))
    if prev is None:
        act.append(0.0); mad.append(0.0)
    else:
        d = np.abs(f - prev)
        act.append(float((d > 6).mean())); mad.append(float(d.mean()))
        if prev2 is not None and mad[-2] > 10 and float(np.abs(f - prev2).mean()) < 2.5:
            flash.append(len(act) - 2)
    prev2, prev = prev, f
proc.wait()

act = np.array(act); mad = np.array(mad); lum = np.array(lum); n = len(act)
if n < 2:
    sys.exit("读不到画面")

sm = np.convolve(act, np.ones(3)/3, mode="same")


def mean_in(t1, t2):
    i1, i2 = max(0, int(round(t1*fps))), min(n, int(round(t2*fps))+1)
    return float(sm[i1:i2].mean()) if i2 > i1 else 0.0


def judge(t0):
    near = mean_in(t0 - a.early, t0 + a.late)
    before = mean_in(t0 - a.early - 1.0, t0 - a.early - 0.1)
    return near >= 1.5*before + 0.001, near, before


kws = []
tl = {}
if a.timeline:
    tl = json.loads(Path(a.timeline).read_text("utf-8"))
    kws = keywords_from_timeline(tl)
elif a.keywords:
    kws = json.loads(Path(a.keywords).read_text("utf-8"))

if a.offset:
    # 片段模式：先偏移，再按片段时长过滤
    kws = [{**k, "t": round(k["t"] - a.offset, 3)} for k in kws]
    kws = [k for k in kws if 0 <= k["t"] <= dur]
else:
    kws = [k for k in kws if 0 <= k["t"] <= dur]

report = {"video": str(a.video), "fps": round(fps,3), "frames": n,
          "duration": round(dur,3), "size": f"{vs.get('width')}x{vs.get('height')}",
          "audio_streams": len(auds)}
problems = []

if kws:
    rows = []
    for k in kws:
        ok, near, before = judge(k["t"])
        rows.append({**k, "hit": bool(ok), "near": round(near*100,2), "before": round(before*100,2)})
    hits = sum(r["hit"] for r in rows)
    lo = max(min(k["t"] for k in kws) - 1.0, a.early + 1.0)
    hi_ = min(max(k["t"] for k in kws) + 1.0, n/fps - a.late)
    grid = np.arange(lo, hi_, 1/fps)
    chance = float(np.mean([judge(t)[0] for t in grid])) if len(grid) else 0.0
    rate = hits / len(rows)
    report.update({"keywords": len(rows), "hits": hits, "kazi_rate": round(rate,3),
                   "chance": round(chance,3), "lift": round(rate-chance,3),
                   "window": [-a.early, a.late], "detail": rows})

black = np.where(lum < 8)[0]
black = [int(i) for i in black if 0.5*fps < i < n - 0.5*fps]
if black:
    problems.append(f"黑帧 {len(black)} 帧，第一处 {black[0]/fps:.2f}s")
if flash:
    problems.append(f"一闪而过 {len(flash)} 处：" + "、".join(f"{i/fps:.2f}s" for i in flash[:8]))

cuts = [i for i in range(1, n) if act[i] > 0.5]
static, run_, longest, at_ = act < 0.0005, 0, 0, 0
for i, s in enumerate(static):
    run_ = run_ + 1 if s else 0
    if run_ > longest:
        longest, at_ = run_, i - run_ + 1
if longest/fps > 6:
    problems.append(f"画面 {longest/fps:.1f}s 完全不动（从 {at_/fps:.1f}s）")

report.update({"black_frames": len(black),
               "flash_frames": [round(i/fps,3) for i in flash],
               "hard_cuts": len(cuts), "longest_static": round(longest/fps,2)})

if auds:
    r = subprocess.run([P.ffmpeg,"-nostats","-i",a.video,"-map","0:a:0",
                        "-af","ebur128=peak=true","-f","null","-"],
                       capture_output=True, text=True)
    m_i = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    m_p = re.findall(r"Peak:\s+(-?[\d.inf]+) dBFS", r.stderr)
    if m_i: report["lufs"] = float(m_i[-1])
    if m_p:
        try: report["true_peak"] = float(m_p[-1])
        except ValueError: pass
    if "lufs" in report and not (-16.5 <= report["lufs"] <= -12.5):
        problems.append(f"响度 {report['lufs']} LUFS，应在 -14 左右")
    if report.get("true_peak", -99) > -1.0:
        problems.append(f"真峰值 {report['true_peak']} dBTP 超过 -1")
else:
    problems.append("没有音轨")

if tl.get("total") and abs(tl["total"] - dur) > 0.5 and dur > 1:
    problems.append(f"片长 {dur:.2f}s 与时间表 {tl['total']:.2f}s 不符")

report["problems"] = problems

if a.json:
    Path(a.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")

if not a.quiet:
    print(f"{a.video}")
    print(f"  {report['size']}  {fps:.2f}fps  {dur:.2f}s  音轨 {len(auds)} 条")
    if kws:
        print(f"\n卡字率 {report['hits']}/{report['keywords']} = {report['kazi_rate']:.0%}")
        print(f"随机基线 {report['chance']:.0%}   高出随机 {report['lift']:+.0%}")
        print(f"\n{'判定':<8}{'时刻':>8}{'关键词':<10}{'这一下':>9}{'前一秒':>9}{'倍数':>7}")
        print("-"*56)
        for r_ in report["detail"]:
            mark = "✓ 卡上" if r_["hit"] else "✗ 没卡上"
            ratio = r_["near"]/max(r_["before"],0.001)
            print(f"{mark:<8}{r_['t']:>8.2f}{r_['word']:<10}{r_['near']:>8.2f}%{r_['before']:>8.2f}%{ratio:>6.1f}x")
    if "lufs" in report:
        print(f"\n响度 {report['lufs']} LUFS   真峰值 {report.get('true_peak','?')} dBTP")
    print(f"\n问题：{'；'.join(problems) if problems else '没有'}")
