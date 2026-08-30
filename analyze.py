#!/usr/bin/env python3
"""
Stage 1: Scan video directory and emit config.json for review.

Usage:
  python analyze.py /path/to/videos
  python analyze.py /path/to/videos -o my_config.json
  python analyze.py /path/to/videos --threshold 0.3   # more sensitive

Requires: ffmpeg, ffprobe
Optional: pip install pdfplumber  (extracts schedule PDFs to text)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

# Lower = more scene changes detected; raise if too many spurious cuts appear
SCENE_THRESHOLD = 0.35
# Quiet stretches longer than this (seconds) are treated as between-performance gaps
MIN_GAP = 90

# ANSI colors -- disabled when not writing to a terminal or NO_COLOR is set
_use_color = sys.stdout.isatty() and os.environ.get('NO_COLOR') is None

class C:
    RESET  = '\033[0m'  if _use_color else ''
    BOLD   = '\033[1m'  if _use_color else ''
    DIM    = '\033[2m'  if _use_color else ''
    RED    = '\033[31m' if _use_color else ''
    GREEN  = '\033[32m' if _use_color else ''
    YELLOW = '\033[33m' if _use_color else ''
    CYAN   = '\033[36m' if _use_color else ''


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def get_video_info(path):
    r = run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', str(path)])
    try:
        d = json.loads(r.stdout)
        dur = float(d['format'].get('duration', 0))
        vs = next(s for s in d.get('streams', []) if s['codec_type'] == 'video')
        return {
            'duration': dur,
            'width': vs.get('width', 1920),
            'height': vs.get('height', 1080),
            'fps': vs.get('r_frame_rate', '30/1'),
        }
    except Exception:
        return {'duration': 0.0, 'width': 1920, 'height': 1080, 'fps': '30/1'}


def detect_scenes(path, threshold):
    """Return list of float timestamps (seconds) where scene changes occur."""
    r = run([
        'ffmpeg', '-i', str(path),
        '-vf', f'select=gt(scene\\,{threshold}),showinfo',
        '-vsync', 'vfr', '-an', '-f', 'null', '-',
    ])
    timestamps = []
    for line in r.stderr.splitlines():
        if 'Parsed_showinfo' in line:
            m = re.search(r'pts_time:(\d+\.?\d*)', line)
            if m:
                timestamps.append(float(m.group(1)))
    return timestamps


def find_cuts(timestamps, duration, n_bands, min_gap=MIN_GAP):
    """Find n_bands-1 performance boundary timestamps via gap analysis."""
    n_cuts = n_bands - 1
    if n_cuts <= 0:
        return []

    if not timestamps:
        seg = duration / n_bands
        return [seg * i for i in range(1, n_bands)]

    ts = [0.0] + sorted(timestamps) + [duration]
    gaps = []
    for i in range(len(ts) - 1):
        gap = ts[i + 1] - ts[i]
        if gap >= min_gap:
            gaps.append((gap, (ts[i] + ts[i + 1]) / 2))

    gaps.sort(key=lambda x: -x[0])
    cuts = sorted(g[1] for g in gaps[:n_cuts])

    while len(cuts) < n_cuts:
        seg = duration / n_bands
        cuts.append(seg * (len(cuts) + 1))
        cuts.sort()

    return cuts


def fmt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f'{h:02d}:{m:02d}:{s:06.3f}'


def slugify(name):
    name = name.lower()
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s-]+', '_', name)
    return name.strip('_')


def parse_names(stem):
    """'02_franklin__greenfield-central__auburn__jordan_hs_WGI' -> display names."""
    stem = re.sub(r'^\d+_', '', stem)
    stem = re.sub(r'_WGI$', '', stem, flags=re.IGNORECASE)
    parts = stem.split('__')
    names = []
    for part in parts:
        name = part.replace('-', ' ').replace('_', ' ').strip()
        name = ' '.join(w.capitalize() for w in name.split())
        names.append(name)
    return names


def parse_schedule(text_files):
    """Parse extracted PDF text for event name, dates, and band/location hints.

    Returns dict with 'event', 'date', and 'bands' list (each: name, location, date).
    The caller uses this to pre-fill config fields where the video filename has no metadata.
    """
    hints = {'event': '', 'date': '', 'bands': []}
    date_pat = re.compile(
        r'(?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+\d{1,2},?\s+\d{4}',
        re.IGNORECASE,
    )
    # Schedule rows look like:  "2:30 PM   Band Name   City, ST"
    # (two or more spaces separate the three fields)
    row_pat = re.compile(
        r'^\d{1,2}:\d{2}\s*[AP]M\s{2,}(.+?)\s{2,}([A-Za-z ]+,\s*[A-Z]{2})\s*$'
    )
    for txt_path in text_files:
        try:
            text = txt_path.read_text(encoding='utf-8')
        except Exception:
            continue
        current_date = ''
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if not hints['event'] and 'wgi' in line.lower() and len(line) < 120:
                hints['event'] = line
            m = date_pat.search(line)
            if m:
                current_date = m.group(0).strip()
                if not hints['date']:
                    hints['date'] = current_date
            m = row_pat.match(line)
            if m:
                hints['bands'].append({
                    'name': m.group(1).strip(),
                    'location': m.group(2).strip(),
                    'date': current_date,
                })
    return hints


def _schedule_lookup(name, schedule_bands):
    """Return best matching schedule entry for a detected band name, or {}."""
    name_l = name.lower()
    for h in schedule_bands:
        h_l = h['name'].lower()
        if name_l in h_l or h_l in name_l:
            return h
    return {}


def extract_pdfs(video_dir, out_dir):
    pdfs = sorted(video_dir.glob('*.pdf'))
    if not pdfs:
        return
    if not HAS_PDF:
        print(f'{C.YELLOW}Found {len(pdfs)} PDF(s) -- install pdfplumber to extract: '
              f'pip install pdfplumber{C.RESET}')
        return
    for pdf in pdfs:
        try:
            with pdfplumber.open(pdf) as doc:
                text = '\n'.join(p.extract_text() or '' for p in doc.pages)
            out = out_dir / f'{pdf.stem}.txt'
            out.write_text(text, encoding='utf-8')
            print(f'  {C.DIM}{pdf.name} -> {out.name}{C.RESET}')
        except Exception as e:
            print(f'  {C.RED}Warning: {pdf.name}: {e}{C.RESET}')


def main():
    ap = argparse.ArgumentParser(description='Analyze WGI video directory and emit config.json')
    ap.add_argument('video_dir')
    ap.add_argument('-o', '--output', default='config.json')
    ap.add_argument('--threshold', type=float, default=SCENE_THRESHOLD,
                    help='Scene sensitivity 0-1, lower = more cuts (default: %(default)s)')
    ap.add_argument('--min-gap', type=float, default=MIN_GAP,
                    help='Min quiet seconds to count as a performance boundary (default: %(default)s)')
    args = ap.parse_args()

    video_dir = Path(args.video_dir).resolve()
    out_path = Path(args.output)

    print(f'{C.DIM}Extracting schedule PDFs...{C.RESET}')
    extract_pdfs(video_dir, out_path.parent)
    txt_files = list(out_path.parent.glob('*.txt'))
    schedule = parse_schedule(txt_files)
    if schedule['event']:
        print(f'  {C.DIM}PDF event: {schedule["event"]}{C.RESET}')
    if schedule['date']:
        print(f'  {C.DIM}PDF date:  {schedule["date"]}{C.RESET}')
    if schedule['bands']:
        print(f'  {C.DIM}PDF schedule: {len(schedule["bands"])} band row(s) found{C.RESET}')

    video_files = sorted(
        f for f in video_dir.iterdir()
        if f.suffix.lower() in ('.mp4', '.mov', '.mkv', '.webm')
        and re.match(r'^\d+_', f.name)
    )
    skipped = sorted(
        f.name for f in video_dir.iterdir()
        if f.suffix.lower() in ('.mp4', '.mov', '.mkv', '.webm')
        and not re.match(r'^\d+_', f.name)
    )
    if skipped:
        print(f'{C.YELLOW}Skipping (no number prefix, add manually if needed): {skipped}{C.RESET}')

    bands = []

    for vf in video_files:
        names = parse_names(vf.stem)
        n = len(names)
        info = get_video_info(vf)
        dur = info['duration']

        print(f'\n{C.CYAN}{C.BOLD}{vf.name}{C.RESET}')
        name_list = ', '.join(f'{C.BOLD}{nm}{C.RESET}' for nm in names)
        print(f'  {n} band(s): {name_list}')
        print(f'  {C.DIM}Duration: {fmt(dur)}  {info["width"]}x{info["height"]}{C.RESET}')

        if n == 1:
            h = _schedule_lookup(names[0], schedule['bands'])
            bands.append({
                'name': names[0],
                'location': h.get('location', ''),
                'date': h.get('date', ''),
                'source_file': vf.name,
                'start': '00:00:00.000',
                'end': fmt(dur),
                'output': slugify(names[0]) + '.mp4',
            })
            continue

        print(f'  Detecting scenes {C.DIM}(threshold={args.threshold}){C.RESET}...', end=' ', flush=True)
        timestamps = detect_scenes(vf, args.threshold)
        print(f'{len(timestamps)} changes found')

        cuts = find_cuts(timestamps, dur, n, args.min_gap)
        cut_strs = ', '.join(fmt(c) for c in cuts)
        print(f'  {C.YELLOW}Suggested cuts: [{cut_strs}]{C.RESET}')

        bounds = [0.0] + cuts + [dur]
        for i, name in enumerate(names):
            h = _schedule_lookup(name, schedule['bands'])
            bands.append({
                'name': name,
                'location': h.get('location', ''),
                'date': h.get('date', ''),
                'source_file': vf.name,
                'start': fmt(bounds[i]),
                'end': fmt(bounds[i + 1]),
                'output': slugify(name) + '.mp4',
                '_review': 'verify start/end timestamps before processing',
            })

    config = {
        '_note': (
            'Fill in location/date/event. Review name/start/end for each band, '
            'remove _review flags when satisfied. '
            'Copy this file to the project dir as config.json, then: make process VIDEO_DIR=...'
        ),
        'input_dir': '/videos',
        'output_dir': '/videos/output',
        'event': schedule.get('event', ''),
        'title_duration_seconds': 4,
        'title_font_size': 72,
        'title_font_color': 'white',
        'title_background_color': 'black',
        'fade_duration_seconds': 1.0,
        'bands': bands,
    }

    out_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    print(f'\n{C.GREEN}Wrote {out_path} ({len(bands)} entries){C.RESET}')
    print(f'{C.DIM}Next: edit config.json to fix names and timestamps, then run process.py{C.RESET}')


if __name__ == '__main__':
    main()
