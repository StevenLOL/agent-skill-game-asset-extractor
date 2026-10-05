"""
garecon.py - reconnaissance stage of the game-asset-extractor CLI.

Subcommands: doctor / inventory / unpack / scan / probe.

Why recon is a separate stage: every extraction decision depends on answers only
recon can give cheaply.

* inventory reads only the ZIP central directory - instant even for 400 MB - and
  reveals where the payload lives.  For Unity games that answer decides the route:
  res/ is launcher icons, assets/bin/Data is the game, assets/aa/*.bundle is
  Addressables content with hashed names.
* scan classifies each candidate container by header magic BEFORE loading it, so
  a 240 MB bundle is not parsed unless --all is given, and so resources.resource
  is reported as a bank of FSB5 audio containers instead of being mistaken for a
  Unity bundle and skipped.
* probe decodes a few objects from the smallest container to prove the pipeline
  works before committing to a long run.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from typing import Any

import gacommon as gc
from gacommon import Counter, Report, human_bytes, run_tool

DEFAULT_SCAN_MB = 64.0


def load_env(path: str):
    """Load a Unity container from a PATH (never from bytes).

    UnityPy resolves external payloads (.resource / .resS) relative to env.path;
    loading from an in-memory buffer breaks that lookup with FileNotFoundError.
    """
    import UnityPy
    return UnityPy.load(path)


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #

def cmd_doctor(args: argparse.Namespace) -> int:
    rep = Report(args.report, "ga doctor - environment self-check")
    rep.kv("python", sys.version.split()[0])
    rep.kv("platform", sys.platform)
    rep.kv("executable", sys.executable)

    try:
        import UnityPy
        rep.kv("UnityPy", getattr(UnityPy, "__version__", "unknown"))
        nums = gc.unitypy_version()
        if nums and nums < (1, 20):
            rep.line("  ! UnityPy < 1.20: falling back to legacy read()/read_typetree()")
    except Exception as e:
        rep.kv("UnityPy", f"MISSING ({e})")
        rep.line('  fix: python -m pip install "UnityPy>=1.25"')

    for mod, required in (("PIL", True), ("texture2ddecoder", False),
                          ("astc_encoder", False), ("lz4", False), ("fmod_toolkit", False)):
        try:
            m = __import__(mod)
            rep.kv(mod, str(getattr(m, "__version__", "installed")))
        except Exception:
            rep.kv(mod, "not installed" + ("" if required else " (optional)"))

    if args.vgmstream and os.path.isfile(args.vgmstream):
        code, _ = run_tool([args.vgmstream, "-h"], timeout=30)
        rep.kv("vgmstream", f"{args.vgmstream} (exit {code})")
    else:
        rep.kv("vgmstream", "MISSING - FSB5 decode disabled, raw banks sliced only")
        rep.line("  fix: curl.exe -L --retry 3 --retry-all-errors -o vgmstream-win64.zip"
                 " https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win64.zip")
        rep.line("  then re-run with --vgmstream <path-to-vgmstream-cli>")

    code, _ = run_tool(["ffmpeg", "-version"], timeout=20)
    rep.kv("ffmpeg", "installed" if code == 0 else "missing (optional)")
    code, _ = run_tool(["java", "-version"], timeout=20)
    rep.kv("java", "installed (Kaitai Struct usable)" if code == 0
           else "missing (Kaitai Struct needs a JDK)")

    rep.section("capability summary")
    try:
        import UnityPy  # noqa: F401
        rep.line("  Unity asset extraction: available")
    except Exception:
        rep.line("  Unity asset extraction: UNAVAILABLE (install UnityPy)")
    rep.line("  DOS/legacy route: manual - see references/dos_format_reversing.md")
    rep.flush()
    return 0


# --------------------------------------------------------------------------- #
# inventory / unpack
# --------------------------------------------------------------------------- #

def cmd_inventory(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.apk):
        print(f"not found: {args.apk}", file=sys.stderr)
        return 2
    rep = Report(args.report, f"ga inventory - {os.path.basename(args.apk)}")
    rep.kv("archive", args.apk)
    rep.kv("archive size", human_bytes(os.path.getsize(args.apk)))

    top: dict[str, list[int]] = {}
    second: dict[str, list[int]] = {}
    exts: dict[str, list[int]] = {}
    rows: list[tuple[str, int, int]] = []
    with zipfile.ZipFile(args.apk) as zf:
        infos = zf.infolist()
        total = 0
        for i in infos:
            if i.is_dir():
                continue
            total += i.file_size
            parts = i.filename.split("/")
            t = parts[0] if len(parts) > 1 else "(root)"
            s = "/".join(parts[:2]) if len(parts) > 2 else t
            e = os.path.splitext(i.filename)[1].lower() or "(none)"
            for store, key in ((top, t), (second, s), (exts, e)):
                cur = store.setdefault(key, [0, 0])
                cur[0] += 1
                cur[1] += i.file_size
            rows.append((i.filename, i.file_size, i.compress_size))
    rep.kv("entries", len(infos))
    rep.kv("uncompressed", human_bytes(total))
    rep.section("top-level directories")
    rep.table(["directory", "files", "size"],
              [(k, v[0], human_bytes(v[1])) for k, v in sorted(top.items(), key=lambda kv: -kv[1][1])])
    rep.section("second level (top 30)")
    rep.table(["directory", "files", "size"],
              [(k, v[0], human_bytes(v[1]))
               for k, v in sorted(second.items(), key=lambda kv: -kv[1][1])[:30]])
    rep.section("extensions (top 30)")
    rep.table(["extension", "files", "size"],
              [(k, v[0], human_bytes(v[1]))
               for k, v in sorted(exts.items(), key=lambda kv: -kv[1][1])[:30]])
    rep.section("largest files (top 25)")
    rep.table(["size", "compressed", "path"],
              [(human_bytes(s), human_bytes(c), n)
               for n, s, c in sorted(rows, key=lambda r: -r[1])[:25]], aligns="rrr")
    rep.section("where to look next")
    rep.line("  assets/bin/Data/*           Unity player data (data.unity3d, datapack.unity3d)")
    rep.line("  assets/bin/Data/*.resource    streamed payload, often FSB5 audio banks")
    rep.line("  assets/aa/**/*.bundle       Addressables content (hashed; see catalog.json)")
    rep.line("  res/                        Android launcher icons - usually NOT game art")
    rep.flush()
    return 0


def cmd_unpack(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.apk):
        print(f"not found: {args.apk}", file=sys.stderr)
        return 2
    prefixes = tuple(p.strip("/") + "/" for p in args.prefix) if args.prefix else ("assets/", "res/")
    copied = skipped = 0
    total = 0
    with zipfile.ZipFile(args.apk) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.startswith(prefixes):
                continue
            dest = os.path.join(args.out, info.filename.replace("/", os.sep))
            gc.ensure_dir(os.path.dirname(dest))
            if os.path.isfile(dest) and os.path.getsize(dest) == info.file_size:
                skipped += 1
                continue
            with zf.open(info) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 20)
            copied += 1
            total += info.file_size
    print(f"unpacked {copied} files ({human_bytes(total)}) -> {args.out} (skipped {skipped} existing)")
    return 0


# --------------------------------------------------------------------------- #
# scan / probe
# --------------------------------------------------------------------------- #

def cmd_scan(args: argparse.Namespace) -> int:
    rep = Report(args.report, "ga scan - container and object-type census")
    containers = gc.find_unity_containers(args.raw)
    rep.kv("raw dir", args.raw)
    rep.kv("candidates", len(containers))

    totals = Counter()
    rows: list[tuple[str, str, str, int, int]] = []
    for path in containers:
        kind, detail = gc.detect_container(path)
        rel = os.path.relpath(path, args.raw)
        size = os.path.getsize(path)
        if kind != "unityfs":
            rows.append((rel, kind, detail, 0, 0))
            continue
        if size > args.max_scan_mb * 1024 * 1024 and not args.all:
            rows.append((rel, kind, detail, -1, 0))
            continue
        try:
            env = load_env(path)
            objs = env.objects            # cache: the property rebuilds the list each access
            census = Counter()
            for obj in objs:
                census.add(gc.object_type_name(obj))
            rows.append((rel, kind, detail, len(objs), census.total()))
            totals.merge(census)
            del env, objs
        except Exception as e:
            rows.append((rel, kind, f"ERROR {type(e).__name__}: {e}", -2, 0))

    rep.section("containers")
    rep.table(["container", "kind", "detail", "objects", "types"], rows, aligns="lllrr")
    rep.line("  objects: -1 = too large for this pass (rerun with --all), -2 = load error")
    rep.section("object type totals")
    rep.table(["type", "count"], totals.most_common(40), aligns="lr")
    rep.section("interpretation")
    rep.line("  kind=fsb5      -> concatenation of standalone FSB5 audio banks; use the audio stage")
    rep.line("  kind=serialized -> bare SerializedFile (engine defaults, little game content)")
    rep.line("  hashed .bundle -> Addressables; map names via assets/aa/catalog.json")
    rep.flush()
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    rep = Report(args.report, "ga probe - small-sample feasibility")
    unity = [p for p in gc.find_unity_containers(args.raw)
             if gc.detect_container(p)[0] == "unityfs"]
    if not unity:
        rep.line("no UnityFS container found under the raw dir")
        rep.flush()
        return 1
    # Prefer the smallest container that actually holds image objects: the smallest
    # container overall is often a tiny localization bundle with nothing to decode,
    # which makes the probe report "no images" and prove nothing.
    ordered = sorted(unity, key=lambda p: os.path.getsize(p))
    smallest = None
    env = None
    for cand in ordered[:12]:
        try:
            trial = load_env(cand)
        except Exception:
            continue
        if any(gc.object_type_name(o) in gc.IMAGE_TYPES for o in trial.objects):
            smallest, env = cand, trial
            break
        del trial
    if env is None:
        smallest = ordered[-1]
        try:
            env = load_env(smallest)
        except Exception as exc:
            rep.line(f"load failed: {type(exc).__name__}: {exc}")
            rep.flush()
            return 1
    rep.kv("sample", os.path.relpath(smallest, args.raw))
    rep.kv("size", human_bytes(os.path.getsize(smallest)))

    counts: Counter = Counter()
    clips: list[Any] = []
    for obj in env.objects:
        t = gc.object_type_name(obj)
        counts.add(t)
        if t == "AudioClip" and len(clips) < 5:
            try:
                clips.append(gc.read_object(obj))
            except Exception:
                pass
    rep.kv("objects", counts.total())
    rep.table(["type", "count"], counts.most_common(15), aligns="lr")

    out_dir = gc.ensure_dir(os.path.join(args.out, "probe"))
    formats: Counter = Counter()
    for obj in env.objects:
        if gc.object_type_name(obj) not in gc.IMAGE_TYPES:
            continue
        try:
            data = gc.read_object(obj)
            img = getattr(data, "image", None)
            if img is None:
                continue
            stem = gc.safe_name(str(getattr(data, "name", "") or ""),
                                f"{gc.object_type_name(obj).lower()}_{obj.path_id}")
            path, write = gc.unique_path(out_dir, stem, ".png", skip_existing=True)
            if write:
                img.save(path)
            formats.add(str(getattr(data, "m_TextureFormat", "?")))
            rep.kv("decoded", f"{os.path.basename(path)} {img.size[0]}x{img.size[1]} "
                              f"fmt={getattr(data, 'm_TextureFormat', '?')}")
        except Exception as e:
            rep.line(f"  decode error: {type(e).__name__}: {e}")
        if formats.total() >= 5:
            break
    rep.section("texture formats decoded")
    rep.table(["TextureFormat", "count"], formats.most_common(), aligns="lr")

    if clips:
        rep.section("audio clip metadata (sample)")
        rows = []
        for c in clips:
            res = getattr(c, "m_Resource", None)
            rows.append((
                str(getattr(c, "name", "?"))[:26],
                getattr(c, "m_CompressionFormat", "?"),
                getattr(c, "m_Frequency", "?"),
                getattr(c, "m_Channels", "?"),
                f"{float(getattr(c, 'm_Length', 0) or 0):.2f}s",
                f"{getattr(res, 'm_Offset', '-')}/{getattr(res, 'm_Size', '-')}" if res else "inline",
            ))
        rep.table(["name", "fmt", "freq", "ch", "length", "off/size"], rows, aligns="llrrrr")
        rep.line("  an off/size range means the samples live in an external payload file;")
        rep.line("  the audio stage resolves and slices it automatically.")
    rep.flush()
    return 0


# @@TAIL@@
