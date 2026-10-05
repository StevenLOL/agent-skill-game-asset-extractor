---
name: game-asset-extractor
description: Extract game assets from APK/archives and reverse-engineer custom binary resource formats. Use when the task involves analyzing a game package (APK/zip/ISO/EXE), unpacking Unity AssetBundles or Addressables, exporting textures, sprites, audio, Spine animations, fonts, config tables, or when reverse-engineering legacy DOS/PC-98 archive and bitmap formats (palette, RLE, tileset, LZSS, custom packers). Trigger keywords - 游戏素材提取, 素材逆向, 提取图片, 提取音频, 骨骼动画, AssetBundle, UnityFS, Addressables, FSB5, Spine, APK 逆向, DOS 格式, 图集, 调色板, RLE, extract assets, asset extraction, game archive, texture atlas, palette. Do not use for APK malware analysis, dynamic instrumentation, hooking, network protocol reversal, or penetration testing - use a security reverse-engineering skill for those.
---

# Game Asset Extractor

## Overview

Turn a game package or a pile of unknown binary files into **usable, indexed, visually verifiable assets**: PNG/WAV/Spine/JSON/TTF plus a machine-readable index and a contact sheet. Covers two worlds that share one workflow:

- **Modern engines** (Unity AssetBundle / Addressables / FSB5 audio / Spine) — high automation, scriptable.
- **Legacy formats** (DOS/PC-98 custom archives, palette-indexed bitmaps, RLE, tilesets) — unknown-by-design, spec-first.

**Core discipline: never guess, always verify.** Every format claim must be backed by a measured number (offset, length, magic, decoded byte count) written into a report. Extraction without an index and a contact sheet is not finished work.

## Compliance and boundaries

- Extracted assets stay in the copyright of their original rightsholders. Use them for **personal research, study, and interoperability analysis only**; do not redistribute, publish, or use commercially without authorization.
- Third-party fonts/licenses inside a game (e.g. Noto, Alibaba PuHuiTi, Liberation, a pixel CJK font) carry their own terms; check each separately.
- Do not bypass DRM, encryption keys, or license checks. Documented format-level interop (reading asset containers) is in scope; access control circumvention is not.
- Put a one-line compliance note into every generated report.

## Step 0 — Environment self-check (always first, cheap, 20 seconds)

```powershell
python -c "import UnityPy, PIL; print('UnityPy', UnityPy.__version__)"   # 1.25+ required
python scripts/ga.py doctor                                             # full report
```

| Check | Pass | If missing |
|-------|------|------------|
| Python ≥3.8 with `UnityPy`, `Pillow` | prints versions | `pip install "UnityPy>=1.25" Pillow texture2ddecoder astc-encoder-py` |
| vgmstream-cli | `ga.py doctor` prints path | `curl.exe -L --retry 3 --retry-all-errors -o vgmstream-win64.zip https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win64.zip` then pass `--vgmstream <path>` |
| ffmpeg (optional) | `ffmpeg -version` | only needed for a few legacy audio formats |
| Free disk | target needs ≈2x extracted size | keep `raw/` only while extracting; it is rebuildable from the source package |

Notes: the system `python` may lack Pillow — on Windows prefer a conda interpreter. `Invoke-WebRequest` is unreliable for GitHub Release downloads; use `curl.exe -L --retry 3`. `ga.py` degrades gracefully: a missing decoder disables that one step and prints a copy-pasteable install command instead of crashing.

## Routing table (three axes — match all three)

**Axis A — target carrier**

| Carrier | Go to |
|---------|-------|
| Android APK / iOS bundle / generic zip | `inventory` → `unpack` → axis B |
| Unity AssetBundle / `.unity3d` / `resources.resource` / Addressables | axis B + `references/unity_apk_pipeline.md` |
| Unreal `.pak` / `.ucas` / `.utoc` / `.uasset` | `references/competitor_matrix.md` (FModel/CUE4Parse; needs AES key) — no scripting support here yet |
| Egret / Cocos / Laya / mini-game | `references/competitor_matrix.md` (resource manifest + TexturePacker plist) |
| DOS/PC-98 `.GRP`/`.LIB`/`.DAT`/`.DDT`/`.CMP`/`.PAL` or unknown binaries | `references/dos_format_reversing.md` |
| Single unknown file (suspected custom packer) | `ga.py probe --raw <dir>` then Kaitai route in `references/dos_format_reversing.md` |

