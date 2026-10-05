# DOS / PC-98 custom format reversing

Methodology distilled from ~30 legacy extractions (DDT/CMP, RSK, a DOS strategy series, HR, ETIN,
CEL, DART, an adult-themed DOS title, a DOS fighter, MKF-style archives). No scripting support is built into
`ga.py` for this branch yet - the CLI deliberately stops at "here is what the bytes
look like" and hands over to this procedure.

## 1. Five stages

1. **Inventory** - list every file with size and entropy. High-entropy blobs are
   compressed or encrypted; low-entropy ones are usually indices or scripts.
2. **Header identification** - dump the first 64-256 bytes; look for magic, version
   fields, and a plausible chunk/record count. Two archives sharing a creator usually
   share a layout: a re-implementation of one game is the best spec you can get.
3. **Structure hypothesis** - write down offsets and sizes of the fields you believe
   you see, then *validate by arithmetic* (does chunk N end where chunk N+1 begins?).
4. **Decoder** - implement the narrowest reader that proves the hypothesis on real
   data, then widen. Log every assumption.
5. **Verification** - round-trip where possible, diff against a reference render, and
   produce a contact sheet. A decoder that "runs" is not a decoder that is correct.

## 2. Four pixel storage morphologies

| Morphology | Layout | Extraction consequence |
|------------|--------|------------------------|
| Palette-indexed | 1 byte per pixel indexing a palette table | need the palette (`.PAL`, embedded 16/256-entry table) before any image makes sense |
| Planar / bitplane | bitplanes per row or per column (CGA/EGA style) | must de-interleave, then map through palette |
| Linear truecolour / 16-bit | RGB555, BGR, 16-bit packed | byte order and stride are the usual traps |
| Compressed raster | RLE / LZ variants inside a container | decompress first, then treat as one of the above |

## 3. The three compression families you will meet

- **Byte-oriented RLE**: (count, value) or (value, count) pairs, sometimes with a
  transparent index. Check both orders before concluding - the marker byte decides.
- **LZSS sliding window**: back-reference (offset, length) pairs; the window size and
  the "copy source is the bytes just written" convention explain most bugs.
- **Bit-level packing**: rare in 8-bit games, common in bitmaps (1/4/8 bpp planes);
  treat it as a morphology conversion, not a compressor.

## 4. Re-implementations are the best spec

Open-source re-implementations expose the original layout in source, with line
numbers you can cite:

- `sdlpal` (SDL2 remake of a DOS martial-arts RPG) documents its archive: chunk
  offsets live at the head of the file as pairs of LE32 (length = next - current),
  the first 4 bytes of a chunk hold the *decompressed* size (two variants depending
  on the target release), and the payload is an LZSS variant. It also lists the
  mandatory file set and notes that one archive embeds external art at its tail.
- `kys-cpp`-style C++ remakes usually expose map/sprite/palette loaders per format.
- `DOSBox`/`SDLPAL` source plus a hex editor is often faster than any generic tool.

Use remakes for *layout*, and original files for *validation*.

## 5. Declare the format before writing the parser

Kaitai Struct is the highest-leverage option available locally: write a `.ksy` schema,
generate a Python decoder, and get validation for free. The bundled compiler needs a
JDK (`bin/kaitai-struct-compiler.bat -t python <file>.ksy`); its standard library
ships ~180 schemas including `formats/game/` (Doom WAD, Quake PAK, Warcraft II PUD,
Fallout II DAT, ...) and `formats/executable/dos_mz.ksy`. Caveat: Kaitai only
**decodes**; there is no encode path, so mods/patching need hand-written writers.

Hand-written `construct` declarations are the lighter alternative when the layout is
simple and you want both directions.

## 6. When to reach for an existing extractor

QuickBMS has hundreds of community scripts and a `-l` (list) / `-f` (filter) /
`-r` (reimport) workflow worth imitating. Two gotchas: its repository ships **no
scripts** (the extensions library is a separate download), and it is a CLI only, so
driving it from Python means subprocess calls and non-interactive flags.

GARbro is the reference implementation for *breadth*: 417 archive classes organized
one-per-file under vendor folders, discovered by MEF, each declaring signature,
extensions and whether it needs parameters. Copy that organisation for your own
format library.

## 7. Sample libraries as fixtures

Small third-party sample sets (per-engine directories holding a few hundred bytes
each) are excellent magic-number fixtures - cheaper than reading someone else's
parser. Keep them out of the deliverable and use them only for identification tests.
