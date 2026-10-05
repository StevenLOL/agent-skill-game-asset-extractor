# Changelog

All notable changes to this skill are documented here.

## [1.0.0] - 2026-10-06

### Added
- `ga.py` unified CLI with 11 subcommands: `doctor`, `inventory`, `unpack`, `scan`,
  `probe`, `images`, `audio`, `texts`, `fixups`, `report`, `all`.
- Container identification for UnityFS, FSB5, native audio (Ogg/RIFF/ftyp), ZIP and
  bare SerializedFile, with a size guard so huge bundles are classified before parsing.
- FSB5 bank slicing driven by each `AudioClip`'s `StreamedResource` offset/size, with
  vgmstream conversion and a graceful "raw banks only" mode when no decoder is present.
- Byte-exact `TextAsset` extraction by stripping the serialised header from
  `obj.get_raw_data()`, with the lossy string path kept as an audited fallback.
- `ExportNamer`: object-level idempotence (container + type + path_id) combined with
  collision-safe suffixes, so re-runs neither duplicate nor drop same-named assets.
- `fixups`: oversized-art second pass, placeholder-texture diagnosis, content-based
  extension sniffing, and MD5 dedup that quarantines instead of deleting.
- `report` with contact sheets (labelled grid previews) and a UTF-8 summary.
- Eight reference notes covering the Unity pipeline, FSB5 audio, texture pitfalls,
  Spine/TextAsset handling, legacy DOS format reversing, the competitor matrix,
  tooling/environment and a case index.
- `doctor` for environment self-checks, with download hints for missing tools.

### Fixed during development
- Same-named assets were silently dropped when `--skip-existing` treated an existing
  filename as "already exported".
- Sprite dimensions were read from `m_Width`/`m_Height` instead of `m_Rect`, producing
  tens of thousands of phantom "0x0 placeholder" reports.
- Unnamed textures overwrote one another because the fallback name was constant.
- `probe` selected the smallest container, which is often a localisation bundle with
  nothing to decode.

### Notes
- Published copy is generalised; see `SANITIZATION.md`.
