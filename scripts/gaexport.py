"""
gaexport.py - export stage of the game-asset-extractor CLI.

Implements the four extraction subcommands (images / audio / texts / fixups) plus
the aggregation step (report).  Kept separate from ``ga.py`` so the entry point
stays readable and each stage can be imported and reused on its own:

    from gaexport import export_images
    export_images(raw_dir, out_dir, max_side=4096, skip_existing=True)

Every hard-won rule from the field is encoded here and commented at its site:

* Empty asset names fall back to ``<type>_<path_id>`` so siblings cannot overwrite
  each other (measured: 8 distinct very wide strips images collapsed into one file).
* TextAsset payloads are stripped from ``obj.get_raw_data()``; the ``m_Script``
  string field decodes lossily and truncated a 43,554 byte Spine skeleton to
  43,082 characters.
* Streamed audio lives in a *separate* file (``resources.resource``) which is a
  concatenation of standalone FSB5 banks, so clips are sliced by the offset/size
  recorded on the AudioClip and converted with an external decoder.
* A ``PermissionError [Errno 13]`` while decoding a texture is a *placeholder*
  texture (0x0 size, empty ``m_StreamData.path`` that resolves to a directory),
  not a lost asset.
* Nothing is deleted: duplicates are moved into ``_quarantine/``.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
from collections import Counter as StdCounter

from gacommon import (
    Counter, IndexWriter, Progress, Report, collect_targets, dir_stats,
    ensure_dir, file_md5, human_bytes, human_duration, natural_key,
    quarantine_move, read_object, run_tool, safe_name, sniff_text_type,
    sorted_files, unique_path, object_type_name,
)
import gacommon as gc


def load_done_keys(index_path: str, kind: str, out_root: str = "") -> set:
    """Read a previous run's CSV index and rebuild the set of object identities.

    This is what makes --skip-existing safe: the decision is based on *which object*
    was exported, not on whether a file with that name happens to exist.  Two
    different assets can share a name (47 clips named "stand" in the reference
    package), so a filename test alone silently drops assets.

    A row only counts as done when its recorded output file is actually present, so a
    row that was written for a skipped/failed object does not permanently veto a retry.
    """
    keys: set = set()
    if not index_path or not os.path.isfile(index_path):
        return keys

    def exists(rel: str) -> bool:
        if not rel:
            return False
        if not out_root:
            return True
        return os.path.exists(os.path.join(out_root, rel.replace("/", os.sep)))

    with open(index_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                if kind == "images":
                    if row.get("status") == "exported":
                        keys.add((row["container"], row["type"], int(row["path_id"])))
                elif kind == "audio":
                    if row.get("status") in ("ok", "ok_native", "ok_existing"):
                        path = (row.get("audio_path") or "").replace("\\", "/")
                        bucket = "wav" if "/wav/" in path else "fsb"
                        keys.add((bucket, row["container"], row.get("offset", "")))
                elif kind == "texts":
                    if row.get("status") == "exported":
                        keys.add((row["container"], row["type"],
                                  row["asset_name"], row["bytes"]))
            except (KeyError, ValueError):
                continue
    return keys


# --------------------------------------------------------------------------- #
# images
# --------------------------------------------------------------------------- #

def export_images(raw_dir: str, out_dir: str, max_side: int = 4096,
                  skip_existing: bool = True, index_path: str = "") -> tuple[Counter, str]:
    targets = collect_targets(raw_dir, out_dir)
    stat = Counter()
    index_path = index_path or os.path.join(targets["reports"], "images.csv")
    containers = [p for p in gc.find_unity_containers(raw_dir)
                  if gc.detect_container(p)[0] == "unityfs"]
    t0 = time.time()
    # ExportNamer keeps re-runs idempotent WITHOUT dropping same-named assets:
    # a naive skip_existing lost thousands files in a reference run.
    namer = gc.ExportNamer(skip_existing=skip_existing,
                           pre_done=load_done_keys(index_path, "images", targets["out"]))

    with IndexWriter(index_path, ["container", "type", "asset_name", "path_id", "width",
                                  "height", "format", "out_path", "status"]) as idx:
        for path in containers:
            tag = os.path.relpath(path, raw_dir)
            try:
                import UnityPy
                env = UnityPy.load(path)      # path, never bytes: external payloads resolve
            except Exception as e:
                stat.add(f"load_error_{type(e).__name__}")
                continue
            objs = env.objects                  # cache: the property rebuilds the list each access
            prog = Progress(len(objs), label=f"images {os.path.basename(tag)[:26]}", every=1000)
            for obj in objs:
                tname = object_type_name(obj)
                if tname not in gc.IMAGE_TYPES:
                    prog.tick()
                    continue
                stat.add(f"seen_{tname}")
                try:
                    data = read_object(obj)
                    img = getattr(data, "image", None)
                    if img is None:
                        stat.add("no_image")
                        prog.tick()
                        continue
                    w, h = img.size
                    if max(w, h) > max_side:
                        stat.add(f"too_big_{tname}")
                        idx.write(tag, tname, str(getattr(data, "name", "")), obj.path_id,
                                  w, h, getattr(data, "m_TextureFormat", ""), "",
                                  f"skipped: {w}x{h} exceeds --max-side {max_side}")
                        prog.tick()
                        continue
                    raw_name = str(getattr(data, "name", "") or getattr(data, "m_Name", "") or "")
                    stem = safe_name(raw_name, f"{tname.lower()}_{obj.path_id}")
                    sub = os.path.join(targets["textures"], tag.replace("/", "_"),
                                       "sprite" if tname == "Sprite" else "tex")
                    dest, write = namer.path_for(sub, stem, ".png",
                                                 key=(tag, tname, obj.path_id))
                    if write:
                        img.save(dest)
                        stat.add(f"ok_{tname}")
                        status = "exported"
                        if re.search(r"_\d{3}\.png$", os.path.basename(dest)):
                            stat.add(f"renamed_collision_{tname}")
                    else:
                        stat.add(f"skip_existing_{tname}")
                        status = "skipped_existing"
                    idx.write(tag, tname, raw_name, obj.path_id, w, h,
                              getattr(data, "m_TextureFormat", ""),
                              os.path.relpath(dest, targets["out"]).replace("\\", "/"),
                              status)
                except Exception as e:
                    if type(e).__name__ == "PermissionError" or "Errno 13" in str(e):
                        # 0x0 placeholder texture: UnityPy resolves the empty
                        # m_StreamData.path to a DIRECTORY and open() fails on Windows.
                        stat.add("placeholder_texture")
                    else:
                        stat.add(f"err_{tname}_{type(e).__name__}")
                prog.tick()
            prog.close()
            del env, objs
    stat.add("seconds", int(time.time() - t0))
    return stat, index_path


def cmd_images(args: argparse.Namespace) -> int:
    stat, index_path = export_images(args.raw, args.out, args.max_side,
                                     args.skip_existing, args.index)
    print(f"images: {stat}")
    print(f"index: {index_path}")
    print("note: 'placeholder_texture' = 0x0 filler textures, not missing assets.")
    return 0


# --------------------------------------------------------------------------- #
# audio
# --------------------------------------------------------------------------- #

def _resolve_payload(raw_dir: str, source: str) -> str | None:
    """Locate an external payload file (e.g. resources.resource) under raw_dir."""
    if not source:
        return None
    base = os.path.basename(source.replace("\\", "/"))
    direct = os.path.join(raw_dir, "assets", "bin", "Data", base)
    if os.path.isfile(direct):
        return direct
    for dirpath, _dirs, files in os.walk(raw_dir):
        if base in files:
            return os.path.join(dirpath, base)
    return None


def collect_audio_clips(raw_dir: str) -> tuple[list[dict], Counter]:
    """Read AudioClip metadata from every Unity container under raw_dir."""
    clips: list[dict] = []
    stat = Counter()
    for path in gc.find_unity_containers(raw_dir):
        if gc.detect_container(path)[0] != "unityfs":
            continue
        try:
            import UnityPy
            env = UnityPy.load(path)
        except Exception:
            stat.add("container_load_error")
            continue
        for obj in env.objects:
            if object_type_name(obj) != "AudioClip":
                continue
            try:
                data = read_object(obj)
            except Exception:
                stat.add("clip_read_error")
                continue
            res = getattr(data, "m_Resource", None)
            clips.append({
                "container": os.path.relpath(path, raw_dir),
                "name": str(getattr(data, "name", "") or f"clip_{obj.path_id}"),
                "path_id": obj.path_id,
                "fmt": getattr(data, "m_CompressionFormat", None),
                "freq": getattr(data, "m_Frequency", None),
                "channels": getattr(data, "m_Channels", None),
                "length": float(getattr(data, "m_Length", 0) or 0.0),
                "offset": getattr(res, "m_Offset", None) if res else None,
                "size": getattr(res, "m_Size", None) if res else None,
                "source": str(getattr(res, "m_Source", "")) if res else "",
            })
        del env
    stat.add("clips_found", len(clips))
    return clips, stat


def export_audio(raw_dir: str, out_dir: str, vgmstream: str = "",
                 skip_existing: bool = True, timeout: int = 120,
                 index_path: str = "") -> tuple[Counter, str]:
    targets = collect_targets(raw_dir, out_dir)
    index_path = index_path or os.path.join(targets["reports"], "audio.csv")
    clips, stat = collect_audio_clips(raw_dir)
    t0 = time.time()
    ext_of = {b"FSB5": ".fsb", b"OggS": ".ogg", b"RIFF": ".wav"}
    namer = gc.ExportNamer(skip_existing=skip_existing,
                           pre_done=load_done_keys(index_path, "audio", targets["out"]))

    with IndexWriter(index_path, ["name", "container", "format", "freq", "channels",
                                  "length_sec", "offset", "size", "audio_path",
                                  "status"]) as idx:
        for i, c in enumerate(clips):
            stem = safe_name(c["name"], f"clip_{c['path_id']}")
            payload = None

            # 1) payload inside its own container
            if c["offset"] is not None and c["size"]:
                own = os.path.join(raw_dir, c["container"].replace("/", os.sep))
                if os.path.isfile(own):
                    with open(own, "rb") as f:
                        f.seek(c["offset"])
                        blob = f.read(c["size"])
                    if blob[:4] in ext_of:
                        payload = blob
                # 2) payload in an external file (typical Unity streamed audio)
                if payload is None and c["source"]:
                    src_path = _resolve_payload(raw_dir, c["source"])
                    if src_path:
                        with open(src_path, "rb") as f:
                            f.seek(c["offset"])
                            payload = f.read(c["size"])

            if not payload:
                stat.add("payload_missing")
                idx.write(c["name"], c["container"], c["fmt"], c["freq"], c["channels"],
                          f"{c['length']:.3f}", c["offset"], c["size"], "", "payload_missing")
                continue

            ext = ext_of.get(payload[:4], ".bin")
            raw_path, write = namer.path_for(targets["fsb"], stem, ext,
                                             key=("fsb", c["container"], str(c["offset"])))
            if write:
                with open(raw_path, "wb") as f:
                    f.write(payload)
            stat.add(f"slice_{ext.lstrip('.')}")

            out_rel = ""
            if ext in (".wav", ".ogg"):
                dest = os.path.join(targets["wav"], os.path.basename(raw_path))
                if not os.path.exists(dest):
                    ensure_dir(os.path.dirname(dest))
                    with open(dest, "wb") as f:
                        f.write(payload)
                out_rel = os.path.relpath(dest, targets["out"]).replace("\\", "/")
                status = "ok_native"
                stat.add("native_audio")
            elif vgmstream and os.path.isfile(vgmstream):
                wav_path, w2 = namer.path_for(targets["wav"], stem, ".wav",
                                               key=("wav", c["container"], str(c["offset"])))
                if w2:
                    code, _out = run_tool([vgmstream, "-o", wav_path, raw_path], timeout=timeout)
                    if code == 0 and os.path.isfile(wav_path):
                        stat.add("wav_ok")
                        out_rel = os.path.relpath(wav_path, targets["out"]).replace("\\", "/")
                        status = "ok"
                    else:
                        stat.add("vgmstream_error")
                        status = f"vgmstream_error:{code}"
                else:
                    out_rel = os.path.relpath(wav_path, targets["out"]).replace("\\", "/")
                    status = "ok_existing"
            else:
                stat.add("no_decoder")
                status = "raw_only_no_decoder"
                out_rel = os.path.relpath(raw_path, targets["out"]).replace("\\", "/")

            idx.write(c["name"], c["container"], c["fmt"], c["freq"], c["channels"],
                      f"{c['length']:.3f}", c["offset"], c["size"], out_rel, status)
            if (i + 1) % 100 == 0:
                print(f"  audio {i + 1}/{len(clips)}", flush=True)

    stat.add("seconds", int(time.time() - t0))
    return stat, index_path


def cmd_audio(args: argparse.Namespace) -> int:
    stat, index_path = export_audio(args.raw, args.out, args.vgmstream,
                                    args.skip_existing, args.timeout, args.index)
    targets = collect_targets(args.raw, args.out)
    n_wav, sz_wav = dir_stats(targets["wav"])
    n_fsb, _ = dir_stats(targets["fsb"])
    print(f"audio: {stat}")
    print(f"wav: {n_wav} files / {human_bytes(sz_wav)}; raw banks: {n_fsb}")
    print(f"index: {index_path}")
    if not args.vgmstream:
        print("hint: FSB5 banks were sliced but not converted; pass --vgmstream <cli> for WAV.")
    return 0


# --------------------------------------------------------------------------- #
# texts / fonts
# --------------------------------------------------------------------------- #

def export_texts(raw_dir: str, out_dir: str, skip_existing: bool = True,
                 index_path: str = "") -> tuple[Counter, str]:
    import re
    targets = collect_targets(raw_dir, out_dir)
    index_path = index_path or os.path.join(targets["reports"], "texts.csv")
    stat = Counter()
    t0 = time.time()
    namer = gc.ExportNamer(skip_existing=skip_existing,
                           pre_done=load_done_keys(index_path, "texts", targets["out"]))
    with IndexWriter(index_path, ["container", "type", "asset_name", "bytes", "method",
                                  "out_path", "status"]) as idx:
        for path in gc.find_unity_containers(raw_dir):
            if gc.detect_container(path)[0] != "unityfs":
                continue
            tag = os.path.relpath(path, raw_dir)
            try:
                import UnityPy
                env = UnityPy.load(path)
            except Exception:
                stat.add("load_error")
                continue
            objs = env.objects
            prog = Progress(len(objs), label=f"texts {os.path.basename(tag)[:26]}", every=2000)
            for obj in objs:
                tname = object_type_name(obj)
                if tname == "TextAsset":
                    try:
                        data = read_object(obj)
                        payload, method = gc.textasset_bytes(obj, data)
                        if not payload:
                            stat.add("text_empty")
                            prog.tick()
                            continue
                        name = str(getattr(data, "name", "") or f"asset_{obj.path_id}")
                        ext = os.path.splitext(name)[1].lower() or ".bin"
                        if not re.match(r"^\.[a-z0-9_]{1,10}$", ext):
                            ext = ".bin"
                        stem = safe_name(os.path.splitext(name)[0] or f"asset_{obj.path_id}")
                        sub = os.path.join(targets["text"], tag.replace("/", "_"),
                                           ext.lstrip("."))
                        dest, write = namer.path_for(sub, stem, ext,
                                                     key=(tag, "TextAsset", name, str(len(payload))))
                        if write:
                            with open(dest, "wb") as f:
                                f.write(payload)
                        stat.add("text_ok")
                        stat.add(f"ext_{ext.lstrip('.')}")
                        idx.write(tag, "TextAsset", name, len(payload), method,
                                  os.path.relpath(dest, targets["out"]).replace("\\", "/"),
                                  "exported" if write else "skipped_existing")
                    except Exception as e:
                        stat.add(f"text_err_{type(e).__name__}")
                elif tname == "Font":
                    try:
                        data = read_object(obj)
                        blob = getattr(data, "m_FontData", None)
                        if not blob:
                            stat.add("font_empty")
                            prog.tick()
                            continue
                        blob = bytes(blob)
                        ext = ".otf" if blob[:4] == b"OTTO" else ".ttf"
                        stem = safe_name(str(getattr(data, "name", "") or ""),
                                         f"font_{obj.path_id}")
                        dest, write = namer.path_for(targets["fonts"], stem, ext,
                                                     key=(tag, "Font", stem, str(len(blob))))
                        if write:
                            with open(dest, "wb") as f:
                                f.write(blob)
                        stat.add("font_ok")
                        idx.write(tag, "Font", stem, len(blob), "m_FontData",
                                  os.path.relpath(dest, targets["out"]).replace("\\", "/"),
                                  "exported" if write else "skipped_existing")
                    except Exception:
                        stat.add("font_err")
                prog.tick()
            prog.close()
            del env, objs
    stat.add("seconds", int(time.time() - t0))
    return stat, index_path


def cmd_texts(args: argparse.Namespace) -> int:
    stat, index_path = export_texts(args.raw, args.out, args.skip_existing, args.index)
    print(f"texts: {stat}")
    print(f"index: {index_path}")
    return 0


# --------------------------------------------------------------------------- #
# fixups
# --------------------------------------------------------------------------- #

def export_big_images(raw_dir: str, out_dir: str, max_side: int = 4096,
                      skip_existing: bool = True) -> tuple[Counter, list[str]]:
    """Second pass for art larger than the default threshold, plus placeholder diagnosis."""
    targets = collect_targets(raw_dir, out_dir)
    stat = Counter()
    notes: list[str] = []
    for path in gc.find_unity_containers(raw_dir):
        if gc.detect_container(path)[0] != "unityfs":
            continue
        tag = os.path.relpath(path, raw_dir).replace("/", "_")
        try:
            import UnityPy
            env = UnityPy.load(path)
        except Exception:
            continue
        for obj in env.objects:
            tname = object_type_name(obj)
            if tname not in gc.IMAGE_TYPES:
                continue
            try:
                data = read_object(obj)
            except Exception:
                continue
            w = int(getattr(data, "m_Width", 0) or 0)
            h = int(getattr(data, "m_Height", 0) or 0)
            if tname == "Sprite" and (w == 0 or h == 0):
                # A Sprite stores its size in m_Rect, not in m_Width/m_Height, so
                # reading those two fields makes every sprite look like a 0x0
                # placeholder (tens of thousands false positives in a reference package).
                rect = getattr(data, "m_Rect", None)
                w = int(getattr(rect, "width", 0) or 0) if rect is not None else 0
                h = int(getattr(rect, "height", 0) or 0) if rect is not None else 0
            if w == 0 or h == 0:
                sd = getattr(data, "m_StreamData", None)
                p = getattr(sd, "path", "") if sd is not None else ""
                o = getattr(sd, "offset", 0) if sd is not None else 0
                s = getattr(sd, "size", 0) if sd is not None else 0
                if not p and not o and not s:
                    stat.add("placeholder_texture")
                    notes.append(f"placeholder texture {tname} path_id={obj.path_id} "
                                 f"(0x0, empty m_StreamData) - not a missing asset")
                else:
                    stat.add("streamed_external")
                    notes.append(f"streamed texture {tname} path_id={obj.path_id} "
                                 f"-> {p} @{o}+{s} (resolve manually)")
                continue
            if max(w, h) <= max_side:
                continue
            try:
                img = getattr(data, "image", None)
                if img is None:
                    continue
                stem = safe_name(str(getattr(data, "name", "") or ""),
                                 f"{tname.lower()}_{obj.path_id}")
                dest, write = unique_path(os.path.join(targets["textures_big"], tag),
                                          stem, ".png", skip_existing=skip_existing)
                if write:
                    img.save(dest)
                    stat.add("big_exported")
                    notes.append(f"big image {w}x{h} -> {os.path.basename(dest)}")
            except Exception as e:
                stat.add(f"big_err_{type(e).__name__}")
        del env
    return stat, notes


def dedup_by_content(root: str, quarantine_dir: str) -> tuple[int, int]:
    """Move content-identical files to quarantine.  Returns (count, bytes)."""
    seen: dict[str, str] = {}
    moved = 0
    freed = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in sorted(files, key=natural_key):
            src = os.path.join(dirpath, fn)
            try:
                h = file_md5(src)
                size = os.path.getsize(src)
            except OSError:
                continue
            if h in seen:
                quarantine_move(src, quarantine_dir)
                moved += 1
                freed += size
            else:
                seen[h] = src
    return moved, freed


def cmd_fixups(args: argparse.Namespace) -> int:
    targets = collect_targets(args.raw or args.out, args.out)
    rep = Report(args.report, "ga fixups - gap analysis and cleanup")
    stat = Counter()

    if args.big and args.raw:
        big_stat, notes = export_big_images(args.raw, args.out, args.max_side, args.skip_existing)
        stat.merge(big_stat)
        rep.section("oversized art / placeholder textures")
        for n in notes[:80]:
            rep.line("  " + n)
        if len(notes) > 80:
            rep.line(f"  ... {len(notes) - 80} more")

    rep.section("extension sniffing")
    rep.line("  Game containers routinely ship TextAssets with misleading extensions;")
    rep.line("  content decides the real type (JSON / Spine atlas / Spine skeleton).")
    rename_plan: list[tuple[str, str]] = []
    for dirpath, _dirs, files in os.walk(targets["text"]):
        for fn in files:
            src = os.path.join(dirpath, fn)
            guess = sniff_text_type(src)
            if not guess or guess == os.path.splitext(fn)[1].lower():
                continue
            rename_plan.append((os.path.relpath(src, targets["out"]), guess))
            stat.add(f"sniff_{os.path.splitext(fn)[1].lower()}_to_{guess.lstrip('.')}")
    for src, guess in rename_plan:
        rep.kv(src[:62], guess)
    if rename_plan and args.apply:
        for src, guess in rename_plan:
            full = os.path.join(targets["out"], src)
            dest = os.path.splitext(full)[0] + guess
            i = 1
            while os.path.exists(dest):
                dest = f"{os.path.splitext(full)[0]}_{i:03d}{guess}"
                i += 1
            os.rename(full, dest)
        rep.kv("applied", f"{len(rename_plan)} renames")
    elif rename_plan:
        rep.kv("dry run", f"{len(rename_plan)} renames pending (use --apply)")

    if args.dedup:
        moved, freed = dedup_by_content(targets["text"], targets["quarantine"])
        stat.add("dupes_quarantined", moved)
        rep.section("content-hash dedup")
        rep.kv("duplicates moved", moved)
        rep.kv("bytes isolated", human_bytes(freed))
        rep.kv("quarantine", targets["quarantine"])
        rep.line("  Nothing was deleted; review the quarantine directory before removing it.")

    rep.section("summary")
    rep.line(f"  {stat}")
    rep.flush()
    print(f"fixups: {stat}")
    return 0


# --------------------------------------------------------------------------- #
# report + contact sheets
# --------------------------------------------------------------------------- #

def contact_sheet(paths: list[str], dest: str, cols: int = 8, rows: int = 6,
                  cell: int = 220, label_h: int = 22) -> int:
    """Grid preview of sample images, labelled with asset names."""
    from PIL import Image, ImageDraw, ImageFont
    picked = paths[: cols * rows]
    if not picked:
        return 0
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 13)
        except Exception:
            font = ImageFont.load_default()
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), (24, 26, 32))
    draw = ImageDraw.Draw(sheet)
    for i, p in enumerate(picked):
        r, c = divmod(i, cols)
        x, y = c * cell, r * (cell + label_h)
        try:
            im = Image.open(p).convert("RGBA")
            bg = Image.new("RGBA", im.size, (40, 42, 50, 255))
            im = Image.alpha_composite(bg, im).convert("RGB")
            im.thumbnail((cell - 8, cell - 8))
            sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        except Exception:
            draw.text((x + 6, y + 20), "[unreadable]", fill=(255, 120, 120), font=font)
        draw.text((x + 4, y + cell + 3),
                  os.path.splitext(os.path.basename(p))[0][:32],
                  fill=(210, 214, 220), font=font)
    ensure_dir(os.path.dirname(dest))
    sheet.save(dest)
    return len(picked)


def build_report(out_dir: str, raw_dir: str = "", sheets: bool = False,
                 sheet_dir: str = "", report_path: str = "") -> Report:
    targets = collect_targets(raw_dir or out_dir, out_dir)
    rep = Report(report_path, "ga report - extraction summary")

    rep.section("output directories")
    rows = []
    total_files = total_bytes = 0
    for name in ("textures", "textures_big", "audio", "text", "fonts"):
        p = os.path.join(targets["out"], name)
        if os.path.isdir(p):
            n, sz = dir_stats(p)
            total_files += n
            total_bytes += sz
            rows.append((name, n, human_bytes(sz)))
    rep.table(["directory", "files", "size"], rows, aligns="lrr")
    rep.kv("TOTAL", f"{total_files} files / {human_bytes(total_bytes)}")

    img_idx = os.path.join(targets["reports"], "images.csv")
    if os.path.isfile(img_idx):
        per_container: StdCounter = StdCounter()
        per_type: StdCounter = StdCounter()
        biggest: list[tuple[int, int, int, str]] = []
        with open(img_idx, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                per_container[row["container"]] += 1
                per_type[row["type"]] += 1
                try:
                    w, h = int(row["width"]), int(row["height"])
                    biggest.append((w * h, w, h, row["asset_name"]))
                except (ValueError, TypeError):
                    pass
        rep.section("images")
        rep.table(["type", "count"], per_type.most_common(), aligns="lr")
        rep.table(["container", "images"],
                  [(k[:66], v) for k, v in per_container.most_common()], aligns="lr")
        biggest.sort(reverse=True)
        rep.line("  largest assets:")
        rep.table(["size", "asset"], [(f"{w}x{h}", n[:44]) for _px, w, h, n in biggest[:10]],
                  aligns="rl")

    aud_idx = os.path.join(targets["reports"], "audio.csv")
    if os.path.isfile(aud_idx):
        rows = list(csv.DictReader(open(aud_idx, encoding="utf-8")))
        total_len = sum(float(r["length_sec"]) for r in rows if r["length_sec"])
        rep.section("audio")
        rep.kv("clips", len(rows))
        rep.kv("total duration", human_duration(total_len))
        rep.table(["format", "count"], StdCounter(r["format"] for r in rows).most_common(), aligns="lr")
        rep.table(["status", "count"], StdCounter(r["status"] for r in rows).most_common(), aligns="lr")
        longest = sorted(rows, key=lambda r: -float(r["length_sec"] or 0))[:10]
        rep.line("  longest:")
        rep.table(["length", "name"],
                  [(f"{float(r['length_sec']):.1f}s", r["name"][:44]) for r in longest], aligns="rl")

    txt_idx = os.path.join(targets["reports"], "texts.csv")
    if os.path.isfile(txt_idx):
        rows = list(csv.DictReader(open(txt_idx, encoding="utf-8")))
        by_ext: StdCounter = StdCounter()
        by_method: StdCounter = StdCounter()
        for r in rows:
            by_ext[os.path.splitext(r["out_path"])[1].lower()] += 1
            by_method[r["method"]] += 1
        rep.section("text assets")
        rep.kv("count", len(rows))
        rep.table(["extension", "count"], by_ext.most_common(), aligns="lr")
        rep.table(["extraction method", "count"], by_method.most_common(), aligns="lr")
        rep.line("  method=raw means the serialized header was stripped manually;")
        rep.line("  method=decode_fallback means the lossy string field was the only option.")

    if sheets:
        rep.section("contact sheets")
        root = targets["textures"]
        made = 0
        if os.path.isdir(root):
            for tag in sorted(os.listdir(root)):
                sub = os.path.join(root, tag)
                if not os.path.isdir(sub):
                    continue
                files: list[str] = []
                for leaf in ("sprite", "tex"):
                    d = os.path.join(sub, leaf)
                    if os.path.isdir(d):
                        files += sorted_files(d, [".png"])
                if not files:
                    continue
                files.sort(key=lambda p: -os.path.getsize(p))
                dest_dir = sheet_dir or os.path.join(targets["out"], "reports")
                dest = os.path.join(dest_dir, f"overview_{tag}.png")
                n = contact_sheet(files, dest)
                made += 1
                rep.kv(tag[:60], f"{len(files)} images, {n} sampled -> {os.path.basename(dest)}")
        rep.kv("sheets", made)
    return rep


def cmd_report(args: argparse.Namespace) -> int:
    rep = build_report(args.out, args.raw, args.sheets, args.sheet_dir, args.report)
    rep.flush()
    return 0
