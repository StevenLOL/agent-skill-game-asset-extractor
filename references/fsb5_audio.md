# FSB5 audio (Unity streamed sound banks)

Measurements below come from a commercial wuxia RPG (all clips, ~37 MB
`resources.resource`, under an hour of audio, Vorbis 44.1 kHz).

## 1. The mechanism

1. `AudioClip` objects live in the Unity bundle, but `m_AudioData` is **empty**.
2. The samples are referenced by `m_Resource = StreamedResource(offset, size, source)`,
   where `source` is typically `resources.resource`.
3. That file is **not** a Unity bundle. It is a plain concatenation of *independent*
   FSB5 containers. Proof: counting the `FSB5` magic across the file yields exactly
   as many hits as there are AudioClips (339 = 339), and each clip's
   `(offset, size)` lands exactly on one container.

Therefore: **locate containers by magic, slice by the clip's offset/size.**
Never assume the first header describes the whole file.

    python -c "import re; d=open('resources.resource','rb').read(); \
      print(len(re.findall(b'FSB5', d)))"

## 2. FSB5 version 1 header (verified layout)

| Offset | Field | Observed |
|--------|-------|----------|
| 0x00 | magic `FSB5` | - |
| 0x04 | version | 1 |
| 0x08 | numSamples | 1 per container in this game |
| 0x0C | sampleHeaderSize | 0x24 (36) |
| 0x10 | nameSize | 0 |
| 0x14 | dataSize | e.g. 0x2160 (8544) |
| 0x18 | mode | 0x0F |
| 0x1C | flags | 1 |
| 0x20-0x3B | reserved / hash (28 bytes) | - |
| 0x3C | sample header (36 bytes) | - |
| 0x60 | raw Vorbis payload (`dataSize` bytes) | - |

Self-check that the layout is right: `container size == 0x3C + sampleHeaderSize
+ nameSize + dataSize`. In a reference package 8640 = 60 + 36 + 0 + 8544.
If the numbers do not add up, fall back to "distance to the next FSB5 magic".

## 3. Why the payload is not an .ogg

Scanning the whole file for `OggS`, `vorbis` and `RIFF` returns **zero** hits: the
banks hold raw Vorbis packets without an Ogg container, so no demuxer will open them.
Unity's own runtime ships a private FMOD build to decode them.

UnityPy's `AudioClip.samples` calls `fmod_toolkit.raw_to_wav`, which failed with
`FmodError: FORMAT` on **all** clips (Unity's FSB5 header variant is not
accepted). Do not spend time on that path.

## 4. Working path: vgmstream

    curl.exe -L --retry 3 --retry-all-errors -o vgmstream-win64.zip ^
      https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win64.zip
    Expand-Archive vgmstream-win64.zip -DestinationPath tools\vgmstream
    ga.py audio --raw work/game/raw --out work/game/out ^
               --vgmstream tools\vgmstream\vgmstream-cli.exe

Result on a reference package: all converted, WAV headers valid, longest track
176 s. `Invoke-WebRequest` is unreliable for GitHub releases on this network - the
connection gets reset - so always use `curl.exe` with retries.

If vgmstream is unavailable the audio stage still slices the banks to `.fsb` files and
records `raw_only_no_decoder` in `audio.csv`; nothing is lost, only the conversion.

## 5. Native audio fast path

Clip payloads starting with `OggS`, `RIFF` or `ftyp` are copied out untouched. The
reference package had none - all 339 were Vorbis/FSB5 - but other titles ship Ogg
directly (`m_CompressionFormat` = Vorbis with an Ogg container rather than FSB5).

## 6. Naming and duplicates

Clip names collide constantly (`stand` appeared 47 times in a reference package,
`atk` 142 times). Disambiguate with a numeric suffix and record the mapping in
`audio.csv` (name, container, format, freq, channels, length, offset, size, path,
status) so a renamed file can always be traced back to its clip.

Grouping by name prefix is a cheap way to understand an audio set: in the reference
package `atk` 142 / `stand` 47 / `dmg` 32 / `walk` 17 / `death` 16 plus 44 tracks
over 10 s revealed a fighting-game SFX set plus background music.
