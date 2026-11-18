---
name: TTS / voice problem
about: Setup cannot detect hardware, voice is wrong, or generation is too slow
title: "[tts] "
labels: tts
assignees: ''
---

## Which tier are you on

- [ ] Local GPU
- [ ] Local CPU
- [ ] Cloud API
- [ ] edge-tts
- [ ] I don't know — `python setup.py --check-only` did not tell me clearly

## Detection output

```bash
python tools/detect_env.py --json
```

<details>
<summary>Click to expand</summary>

```json
paste here
```

</details>

## The problem

- [ ] GPU exists but was not detected
- [ ] Voice does not sound like my reference sample
- [ ] Words are mispronounced
- [ ] Too slow (how long per line? ____ s)
- [ ] Loudness / volume inconsistent between sentences
- [ ] edge-tts fails with `NoAudioReceived`
- [ ] other: 

## If GPU exists but was not detected

Run these two and paste both:

```bash
# what the engine sees
path\to\audiocpp_cli.exe --list-devices

# what the OS sees
# Windows:
powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object Name"
# Linux:
lspci | grep -i -E 'vga|3d|display'
# macOS:
system_profiler SPDisplaysDataType | grep -i chipset
```

If the OS lists a GPU but `--list-devices` does not, it is a driver issue —
install or update Vulkan/CUDA runtime.

Virtual display adapters (Parsec, Sunshine, DisplayLink, RDP mirrors) are
filtered out on purpose and cannot be used.

## If the voice does not match

Reference sample requirements:

| Item | Requirement |
|---|---|
| Duration | 15-30 s (6-15 s recommended) |
| Format | WAV, 16 kHz+, mono |
| Environment | quiet, no music, no echo |
| Content | anything, **but write it down verbatim in `ref.txt`** |
| Delivery | one breath, no pauses |

**`ref.txt` must match the audio word for word.** One character off and cloning degrades noticeably.

Also check: more than 28 s of *concatenated* audio makes similarity drop.

## If sentences vary in loudness

That is a known issue — TTS output varies 10-12 dB between lines.
`gen_voice.py` normalizes per line (`normalize_rms`). If you wrote your own
generator, do the same:

```python
def normalize_rms(x, target_db=-23.0):
    rms = float(np.sqrt(np.mean(x ** 2)))
    gain = 10 ** ((target_db - 20 * np.log10(rms)) / 20)
    y = x * gain
    LIMIT = 10 ** (-3.0 / 20)      # ⚠️ -3 dBFS, NOT -1.5
    pk = float(np.abs(y).max())
    if pk > LIMIT:
        y = y * (LIMIT / pk)
    return y
```

**The peak cap must be -3 dBFS.** At -1.5 the cap engages and RMS normalization silently fails.

## What I already tried

<!-- Optional -->
