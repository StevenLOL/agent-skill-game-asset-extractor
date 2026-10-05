# Unity APK pipeline

Verified against a commercial wuxia RPG (a recent build,
Unity 2021.3 LTS, IL2CPP, Addressables 1.19.19) and *an indie Unity title*.

## 1. Where things live

    assets/bin/Data/data.unity3d        boot scene, PlayerSettings, a few hundred sprites
    assets/bin/Data/datapack.unity3d    main content pack (can be 200 MB+)
    assets/bin/Data/resources.resource  NOT a bundle: streamed payload, usually FSB5 audio banks
    assets/bin/Data/Managed/Metadata/global-metadata.dat   IL2CPP metadata
    assets/aa/Android/*.bundle          Addressables content, file names carry hashes
    assets/aa/catalog.json              address -> bundle mapping (thousands of addresses / 12 bundles)
    lib/<abi>/libil2cpp.so              game code; libunity.so holds the engine version string
    res/                                Android launcher icons and SDK layouts (usually < 1 MB)

Decision rule: `res/` is NOT game art. In a reference package it held 439 files
(0.51 MB, 282 PNGs) of launcher icons while all real art sat in `assets/`.

## 2. Container identification (before loading anything)

| Header bytes | Container | Handling |
|--------------|-----------|----------|
| `UnityFS\0` + u32 BE format version (8) + version string | AssetBundle | load with UnityPy |
| `FSB5` | FMOD sound bank | slice per AudioClip, convert with vgmstream |
| `OggS` / `RIFF` / `...ftyp` | native audio | copy out as-is |
| `PK` | zip / APK | recurse with `unpack` |
| u32 metadata_size, u32 file_size, u32 version (9..30) | bare SerializedFile | engine defaults, rarely game content |

`ga.py scan` prints this classification for every candidate and refuses to load
containers above `--max-scan-mb` (default 64) unless `--all` is given: classifying a
240 MB bundle takes seconds, parsing it takes minutes and multiple GB.

## 3. Extraction order that works

1. `inventory` - size census from the ZIP central directory (instant, no extraction)
2. `unpack` - extract `assets/` and `res/` only
3. `scan --all` - object type census; you learn there are all AudioClips and
   thousands TextAssets *before* spending time exporting
4. `probe` - decode a handful of objects to prove the toolchain works
5. `images` / `audio` / `texts` - the three export stages
6. `fixups` - oversized art, placeholder diagnosis, extension sniffing, dedup
7. `report --sheets` - summary plus contact sheets

## 4. Addressables

Bundle file names are hashes, so map them back through `assets/aa/catalog.json`:

- `m_InternalIds` lists every internal id; entries ending in `.bundle` are bundles
- the rest are logical addresses (`ArtAsset/Sprite/bg_payway`,
  `AccountSdkPrefabs/ui_loading`, ...) that reveal what a bundle contains
- `m_EntryDataString` is a binary blob needing Addressables' own serialization;
  address-prefix statistics are the practical shortcut

In a reference package the bundle names were already self-describing
(`map_xiaoxiang_*`, `map_jiangdong_*`, `localization-*`), so the catalog was only
needed to confirm the split.

## 5. Performance and memory (measured on a reference package)

| Stage | Input | Time | Notes |
|-------|-------|------|-------|
| inventory | 380 MB APK | < 1 s | central directory only |
| load main pack | 237 MB datapack, tens of thousands of objects | ~3 s | peak RSS ~several GB |
| export images | tens of thousands textures + tens of thousands sprites | ~15 min | ASTC decode dominates |
| export audio | one FSB5 container per clip -> WAV | ~3 min | one external process per clip |

Mitigations: cache `env.objects` (it is a property that rebuilds a list per access),
export in batches, print progress, and never parse one environment from two threads
(all objects of a SerializedFile share one binary cursor).

## 6. Engine and app identification

PlayerSettings yields product name, company, bundle version, screen size.
The Unity version is usually missing there - read it from the engine library:

    python -c "import re,zipfile; b=zipfile.ZipFile(r'game.apk').read('lib/arm64-v8a/libunity.so'); \
      print(sorted({m.group().decode() for m in re.finditer(rb'\d{4}\.\d+\.\d+[fpab]\d+', b)})[:5])"

Other quick tells: `libil2cpp.so` = IL2CPP scripting; `*.resource` next to
`Managed/Metadata` = streamed assets; `assets/protected_by_np/*` = DEX protection
(does not affect asset extraction); `boot.config` `gfx-disable-mt-rendering=1`
means single-threaded GL rendering.
