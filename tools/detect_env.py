# -*- coding: utf-8 -*-
"""
环境检测 —— 开工前跑一次，告诉用户能用哪个 TTS 方案

用法：
  python tools/detect_env.py
  python tools/detect_env.py --json        # 机器可读

检测顺序（按优先级）：
  ① 本地 GPU（Vulkan/CUDA）→ 最优，3.9 秒/句
  ② 在线 API（有 Key）    → 快，但音色受服务商限制
  ③ 本地 CPU              → 慢 48 倍，音色可克隆
  ④ edge-tts              → 免费兜底，音色通用

依据：docs/TTS-PLANS.md 实测数据
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ── 阈值（实测得出，见 docs/TTS-PLANS.md）──
MIN_VRAM_GB = 6       # 低于这个，独显也跑不快
MIN_RAM_GB = 16
MIN_CPU_CORES = 8
GPU_SEC_PER_LINE = 4      # 实测 3.9
CPU_SEC_PER_LINE = 188    # 实测 187.8
EDGE_SEC_PER_LINE = 1


def run(cmd, timeout=30, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore",
                           timeout=timeout, **kw)
        return (r.stdout or "") + (r.stderr or ""), r.returncode
    except Exception as e:
        return str(e), -1


# ══════════════════════════════════════════════════════════
# 硬件探测
# ══════════════════════════════════════════════════════════

def detect_cpu():
    """返回 {cores, threads, name}"""
    out = {"cores": 0, "threads": 0, "name": "unknown"}
    if platform.system() == "Windows":
        # 优先 PowerShell CIM（wmic 在新系统被移除）
        ps = ('Get-CimInstance Win32_Processor | '
              'Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | '
              'ConvertTo-Json')
        txt, rc = run(["powershell", "-NoProfile", "-Command", ps])
        if rc == 0 and txt.strip().startswith(("{", "[")):
            try:
                d = json.loads(txt)
                if isinstance(d, list):
                    d = d[0]
                out["cores"] = int(d.get("NumberOfCores") or 0)
                out["threads"] = int(d.get("NumberOfLogicalProcessors") or 0)
                out["name"] = (d.get("Name") or "").strip()
            except Exception:
                pass
    else:
        try:
            out["threads"] = os.cpu_count() or 0
            out["cores"] = out["threads"] // 2 or out["threads"]
            if platform.system() == "Linux":
                txt, _ = run(["bash", "-c",
                              "lscpu | grep -E 'Model name|Core|Thread' || true"])
                m = re.search(r"Model name:\s*(.+)", txt)
                if m:
                    out["name"] = m.group(1).strip()
        except Exception:
            pass
    return out


def detect_ram_gb():
    if platform.system() == "Windows":
        ps = 'Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize | ConvertTo-Json'
        txt, rc = run(["powershell", "-NoProfile", "-Command", ps])
        if rc == 0:
            try:
                d = json.loads(txt)
                if isinstance(d, list):
                    d = d[0]
                return round(int(d["TotalVisibleMemorySize"]) / 1024 / 1024, 1)
            except Exception:
                pass
    else:
        try:
            with open("/proc/meminfo") as f:
                m = re.search(r"MemTotal:\s*(\d+)\s*kB", f.read())
                if m:
                    return round(int(m.group(1)) / 1024 / 1024, 1)
        except Exception:
            pass
    return 0.0


def detect_vulkan_devices(audiocpp_exe):
    """用 audiocpp_cli --list-devices 探 Vulkan/CUDA 设备"""
    if not audiocpp_exe or not Path(audiocpp_exe).exists():
        return {"available": False, "devices": [], "reason": "引擎不存在"}

    txt, rc = run([str(audiocpp_exe), "--list-devices"], timeout=60)
    if rc != 0:
        return {"available": False, "devices": [], "reason": f"list-devices 失败 rc={rc}"}

    devices = []
    # 格式： Vulkan:0 "<显卡名>" [GPU]
    for line in txt.splitlines():
        m = re.match(r'\s*(Vulkan|CUDA|HIP|Metal|CPU):(\d+)\s+"([^"]+)"\s*\[(\w+)\]', line)
        if m:
            devices.append({
                "backend": m.group(1).lower(),
                "index": int(m.group(2)),
                "name": m.group(3).strip(),
                "kind": m.group(4).lower(),   # GPU / IGPU / CPU
            })
    return {"available": bool(devices), "devices": devices, "reason": "ok"}


def detect_gpu_system():
    """不依赖 audiocpp，直接从系统查有没有独显

    为什么需要：
      audiocpp 第一次跑时还没下载，但用户可能已经有显卡。
      如果只看 --list-devices，会误判成「没显卡」→ 推荐 8 小时的 CPU 方案。
      新人看到 8 小时可能直接关掉。

    返回：{has_discrete, has_igpu, names[]}
    """
    out = {"has_discrete": False, "has_igpu": False,
           "names": [], "discrete": [], "igpu": []}
    system = platform.system()

    if system == "Windows":
        ps = 'Get-CimInstance Win32_VideoController | Select-Object Name | ConvertTo-Json'
        txt, rc = run(["powershell", "-NoProfile", "-Command", ps])
        if rc == 0 and txt.strip().startswith(("{", "[")):
            try:
                d = json.loads(txt)
                if isinstance(d, dict):
                    d = [d]
                for g in d:
                    name = (g.get("Name") or "").strip()
                    if not name:
                        continue
                    low = name.lower()
                    # ⚠️ 排除虚拟显示适配器（远程桌面 / 串流 / 虚拟机的假显卡）
                    VIRTUAL = ["virtual", "gameviewer", "parsec", "sunshine",
                               "basic display", "remote", "spacedesk",
                               "mirror", "idd", "displaylink"]
                    if any(v in low for v in VIRTUAL):
                        continue
                    out["names"].append(name)
                    # 核显关键词
                    if any(k in low for k in ["intel", "radeon(tm) graphics",
                                               "uhd graphics", "iris", "vega 8",
                                               "vega 11", "apu"]):
                        out["has_igpu"] = True
                        out["igpu"].append(name)
                    # 独显关键词
                    elif any(k in low for k in ["nvidia", "geforce", "rtx", "gtx",
                                                "radeon rx", "arc a", "quadro", "tesla"]):
                        out["has_discrete"] = True
                        out["discrete"].append(name)
            except Exception:
                pass

    elif system == "Darwin":
        txt, rc = run(["system_profiler", "SPDisplaysDataType"])
        if rc == 0:
            # Apple Silicon 的 GPU 也算能跑
            if "Apple M" in txt:
                out["has_discrete"] = True
                m = re.search(r"Chipset Model:\s*(.+)", txt)
                out["names"].append(m.group(1).strip() if m else "Apple Silicon")
            elif "AMD" in txt or "NVIDIA" in txt:
                out["has_discrete"] = True
                for m in re.finditer(r"Chipset Model:\s*(.+)", txt):
                    out["names"].append(m.group(1).strip())

    else:  # Linux
        txt, rc = run(["bash", "-c", "lspci | grep -i -E 'vga|3d|display' || true"])
        if rc == 0:
            for line in txt.splitlines():
                if ":" not in line:
                    continue
                name = line.split(":", 2)[-1].strip()
                out["names"].append(name)
                low = name.lower()
                if any(k in low for k in ["nvidia", "amd", "radeon"]):
                    # AMD 有可能是核显
                    if "renoir" in low or "cezanne" in low or "vega" in low:
                        out["has_igpu"] = True
                    else:
                        out["has_discrete"] = True
                elif "intel" in low:
                    out["has_igpu"] = True

    return out


def detect_gpu_wmi():
    """WMI 查显卡名和显存（显存可能不准，只能参考）"""
    out = []
    if platform.system() != "Windows":
        return out
    ps = ('Get-CimInstance Win32_VideoController | '
          'Select-Object Name,AdapterRAM | ConvertTo-Json')
    txt, rc = run(["powershell", "-NoProfile", "-Command", ps])
    if rc == 0 and txt.strip().startswith(("{", "[")):
        try:
            d = json.loads(txt)
            if isinstance(d, dict):
                d = [d]
            for g in d:
                vram = g.get("AdapterRAM")
                out.append({
                    "name": (g.get("Name") or "").strip(),
                    "vram_gb": round(int(vram) / 1024**3, 1) if vram and str(vram).isdigit() else 0,
                })
        except Exception:
            pass
    return out


def detect_tools():
    """检查外部工具是否可用"""
    out = {}
    out["ffmpeg"] = shutil.which("ffmpeg") or ""
    out["ffprobe"] = shutil.which("ffprobe") or ""
    out["node"] = shutil.which("node") or ""

    # Chrome
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
    ]
    out["chrome"] = next((c for c in chrome_candidates if c and Path(c).exists()), "")

    return out


def detect_api_keys():
    """看环境变量里有没有在线 TTS 的 Key"""
    keys = {
        "dashscope": ["DASHSCOPE_API_KEY", "ALIYUN_API_KEY"],
        "volcengine": ["VOLC_ACCESSKEY", "VOLCENGINE_API_KEY"],
        "minimax": ["MINIMAX_API_KEY", "MINIMAX_GROUP_ID"],
        "azure": ["AZURE_SPEECH_KEY"],
    }
    found = []
    for name, envs in keys.items():
        if any(os.environ.get(e) for e in envs):
            found.append(name)
    return found


def detect_python():
    return {
        "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "exe": sys.executable,
        "ok": sys.version_info >= (3, 9),
    }


# ══════════════════════════════════════════════════════════
# 决策
# ══════════════════════════════════════════════════════════

def candidates(cpu, ram, vk, api_keys, tools):
    """返回所有可行方案，按优先级排序 [(plan_id, 理由, 秒/句), ...]"""

    out = []

    # ① 独显
    sysgpu = None
    if vk["available"]:
        gpus = [d for d in vk["devices"] if d["kind"] in ("gpu", "igpu")]
        discrete = [d for d in gpus if d["kind"] == "gpu"]
        igpu = [d for d in gpus if d["kind"] == "igpu"]

        if discrete and ram >= MIN_RAM_GB:
            out.append(("local-gpu", f"独显 {discrete[0]['name']}", GPU_SEC_PER_LINE))
        elif igpu and ram >= MIN_RAM_GB:
            out.append(("local-igpu", f"核显 {igpu[0]['name']}，比 CPU 快 3 倍左右",
                        GPU_SEC_PER_LINE * 3))
    else:
        # 引擎还没下载，但从系统层看看有没有独显
        sysgpu = detect_gpu_system()
        if sysgpu["has_discrete"] and ram >= MIN_RAM_GB:
            name = (sysgpu["discrete"][0] if sysgpu["discrete"]
                    else (sysgpu["names"][0] if sysgpu["names"] else "独显"))
            out.append(("local-gpu",
                        f"检测到独显 {name}（需先下载引擎，setup.py 会引导）",
                        GPU_SEC_PER_LINE))
        elif sysgpu["has_igpu"] and ram >= MIN_RAM_GB:
            name = (sysgpu["igpu"][0] if sysgpu["igpu"]
                    else (sysgpu["names"][0] if sysgpu["names"] else "核显"))
            out.append(("local-igpu", f"检测到核显 {name}（需先下载引擎）",
                        GPU_SEC_PER_LINE * 3))

    # ② 在线 API
    if api_keys:
        out.append(("cloud-api", f"已有 API Key：{', '.join(api_keys)}", 3))

    # ③ 本地 CPU
    if cpu["cores"] >= MIN_CPU_CORES and ram >= MIN_RAM_GB:
        out.append(("local-cpu",
                    f"CPU {cpu['cores']} 核 {ram}GB（可跑但慢，建议挂机过夜）",
                    CPU_SEC_PER_LINE))

    # ④ edge-tts 永远兜底
    out.append(("edge-tts", "免费、无需显卡、1 秒一句（但音色是通用的）",
                EDGE_SEC_PER_LINE))

    return out


def decide(cpu, ram, vk, api_keys, tools):
    """返回首选方案（兼容旧接口）"""
    c = candidates(cpu, ram, vk, api_keys, tools)
    return c[0]


def estimate(plan_sec_per_line, n_lines=39, rounds=4):
    """估算总耗时"""
    total = plan_sec_per_line * n_lines * rounds
    if total < 120:
        return f"{total:.0f} 秒"
    if total < 3600:
        return f"{total/60:.0f} 分钟"
    return f"{total/3600:.1f} 小时"


# ══════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════

PLAN_INFO = {
    "local-gpu": {
        "name": "A. 本地 GPU",
        "clone": True,
        "download": "2.2 GB（引擎 84MB + q8 模型 2.1GB）",
        "quality": "★★★★★ 自己的音色",
    },
    "local-igpu": {
        "name": "A-. 本地核显",
        "clone": True,
        "download": "2.2 GB",
        "quality": "★★★★☆ 自己的音色（慢）",
    },
    "cloud-api": {
        "name": "C. 在线 API",
        "clone": "部分",
        "download": "~50 MB（只要 Python 包）",
        "quality": "★★★★ 服务商预置音色",
    },
    "local-cpu": {
        "name": "B. 本地 CPU",
        "clone": True,
        "download": "2.2 GB",
        "quality": "★★★★★ 自己的音色（很慢）",
    },
    "edge-tts": {
        "name": "D. edge-tts",
        "clone": False,
        "download": "~5 MB（只要 Python 包）",
        "quality": "★★★ 微软通用音色",
    },
}


def main():
    ap = argparse.ArgumentParser(description="环境检测")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--audiocpp", default="", help="audiocpp_cli 路径")
    ap.add_argument("--lines", type=int, default=39, help="预计句数")
    ap.add_argument("--rounds", type=int, default=4, help="每句几轮")
    ap.add_argument("--force", default="", help="强制指定方案（覆盖自动检测）")
    a = ap.parse_args()

    # 探测
    cpu = detect_cpu()
    ram = detect_ram_gb()
    py = detect_python()
    tools = detect_tools()
    api_keys = detect_api_keys()

    # audiocpp 路径：参数 > 常见位置
    cpp = a.audiocpp
    if not cpp:
        for c in ["./vendor/audiocpp/audiocpp_cli.exe",
                  "./audiocpp/audiocpp_cli.exe",
                  "../audiocpp/audiocpp_cli.exe"]:
            if Path(c).exists():
                cpp = str(Path(c).resolve())
                break
    vk = detect_vulkan_devices(cpp) if cpp else {"available": False, "devices": [], "reason": "未找到引擎"}
    gpu_wmi = detect_gpu_wmi()

    cands = candidates(cpu, ram, vk, api_keys, tools)
    if a.force and a.force in PLAN_INFO:
        cands = [(a.force, "用户强制指定", 
                  {"local-gpu":GPU_SEC_PER_LINE,"local-igpu":GPU_SEC_PER_LINE*3,
                   "cloud-api":3,"local-cpu":CPU_SEC_PER_LINE,
                   "edge-tts":EDGE_SEC_PER_LINE}[a.force])]
    plan, reason, spd = cands[0]
    info = PLAN_INFO[plan]

    result = {
        "platform": f"{platform.system()} {platform.release()}",
        "python": py,
        "cpu": cpu,
        "ram_gb": ram,
        "gpu_wmi": gpu_wmi,
        "vulkan": vk,
        "tools": tools,
        "api_keys": api_keys,
        "recommended": plan,
        "candidates": [{"plan": p, "reason": r, "sec_per_line": s,
                        "estimate": estimate(s, a.lines, a.rounds)}
                       for p, r, s in cands],
        "reason": reason,
        "sec_per_line": spd,
        "estimate": estimate(spd, a.lines, a.rounds),
        "plan_info": info,
    }

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    # 人读输出
    print("=" * 68)
    print("环境检测")
    print("=" * 68)

    print(f"\n【系统】{result['platform']}")
    ok = "✓" if py["ok"] else "✗"
    print(f"【Python】{py['version']} {ok}  ({py['exe']})")

    print(f"\n【CPU】{cpu['name'] or '未知'}")
    c_ok = "✓" if cpu["cores"] >= MIN_CPU_CORES else "⚠"
    print(f"        {cpu['cores']} 核 {cpu['threads']} 线程 {c_ok}")

    r_ok = "✓" if ram >= MIN_RAM_GB else "⚠"
    print(f"【内存】{ram} GB {r_ok}")

    print(f"\n【显卡】")
    if gpu_wmi:
        for g in gpu_wmi:
            print(f"        {g['name']}  {g['vram_gb']} GB")
    else:
        print("        未检测到")

    print(f"\n【Vulkan/CUDA 设备】{vk['reason']}")
    if vk["devices"]:
        for d in vk["devices"]:
            mark = "★" if d["kind"] == "gpu" else " "
            print(f"        {mark} {d['backend']}:{d['index']}  {d['name']}  [{d['kind']}]")
    else:
        print(f"        ✗ 没有可用设备（引擎可能还没下载）")
        sg = detect_gpu_system()
        if sg["names"]:
            print(f"        但从系统看，你有：")
            for n in sg["names"][:3]:
                print(f"          · {n}")
            if sg["has_discrete"]:
                print(f"        → 下载引擎后应该能用 GPU 加速")

    print(f"\n【工具】")
    for k, v in tools.items():
        print(f"        {'✓' if v else '✗'} {k:<10} {v or '未找到'}")

    print(f"\n【在线 API Key】{', '.join(api_keys) if api_keys else '未检测到'}")

    # 推荐
    print("\n" + "=" * 68)
    print("可选方案（按推荐排序）")
    print("=" * 68)

    for i, (pid, why, spd_) in enumerate(cands, 1):
        pi = PLAN_INFO[pid]
        mark = "★ 推荐" if i == 1 else f"  [{i}]"
        est = estimate(spd_, a.lines, a.rounds)
        clone = "可克隆音色" if pi["clone"] is True else \
                ("部分可克隆" if pi["clone"] == "部分" else "⚠️ 不能克隆")
        print(f"\n{mark}  {pi['name']}")
        print(f"      理由      {why}")
        print(f"      音色      {clone}")
        print(f"      音质      {pi['quality']}")
        print(f"      要下载    {pi['download']}")
        print(f"      预计      {est}（{a.lines} 句 × {a.rounds} 轮）")

    if plan == "edge-tts":
        print(f"\n  ⚠️ 这个方案不能克隆你的声音，用微软的通用中文音色。")
        print(f"     但卡字率、画面、节奏这些完全不受影响。")

    print("\n" + "-" * 68)
    print("⚠️ 提醒：卡字率、画面、节奏、字幕这些核心技术指标")
    print("   跟用哪个 TTS 完全无关。换方案只影响「声音是不是你自己的」。")
    print()
    print("想换方案？")
    print("  有显卡但没识别  → 检查驱动，或用 --audiocpp 指定引擎路径")
    print("  想用在线 API    → 设置 DASHSCOPE_API_KEY 后重跑")
    print("  想强制用 edge   → python tools/detect_env.py --force edge-tts")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
