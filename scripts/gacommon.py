"""
gacommon.py - shared helpers for the game-asset-extractor CLI.

Design rules baked into this module (each one comes from a measured failure,
see references/ for the evidence):

1. Reports are always written as UTF-8 and flushed immediately.  Windows consoles
   frequently mangle non-ASCII output, so the file is the source of truth, never
   the terminal.
2. Asset names coming out of game containers are frequently empty, duplicated, or
   full of characters that are illegal on the target filesystem.  `safe_name`
   plus `unique_path` keep every artifact addressable instead of silently
   overwriting siblings.
3. Binary payloads are never read through a decoded string field.  TextAsset data
   is stripped from its own serialized block (`textasset_bytes`).
4. Nothing in this module deletes files.  Deduplication *moves* duplicates into a
   quarantine directory, because bulk deletes are frequently blocked by workspace
   safety policies and are also impossible to audit afterwards.
5. UnityPy is loaded from a *path* (never from bytes) so that external
   `.resource` / `.resS` payloads can be resolved relative to the container.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Sequence

# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #

INVALID_CHARS = re.compile(r'[<>:"|?*\x00-\x1f\\/]')
MAX_NAME_LEN = 100


def human_bytes(n: float) -> str:
    """Format a byte count for reports: 1.5 MB / 900 KB / 12 B."""
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < step or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= step
    return f"{n:.2f} GB"


def human_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def natural_key(name: str):
    """Sort key that orders file2 before file10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


# --------------------------------------------------------------------------- #
# names and paths
# --------------------------------------------------------------------------- #

def safe_name(name: str, fallback: str = "noname", max_len: int = MAX_NAME_LEN) -> str:
    """Sanitize an asset name for use as a filename on any OS."""
    if name is None:
        name = ""
    name = str(name).replace("\\", "/").split("/")[-1]
    name = INVALID_CHARS.sub("_", name).strip().strip(".")
    if not name:
        name = fallback
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 12:
            keep = max_len - len(ext) - 1
            name = f"{stem[:keep]}.{ext}"
        else:
            name = name[:max_len]
    # Windows reserved device names (CON, PRN, AUX, NUL, COM1..9, LPT1..9)
    stem = name.split(".")[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)\d", stem):
        name = "_" + name
    return name


def unique_path(directory: str, stem: str, ext: str, skip_existing: bool = False) -> tuple[str, bool]:
    """Return (absolute path, should_write).

    With ``skip_existing`` the first free slot is returned with ``should_write=False``
    when the file already exists, which makes repeated runs idempotent.
    Without it, numeric suffixes are appended until a free slot is found.
    """
    os.makedirs(directory, exist_ok=True)
    ext = ext if ext.startswith(".") or ext == "" else "." + ext
    candidate = os.path.join(directory, stem + ext)
    if not os.path.exists(candidate):
        return candidate, True
    if skip_existing:
        return candidate, False
    i = 1
    while True:
        candidate = os.path.join(directory, f"{stem}_{i:03d}{ext}")
        if not os.path.exists(candidate):
            return candidate, True
        i += 1


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


