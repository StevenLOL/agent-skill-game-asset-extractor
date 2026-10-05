# Spine and TextAssets

## 1. Why TextAsset needs special care

`TextAsset` exposes only `m_Name` and `m_Script` (a **string**). UnityPy decodes
that string with a lossy codec, so binary payloads come out truncated:

| Asset | Real bytes (`get_raw_data` header stripped) | `len(m_Script)` |
|-------|--------------------------------------------|-----------------|
| `login.skel` | 43,554 | 43,082 (472 bytes lost) |

The official README suggests `m_Script.encode("utf-8", "surrogateescape")`, but on
1.25.3 that reproduces the lossy decode - the character count is already smaller than
the byte count, which is the tell. **Measure, do not trust the docs.**

Correct route - strip the serialized header off the object's own block:

    [u32 name length][name bytes][pad to 4 bytes][u32 payload length][payload]

`gacommon.textasset_bytes()` implements this and falls back to the string field only
when the header is implausible, recording which path was used (`raw` vs
`decode_fallback`) in the CSV index so a reviewer can audit it.

## 2. Extension names are not evidence

In a reference package 114 files carried `.bin`, and **37 of them were actually
Spine JSON** (they start with `{"skeleton": {"hash": ...`). The remaining 77 were
genuine binary data (story/dialogue tables, e.g. `gang_e02.bin` 11.4 MB,
`对话表翻译数据.bin` 2.5 MB, `*_TransDict.bin` translation dictionaries).

Sniff by content instead:

| Sniff | Meaning |
|-------|---------|
| first byte 0x1C, "spine" nearby | Spine binary skeleton -> `.skel` |
| first non-space char `{` or `[` | JSON -> `.json` |
| contains `format:` and `size:`/`repeat:` | Spine atlas -> `.atlas` |

`ga.py fixups` lists the planned renames and only applies them with `--apply`, so
the decision stays reviewable.

## 3. Spine asset triples

A usable Spine animation needs three parts, usually shipped together:

- `<name>.skel` - binary skeleton (or `.json` for the JSON variant)
- `<name>.atlas` - texture atlas description: page image name, size, format, and the
  region rectangles
- page image(s) - exported by the `images` stage, matched by the atlas' page name

Examples from a reference package: `login.skel` + `login.atlas` (loading screen),
`01-UI-text-01.json` (UI text pop-in), and per-character sets named
`<id>-<gender>-<archetype>-<TOP|LEFT|RIGHT|BACK>.json` (Spine skeletons exported as
JSON because the game shipped the JSON variant).

Skeleton version strings are visible in the first bytes (`3.8.99` in this game),
which tells you which Spine editor/runtime to use.

## 4. Fonts

`Font.m_FontData` is the complete TTF/OTF byte stream - just write it out. Detect the
format by magic: `OTTO` -> `.otf`, otherwise `.ttf`. The reference package contained
13 fonts (40.78 MB) including a bespoke calligraphy face
(`a bespoke calligraphy font.ttf`), a pixel CJK font, Alibaba PuHuiTi and several Noto
families. Third-party licences apply per font - record them, do not redistribute.

## 5. Practical checklist for text assets

1. Export with the raw-byte path; count how many used `raw` vs `decode_fallback`.
2. Cross-check a sample: `get_raw_data()` length minus header must equal the written
   file size. A mismatch means the lossy path was used.
3. Run `fixups` to correct extensions, then group by extension to see what the game
   actually shipped (skel/atlas = animation, json = data or JSON skeletons,
   bin = opaque tables).
4. Keep the container-relative path in the index; asset names repeat across bundles.
