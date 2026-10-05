# Tooling and environment

## 1. Interpreter

Run `python -c "import UnityPy, PIL; print(UnityPy.__version__)"` first.
On Windows the default `python` is often a bare install **without Pillow**; a conda
interpreter is usually the one that has the full stack. Never hard-code a path in a
script - take it from a flag or ask.

    python -m pip install -r requirements.txt

## 2. Packages

| Package | Needed for | If missing |
|---------|-----------|------------|
| UnityPy >= 1.25 | everything Unity | install; assert `__version__` because breaking changes land in minor releases |
| Pillow | image writing, contact sheets | image stages fail |
| texture2ddecoder | PVRTC/ATC/ETC/ETC2/EAC | those textures fail |
| astc-encoder-py | ASTC decode/encode | modern mobile textures fail |
| lz4 | UnityFS block compression | bundles may fail to load |
| fmod_toolkit | UnityPy's own AudioClip decode | optional; the FSB5 path uses vgmstream instead |

## 3. External tools

| Tool | Purpose | Install |
|------|---------|---------|
| vgmstream-cli | FSB5 -> WAV (the only path that worked: all) | `curl.exe -L --retry 3 --retry-all-errors -o vgmstream-win64.zip https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win64.zip` then unzip |
| ffmpeg | a few legacy audio formats | any build; put its directory on PATH |
| JDK | Kaitai Struct compiler | for `.ksy` -> decoder generation |

`Invoke-WebRequest` gets its connection reset on GitHub releases from some networks;
`curl.exe -L --retry 3 --retry-all-errors` is the reliable form. GitHub itself is
usually reachable; HF / Kaggle / Google Storage are often not - use mirrors such as
`hf-mirror.com`.

## 4. Shell and encoding pitfalls (Windows)

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| `powershell.exe` (5.1) reading a UTF-8 script without BOM | mojibake, then parser errors such as "the string is missing the terminator" | keep `.ps1` ASCII-only, or save with a BOM, or run with `pwsh` |
| console codepage | non-ASCII output garbled | write every report as UTF-8 and read the file back; never trust stdout |
| reading a text file in PowerShell without an explicit `-Encoding` | blocked by policy or mojibake | always pass `-Encoding UTF8` |
| `tail` does not exist | - | use `Select-Object -Last N` |
| bulk deletes | blocked by workspace safety policy | move to a quarantine directory instead |

## 5. UnityPy API generations

- modern: `parse_as_object()`, `parse_as_dict()`, `patch()`
- legacy: `read()`, `read_typetree()`, `save_typetree()` - slated for removal in 2.0

Branch on `UnityPy.__version__` (>= 1.20 modern, older legacy). `gacommon.read_object`
does this once so no stage has to care.

## 6. Non-negotiables when scripting UnityPy

1. Load from a **path**, never from bytes, so external `.resource` / `.resS` resolve.
2. Cache `env.objects` - it is a property that rebuilds the list on every access.
3. Never use two threads on one loaded environment (shared cursor per SerializedFile).
4. `obj.get_raw_data()` returns **that object's** serialized block, not the file and
   not the payload - strip the header yourself for TextAssets.
5. Version strings of `0.0.0` raise `UnityVersionFallbackError`; set
   `UnityPy.config.FALLBACK_UNITY_VERSION` when a container lacks one.
6. The C++ boost reader can crash without warning; if a run is unstable, disable it
   and fall back to the pure-python typetree path.

## 7. Exit-code discipline for CI-style use

`ga.py` returns 0 on success and 2 for a missing input file. `ga.py all` runs every
step, prints which steps returned non-zero, and always exits 0 so a partial success
stays inspectable - read the summary report to decide whether a rerun is needed.

## 8. Validating and packaging this skill

The bundled skill-creator scripts read files with Python's *default* encoding, which
on a Chinese Windows install is GBK. Validating a skill whose `SKILL.md` contains
non-ASCII trigger keywords therefore crashes with
`UnicodeDecodeError: 'gbk' codec can't decode byte ...`. Force UTF-8 mode:

    $env:PYTHONUTF8 = "1"
    python <skill-creator>/scripts/quick_validate.py <skill-dir>      # -> "Skill is valid!"
    python <skill-creator>/scripts/package_skill.py <skill-dir> <dist-dir>

Delete `__pycache__/` before packaging so the archive contains only sources.