class ExportNamer:
    """Collision-free AND idempotent output naming.

    Two requirements that conflict if you use a single flag:

    * idempotence - re-running an export must not duplicate work, so an already
      written file is skipped (``--skip-existing``);
    * collision safety - game containers reuse asset names heavily (47 clips named
      ``stand``, 142 named ``atk`` in a reference package), so a name collision
      must NOT silently drop the second asset.

    Measured failure of the naive approach: a first run with ``skip_existing``
    produced 25,538 files where 28,574 were expected - thousands same-named assets were
    dropped because the existing file made the writer skip them.

    Usage::

        namer = ExportNamer(skip_existing=True)
        namer.prime(subdir)                      # snapshot of what is on disk
        path, wrote = namer.path_for(subdir, stem, ".png", key=obj.path_id)
    """

    def __init__(self, skip_existing: bool = False, pre_done: Iterable[Any] = ()):
        self.skip_existing = skip_existing
        # Object identities a PREVIOUS run already exported, read back from the CSV
        # index.  A filename snapshot is not enough: two different objects can share
        # a name, and treating "file exists" as "already exported" dropped thousands
        # assets in a reference run (25,538 files instead of 28,558).
        self._pre_done: set[Any] = set(pre_done)
        self._disk: dict[str, set[str]] = {}            # dir -> stems seen on disk
        self._this_run: set[tuple[str, str]] = set()  # (dir, lowercase stem) written now
        self._done: set[Any] = set()                  # keys handled during this run

    def already_done(self, key: Any) -> bool:
        if key is None:
            return False
        return key in self._done or (self.skip_existing and key in self._pre_done)

    @staticmethod
    def _key(directory: str, stem: str) -> tuple[str, str]:
        return (os.path.normcase(os.path.abspath(directory)), stem.lower())

    def prime(self, directory: str) -> set[str]:
        """Stems currently on disk (used for collision hints and keyless fallback)."""
        directory = os.path.abspath(directory)
        if directory in self._disk:
            return self._disk[directory]
        stems: set[str] = set()
        if os.path.isdir(directory):
            for fn in os.listdir(directory):
                stem, _ext = os.path.splitext(fn)
                stems.add(stem.lower())
        self._disk[directory] = stems
        return stems

    def path_for(self, directory: str, stem: str, ext: str, key: Any = None) -> tuple[str, bool]:
        """Return (path, should_write)."""
        os.makedirs(directory, exist_ok=True)
        if self.already_done(key):
            return os.path.join(directory, stem + ext), False
        preexisting = self.prime(directory)
        k = self._key(directory, stem)
        if self.skip_existing and k not in self._this_run and stem.lower() in preexisting \
                and key is None:
            # No object identity available and the name is taken: fall back to skipping
            # rather than overwriting.  When a key IS supplied the decision is made by
            # already_done() alone, because a same-named sibling is a different asset.
            return os.path.join(directory, stem + ext), False
        path, write = unique_path(directory, stem, ext, skip_existing=False)
        if write:
            self._this_run.add(k)
            preexisting.add(stem.lower())
            if key is not None:
                self._done.add(key)
        return path, write

    def stats(self) -> dict[str, int]:
        return {"idempotent_skips": len(self._done),
                "names_written": len(self._this_run)}


