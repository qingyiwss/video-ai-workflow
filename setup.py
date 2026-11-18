# -*- coding: utf-8 -*-
"""
环境搭建向导 —— 第一次跑这个

它会：
  ① 检查 Python / ffmpeg / Chrome
  ② 检测硬件，推荐 TTS 方案
  ③ 装 Python 依赖
  ④ 按方案下载需要的模型（或跳过）
  ⑤ 引导录参考音（仅本地模型方案）
  ⑥ 跑一次 3 秒测试音频，验证全链路

用法：
  python setup.py
  python setup.py --check-only     只看不装
  python setup.py --yes            全部默认
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))

MIN_PY = (3, 9)


def hr(title=""):
    print("\n" + "=" * 64)
    if title:
        print(title)
        print("=" * 64)


def ask(prompt, default="n"):
    """y/n 提问，非交互环境返回默认"""
    if not sys.stdin.isatty():
        return default.lower() == "y"
    r = input(f"{prompt} [{'Y/n' if default=='y' else 'y/N'}] ").strip().lower()
    if not r:
        return default.lower() == "y"
    return r in ("y", "yes", "是")


def run(cmd, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=120, **kw)
        return (r.stdout or "") + (r.stderr or ""), r.returncode
    except Exception as e:
        return str(e), -1


# ══════════════════════════════════════════════════════════
# ① Python
# ══════════════════════════════════════════════════════════

def check_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PY
    print(f"  {'✓' if ok else '✗'} Python {v.major}.{v.minor}.{v.micro}")
    if not ok:
        print(f"      需要 {MIN_PY[0]}.{MIN_PY[1]}+")
        print(f"      https://www.python.org/downloads/")
    return ok


# ══════════════════════════════════════════════════════════
# ② Python 依赖
# ══════════════════════════════════════════════════════════

DEPS = {
    "numpy": "numpy>=1.24",
    "soundfile": "soundfile>=0.12",
    "faster_whisper": "faster-whisper>=1.0",
    "edge_tts": "edge-tts>=6.1",
}


def check_deps():
    missing = []
    print()
    for mod, pkg in DEPS.items():
        try:
            __import__(mod)
            print(f"  ✓ {mod}")
        except ImportError:
            print(f"  ✗ {mod}")
            missing.append(pkg)
    return missing


def install_deps(missing, assume_yes=False):
    if not missing:
        return True
    print(f"\n  要装 {len(missing)} 个包：{', '.join(missing)}")
    if not assume_yes and not ask("现在装吗？", "y"):
        print("  跳过。之后手动跑：pip install " + " ".join(missing))
        return False
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + missing
    print(f"\n  执行：{' '.join(cmd[-len(missing)-0:])}\n")
    r = subprocess.run(cmd)
    return r.returncode == 0


# ══════════════════════════════════════════════════════════
# ③ 外部工具
# ══════════════════════════════════════════════════════════

def check_tools():
    from paths import P
    print()
    result = {}
    for name, label in [("ffmpeg", "FFmpeg"), ("ffprobe", "ffprobe"),
                        ("chrome", "Chrome/Edge"), ("node", "Node.js")]:
        if name == "node":
            v = shutil.which("node") or ""
        else:
            v = getattr(P, name)
        ok = bool(v) and (name == "node" or Path(v).exists())
        result[name] = v
        print(f"  {'✓' if ok else '✗'} {label:<12} {v or '未找到'}")

    # 提示怎么装
    if not result["ffmpeg"]:
        print("\n  FFmpeg 没装，怎么装：")
        s = platform.system()
        if s == "Windows":
            print("    winget install Gyan.FFmpeg")
            print("    或下载 https://www.gyan.dev/ffmpeg/builds/ 解压后把 bin 加进 PATH")
        elif s == "Darwin":
            print("    brew install ffmpeg")
        else:
            print("    sudo apt install ffmpeg    (Debian/Ubuntu)")
            print("    sudo dnf install ffmpeg    (Fedora)")

    if not result["chrome"]:
        print("\n  Chrome 没找到：")
        print("    装 Chrome 或 Edge，或用 KAZI_CHROME 指定路径")

    if not result["node"]:
        print("\n  Node.js 没装（渲染画面要用）：")
        print("    https://nodejs.org/  或 winget install OpenJS.NodeJS.LTS")

    return result


def install_node_deps():
    """装 puppeteer-core"""
    from paths import P
    nm = ROOT / "node_modules"
    if (nm / "puppeteer-core").exists():
        print("\n  ✓ puppeteer-core 已装")
        return True

    if not shutil.which("npm"):
        print("\n  ✗ 没有 npm，跳过。手动跑：npm install")
        return False

    print("\n  装 puppeteer-core（约 5 MB）...")
    r = subprocess.run(["npm", "install", "--omit=dev"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="ignore", timeout=300)
    if (nm / "puppeteer-core").exists():
        print("  ✓ 装好了")
        return True
    print(f"  ✗ 失败：{r.stderr[:300] if r.stderr else r.stdout[:300]}")
    print(f"    手动跑：cd {ROOT} && npm install")
    return False


# ══════════════════════════════════════════════════════════
# ④ 硬件检测 + TTS 方案
# ══════════════════════════════════════════════════════════

def detect_and_choose():
    from detect_env import (candidates, detect_cpu, detect_ram_gb,
                            detect_vulkan_devices, detect_api_keys,
                            detect_tools, PLAN_INFO, estimate)

    hr("硬件检测")
    cpu = detect_cpu()
    ram = detect_ram_gb()

    print(f"  CPU    {cpu['name'] or '未知'}")
    print(f"         {cpu['cores']} 核 {cpu['threads']} 线程")
    print(f"  内存   {ram} GB")

    from paths import P
    vk = detect_vulkan_devices(P.audiocpp)
    if vk["available"]:
        for d in vk["devices"]:
            mark = "★" if d["kind"] == "gpu" else " "
            print(f"  {mark}      {d['backend']}:{d['index']}  {d['name']}  [{d['kind']}]")
    else:
        print(f"  GPU    未检测到（{vk['reason']}）")

    keys = detect_api_keys()
    print(f"  API Key  {', '.join(keys) if keys else '无'}")

    cands = candidates(cpu, ram, vk, keys, detect_tools())

    hr("推荐 TTS 方案")
    for i, (pid, why, spd) in enumerate(cands, 1):
        info = PLAN_INFO[pid]
        mark = "★ 推荐" if i == 1 else f"  [{i}]"
        clone = "可克隆音色" if info["clone"] is True else \
                ("部分" if info["clone"] == "部分" else "⚠️ 不能克隆")
        print(f"\n{mark}  {info['name']}")
        print(f"      {why}")
        print(f"      音色：{clone}    下载：{info['download']}")
        print(f"      预计：{estimate(spd, 39, 4)}（39 句 × 4 轮）")

    print("\n  提醒：卡字率、画面、节奏跟用哪个 TTS 无关，")
    print("        换的只是「声音是不是你自己的」。")

    # 选
    choice = cands[0][0]
    if len(cands) > 1 and sys.stdin.isatty():
        try:
            r = input(f"\n用哪个？[1-{len(cands)}，默认 1] ").strip()
            if r.isdigit() and 1 <= int(r) <= len(cands):
                choice = cands[int(r)-1][0]
        except EOFError:
            pass

    return choice


# ══════════════════════════════════════════════════════════
# ⑤ 模型下载（仅本地方案）
# ══════════════════════════════════════════════════════════

MODEL_INFO = {
    "url": "https://huggingface.co/cstr/cosyvoice3-0.5b-2512-GGUF/resolve/main/cosyvoice3-q8_0.gguf",
    "size": "2.1 GB",
    "name": "cosyvoice3-q8_0.gguf",
}

ENGINE_INFO = {
    "note": "audiocpp 引擎（84 MB）需要从 GitHub Releases 下载",
    "url": "https://github.com/ShugoAI/audiocpp/releases",
}


def ensure_local_assets(assume_yes=False):
    """检查本地模型方案需要的文件"""
    from paths import P

    hr("本地模型文件")

    model_dir = ROOT / "models"
    model_dir.mkdir(exist_ok=True)
    voice_dir = ROOT / "my-voice"
    voice_dir.mkdir(exist_ok=True)
    vendor_dir = ROOT / "vendor" / "audiocpp"
    vendor_dir.mkdir(parents=True, exist_ok=True)

    ok = True

    # ① 引擎
    if P.audiocpp and Path(P.audiocpp).exists():
        print(f"  ✓ 引擎    {P.audiocpp}")
    else:
        print(f"  ✗ 引擎    未找到")
        print(f"      {ENGINE_INFO['note']}")
        print(f"      {ENGINE_INFO['url']}")
        print(f"      下载后放：{vendor_dir}")
        ok = False

    # ② 模型
    if P.model and Path(P.model).exists():
        sz = Path(P.model).stat().st_size / 1024**3
        print(f"  ✓ 模型    {P.model}  ({sz:.1f} GB)")
    else:
        print(f"  ✗ 模型    未找到（{MODEL_INFO['size']}）")
        target = model_dir / MODEL_INFO["name"]
        print(f"      下载地址：{MODEL_INFO['url']}")
        print(f"      保存为：  {target}")
        if ask("      现在下载吗？（国内可能需要代理）", "n"):
            download_file(MODEL_INFO["url"], target)
        else:
            ok = False

    # ③ 参考音
    if P.ref and Path(P.ref).exists():
        print(f"  ✓ 参考音  {P.ref}")
    else:
        print(f"  ✗ 参考音  未找到")
        print(f"      需要录 20 秒你自己的声音，存成 {voice_dir / 'ref.wav'}")
        print(f"      并在同目录写 ref.txt（这段音频的文字）")
        print(f"\n      要求：")
        print(f"        · 16kHz 以上，单声道或立体声")
        print(f"        · 15-30 秒，一口气念完，不要念稿停顿")
        print(f"        · 安静环境，无背景音乐")
        print(f"        · 内容：随便一段话，但要写下来")
        ok = False

    return ok


def download_file(url, target):
    import urllib.request
    print(f"  下载中...")
    try:
        def hook(blocks, bs, total):
            if total > 0:
                pct = min(100, blocks * bs * 100 // total)
                mb = blocks * bs / 1024**2
                print(f"\r    {pct}%  {mb:.0f} MB", end="", flush=True)
        urllib.request.urlretrieve(url, target, hook)
        print(f"\n  ✓ 完成 {target.stat().st_size/1024**3:.1f} GB")
        return True
    except Exception as e:
        print(f"\n  ✗ 失败：{e}")
        print(f"    可以手动下载：{url}")
        return False


# ══════════════════════════════════════════════════════════
# ⑥ 冒烟测试
# ══════════════════════════════════════════════════════════

def smoke_test(backend):
    hr("冒烟测试")
    tmp = ROOT / "_setup-test"
    tmp.mkdir(exist_ok=True)

    (tmp / "script.md").write_text(
        "[01 测试]\n这是一句用来验证环境的话，大概二十个字左右。 | 0.5\n",
        encoding="utf-8")

    cmd = [sys.executable, str(ROOT/"tools"/"gen_voice.py"), str(tmp),
           "--backend", backend]
    print(f"  执行：gen_voice.py --backend {backend}\n")
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", timeout=600)
    out = (r.stdout or "") + (r.stderr or "")

    # 只打印关键行
    for line in out.splitlines():
        if any(k in line for k in ["配音：", "音色", "句", "cps", "✓", "✗", "完成", "失败"]):
            print(f"    {line.strip()[:90]}")

    wav = tmp / "narration.wav"
    ok = wav.exists() and wav.stat().st_size > 1000

    if ok:
        print(f"\n  ✓ 生成 {wav.stat().st_size/1024:.0f} KB")
        print(f"    听一下：{wav}")
    else:
        print(f"\n  ✗ 失败")
        print(f"    完整输出：")
        for line in out.splitlines()[-15:]:
            print(f"      {line}")

    # 清理
    import shutil as sh
    sh.rmtree(tmp, ignore_errors=True)
    return ok


# ══════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="环境搭建向导")
    ap.add_argument("--check-only", action="store_true", help="只检查不安装")
    ap.add_argument("--yes", action="store_true", help="全部用默认值")
    a = ap.parse_args()

    print("""
