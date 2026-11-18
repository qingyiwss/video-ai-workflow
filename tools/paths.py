# -*- coding: utf-8 -*-
"""
统一路径解析 —— 所有工具都从这里拿路径，不写死

优先级（从高到低）：
  ① 环境变量  KAZI_FFMPEG / KAZI_CHROME / KAZI_PUPPETEER / KAZI_AUDIOCPP / KAZI_MODEL
  ② 项目根 config.json 里的路径
  ③ 自动探测（PATH / 常见安装位置 / 项目内 vendor/）

用法：
  from paths import P
  P.ffmpeg        → "/path/to/ffmpeg" 或 "ffmpeg"（从 PATH 找）
  P.chrome        → "/path/to/chrome" 或 ""（自动探测）
  P.puppeteer     → "./node_modules/puppeteer-core"
  P.audiocpp      → "./vendor/audiocpp/audiocpp_cli.exe"
  P.model         → "./models/cosyvoice3-q8_0.gguf"

  P.require("ffmpeg")   → 找不到就报错并给出安装提示
"""
import json
import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"


def _load_config():
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


_CFG = _load_config()


def _from_cfg(section, key, default=""):
    return (_CFG.get(section) or {}).get(key) or default


# ══════════════════════════════════════════════════════════
# FFmpeg / ffprobe
# ══════════════════════════════════════════════════════════

def _find_ffmpeg(name):
    # ① 环境变量
    env = os.environ.get(f"KAZI_{name.upper()}")
    if env and Path(env).exists():
        return str(Path(env).resolve())
    # ② config
    cfg = _from_cfg("ffmpeg", name)
    if cfg and Path(cfg).exists():
        return str(Path(cfg).resolve())
    # ③ PATH
    w = shutil.which(name)
    if w:
        return w
    # ④ 常见位置（Windows）
    if platform.system() == "Windows":
        for base in [r"C:\ffmpeg\bin", os.path.expanduser(r"~\scoop\shims"),
                     r"C:\ProgramData\chocolatey\bin",
                     str(ROOT / "vendor" / "ffmpeg" / "bin")]:
            p = Path(base) / f"{name}.exe"
            if p.exists():
                return str(p)
    # ⑤ 项目内
    for sub in [ROOT/"vendor"/"ffmpeg"/"bin", ROOT/"vendor"]:
        p = sub/f"{name}.exe" if platform.system()=="Windows" else sub/name
        if p.exists():
            return str(p)
    return ""


# ══════════════════════════════════════════════════════════
# Chrome
# ══════════════════════════════════════════════════════════

def _find_chrome():
    env = os.environ.get("KAZI_CHROME")
    if env and Path(env).exists():
        return str(Path(env).resolve())
    cfg = _from_cfg("chrome", "path")
    if cfg and Path(cfg).exists():
        return str(Path(cfg).resolve())

    system = platform.system()
    cands = []
    if system == "Windows":
        cands = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
    elif system == "Darwin":
        cands = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        for n in ["google-chrome", "google-chrome-stable", "chromium",
                  "chromium-browser", "microsoft-edge"]:
            w = shutil.which(n)
            if w:
                cands.append(w)
    for c in cands:
        if c and Path(c).exists():
            return c
    return ""


# ══════════════════════════════════════════════════════════
# puppeteer-core
# ══════════════════════════════════════════════════════════

def _find_puppeteer():
    env = os.environ.get("KAZI_PUPPETEER")
    if env and Path(env).exists():
        return str(Path(env).resolve())
    cfg = _from_cfg("node", "puppeteer")
    if cfg and Path(cfg).exists():
        return str(Path(cfg).resolve())

    for sub in [ROOT, ROOT/"node_modules", ROOT.parent, Path.cwd()]:
        p = sub/"node_modules"/"puppeteer-core"
        if p.exists():
            return str(p).replace("\\", "/")
    # 全局
    w = shutil.which("node")
    if w:
        try:
            import subprocess
            r = subprocess.run([w, "-e",
                                "try{console.log(require.resolve('puppeteer-core'))}catch(e){console.log('')}"],
                               capture_output=True, text=True, timeout=10)
            if r.stdout.strip():
                return str(Path(r.stdout.strip()).parent.parent).replace("\\", "/")
        except Exception:
            pass
    return ""


# ══════════════════════════════════════════════════════════
# audiocpp 引擎 + 模型 + 参考音
# ══════════════════════════════════════════════════════════