**Axis B — user intent**

| Intent | Command |
|--------|---------|
| "看看这个包里有什么" | `ga.py inventory` then `ga.py scan` |
| 提取图片/贴图/精灵 | `ga.py images` |
| 提取音频/音乐/音效 | `ga.py audio` |
| 提取骨骼动画/配置/文本 | `ga.py texts` |
| 全都要 / 做一次完整提取 | `ga.py all --apk <apk> --out <dir>` |
| 验证某格式怎么解 | `ga.py probe` + read the matched `references/` page |
| 生成总览图 / 报告 | `ga.py report` |

**Axis C — toolchain available**

| Available | Prefer |
|-----------|--------|
| `UnityPy` | `ga.py scan/images/audio/texts` (headless, scriptable) |
| GUI tools (AssetStudio / AssetRipper / UABEA) | only for **interactive inspection or bundle editing**; batch work stays in `ga.py` |
| `vgmstream-cli` | FSB5 → WAV (the only reliable path; see `references/fsb5_audio.md`) |
| Kaitai Struct compiler (needs JDK) | declare unknown binary formats in `.ksy` → auto-generate a Python decoder |
| QuickBMS | known commercial engines; note the script library is **not** bundled with its repo |
| only a hex editor | stop, gather measurements first (`probe`), then pick or write a parser |

## Standard workflow (Unity/APK, the highest-volume case)

```powershell
$ga = "python ~/.codebuddy\skills\game-asset-extractor\scripts\ga.py"

& python $ga inventory --apk game.apk --report logs/01_inventory.txt   # zero-extraction recon
& python $ga unpack    --apk game.apk --out work/game/raw               # skip lib/, keep assets+res
& python $ga scan      --raw work/game/raw --all                        # UnityFS header + object type census
& python $ga images    --raw work/game/raw --out work/game/out --skip-existing
& python $ga audio     --raw work/game/raw --out work/game/out --vgmstream <path>
& python $ga texts     --raw work/game/raw --out work/game/out
& python $ga fixups    --raw work/game/raw --out work/game/out          # big images + dedup + type sniffing
& python $ga report    --out work/game/out                               # summary.txt + contact sheets
```

`ga.py all` runs exactly this chain. Every step writes an index CSV (`images.csv`, `audio.csv`) plus a UTF-8 report, and is re-runnable (`--skip-existing`).

### Reading the scan report

- `resources.resource` is **not** a Unity bundle: an `FSB5` magic means it is a **concatenation of standalone FSB5 audio containers**. Do not skip it; it holds the audio bytes.
- `map_*.bundle` files with hash names are Addressables bundles; the semantic name lives in `assets/aa/catalog.json`.
- `res/` is almost always Android launcher icons and SDK layouts, not game art. Keep it out of the image deliverable.

## Non-negotiable engineering rules

1. **Idempotence**: every export accepts `--skip-existing`; never let a re-run create `_001` copies. Dedupe by **content hash**, and move duplicates to a quarantine directory instead of deleting (bulk deletes are frequently blocked by workspace safety policies).
2. **Filename fallback**: asset names can be empty. Fall back to `tex_<path_id>`, otherwise silent overwrite loses assets (measured: 8 images of very wide strips collapsed to 1).
3. **Never read binary payloads through a decoded string field** (see `references/spine_and_textassets.md` for the measured proof). Read raw serialized bytes and parse the header yourself.
4. **Single-thread per environment**: UnityPy object readers share a binary cursor per SerializedFile; parallel threads on one loaded env corrupt reads.
5. **Cache `env.objects`**: it is a property that rebuilds the list on every access.
6. **Always pass a file path** to `UnityPy.load` (never bytes) so external `.resource` / `.resS` resolution can find sibling files.
7. **Memory**: a 200 MB+ UnityFS bundle peaks several GB during decode. Export in batches, print progress every N objects, and make interruption safe.
8. **Encoding**: write every report with `encoding="utf-8"`; assume the console mangles non-ASCII output.

