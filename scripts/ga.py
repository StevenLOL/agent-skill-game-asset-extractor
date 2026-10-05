#!/usr/bin/env python3
"""
ga.py - unified CLI for game asset extraction (recon + orchestration).

One entry point, no hard-coded paths: everything comes from --apk / --raw / --out
or is auto-discovered.  Stages live in garecon.py (doctor/inventory/unpack/scan/
probe), gaexport.py (images/audio/texts/fixups/report) and gacommon.py (helpers).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gacommon as gc          # noqa: E402
import garecon                 # noqa: E402
import gaexport                # noqa: E402
from gacommon import human_duration  # noqa: E402

DEFAULT_SCAN_MB = garecon.DEFAULT_SCAN_MB
DEFAULT_MAX_SIDE = 4096

def cmd_all(args: argparse.Namespace) -> int:
    """Run the full chain in dependency order.

    Ordering matters: scan classifies containers before any export decides what to
    open, and report runs last because it reads the CSV indexes the export stages
    produce.
    """
    reports = gc.ensure_dir(os.path.join(args.out, "reports"))
    raw = os.path.join(args.out, "raw")
    plan = [
        ("inventory", garecon.cmd_inventory,
         {"apk": args.apk, "report": os.path.join(reports, "inventory.txt")}),
        ("unpack", garecon.cmd_unpack,
         {"apk": args.apk, "out": raw, "prefix": None}),
        ("scan", garecon.cmd_scan,
         {"raw": raw, "all": args.all, "max_scan_mb": args.max_scan_mb,
          "report": os.path.join(reports, "scan.txt")}),
        ("probe", garecon.cmd_probe,
         {"raw": raw, "out": args.out, "report": os.path.join(reports, "probe.txt")}),
        ("images", gaexport.cmd_images,
         {"raw": raw, "out": args.out, "max_side": args.max_side,
          "skip_existing": args.skip_existing, "index": ""}),
        ("audio", gaexport.cmd_audio,
         {"raw": raw, "out": args.out, "vgmstream": args.vgmstream,
          "skip_existing": args.skip_existing, "timeout": 120, "index": ""}),
        ("texts", gaexport.cmd_texts,
         {"raw": raw, "out": args.out, "skip_existing": args.skip_existing, "index": ""}),
        ("fixups", gaexport.cmd_fixups,
         {"raw": raw, "out": args.out, "max_side": args.max_side, "big": True,
          "dedup": True, "apply": True, "skip_existing": args.skip_existing,
          "report": os.path.join(reports, "fixups.txt")}),
        ("report", gaexport.cmd_report,
         {"raw": raw, "out": args.out, "sheets": args.sheets, "sheet_dir": "",
          "report": os.path.join(reports, "summary.txt")}),
    ]
    t0 = time.time()
    failures = []
    for name, fn, kwargs in plan:
        print(f"\n=== ga {name} ===", flush=True)
        try:
            code = fn(argparse.Namespace(**kwargs))
        except Exception as e:
            code = 1
            print(f"  step {name} crashed: {type(e).__name__}: {e}", file=sys.stderr)
        if code != 0:
            failures.append(name)
    print(f"\n=== chain finished in {human_duration(time.time() - t0)} ===")
    if failures:
        print("steps with non-zero exit: " + ", ".join(failures), file=sys.stderr)
    print(f"reports: {reports}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ga.py",
        description="Extract game assets from packages and archives; reverse legacy formats.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("typical run:\n"
                "  ga.py all --apk game.apk --out work/game --vgmstream <cli>\n"
                "  ga.py images --raw work/game/raw --out work/game/out --skip-existing\n"))
    p.add_argument("--version", action="version", version="ga.py 1.0 (game-asset-extractor)")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, help_):
        return sub.add_parser(name, help=help_, description=help_)

    d = add("doctor", "environment self-check")
    d.add_argument("--report", default="doctor.txt")
    d.add_argument("--vgmstream", default="")
    d.set_defaults(func=garecon.cmd_doctor)

    i = add("inventory", "read-only size census of an APK/zip")
    i.add_argument("--apk", required=True)
    i.add_argument("--report", default="inventory.txt")
    i.set_defaults(func=garecon.cmd_inventory)

    u = add("unpack", "extract selected prefixes from an archive")
    u.add_argument("--apk", required=True)
    u.add_argument("--out", required=True, help="raw tree, e.g. work/game/raw")
    u.add_argument("--prefix", nargs="*", default=None, help="default: assets/ res/")
    u.set_defaults(func=garecon.cmd_unpack)

    s = add("scan", "classify containers and census object types")
    s.add_argument("--raw", required=True)
    s.add_argument("--all", action="store_true", help="also load containers above --max-scan-mb")
    s.add_argument("--max-scan-mb", type=float, default=DEFAULT_SCAN_MB)
    s.add_argument("--report", default="scan.txt")
    s.set_defaults(func=garecon.cmd_scan)

    pr = add("probe", "small-sample feasibility test")
    pr.add_argument("--raw", required=True)
    pr.add_argument("--out", required=True)
    pr.add_argument("--report", default="")
    pr.set_defaults(func=garecon.cmd_probe)

    im = add("images", "export Texture2D/Sprite to PNG")
    im.add_argument("--raw", required=True)
    im.add_argument("--out", required=True)
    im.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE)
    im.add_argument("--skip-existing", action="store_true")
    im.add_argument("--index", default="")
    im.set_defaults(func=gaexport.cmd_images)

    a = add("audio", "export AudioClip (FSB5 -> WAV via vgmstream)")
    a.add_argument("--raw", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--vgmstream", default="", help="path to vgmstream-cli")
    a.add_argument("--skip-existing", action="store_true")
    a.add_argument("--timeout", type=int, default=120)
    a.add_argument("--index", default="")
    a.set_defaults(func=gaexport.cmd_audio)

    t = add("texts", "export TextAsset (raw-byte safe) and Font")
    t.add_argument("--raw", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--skip-existing", action="store_true")
    t.add_argument("--index", default="")
    t.set_defaults(func=gaexport.cmd_texts)

    f = add("fixups", "oversized art, placeholder diagnosis, extension sniffing, dedup")
    f.add_argument("--raw", default="")
    f.add_argument("--out", required=True)
    f.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE)
    f.add_argument("--big", action="store_true")
    f.add_argument("--dedup", action="store_true",
                   help="move duplicates to _quarantine (never delete)")
    f.add_argument("--apply", action="store_true", help="perform renames (default: dry run)")
    f.add_argument("--skip-existing", action="store_true")
    f.add_argument("--report", default="")
    f.set_defaults(func=gaexport.cmd_fixups)

    r = add("report", "aggregate indexes into a summary and contact sheets")
    r.add_argument("--raw", default="")
    r.add_argument("--out", required=True)
    r.add_argument("--sheets", action="store_true")
    r.add_argument("--sheet-dir", default="")
    r.add_argument("--report", default="")
    r.set_defaults(func=gaexport.cmd_report)

    al = add("all", "run the whole chain")
    al.add_argument("--apk", required=True)
    al.add_argument("--out", required=True, help="work dir, e.g. work/game")
    al.add_argument("--vgmstream", default="", help="path to vgmstream-cli")
    al.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE)
    al.add_argument("--max-scan-mb", type=float, default=DEFAULT_SCAN_MB)
    al.add_argument("--skip-existing", action="store_true")
    al.add_argument("--sheets", action="store_true", help="generate contact sheets at the end")
    al.add_argument("--all", action="store_true", help="scan large containers too (slow, memory heavy)")
    al.set_defaults(func=cmd_all)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

