![wgi-video-sync](logo.svg)

# wgi-video-sync

Two-stage pipeline for cutting WGI competition recordings into per-band clips with title cards.

**Stage 1 — `analyze`**: scans a video directory, detects scene changes, and writes `config.json` with auto-detected start/end timestamps for each band.  
**Stage 2 — `process`**: reads `config.json`, cuts each segment, generates a title card, and concatenates them into finished output files.

## Prerequisites

- Docker or Podman
- `make`

The container bundles ffmpeg and ffprobe — no local install needed.

## Workflow

```sh
# 1. Build the image (once)
make build

# 2. Analyze videos — writes config.json
make analyze VIDEO_DIR=/path/to/videos

# 3. Edit config.json — fix names, timestamps, remove _review flags

# 4. Preview what will be cut (no video written)
make dry-run VIDEO_DIR=/path/to/videos

# 5. Process — cuts segments and renders title cards
make process VIDEO_DIR=/path/to/videos
```

## Targets

| Target | Description |
|--------|-------------|
| `build` | Build the container image |
| `analyze` | Scan videos and write `config.json` |
| `process` | Cut segments and render title cards |
| `dry-run` | Show plan without touching video |
| `shell` | Interactive shell inside the container |
| `deploy` | Rsync scripts to `little-willow` and rebuild |
| `clean` | Remove `output/` directory |
| `clean-all` | Remove `output/` and `config.json` |

`VIDEO_DIR` is required for all targets except `build` and `deploy`.

## Optional variables

| Variable | Default | Description |
|----------|---------|-------------|
| `THRESHOLD` | `0.35` | Scene detection sensitivity (lower = more cuts) |
| `MIN_GAP` | `90` | Minimum quiet seconds between performances |
| `ONLY` | — | Process only bands whose name contains this string |
| `REMOTE` | `little-willow` | Deploy target host |
| `REMOTE_DIR` | `~/wgi-video-sync` | Deploy path on remote |
| `RUNTIME` | auto | `podman` or `docker` (detected automatically) |

## config.json

`analyze` writes a draft. Edit it before running `process`.

```json
{
  "input_dir": "/videos",
  "output_dir": "/videos/output",
  "event": "WGI World Championships, Dayton, OH",
  "title_duration_seconds": 4,
  "title_font_size": 72,
  "title_font_color": "white",
  "title_background_color": "black",
  "fade_duration_seconds": 1.0,
  "bands": [
    {
      "name": "Band Name",
      "location": "City, ST",
      "date": "April 18, 2026",
      "source_file": "01_filename.mp4",
      "start": "00:00:27.000",
      "end": "00:06:35.211",
      "output": "band_name.mp4"
    }
  ]
}
```

### Multi-segment entries

For bands whose performance spans multiple source files:

```json
{
  "name": "Jordan HS",
  "segments": [
    { "source_file": "02_file.mp4", "start": "00:35:30.000", "end": "00:39:10.404" },
    { "source_file": "03_file.mp4", "start": "00:00:00.000", "end": "00:04:00.000" }
  ],
  "output": "jordan_hs.mp4"
}
```

### Video file naming

`analyze` parses double-underscore (`__`) as the band separator and requires a numeric prefix:

```
01_band_name_WGI.mp4           → one band
02_band_a__band_b_WGI.mp4     → two bands; suggests a split point
```

Files without a numeric prefix are skipped — add them manually to `config.json` if needed.

## Broken timestamp sources

FloMarching and similar live-capture sources sometimes have broken PTS or frame-rate metadata. `process` detects this automatically and re-encodes to a clean CFR file before seeking, so segments land at correct timestamps.

## Config.json ownership