╔══════════════════════════════════════════════════════════╗
║  AI 讲解视频工作流 · 环境搭建向导                        ║
╚══════════════════════════════════════════════════════════╝
""")

    # ① Python
    hr("① Python")
    if not check_python():
        return 1

    # ② 依赖
    hr("② Python 依赖")
    missing = check_deps()
    if a.check_only:
        print(f"\n  缺 {len(missing)} 个包")
    else:
        install_deps(missing, a.yes)

    # ③ 工具
    hr("③ 外部工具")
    tools = check_tools()
    if not a.check_only and tools.get("node"):
        install_node_deps()

    # ④ 硬件 + 方案
    backend = detect_and_choose()

    # ⑤ 模型（本地方案才需要）
    local_ok = True
    if backend.startswith("local"):
        if a.check_only:
            from paths import P
            print(f"\n  引擎 {P.audiocpp or '未找到'}")
            print(f"  模型 {P.model or '未找到'}")
            print(f"  参考音 {P.ref or '未找到'}")
        else:
            local_ok = ensure_local_assets(a.yes)
            if not local_ok:
                print(f"\n  ⚠ 本地文件不全，先用 edge-tts 跑通流程")
                print(f"    之后补齐文件再切回来")
                backend = "edge-tts"

    if a.check_only:
        hr("检查完毕")
        print("  加 --yes 会自动装（不改系统）")
        return 0

    # ⑥ 冒烟
    if backend == "edge-tts" or local_ok:
        smoke_test(backend)
    else:
        print("\n  ⚠ 跳过冒烟测试（本地文件不全）")

    hr("完成")
    print(f"""
  下一步：

    ① 看 README.md 了解全流程
    ② 跑 python make_demo.py 生成 15 秒示例
    ③ 读 工作流.md 开始做你自己的片子

  你的 TTS 方案：{backend}
  要换？改 config.json 或设环境变量，或重跑 python setup.py
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
