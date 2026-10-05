# game-asset-extractor

An Agent Skill for extracting game assets from APK/Unity packages and for reversing
legacy DOS/PC-98 archive formats. It ships a working CLI plus the field notes that
only come from repeatedly breaking things on real packages.

> **Legal note.** Extracted assets stay the property of their original rightsholders.
> This skill exists for study, interoperability and preservation work. Do not
> redistribute extracted assets or use them commercially without authorisation.

## Why this exists

Most "how to extract Unity assets" guides stop at `AssetStudio`. In practice the hard
part is not decoding a PNG - it is knowing which file holds the pixels, why
`resources.resource` is not a bundle, why 3,000 same-named sprites silently vanish, and
why `TextAsset` bytes rot when you read them through the documented API. All of that
is recorded here, with the measurements that produced each rule.

## What you get

| Component | Purpose |
|-----------|---------|
| `SKILL.md` | routing table: pick a track by container type, intent and toolchain |
| `scripts/ga.py` | one CLI for the whole pipeline (11 subcommands) |
| `scripts/gacommon.py` | shared library: container sniffing, TextAsset header stripping, FSB5 slicing, idempotent naming |
| `scripts/garecon.py` | `doctor`, `inventory`, `unpack`, `scan`, `probe` |
| `scripts/gaexport.py` | `images`, `audio`, `texts`, `fixups`, `report` |
| `references/` | eight focused notes (see below) |
| `scripts/requirements.txt` | Python dependencies |

## Install

    # clone into your skills directory
    git clone https://github.com/StevenLOL/game-asset-extractor \
                ~/.codebuddy/skills/game-asset-extractor

Or grab the release archive and unpack it into `~/.codebuddy/skills/`.

Python dependencies:

    pip install -r scripts/requirements.txt

One external tool is needed for Unity audio: `vgmstream-cli` (see
`references/tooling_and_env.md` for the exact download command).

## Quick start

    # 0. what do I have?
    python scripts/ga.py doctor

    # 1. zero-extraction recon
    python scripts/ga.py inventory --apk game.apk --report logs/01_inventory.txt

    # 2. extract the asset layer (skip lib/)
    python scripts/ga.py unpack --apk game.apk --out work/game/raw

    # 3. what object types live where?
    python scripts/ga.py scan --raw work/game/raw --all

    # 4. prove the toolchain on a few objects
    python scripts/ga.py probe --raw work/game/raw

    # 5. export
    python scripts/ga.py images --raw work/game/raw --out work/game/out
    python scripts/ga.py audio  --raw work/game/raw --out work/game/out ^
               --vgmstream tools/vgmstream/vgmstream-cli.exe
    python scripts/ga.py texts  --raw work/game/raw --out work/game/out

    # 6. gap analysis, cleanup, report + contact sheets
    python scripts/ga.py fixups --raw work/game/raw --out work/game/out --big --dedup --apply
    python scripts/ga.py report --out work/game/out --sheets

Or run the whole chain with `all`:

    python scripts/ga.py all --apk game.apk --out work/game --vgmstream <cli>

## The eight notes

| Note | Read it when |
|------|--------------|
| `references/unity_apk_pipeline.md` | working on an APK: where assets hide, container identification, extraction order, measured timings |
| `references/fsb5_audio.md` | audio: why clips live outside the bundle, the FSB5 field table, why vgmstream is the working path |
| `references/texture_pitfalls.md` | images: compression formats, empty names, the `PermissionError` that is not a permission problem, size thresholds |
| `references/spine_and_textassets.md` | text: byte-exact TextAsset extraction, Spine triples, extension sniffing |
| `references/dos_format_reversing.md` | legacy formats: the five-stage method, four pixel morphologies, three compression families, Kaitai/QuickBMS/GARbro trade-offs |
| `references/competitor_matrix.md` | choosing a tool: AssetStudio / AssetRipper / UABE / UnityPy / FModel / CUE4Parse / QuickBMS / GARbro / UnPKD, plus agent-skill shaped competitors |
| `references/tooling_and_env.md` | environment: interpreter, packages, vgmstream, Windows encoding traps, UnityPy API generations, exit codes |
| `references/workflow_records.md` | case index: which case study documents exist and what each one proves |

## Rules that exist because something broke

- **One FSB5 container per AudioClip.** Count the `FSB5` magic, then slice by the
  clip's offset/size. Never assume the first header describes the file.
- **Read TextAssets from `obj.get_raw_data()`.** The string field is decoded and lossy;
  it silently truncated a 43,554-byte skeleton to 43,082 bytes.
- **Idempotence must be object-level.** Deciding "already exported" from "file exists"
  dropped thousands of same-named sprites. Key on (container, type, path_id) and read
  the status column of the CSV index.
- **Fallback file names to `path_id`.** Unnamed textures otherwise overwrite each other.
- **A Sprite's size lives in `m_Rect`, not `m_Width/m_Height`.** Reading the wrong
  fields reported 15,783 phantom "0x0 placeholders".
- **Duplicates get quarantined, never deleted.** Bulk deletes are unreviewable and often
  blocked outright; a move keeps the data auditable.
- **Force UTF-8 mode for tooling scripts** (`PYTHONUTF8=1` on Chinese Windows) or the
  validator crashes on non-ASCII content.

## Verified

Full-pipeline regression against a commercial Unity 2021.3 title produced
tens of thousands of images, every audio clip converted, thousands of text assets and
13 fonts - matching the numbers the original ad-hoc scripts produced, plus recovered
assets that the ad-hoc scripts had silently dropped. Numbers are kept qualitative in
this published copy; see `SANITIZATION.md`.

## License

MIT for the tooling and documentation. Extracted game assets are **not** covered by this
license and remain the property of their respective rightsholders.
