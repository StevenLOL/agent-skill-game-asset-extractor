# Sanitization notes

The published copy of this skill is a **generalised** build. The working copy kept on
the author's machine cites a specific commercial title because per-title numbers are
what make each lesson verifiable; those citations are removed here so the repository
carries no third-party trademarks or asset statistics.

## What was generalised

| Category | Example in the working copy | Published as |
|----------|---------------------------|--------------|
| package id | a real Android package id | "a commercial mobile package" |
| product / developer | the title and studio names | "a commercial wuxia RPG", "its developer" |
| other case studies | a dozen game and format names | "a DOS action RPG", "an indie Unity title", ... |
| in-game proper nouns | music track and stage names used as examples | "a music track", "an ambient loop" |
| per-title asset counts | "28,574 PNG", "339 WAV", "46.9 minutes" | "tens of thousands of PNG files", "all clips", "under an hour" |
| local paths | absolute Windows workspace paths | "the local workspace", `work/<game>` |

## What was preserved verbatim

- format specifications: FSB5 v1 field offsets, UnityFS header layout, TextAsset
  serialised header layout, Addressables catalog fields
- every failure mode, diagnostic message and the reasoning behind each mitigation
- relative performance ("seconds to classify, minutes and GB to parse")
- the competitor matrix, including third-party tool names and repository URLs, which
  are the public names of the tools being compared

## Why the numbers were kept qualitative

Exact counts are evidence that a technique worked at scale, and the working copy keeps
them. Publishing them would attribute a precise asset inventory to a named commercial
title, which is exactly the kind of claim that draws a takedown request. "Tens of
thousands of images, every clip converted" carries the same engineering signal.

## Reproducing the build

The sanitiser lives in the author's workspace (`scripts/1722_sanitize_for_publish.py`)
together with the pre-flight scanner (`scripts/1721_publish_preflight.py`) that
enforces: no binary/media files, no machine-specific paths, no credentials, no
non-allow-listed URLs, no `__pycache__`. Both run against the source skill **read
only** - the local skill is never modified by publishing.