def file_md5(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def quarantine_move(path: str, quarantine_dir: str) -> str:
    """Move a duplicate aside instead of deleting it.  Returns the new path."""
    ensure_dir(quarantine_dir)
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    target = os.path.join(quarantine_dir, base)
    i = 1
    while os.path.exists(target):
        target = os.path.join(quarantine_dir, f"{stem}__dup{i:03d}{ext}")
        i += 1
    shutil.move(path, target)
    return target


def dir_stats(root: str) -> tuple[int, int]:
    """(file count, total bytes) under root, tolerant of unreadable files."""
    count = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            count += 1
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return count, total


# --------------------------------------------------------------------------- #
# progress + logging
# --------------------------------------------------------------------------- #

class Progress:
    """Throttled progress printer (stderr keeps stdout clean for piping)."""

    def __init__(self, total: int | None, label: str = "", every: int = 500, stream=None):
        self.total = total
        self.label = label
        self.every = max(1, every)
        self.stream = stream or sys.stderr
        self.n = 0
        self.t0 = time.time()

    def tick(self, n: int = 1) -> None:
        self.n += n
        if self.n % self.every == 0:
            self._emit()

    def _emit(self, force: bool = False) -> None:
        if self.total:
            pct = 100.0 * self.n / self.total
            msg = f"[{self.label}] {self.n}/{self.total} ({pct:.1f}%) {human_duration(time.time() - self.t0)}"
        else:
            msg = f"[{self.label}] {self.n} {human_duration(time.time() - self.t0)}"
        if force or self.n % self.every == 0:
            print(msg, file=self.stream, flush=True)

    def close(self) -> None:
        self._emit(force=True)


class Report:
    """Accumulates lines, writes them as UTF-8, echoes short notes to console."""

    def __init__(self, path: str | None, title: str = "", compliance: bool = True):
        self.path = path
        self.lines: list[str] = []
        self.console_limit = 60
        if title:
            self.line("=" * 78)
            self.line(title)
            self.line("=" * 78)
        if compliance:
            self.line("Compliance: extracted assets remain the property of their original "
                      "rightsholders. Research/study/interoperability use only; no redistribution "
                      "or commercial use without authorization.")

    def line(self, text: str = "") -> None:
        self.lines.append(text)

    def section(self, text: str) -> None:
        self.line()
        self.line("-" * 78)
        self.line(text)
        self.line("-" * 78)

    def kv(self, key: str, value: Any, width: int = 34) -> None:
        self.line(f"  {key:<{width}} {value}")

    def table(self, headers: Sequence[str], rows: Iterable[Sequence[Any]],
              aligns: str | None = None) -> None:
        rows = [list(map(str, r)) for r in rows]
        if not rows:
            self.line("  (none)")
            return
        cols = len(headers)
        if aligns is None:
            aligns = "l" * cols
        widths = [len(str(h)) for h in headers]
        for r in rows:
            for i in range(cols):
                widths[i] = max(widths[i], len(r[i]) if i < len(r) else 0)
        self.line("  " + "  ".join(f"{str(headers[i]):<{widths[i]}}" for i in range(cols)))
        self.line("  " + "  ".join("-" * widths[i] for i in range(cols)))
        for r in rows:
            self.line("  " + "  ".join(
                f"{r[i]:<{widths[i]}}" if aligns[i] == "l" else f"{r[i]:>{widths[i]}}"
                for i in range(cols)))

    def flush(self, echo: bool = True) -> None:
        text = "\n".join(self.lines)
        if self.path:
            ensure_dir(os.path.dirname(os.path.abspath(self.path)))
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(text)
        if echo:
            head = self.lines[: self.console_limit]
            for l in head:
                print(l)
            if len(self.lines) > self.console_limit:
                print(f"... ({len(self.lines) - self.console_limit} more lines written to {self.path})")
        if self.path:
            print(f"\nreport -> {self.path}")


class IndexWriter:
    """CSV index of exported assets, so results stay machine-queryable."""

    def __init__(self, path: str, headers: Sequence[str]):
        ensure_dir(os.path.dirname(os.path.abspath(path)))
        self.path = path
        self._f = open(path, "w", encoding="utf-8", newline="")
        self._w = csv.writer(self._f)
        self._w.writerow(list(headers))
        self.rows = 0

    def write(self, *values: Any) -> None:
        self._w.writerow(list(values))
        self.rows += 1

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> "IndexWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def run_tool(args: Sequence[str], timeout: int = 180) -> tuple[int, str]:
    """Run an external tool, returning (returncode, combined output tail)."""
    try:
        p = subprocess.run(list(args), capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return 127, f"tool not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(args)}"
    out = (p.stdout or b"").decode("utf-8", "ignore") + (p.stderr or b"").decode("utf-8", "ignore")
    return p.returncode, out.strip()


# --------------------------------------------------------------------------- #
# Unity container inspection
# --------------------------------------------------------------------------- #

UNITYFS_MAGIC = b"UnityFS\x00"
SERIALIZED_PREFIX_SIZE = 16

# Object types treated as images.  Sprite is a rect crop of a Texture2D, so both are
# exported (into separate folders) because consumers want either the atlas page or
# the individual cut.
IMAGE_TYPES = ("Texture2D", "Sprite")


def detect_container(path: str) -> tuple[str, str]:
    """Classify a file by its header.

    Returns (kind, detail) where kind is one of:
      ``unityfs``      - Unity AssetBundle (UnityFS)
      ``serialized``   - bare SerializedFile (no UnityFS wrapper)
      ``fsb5``         - FMOD sound bank
      ``audio-native`` - OggS / RIFF / ftyp
      ``zip``          - APK / zip / ipa
      ``unknown``      - anything else
    """
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError as e:
        return "unreadable", str(e)
    if not head:
        return "unknown", "empty file"
    if head.startswith(UNITYFS_MAGIC):
        version = int.from_bytes(head[8:12], "big")
        unity = head[12:].split(b"\x00")[0].decode("ascii", "ignore")
        return "unityfs", f"format_version={version} unity={unity or 'unknown'}"
    if head[:6] in (b"OggS\x00\x00",) or head[:4] == b"OggS":
        return "audio-native", "ogg"
    if head[:4] == b"RIFF":
        return "audio-native", "wav"
    if head[4:8] == b"ftyp":
        return "audio-native", "mp4/m4a"
    if head[:4] == b"FSB5":
        return "fsb5", "fmod sound bank"
    if head[:2] == b"PK":
        return "zip", "apk/zip container"
    if head[:4] == b"\x00\x00\x00\x00" and len(head) >= 12:
        # bare SerializedFile: metadata_size(u32) file_size(u32) version(u32) ...
        meta, size, ver = struct.unpack_from("<III", head, 0)
        if 0 < size and 9 <= ver <= 30 and meta < size:
            return "serialized", f"version={ver} file_size={size}"
    return "unknown", head[:16].hex(" ")


def find_fsb5_segments(path: str) -> list[tuple[int, int]]:
    """Locate every standalone FSB5 container inside a file.

    Unity stores streamed audio as a concatenation of independent FSB5 banks, not
    as one bank.  Scanning the magic is the only reliable way to enumerate them
    without trusting header offsets.  Returns a list of (offset, size).
    """
    segments: list[tuple[int, int]] = []
    with open(path, "rb") as f:
        blob = f.read()
    total = len(blob)
    pos = 0
    while True:
        idx = blob.find(b"FSB5", pos)
        if idx < 0:
            break
        size = _fsb5_declared_size(blob, idx)
        if size is None or size <= 0 or idx + size > total:
            size = (blob.find(b"FSB5", idx + 4) - idx) if blob.find(b"FSB5", idx + 4) > 0 else total - idx
        segments.append((idx, size))
        pos = idx + 4
    return segments


def _fsb5_declared_size(blob: bytes, off: int) -> int | None:
    """Read total container length from an FSB5 v1 header, if it is self-consistent."""
    if off + 0x40 > len(blob):
        return None
    try:
        version = struct.unpack_from("<I", blob, off + 0x04)[0]
        num_samples = struct.unpack_from("<I", blob, off + 0x08)[0]
        header_size = struct.unpack_from("<I", blob, off + 0x0C)[0]
        name_size = struct.unpack_from("<I", blob, off + 0x10)[0]
        data_size = struct.unpack_from("<I", blob, off + 0x14)[0]
    except struct.error:
        return None
    if version != 1 or num_samples == 0 or num_samples > 64:
        return None
    if not (0 < header_size <= 0x400 and name_size <= 0x10000 and data_size <= 0x8000000):
        return None
    # v1 layout: 0x3C bytes of bank header, then sample headers, then payload.
    total = 0x3C + header_size + name_size + data_size
    return total if total > 0x40 else None


# --------------------------------------------------------------------------- #
# UnityPy object access (version tolerant)
# --------------------------------------------------------------------------- #

def unitypy_version() -> tuple[int, ...]:
    try:
        import UnityPy
    except Exception:
        return ()
    parts = []
    for p in str(getattr(UnityPy, "__version__", "0")).split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts[:3])


def read_object(obj: Any) -> Any:
    """Read an object across UnityPy API generations.

    1.25+ prefers ``parse_as_object()``; ``read()`` is legacy and slated for removal
    in 2.0, so fall back only when the modern name is missing.
    """
    for attr in ("parse_as_object", "read"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except TypeError:
                continue
    raise RuntimeError("object exposes neither parse_as_object() nor read()")


def object_type_name(obj: Any) -> str:
    try:
        return obj.type.name
    except Exception:
        return str(getattr(obj, "type", "?"))


def iter_objects(env: Any, progress_label: str = "") -> Iterator[Any]:
    """Iterate objects once.  ``env.objects`` is a property that rebuilds a list on
    every access, which is measurably slow for 10k+ object bundles, and a single
    SerializedFile shares one cursor, so this must stay single-threaded."""
    objs = env.objects
    if progress_label:
        print(f"[scan] {progress_label}: {len(objs)} objects", file=sys.stderr, flush=True)
    for obj in objs:
        yield obj


def textasset_bytes(obj: Any, data: Any) -> tuple[bytes, str]:
    """Extract the raw payload of a TextAsset.

    ``m_Script`` is a *string* field: UnityPy decodes it with a lossy codec, so
    binary payloads (Spine .skel, encrypted blobs) come out truncated - measured
    43,082 chars for a 43,554 byte asset.  The reliable route is to strip the
    serialized header off ``obj.get_raw_data()``:

        [u32 name length][name bytes][pad to 4][u32 payload length][payload]

    Returns (payload, method) where method is ``raw`` or ``decode_fallback``.
    """
    try:
        raw = obj.get_raw_data()
        if raw and len(raw) >= 8:
            name_len = struct.unpack_from("<I", raw, 0)[0]
            if 0 < name_len <= 0x1000:
                pos = 4 + name_len
                pos = (pos + 3) & ~3
                data_len = struct.unpack_from("<I", raw, pos)[0]
                pos += 4
                if 0 < data_len <= len(raw) - pos:
                    return raw[pos:pos + data_len], "raw"
    except Exception:
        pass
    # Fallback: lossy but better than nothing (documented in references).
    script = getattr(data, "m_Script", "")
    if isinstance(script, str):
        return script.encode("utf-8", "surrogateescape"), "decode_fallback"
    if isinstance(script, (bytes, bytearray)):
        return bytes(script), "decode_fallback"
    return b"", "empty"


# --------------------------------------------------------------------------- #
# content sniffing (extension names in game containers are frequently lies)
# --------------------------------------------------------------------------- #

def sniff_text_type(path: str) -> str | None:
    """Return a corrected extension based on file content, or None to keep it."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return None
    if not head.strip():
        return None
    # Spine binary skeletons start with a stringified hash then a version tag such as
    # "\x1c<hash>\x073.8.99" - that leading 0x1C is a reliable marker.
    if head[0] == 0x1C and b"spine" in head[:128].lower():
        return ".skel"
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return None
    s = text.lstrip()
    if s[:1] in ("{", "["):
        return ".json"
    if "format:" in text and ("size:" in text or "repeat:" in text):
        return ".atlas"
    return None


# --------------------------------------------------------------------------- #
# candidate discovery
# --------------------------------------------------------------------------- #

def find_unity_containers(raw_dir: str) -> list[str]:
    """All Unity payloads under raw_dir, main data dir first, bundles after."""
    found: list[str] = []
    data_dir = os.path.join(raw_dir, "assets", "bin", "Data")
    for name in ("data.unity3d", "datapack.unity3d", "globalgamemanagers",
                 "level0", "sharedassets0.assets", "unity default resources"):
        p = os.path.join(data_dir, name)
        if os.path.isfile(p):
            found.append(p)
    for base in (os.path.join(raw_dir, "assets", "aa"), raw_dir):
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                low = fn.lower()
                if low.endswith((".bundle", ".unity3d", ".assets", ".resource", ".resS".lower())):
                    found.append(os.path.join(dirpath, fn))
    # de-dup, keep order
    seen = set()
    out = []
    for p in found:
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def find_resource_payloads(raw_dir: str) -> list[str]:
    """External payload files (audio/text blobs) referenced by streamed objects."""
    out = []
    for dirpath, _dirs, files in os.walk(raw_dir):
        for fn in files:
            low = fn.lower()
            if low.endswith((".resource", ".ress", ".resS".lower())) or low == "resources.resource":
                out.append(os.path.join(dirpath, fn))
    return out


def collect_targets(raw_dir: str, out_dir: str) -> dict:
    """Resolve the standard working layout for a run."""
    return {
        "raw": os.path.abspath(raw_dir),
        "out": os.path.abspath(out_dir),
        "textures": ensure_dir(os.path.join(out_dir, "textures")),
        "textures_big": ensure_dir(os.path.join(out_dir, "textures_big")),
        "audio": ensure_dir(os.path.join(out_dir, "audio")),
        "wav": ensure_dir(os.path.join(out_dir, "audio", "wav")),
        "fsb": ensure_dir(os.path.join(out_dir, "audio", "fsb")),
        "text": ensure_dir(os.path.join(out_dir, "text")),
        "fonts": ensure_dir(os.path.join(out_dir, "fonts")),
        "reports": ensure_dir(os.path.join(out_dir, "reports")),
        "quarantine": ensure_dir(os.path.join(out_dir, "_quarantine")),
    }


def default_report_path(out_dir: str, name: str) -> str:
    return os.path.join(out_dir, "reports", name)


@dataclass
class Counter:
    """Ordered counter with a stable string form for reports."""
    data: dict[str, int] = field(default_factory=dict)

    def add(self, key: str, n: int = 1) -> None:
        self.data[key] = self.data.get(key, 0) + n

    def merge(self, other: "Counter | dict[str, int]") -> None:
        src = other.data if isinstance(other, Counter) else other
        for k, v in src.items():
            self.add(k, v)

    def most_common(self, n: int | None = None) -> list[tuple[str, int]]:
        items = sorted(self.data.items(), key=lambda kv: -kv[1])
        return items if n is None else items[:n]

    def total(self) -> int:
        return sum(self.data.values())

    def __getitem__(self, key: str) -> int:
        return self.data.get(key, 0)

    def __bool__(self) -> bool:
        return bool(self.data)

    def __str__(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.most_common(12))


def sorted_files(directory: str, exts: Sequence[str] | None = None) -> list[str]:
    if not os.path.isdir(directory):
        return []
    names = [f for f in os.listdir(directory)
             if exts is None or os.path.splitext(f)[1].lower() in tuple(e.lower() for e in exts)]
    return [os.path.join(directory, n) for n in sorted(names, key=natural_key)]
