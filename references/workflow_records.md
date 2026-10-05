# Workflow records (case index)

Where the full case studies live: the `a local asset-extraction workspace` workspace
(`the local workspace`), documents in `docs/`, per-case scripts in
`scripts/`, extraction output under `work/<game>/out/`, reports in `logs/`.
Each record follows the same shape: inventory -> format hypothesis -> decoder ->
contact sheet -> numbers.

## Modern engines

| Case | Engine | What it proves |
|------|--------|----------------|
| `docs/027_*` (a commercial wuxia RPG, 1.0.7) | Unity 2021.3 LTS + Addressables | the full reference run: tens of thousands of PNG files / ~1 GB, 339 WAV / 455 MB from one FSB5 container per clip banks, thousands Spine/data files, 13 fonts, 9 oversized strips; 7 documented pitfalls (see `texture_pitfalls.md`, `fsb5_audio.md`, `spine_and_textassets.md`) |
| `docs/014_an indie Unity title*` | Unity | desktop title, same pipeline, smaller scale |
| `docs/015`, `docs/016` (Haojie Chengzhang Jihua) | Egret | no container format at all: a `res.json` manifest plus TexturePacker atlases; 6,659 files / 393 MB, including 38 scene folders and a 1,014-file audio set |
| `docs/009_WDXK*` | Unity (APK) | handover-style record of a large Chinese MMO APK |

## Legacy formats

| Case | Format family | What it proves |
|------|---------------|----------------|
| `docs/003`, `docs/004` (Lieyan Ganglangzhuan) | DDT + CMP | palette-indexed bitmaps plus an RLE-ish CMP container |
| `docs/005` (Shendiaoxialv) | mixed | sprites, atlases, palettes and audio in one title |
| `docs/011` (Fengzhi Wu RSK) | RSK archive | full archive layout, 29 KB spec |
| `docs/013`, `docs/014` (a DOS strategy series Xiongba Tianxia) | a DOS strategy series | battlefield unit sprites in a custom RLE; `docs/014` distils it into a reusable RLE specification |
| `docs/012`, `docs/024` (Gaobaochou Xizhan) | HR | resource container plus decoding parameters |
| `docs/017` (ETIN) | ETIN | standalone format crack |
| `docs/018`/`019` (a DOS fighter, SUPER) | GPC, CEL | sprite/atlas/audio full runs |
| `docs/020` (Yunbiao Tianxia) | DART | format probing plus loader disassembly |
| `docs/021` (Daso Yinghao Yuefeizhuan) | DOS | full extraction record |
| `docs/022*` (a DOS strategy series Yingxiong, sanguo_11..14) | custom | four-stage escalation: asset report -> proprietary format -> deep reverse -> graphics format engineering (the Chinese-language tutorial in `docs/022_sanguo_14`) |
| `docs/025` (Jin Ping Mei) | an adult-themed DOS title | container plus codec |

## Method references

| Document | Use it for |
|----------|------------|
| `docs/000` / `docs/026` | the general method: four pixel morphologies, three compression families, five-stage extraction, toolchain overview, troubleshooting table, legal boundaries |
| `docs/023` | tool ecosystem: what is installed, what to download, selection advice, and the format-spec databases (XentaxWiki, ZenHAX, GameFAQs, ArchiveTeam "Just Solve the File Format Problem") |
| `docs/010` | how to research competitors and open-source alternatives properly |
| `docs/001` | the workspace's working rules (numbering, evidence, git, no redundant downloads) |

## Reusable scripts in that workspace

`scripts/1703`-`1717` are the ad-hoc ancestors of this skill's `ga.py`
(APK census, unpack, bundle scan, probe, image/audio/text export, Addressables
catalog, contact sheets, app info, texture diagnostics, gap fixes, dedup, summary,
extension sniffing). They are kept as a regression baseline: run `ga.py` against the
same input and compare the counts, as done in `docs/028` section 8.

The competitor deep-dive notes are in `others/competitors/ANALYSIS.md`, including the
GARbro / Kaitai / sdlpal / gamegraphicsjs findings that shaped the legacy-format
recommendations here.