`analyze` writes `config.json` into `VIDEO_DIR` (the container's `/videos` working dir). That file is a starting draft — edit it freely. The **project-dir copy** (`./config.json`) is what `process` actually uses: the Makefile mounts it read-only into the container at `/config.json`, independent of whatever is in `VIDEO_DIR`.

Typical lifecycle:
1. `make analyze` drops a draft into `VIDEO_DIR/config.json`
2. Copy and refine it as `./config.json` in this project dir (add `location`, `date`, `event`, fix timestamps, build multi-segment entries)
3. `make process` reads `./config.json`; the copy in `VIDEO_DIR` is no longer used

Keep the project-dir `config.json` as the source of truth. The one in `VIDEO_DIR` is just the raw analyze output.

### 2026 WGI Dayton run

Source videos: `/Volumes/data/media/3.6T/data/dc_pics/paradigm_percussion_2026/2026-04-16_thru_19_WGI_dayton_ohio_paradigm_percussion/`  
Output: `…/output/` (26 numbered clips, `01_central_lafourche_hs.mp4` through `26_perc_world_champion_awards.mp4`)

```sh
make build
make analyze VIDEO_DIR=/Volumes/data/media/3.6T/data/dc_pics/paradigm_percussion_2026/2026-04-16_thru_19_WGI_dayton_ohio_paradigm_percussion
# refined config saved as ./config.json in this project dir
make process VIDEO_DIR=/Volumes/data/media/3.6T/data/dc_pics/paradigm_percussion_2026/2026-04-16_thru_19_WGI_dayton_ohio_paradigm_percussion
```

The `config.json` in the source video dir is the older analyze draft (simpler names, different timestamps). The authoritative cut config is `./config.json` in this repo.

`./config.json` aligns exactly with the 26 files in `output/` — same order, same count, same slugified names. Running `make process` with this config reproduces all 26 clips identically.

### Output files

| # | File | Band | Location |
|---|------|------|----------|
| 01 | `01_central_lafourche_hs.mp4` | Central Lafourche HS | Raceland, LA |
| 02 | `02_franklin_community_hs.mp4` | Franklin Community HS | Franklin, IN |
| 03 | `03_greenfield_central_hs.mp4` | Greenfield-Central HS | Greenfield, IN |
| 04 | `04_auburn_hs.mp4` | Auburn HS | Auburn, AL |
| 05 | `05_jordan_hs.mp4` | Jordan HS | Fulshear, TX |
| 06 | `06_beavercreek_hs.mp4` | Beavercreek HS | Beavercreek, OH |
| 07 | `07_pace_hs.mp4` | Pace HS | Pace, FL |
| 08 | `08_victor_j_andrew_hs.mp4` | Victor J Andrew HS | Tinley Park, IL |
| 09 | `09_sonia_sotomayor_hs.mp4` | Sonia Sotomayor HS | San Antonio, TX |
| 10 | `10_sparkman_hs.mp4` | Sparkman HS | Harvest, AL |
| 11 | `11_buckhorn_percussion.mp4` | Buckhorn Percussion | New Market, AL |
| 12 | `12_paradigm_percussion.mp4` | Paradigm Percussion | Iron Station, NC |
| 13 | `13_infinity_2.mp4` | Infinity 2 | Orlando, FL |
| 14 | `14_redline.mp4` | Redline | Plymouth, MI |
| 15 | `15_cap_city.mp4` | Cap City | Columbus, OH |
| 16 | `16_matrix.mp4` | Matrix | Akron, OH |
| 17 | `17_rhythmic_force_percussion.mp4` | Rhythmic Force Percussion | Austin, TX |
| 18 | `18_george_mason_university.mp4` | George Mason University | Fairfax, VA |
| 19 | `19_infinity.mp4` | Infinity | Orlando, FL |
| 20 | `20_music_city_mystique.mp4` | Music City Mystique | Nashville, TN |
| 21 | `21_broken_city.mp4` | Broken City | Lake Elsinore, CA |
| 22 | `22_pulse_percussion.mp4` | Pulse Percussion | Ontario, CA |
| 23 | `23_rcc.mp4` | RCC | Riverside, CA |
| 24 | `24_rhythm_x.mp4` | Rhythm X | Indianapolis, IN |
| 25 | `25_atlanta_quest.mp4` | Atlanta Quest | Atlanta, GA |
| 26 | `26_perc_world_champion_awards.mp4` | Perc World Champion Awards | — |

Event: WGI World Championships, Dayton, OH — April 18, 2026

## Tips

- Export `VIDEO_DIR` to avoid repeating it: `export VIDEO_DIR=/path/to/videos`
- Use `ONLY=buckhorn` (or `--only "buckhorn"`) to reprocess a single band
- `_review` flags are surfaced as warnings during `process` — remove them once timestamps are confirmed
- `pdfplumber` is optional: if installed (`pip install pdfplumber`), `analyze` extracts any schedule PDFs found alongside the videos