## High-frequency recipes

| Ask | Do |
|-----|-----|
| "这个 APK 里有多少图片/音频" | `inventory` → `scan --all` → quote the type census table |
| "把音乐都导出来" | `audio --vgmstream <path>`, then sort by duration from `audio.csv` |
| "角色骨骼动画" | `texts` (`.skel` + `.atlas` + Spine `.json`) paired with same-named PNGs from `images` |
| "这个 .DAT 怎么解" | `probe --raw <dir>` → read magic/size → `references/dos_format_reversing.md` → Kaitai `.ksy` |
| "图集能看个大概吗" | `report --out <dir>` → contact sheet PNGs, then open them |
| "上一轮漏了素材" | `fixups` (large-image threshold, placeholder-texture diagnosis, extension sniffing) |

## Top traps (detail in `references/`)

| Trap | Symptom | Fix |
|------|---------|-----|
| TextAsset read via `m_Script` | binary silently truncated (43,554 B → 43,082 chars measured) | `get_raw_data()` + manual header strip |
| FSB5 decoded by UnityPy | `FmodError: FORMAT` | slice per AudioClip offset, convert with vgmstream-cli |
| Empty asset name | outputs overwrite each other | fallback to `obj.path_id` |
| `PermissionError [Errno 13]` on texture | UnityPy opened a **directory** for a 0x0 placeholder texture with empty `m_StreamData.path` | treat as placeholder, not a missing asset |
| FSB5 assumed to be one bank | garbage sizes | locate every `FSB5` magic, slice by AudioClip `offset`/`size` |
| Extension names trusted | 37 of 114 `.bin` files were actually Spine JSON | sniff file content, rename |
| Bulk delete | operation blocked / half-done | move to quarantine, delete manually if ever needed |

## References

| File | Load when |
|------|-----------|
| `references/unity_apk_pipeline.md` | Unity APK structure, UnityFS header, Addressables catalog, extraction order |
| `references/fsb5_audio.md` | FSB5 v1 field table, container splitting, Vorbis, vgmstream usage |
| `references/texture_pitfalls.md` | compression formats, ASTC, empty names, placeholder textures, size thresholds |
| `references/spine_and_textassets.md` | Spine skel/atlas/json, TextAsset raw-byte parsing, extension sniffing |
| `references/dos_format_reversing.md` | five-stage method, four pixel morphologies, palette/RLE/tileset/LZSS, Kaitai workflow |
| `references/competitor_matrix.md` | which existing tool to reach for, and its limits |
| `references/tooling_and_env.md` | interpreter, packages, download commands, mirrors, shell/encoding pitfalls |
| `references/workflow_records.md` | index of real extraction case records, grouped by engine/format |

## ACTION REQUIRED

1. **NOW** — run `ga.py doctor`; report which toolchain is present before promising any output.
2. **NEXT** — run `inventory`/`scan` before any extraction; never skip recon on a 300 MB+ package.
3. **ACT** — execute the routed command chain, then finish with `report` (contact sheet + index) and a written record.

## Completion checklist

- [ ] Environment self-check recorded (interpreter, UnityPy version, external tools)
- [ ] Recon done before extraction (`inventory` + `scan` with `--all`)
- [ ] Index CSVs exist for images / audio / text
- [ ] Zero unexplained failures (placeholder textures and unsupported formats are **labeled**, not silently skipped)
- [ ] Duplicate handling used quarantine-move, not deletion
- [ ] Contact sheet generated and visually inspected
- [ ] Findings written to a report file with measured numbers and a compliance note
