# Competitor matrix

Verified 2026-10. Sources are listed so claims stay checkable. Local clones live in
`others/competitors/` (shallow, `--depth 1`); deep analysis notes in
`others/competitors/ANALYSIS.md` of the originating workspace.

## Unity

| Tool | Language | Input -> Output | Choose it when | Source |
|------|----------|-----------------|----------------|--------|
| AssetStudio | C#/Windows | bundles -> tree browser + PNG/WAV/JSON | interactive inspection, quick eyeballing | https://github.com/Perfare/AssetStudio |
| AssetRipper | C#/Windows | bundles -> assets + compilable project | you need the project structure back | https://github.com/AssetRipper/AssetRipper , comparison https://assetripper.org/assetstudio-vs-assetripper-unity-asset-extraction-and-analysis-compared/ |
| UABE | C#/Windows | bundle split / edit | editing asset fields | https://github.com/emtee40/UABE |
| UABEA | C#/Avalonia | modern Unity bundle read/write | newer Unity versions; author states it targets modding/research, and recommends AssetRipper/AssetStudio for pure extraction | https://github.com/nesrak1/UABEA |
| **UnityPy** | Python | bundles -> object tree -> anything | **automation, batch work, CI** (this skill's choice) | https://github.com/K0lb3/UnityPy |

Trade-off summary (from the 2026-09 comparison articles by assetstudio.org,
assetripper.org, uabea.com): AssetRipper optimises for bulk extraction and project
reconstruction, UABE/UABEA for bundle editing, AssetStudio for browsing, UnityPy for
scripted headless work. UnityPy has **no batch-export CLI** (its only subcommand is
`update_tpk`), which is exactly why this skill ships its own `ga.py`.

## Unreal

| Tool | Notes | Source |
|------|-------|--------|
| CUE4Parse | parser library behind FModel; pak/ucas/utoc + IoStore + usmap; **needs the AES key** for encrypted pak | https://github.com/FabianFG/CUE4Parse |
| FModel | GUI on top of CUE4Parse, the usual entry point | https://github.com/ForgottenDreams/FModel |
| UAssetGUI | lightweight single-asset viewer/editor | https://github.com/atenfyr/UAssetGUI |

No scripting support exists in this skill yet; the practical route is FModel for
inspection plus CUE4Parse in your own script.

## Engines with a plain-file layout

| Engine | What to read | Notes |
|--------|--------------|-------|
| Egret | `res.json` / `default.res.json` manifest + TexturePacker atlases | a shipped example contained 38 scene folders, 168 atlases, an audio set files, 190 JSON configs |
| Cocos Creator | `res/import/`, `*.plist` + page PNG, `ccbi`/`csb` | plist gives per-sprite rects |
| Laya / mini-game | `atlas/*.atlas` + page images | - |

## Legacy formats

| Tool | Language | Notes | Source |
|------|----------|-------|--------|
| QuickBMS | C/C++ | script DSL + hundreds of built-in codecs; `-l` list, `-f` filter, `-r` reimport. **The repo ships zero `.bms` scripts** - the extensions library is a separate download | https://github.com/LittleBigBigBoy/QuickBMS |
| GARbro | C#/.NET | the breadth reference: 417 `Arc*.cs` classes, one per format, grouped by vendor, MEF auto-discovery, signature/extension/parameter metadata per format | https://github.com/morkt/GARbro , format list https://morkt.github.io/GARbro/supported.html |
| Dragon UnPACKer | Object Pascal | "sniff -> driver -> mount recursively" skeleton; 469 KB driver package; Windows only, not scriptable - design reference only | https://github.com/elbereth/DragonUnPACKer |
| UnPKD | Rust + wxDragon | PKLite only (EXE 1.00-2.01, COM 1.00-1.15); **GUI only**; its detection heuristics and version matrix are a good template | https://github.com/GameExtraction/unpkd |
| depklite | C99 | smallest readable PKLite reference; no auto offset probing, fixed 4 MiB output buffer | https://github.com/openTESArena/depklite |
| Kaitai Struct | Scala/JVM | YAML schema -> generated decoder; ~180 bundled schemas incl. `formats/game/*`; **decode only**, needs a JDK | https://kaitai.io |
| gamegraphicsjs | JavaScript | 20 handlers with a clean `identify/read/write + options + supps` contract and a documented 5-step "add a format" procedure | https://github.com/lifthrasiir/gamegraphicsjs |
| Naeferith RPGViewer | C#/WPF | despite the name it is a tabletop RPG engine, **not** an asset viewer - do not count on it | https://github.com/Naeferith/RPGViewer |

## Agent-skill shaped competitors

| Project | Design | What to borrow |
|---------|--------|----------------|
| `tbckdev/reverse-skill` (~460 files) | RULES.md global router + `skills/SKILL.md` + `skills/routing.md` (three-axis matrix: target type x user phrasing x toolchain, all three must match) + tool bootstrap (`ToolDiscovery.ps1`, `bootstrap-manifest.json`, three-level degradation to `manual-required`) + runtime-generated `tool-index` (template in repo, results gitignored) | 1) three-axis routing tables as plain Markdown; 2) writing "when NOT to use this" into `description`; 3) explicit trigger keywords in frontmatter; 4) tool self-bootstrap with graceful degradation; 5) fixed `ACTION REQUIRED` + completion checklist tail; 6) "route not matched" as a signal to add a skill |
| Anthropic `anthropics/skills` | official marketplace, same SKILL.md + progressive disclosure + packaging conventions | packaging and validation flow (`init_skill.py` / `quick_validate.py` / `package_skill.py`) |

Deliberately **not** copied from `reverse-skill`: its 41 CTF sub-skills plus 20+
penetration-testing skills (noise for asset extraction), its "precedent-auth" pattern
that instructs the agent to suppress authorisation/legal warnings (wrong for asset
extraction, where copyright notices must stay), and its PowerShell-deep bootstrap
(35 KB + 32 KB scripts, winget-centric). Its routing already showed rot - it routes to
a `game-security/` directory that does not exist - so any multi-file routing scheme we
adopt needs an automated consistency check.