def _find_audiocpp():
    env = os.environ.get("KAZI_AUDIOCPP")
    if env and Path(env).exists():
        return str(Path(env).resolve())
    cfg = _from_cfg("tts", "exe")
    if cfg and Path(cfg).exists():
        return str(Path(cfg).resolve())

    exe = "audiocpp_cli.exe" if platform.system() == "Windows" else "audiocpp_cli"
    for sub in [ROOT/"vendor"/"audiocpp", ROOT/"audiocpp",
                ROOT/"vendor"/"audiocpp"/"build"/"bin",
                ROOT/"vendor"/"audiocpp"/"bin"]:
        p = sub/exe
        if p.exists():
            return str(p.resolve())
    w = shutil.which("audiocpp_cli")
    return w or ""


def _find_model():
    env = os.environ.get("KAZI_MODEL")
    if env and Path(env).exists():
        return str(Path(env).resolve())
    cfg = _from_cfg("tts", "model")
    if cfg and Path(cfg).exists():
        return str(Path(cfg).resolve())

    # 优先 q8（2.1GB，够用），再 f32
    names = ["cosyvoice3-q8_0.gguf", "cosyvoice3-f32.gguf"]
    for sub in [ROOT/"models", ROOT/"vendor"/"models",
                ROOT/"vendor"/"audiocpp"/"models"/"CosyVoice3"]:
        for n in names:
            p = sub/n
            if p.exists():
                return str(p.resolve())
    return ""


def _find_ref():
    """参考音 —— 用户自己录的，或 config 指定"""
    env = os.environ.get("KAZI_REF")
    if env and Path(env).exists():
        return str(Path(env).resolve())
    cfg = _from_cfg("tts", "ref")
    if cfg and Path(cfg).exists():
        return str(Path(cfg).resolve())

    for sub in [ROOT/"my-voice", ROOT/"voice", ROOT/"assets"]:
        for n in ["ref.wav", "ref-norm.wav", "reference.wav"]:
            p = sub/n
            if p.exists():
                return str(p.resolve())
    return ""


def _find_ref_text():
    env = os.environ.get("KAZI_REF_TEXT")
    if env:
        return env
    t = _from_cfg("tts", "ref_text")
    if t:
        return t
    # 找 sidecar 文件
    ref = _find_ref()
    if ref:
        p = Path(ref).with_suffix(".txt")
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return ""


# ══════════════════════════════════════════════════════════
# Whisper 模型
# ══════════════════════════════════════════════════════════

def _find_whisper():
    """找 Whisper 模型

    顺序：
      ① 环境变量 KAZI_WHISPER
      ② config.json asr.model
      ③ 项目内 models/faster-whisper-*
      ④ HuggingFace 缓存里已有的
      ⑤ 回退 "small"（会联网下载，约 300MB）
    """
    env = os.environ.get("KAZI_WHISPER")
    if env:
        return env
    cfg = _from_cfg("asr", "model")
    if cfg:
        return cfg

    # 项目内
    for name in ["faster-whisper-medium", "faster-whisper-small",
                 "faster-whisper-base"]:
        p = ROOT/"models"/name
        if p.exists():
            return str(p.resolve())

    # 用户 home 下的 models（常见做法）
    for base in [Path.home()/"models"]:
        if not base.exists():
            continue
        for name in ["models--Systran--faster-whisper-medium",
                     "models--Systran--faster-whisper-small"]:
            d = base/name/"snapshots"
            if d.exists():
                snaps = [s for s in d.iterdir() if s.is_dir()]
                if snaps:
                    return str(snaps[0].resolve())

    # HuggingFace 缓存（已经下过的）
    hf = Path.home()/".."/".cache"/"huggingface"/"hub"
    for base in [Path(os.environ.get("HF_HOME", "")) if os.environ.get("HF_HOME") else None,
                 Path.home()/".cache"/"huggingface"/"hub",
                 Path(os.environ.get("LOCALAPPDATA", ""))/"huggingface"/"hub"
                 if os.environ.get("LOCALAPPDATA") else None]:
        if not base or not base.exists():
            continue
        for name in ["models--Systran--faster-whisper-medium",
                     "models--Systran--faster-whisper-small"]:
            d = base/name/"snapshots"
            if d.exists():
                snaps = [s for s in d.iterdir() if s.is_dir()]
                if snaps:
                    return str(snaps[0].resolve())

    # 兜底：让 faster-whisper 下（需要网络）
    return "small"


