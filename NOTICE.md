# 第三方组件声明

本项目包含或依赖以下第三方组件。各自遵循其原始授权。

---

## 1. audiocpp（TTS 推理引擎）

- **来源**：https://github.com/ShugoAI/audiocpp
- **授权**：**Apache License 2.0**
- **版权**：Copyright 2026 ShugoAI LLC
- **使用方式**：本项目通过命令行调用其可执行文件，不修改源码
- **原文**：

```
Copyright 2026 ShugoAI LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

**注意**：本项目不重新分发 audiocpp 的可执行文件。用户需自行从官方
Releases 下载。`setup.py` 会提示下载地址。

---

## 2. CosyVoice3（语音合成模型）

- **来源**：https://github.com/QwenAudio/CosyVoice
- **授权**：**Apache License 2.0**
- **使用方式**：通过 audiocpp 加载 GGUF 量化版本
- **GGUF 转换**：https://huggingface.co/cstr/cosyvoice3-0.5b-2512-GGUF

**本项目不分发模型权重。** 用户需自行下载（约 2.1 GB）。

---

## 3. faster-whisper（语音识别）

- **来源**：https://github.com/SYSTRAN/faster-whisper
- **授权**：**MIT License**
- **用途**：逐字对齐、配音质量筛选

---

## 4. Whisper 模型（Systran/faster-whisper-medium）

- **来源**：https://huggingface.co/Systran/faster-whisper-medium
- **授权**：**MIT License**（OpenAI Whisper 权重为 MIT）
- **本项目不分发**，`faster-whisper` 会自动下载或用本地缓存

---

## 5. edge-tts

- **来源**：https://github.com/rany2/edge-tts
- **授权**：**GPL-3.0**（本项目仅作为可选依赖调用，不修改、不内嵌）

**⚠️ 重要说明**：

`edge-tts` 是**非官方接口**，通过逆向 Microsoft Edge 浏览器的
「大声朗读」功能实现。它：

- 不是微软官方支持的 API
- 可能随时失效或被限流
- 生成的音频使用条款见微软服务协议
- **仅建议用于学习和个人项目**

如果你需要商用，请使用官方服务（Azure 语音、阿里云 DashScope 等）。

本项目把 edge-tts 作为「没显卡用户的兜底方案」，并在代码和文档中
明确标注其局限（不能克隆音色）。

---

## 6. Kenney Interface Sounds（音效）

- **来源**：https://kenney.nl/assets/interface-sounds
- **授权**：**CC0 1.0 Universal（公共领域）**
- **版权**：Created/distributed by Kenney (www.kenney.nl)
- **原文**：

```
Interface Sounds (1.0)

Created/distributed by Kenney (www.kenney.nl)
Creation date: 11-02-2020

License: (Creative Commons Zero, CC0)
http://creativecommons.org/publicdomain/zero/1.0/

This content is free to use in personal, educational and commercial projects.
```

**CC0 允许无条件使用、修改、分发，包括商用，无需署名。**
本项目仍在此处署名，以示尊重。

---

## 7. puppeteer-core（浏览器自动化）

- **来源**：https://github.com/puppeteer/puppeteer
- **授权**：**Apache License 2.0**
- **用途**：驱动 Chrome 逐帧截图，生成视频帧序列
- **本项目不分发**，通过 `npm install` 安装

---

## 8. FFmpeg

- **来源**：https://ffmpeg.org/
- **授权**：**LGPL 2.1+** 或 **GPL 2+**（取决于编译选项）
- **使用方式**：命令行调用，不链接库
- **本项目不分发**，用户自行安装

---

## 9. Google Chrome / Microsoft Edge

- **用途**：puppeteer 的渲染内核
- **授权**：各自专有软件许可
- **本项目不分发**，使用用户已安装的浏览器

---

## 10. 字体

本项目 CSS 里引用的字体：

| 字体 | 说明 |
|---|---|
| PingFang SC | macOS 系统字体，不随项目分发 |
| Microsoft YaHei（微软雅黑） | Windows 系统字体，不随项目分发 |
| Noto Sans CJK SC | Linux 常见开源字体（SIL OFL 1.1） |
| sans-serif | 浏览器兜底 |

**字体不随本项目分发**，使用用户系统已安装的字体。如果系统没有
PingFang / 雅黑，会自动回退到 Noto 或 sans-serif，视觉效果会有差异。

---

## 汇总表

| 组件 | 授权 | 是否分发 | 商用 |
|---|---|---|---|
| 本项目代码 | MIT | ✓ | ✓ |
| audiocpp | Apache-2.0 | ✗ 用户下载 | ✓ |
| CosyVoice3 | Apache-2.0 | ✗ 用户下载 | ✓ |
| faster-whisper | MIT | 依赖安装 | ✓ |
| Whisper 模型 | MIT | ✗ 自动下载 | ✓ |
| **edge-tts** | **GPL-3.0** | 依赖安装 | **⚠️ 见上** |
| **Kenney 音效** | **CC0** | ✓ | ✓ |
| puppeteer-core | Apache-2.0 | 依赖安装 | ✓ |
| FFmpeg | LGPL/GPL | ✗ 用户安装 | ✓ |
| 系统字体 | 专有 | ✗ | ✓（本机使用）|

---

## 如果你要二次分发

**必须保留**：
- `LICENSE`（MIT）
- `NOTICE`（本文件）

**不能分发**（需用户自己获取）：
- audiocpp 可执行文件
- CosyVoice3 模型权重
- Whisper 模型
- 任何你克隆的**他人声音**的参考音频

**可以分发**：
- 本项目代码
- Kenney 音效（CC0）
- 你自己录的参考音（你得同意）
