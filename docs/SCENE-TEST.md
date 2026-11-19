# 10 场景测试项目

用来逐个验证 10 个场景类型。改造某一场景后，跑这个项目确认没坏。

## 建项目

```bash
mkdir _scenetest && cd _scenetest
＃ 把 docs/scene-test/ 里的 script.md 和 scene-def.json 复制进来
cp ../docs/scene-test/* .

＃ 配音
python ../tools/gen_voice.py . --backend edge-tts

＃ 对齐
python ../tools/align.py .

＃ 闸门 1
python ../tools/gate1.py .

＃ 复制画布运行时
cp ../canvas/* .

＃ 渲染（127 秒 = 7622 帧，约 13 分钟）
node render.cjs . 9:16

＃ 合成
ffmpeg -y -framerate 60 -i frames/f%05d.png -i narration.wav \
  -c:v libx264 -preset fast -crf 22 -pix_fmt yuv420p \
  -c:a aac -b:a 160k -shortest FINAL.mp4

＃ 卡字率
python ../tools/kazi_check.py FINAL.mp4 --timeline timeline.json
```

## 基线（2026-11-18，设计改造后）

```
10/10 = 100%，before 全部 0.04-0.10

hero          2.85% / 0.07%   40.7x
points        1.22% / 0.06%   20.3x
steps         0.97% / 0.05%   19.4x
compare       3.86% / 0.04%   96.5x
number        0.72% / 0.05%   14.4x
quote         1.62% / 0.10%   16.2x
before-after  0.60% / 0.06%   10.0x
list          0.44% / 0.05%    8.8x
product       2.32% / 0.07%   33.1x
cta           0.84% / 0.06%   14.0x
```

## 四画幅溢出检查

4 个画幅 × 10 个关键词时刻 = 40 次检查，当前 0 溢出。

改造场景后必须重跑。