# ══════════════════════════════════════════════════════════
# 音效 / BGM
# ══════════════════════════════════════════════════════════

def _find_sfx():
    env = os.environ.get("KAZI_SFX")
    if env and Path(env).exists():
        return str(Path(env).resolve())
    cfg = _from_cfg("audio", "sfx")
    if cfg and Path(cfg).exists():
        return str(Path(cfg).resolve())
    for sub in [ROOT/"assets"/"sfx", ROOT/"vendor"/"kenney"/"interface-sounds"/"Audio"]:
        if sub.exists():
            return str(sub.resolve())
    return ""


def _find_bgm():
    env = os.environ.get("KAZI_BGM")
    if env and Path(env).exists():
        return str(Path(env).resolve())
    cfg = _from_cfg("audio", "bgm")
    if cfg and Path(cfg).exists():
        return str(Path(cfg).resolve())
    for sub in [ROOT/"assets"/"bgm"]:
        if sub.exists():
            return str(sub.resolve())
    return ""


# ══════════════════════════════════════════════════════════

class Paths:
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        cache = self.__dict__.setdefault("_cache", {})
        if name in cache:
            return cache[name]
        fn = {
            "ffmpeg": lambda: _find_ffmpeg("ffmpeg"),
            "ffprobe": lambda: _find_ffmpeg("ffprobe"),
            "chrome": _find_chrome,
            "puppeteer": _find_puppeteer,
            "audiocpp": _find_audiocpp,
            "model": _find_model,
            "ref": _find_ref,
            "ref_text": _find_ref_text,
            "whisper": _find_whisper,
            "sfx": _find_sfx,
            "bgm": _find_bgm,
            "root": lambda: str(ROOT),
        }.get(name)
        if fn is None:
            raise AttributeError(f"Paths 没有 {name}")
        v = fn()
        cache[name] = v
        return v

    def require(self, *names):
        """检查必需项，缺了给出安装提示并退出"""
        missing = []
        for n in names:
            v = getattr(self, n)
            if not v or (n in ("ffmpeg","ffprobe","chrome","audiocpp","model","ref")
                         and not Path(v).exists()):
                missing.append(n)
        if not missing:
            return True

        print("\n" + "="*60)
        print("缺少依赖")
        print("="*60)
        tips = {
            "ffmpeg": "  Windows: winget install ffmpeg\n"
                      "  macOS:   brew install ffmpeg\n"
                      "  Linux:   sudo apt install ffmpeg\n"
                      "  或设置 KAZI_FFMPEG=/path/to/ffmpeg",
            "ffprobe": "  跟 ffmpeg 一起装的，检查 PATH",
            "chrome": "  装 Chrome，或设置 KAZI_CHROME=/path/to/chrome\n"
                      "  （Edge 也行，会自动找）",
            "audiocpp": "  从 GitHub Releases 下载，放到 vendor/audiocpp/\n"
                        "  或设置 KAZI_AUDIOCPP=/path/to/audiocpp_cli",
            "model": "  下载 cosyvoice3-q8_0.gguf（2.1GB），放到 models/\n"
                     "  或设置 KAZI_MODEL=/path/to/model.gguf\n"
                     "  没有显卡？用 --backend edge-tts，不需要模型",
            "ref": "  录 20 秒自己的声音，存成 my-voice/ref.wav\n"
                   "  并在同目录写 ref.txt（这段音频的文字）\n"
                   "  没有？用 --backend edge-tts",
        }
        for m in missing:
            print(f"\n✗ {m}")
            print(tips.get(m, "  未知依赖"))
        print("\n先跑 python tools/detect_env.py 看你的机器适合哪个方案")
        print("="*60 + "\n")
        sys.exit(1)


P = Paths()


def load_project_config(project_dir):
    """读项目目录下的 config.json（覆盖全局）"""
    p = Path(project_dir)/"config.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


if __name__ == "__main__":
    print("路径解析结果：\n")
    for k in ["root","ffmpeg","ffprobe","chrome","puppeteer",
              "audiocpp","model","ref","whisper","sfx","bgm"]:
        v = getattr(P, k)
        if k == "ref_text":
            v = (v or "")[:40] + "..."
        mark = "✓" if v else "✗"
        if v and k not in ("ref_text","whisper") and not Path(str(v)).exists():
            mark = "✗"
        print(f"  {mark} {k:<12} {v or '（未找到）'}")
