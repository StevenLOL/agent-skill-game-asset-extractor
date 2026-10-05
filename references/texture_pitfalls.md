# Texture pitfalls

Every item here is a measured failure from real packages, not theory.

## 1. Compression formats

Unity TextureFormat numbers seen in the wild and how UnityPy handles them:

| Format | Decoder used by UnityPy 1.25 |
|--------|-----------------------------|
| uncompressed RGBA/RGB/half/RGB9e5, BC4-BC7, DXT1-5 (incl. Crunched) | Pillow |
| PVRTC, ATC, ETC, ETC2, EAC | `texture2ddecoder` |
| ASTC 4x4 ... 12x12 (48-53), ASTC HDR | `astc-encoder-py` (HDR clamped to 8 bit) |
| YUY2, ETC_RGBA8 (non-3DS) | **not implemented** - expect failure |

Install `texture2ddecoder` and `astc-encoder-py`; without them the reference
package's ASTC 8x8 textures (TextureFormat 51) and 4x4 atlases (48) would fail.
`etcpak` is encode-only and irrelevant for extraction.

## 2. Empty asset names silently destroy data

Textures with no `m_Name` all land on the same filename. In a reference package
8 distinct very wide strips background strips collapsed into a single file because the
fallback name was constant.

Rule: fallback to `<type>_<obj.path_id>`, e.g. `texture2d_1568.png`. `ga.py` does
this in `safe_name(..., fallback=f"{type}_{path_id}")`.

## 3. `PermissionError [Errno 13]` on a texture is NOT a missing asset

    PermissionError: [Errno 13] Permission denied: '.../assets/bin/Data'

The message looks like a file-permission problem. It is not: the texture has
`m_Width = m_Height = 0` and `m_StreamData.path = ""`, so UnityPy resolves the empty
path to the **containing directory** and `open()` on a directory fails on Windows.
14 such objects existed in a reference package. They are runtime/filler textures
with no pixels; count them separately and move on.

A genuinely streamed texture looks different: `m_StreamData.path` is a real file
with a non-zero offset/size, and the pixels live outside the bundle.

## 4. Size thresholds hide your biggest assets

A first pass with a 4096 px cap skipped 8 of the largest images (very wide strips strips,
79.6 MB). Choose the threshold deliberately and record it; `fixups --big` re-runs
with the same flag set so the report shows both passes.

## 5. Export both Texture2D and Sprite

A `Sprite` is a rectangle inside a `Texture2D`. Consumers want both levels: the
atlas page for editing and the individual cut for use. Exporting both on the
reference package produced tens of thousands + tens of thousands = 28,574 files, ~~1 GB.

## 6. Idempotence and duplicates

Re-running an export must not create `_001` copies. Use `--skip-existing`, and when
deduplicating prefer a content-hash move into a quarantine directory over deletion
(bulk deletes are frequently blocked by workspace safety policies and cannot be
audited afterwards). The reference package ended with thousands unique text assets after
content-hash dedup removed 2 byte-identical pairs.

## 7. Contact sheets are part of the deliverable

A grid preview (largest files first, names labelled, transparent art on a checker
background) is how you confirm at a glance whether a container held UI, characters or
terrain. `ga.py report --sheets` writes one sheet per container.
