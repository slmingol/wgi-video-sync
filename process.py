#!/usr/bin/env python3
"""
Stage 2: Cut performance segments and prepend band-name title cards.

Supports single-source entries (source_file + start/end) and multi-segment
entries (segments array) for performances that span across multiple files.

Usage:
  python process.py config.json
  python process.py config.json --dry-run
  python process.py config.json --only "buckhorn"   # substring match, case-insensitive

Requires: ffmpeg, ffprobe
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


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


def _parse_fps(fps_str):
    """Return fps as float. Returns 0.0 on parse error."""
    try:
        parts = fps_str.split('/')
        return float(parts[0]) / float(parts[1]) if len(parts) == 2 else float(parts[0])
    except Exception:
        return 0.0


# Standard frame rates as (numerator, denominator) pairs, used to snap
# unreliable avg_frame_rate values to a clean canonical string.
_STD_FPS = [
    (24000, 1001), (24, 1), (25, 1),
    (30000, 1001), (30, 1),
    (50, 1), (60000, 1001), (60, 1),
]


def _snap_fps(val):
    """Snap a floating-point fps to the nearest standard rate string."""
    best = min(_STD_FPS, key=lambda f: abs(val - f[0] / f[1]))
    return f'{best[0]}/{best[1]}'


def get_video_info(path):
    r = run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_streams', str(path)])
    try:
        d = json.loads(r.stdout)
        vs = next(s for s in d.get('streams', []) if s['codec_type'] == 'video')
        fps_raw = vs.get('r_frame_rate', '30/1')
        fps_ok = 0 < _parse_fps(fps_raw) <= 120
        if fps_ok:
            fps = fps_raw
        else:
            # r_frame_rate is a broken codec timebase (e.g. 57600/1 for a ~60fps
            # stream). Fall back to avg_frame_rate, snapped to the nearest standard
            # rate so the normalize pass uses the right frame cadence.
            avg_raw = vs.get('avg_frame_rate', '30/1')
            avg_val = _parse_fps(avg_raw)
            fps = _snap_fps(avg_val) if 0 < avg_val <= 120 else '30/1'
        return {
            'width': vs.get('width', 1920),
            'height': vs.get('height', 1080),
            'fps': fps,
            # True when r_frame_rate is a broken codec timebase.
            # Such sources must be normalized before seeking into them is reliable.
            'needs_fix': not fps_ok,
        }
    except Exception:
        return {'width': 1920, 'height': 1080, 'fps': '30/1', 'needs_fix': False}


# Normalized copies of broken sources, keyed by original path string.
# Populated lazily; lives for the duration of a single process run.
_normalize_cache: dict = {}


def normalize_source(source, info, tmp_dir):
    """Re-encode a broken source (bad fps/PTS) to a clean CFR file.

    Stamps video PTS from frame index and audio PTS from sample index so
    any mid-stream timestamp discontinuity is erased. Returns the path of
    the clean file; falls back to the original path on failure.
    """
    key = str(source)
    if key in _normalize_cache:
        return _normalize_cache[key]

    fps_str = info['fps']   # already snapped to a standard rate by get_video_info
    fps_val = _parse_fps(fps_str)
    fixed_path = tmp_dir / f'fixed_{source.stem}.mp4'
    print(f'\n    {C.YELLOW}broken timestamps detected -- normalizing {source.name}{C.RESET}... ',
          end='', flush=True)
    cmd = [
        'ffmpeg', '-y', '-i', str(source),
        '-map', '0:v:0', '-map', '0:a:0',
        '-vf', f'setpts=N/TB/({fps_str})',
        '-af', 'asetpts=N/SR/TB',
        '-fps_mode', 'cfr', '-r', fps_str,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
        str(fixed_path),
    ]
    r = run(cmd)
    if r.returncode != 0:
        print(f'{C.RED}failed{C.RESET}\n{r.stderr[-800:]}')
        _normalize_cache[key] = source
        return source
    print(f'{C.GREEN}ok{C.RESET}')
    _normalize_cache[key] = fixed_path
    return fixed_path


def find_font():
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
    ]
    for f in candidates:
        if os.path.exists(f):
            return f
    r = run(['fc-match', '--format=%{file}', 'sans-serif:bold'])
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return None


def ts_to_secs(ts):
    parts = ts.split(':')
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def make_title_card(band_name, location, date, event, info, title_dur, fade_dur, font_size,
                    font_color, bg_color, font_path, tmp_dir, out_path):
    w, h, fps = info['width'], info['height'], info['fps']
    fade_out_start = title_dur - fade_dur

    name_file = tmp_dir / 'title_name.txt'
    name_file.write_text(band_name, encoding='utf-8')

    font_arg = f':fontfile={font_path}' if font_path else ''
    subtitles = [s for s in [location, date, event] if s]
    n = len(subtitles)
    sub_size = max(28, font_size // 2)
    gap = 10

    if n == 0:
        name_y = '(h-text_h)/2'
    else:
        name_y = f'h/2-text_h-{gap}'

    name_dt = (
        f"drawtext=textfile='{name_file}'"
        f':fontsize={font_size}'
        f':fontcolor={font_color}'
        f':x=(w-text_w)/2:y={name_y}'
        f'{font_arg}'
    )

    sub_dts = []
    for i, text in enumerate(subtitles):
        sub_file = tmp_dir / f'title_sub_{i}.txt'
        sub_file.write_text(text, encoding='utf-8')
        if n == 1:
            sub_y = f'h/2+{gap}'
        else:
            sub_y = f'h/2+{i * (sub_size + gap)}'
        sub_dts.append(
            f"drawtext=textfile='{sub_file}'"
            f':fontsize={sub_size}'
            f':fontcolor={font_color}'
            f':x=(w-text_w)/2:y={sub_y}'
            f'{font_arg}'
        )

    filters = ','.join([name_dt] + sub_dts)
    vf = (
        f'{filters}'
        f',fade=t=in:st=0:d={fade_dur}'
        f',fade=t=out:st={fade_out_start}:d={fade_dur}'
    )

    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'color=c={bg_color}:size={w}x{h}:rate={fps}:duration={title_dur}',
        '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
        '-vf', vf,
        '-t', str(title_dur),
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-c:a', 'aac', '-b:a', '128k',
        '-pix_fmt', 'yuv420p',
        str(out_path),
    ]
    r = run(cmd)
    if r.returncode != 0:
        print(f'\n    {C.RED}title card failed:{C.RESET}\n{r.stderr[-800:]}')
    return r.returncode == 0


def extract_segment(source, start, end, info, fade_dur, out_path, tmp_dir=None):
    w, h = info['width'], info['height']
    start_s = ts_to_secs(start) if start else 0.0

    # Sources with broken timestamps (e.g. FloMarching live captures) must be
    # normalized first so that -ss seeks land in the right place and mid-stream
    # PTS jumps don't cause slow motion or duration inflation.
    actual_source = source
    if info.get('needs_fix') and tmp_dir is not None:
        actual_source = normalize_source(source, info, tmp_dir)

    cmd = ['ffmpeg', '-y', '-ss', start or '00:00:00.000', '-i', str(actual_source)]

    if end and end.upper() != 'END':
        end_s = ts_to_secs(end)
        cmd += ['-t', str(end_s - start_s)]

    vf_parts = [
        f'scale={w}:{h}:force_original_aspect_ratio=decrease',
        f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2',
        'setsar=1',
    ]
    if fade_dur > 0:
        vf_parts.append(f'fade=t=in:st=0:d={fade_dur}')
    vf = ','.join(vf_parts)

    cmd += [
        '-vf', vf,
        '-r', info['fps'],
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-c:a', 'aac', '-b:a', '128k',
        '-pix_fmt', 'yuv420p',
        str(out_path),
    ]
    r = run(cmd)
    if r.returncode != 0:
        print(f'\n    {C.RED}segment extraction failed:{C.RESET}\n{r.stderr[-800:]}')
    return r.returncode == 0


def extract_multi_segment(segments, config, info, fade_dur, out_path, tmp_dir):
    """Extract parts from multiple source files and join them seamlessly."""
    part_paths = []
    for i, seg in enumerate(segments):
        source = Path(config['input_dir']) / seg['source_file']
        if not source.exists():
            print(f'\n    {C.RED}ERROR: source not found: {source}{C.RESET}')
            return False
        part_path = tmp_dir / f'part_{out_path.stem}_{i}.mp4'
        # Fade-in only on the first part; subsequent parts join seamlessly
        this_fade = fade_dur if i == 0 else 0
        if not extract_segment(source, seg.get('start'), seg.get('end'), info, this_fade, part_path, tmp_dir):
            return False
        part_paths.append(part_path)

    return concat_files(part_paths, out_path, tmp_dir)


def concat_files(paths, out_path, tmp_dir, reencode=False):
    """Concatenate a list of video files."""
    if reencode:
        # Use concat filter with explicit inputs for clean timestamp handling
        filter_in = ''.join(f'[{i}:v][{i}:a]' for i in range(len(paths)))
        cmd = ['ffmpeg', '-y']
        for p in paths:
            cmd += ['-i', str(p)]
        cmd += [
            '-filter_complex', f'{filter_in}concat=n={len(paths)}:v=1:a=1[v][a]',
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-c:a', 'aac', '-b:a', '128k',
            '-pix_fmt', 'yuv420p',
            str(out_path),
        ]
    else:
        list_file = tmp_dir / 'concat.txt'
        list_file.write_text(
            ''.join(f"file '{p}'\n" for p in paths),
            encoding='utf-8',
        )
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', str(list_file),
            '-c', 'copy', '-movflags', '+faststart',
            str(out_path),
        ]
    r = run(cmd)
    if r.returncode != 0:
        print(f'\n    {C.RED}concat failed:{C.RESET}\n{r.stderr[-2000:]}')
    return r.returncode == 0


def process_band(band, config, output_dir, tmp_dir, font_path):
    name = band['name']
    out = output_dir / band['output']
    segments = band.get('segments')

    # Get video info from the first source file
    first_source_file = segments[0]['source_file'] if segments else band.get('source_file')
    first_source = Path(config['input_dir']) / first_source_file
    if not first_source.exists():
        print(f'  {C.RED}ERROR: source not found: {first_source}{C.RESET}')
        return False

    title_dur = float(config.get('title_duration_seconds', 4))
    font_size = int(config.get('title_font_size', 72))
    font_color = config.get('title_font_color', 'white')
    bg_color = config.get('title_background_color', 'black')
    fade_dur = float(config.get('fade_duration_seconds', 1.0))

    info = get_video_info(first_source)
    stem = re.sub(r'[^\w]', '_', name)
    title_path = tmp_dir / f'title_{stem}.mp4'
    seg_path = tmp_dir / f'seg_{stem}.mp4'

    location = band.get('location', '')
    date = band.get('date', '')
    event = config.get('event', '')
    print(f'  title card... ', end='', flush=True)
    if not make_title_card(name, location, date, event, info, title_dur, fade_dur, font_size,
                           font_color, bg_color, font_path, tmp_dir, title_path):
        return False

    if segments:
        seg_desc = f'{len(segments)} segments across {len(set(s["source_file"] for s in segments))} files'
    else:
        seg_desc = f'[{band.get("start", "?")} -> {band.get("end", "?")}]'

    print(f'{C.GREEN}ok{C.RESET}  segment {C.DIM}{seg_desc}{C.RESET}... ', end='', flush=True)

    if segments:
        if not extract_multi_segment(segments, config, info, fade_dur, seg_path, tmp_dir):
            return False
    else:
        if not extract_segment(first_source, band.get('start'), band.get('end'), info, fade_dur, seg_path, tmp_dir):
            return False

    title_mb = title_path.stat().st_size / 1e6
    seg_mb = seg_path.stat().st_size / 1e6
    print(f'{C.GREEN}ok{C.RESET}  concat {C.DIM}(title:{title_mb:.1f}MB seg:{seg_mb:.1f}MB){C.RESET}... ', end='', flush=True)
    if not concat_files([title_path, seg_path], out, tmp_dir, reencode=True):
        return False

    print(f'{C.GREEN}ok{C.RESET}  {C.BOLD}->{C.RESET} {C.CYAN}{out.name}{C.RESET}')
    return True


def validate_config(config, config_path):
    errors = []
    for key in ('input_dir', 'output_dir', 'bands'):
        if key not in config:
            errors.append(f"missing required key: '{key}'")
    for i, band in enumerate(config.get('bands', [])):
        prefix = f"bands[{i}] ({band.get('name', '?')})"
        if 'name' not in band:
            errors.append(f"{prefix}: missing 'name'")
        if 'output' not in band:
            errors.append(f"{prefix}: missing 'output'")
        has_single = 'source_file' in band
        has_multi = 'segments' in band
        if not has_single and not has_multi:
            errors.append(f"{prefix}: needs 'source_file' or 'segments'")
        if has_single and has_multi:
            errors.append(f"{prefix}: has both 'source_file' and 'segments' — use one")
        if has_single:
            for ts_key in ('start', 'end'):
                if ts_key not in band:
                    errors.append(f"{prefix}: missing '{ts_key}'")
        if has_multi:
            for j, seg in enumerate(band.get('segments', [])):
                for field in ('source_file', 'start', 'end'):
                    if field not in seg:
                        errors.append(f"{prefix} segments[{j}]: missing '{field}'")
    if errors:
        print(f"{C.RED}Config errors in {config_path}:{C.RESET}")
        for e in errors:
            print(f"  {C.RED}• {e}{C.RESET}")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description='Cut WGI segments and prepend title cards')
    ap.add_argument('config')
    ap.add_argument('--dry-run', action='store_true', help='Show plan without processing')
    ap.add_argument('--only', metavar='NAME',
                    help='Process only bands whose name contains NAME (case-insensitive)')
    ap.add_argument('--skip-existing', action='store_true',
                    help='Skip bands whose output file already exists')
    args = ap.parse_args()

    with open(args.config, encoding='utf-8') as f:
        config = json.load(f)

    validate_config(config, args.config)

    output_dir = Path(config.get('output_dir', './output'))
    output_dir.mkdir(parents=True, exist_ok=True)

    all_bands = config.get('bands', [])
    idx_width = len(str(len(all_bands)))

    def with_prefix(i, band):
        b = dict(band)
        b['output'] = f'{(i + 1):0{idx_width}d}_{band["output"]}'
        return b

    bands = [with_prefix(i, b) for i, b in enumerate(all_bands)]
    if args.only:
        filters = [f.strip().lower() for f in args.only.split(',')]
        def matches(name):
            n = name.lower()
            return any(n.endswith(f[:-1]) if f.endswith('$') else f in n for f in filters)
        bands = [b for b in bands if matches(b['name'])]
        if not bands:
            print(f"{C.RED}No bands match '{args.only}'{C.RESET}")
            return

    print(f'{C.BOLD}{len(bands)} band(s){C.RESET}  ->  {C.CYAN}{output_dir}{C.RESET}')

    if args.dry_run:
        for b in bands:
            flag = f'  {C.YELLOW}[REVIEW]{C.RESET}' if b.get('_review') else ''
            if b.get('segments'):
                segs = ' + '.join(
                    f'{s["source_file"]}[{s.get("start","?")} -> {s.get("end","?")}]'
                    for s in b['segments']
                )
                print(f"  {C.BOLD}{b['name']}{C.RESET}: {C.DIM}{segs}{C.RESET} -> {b['output']}{flag}")
            else:
                print(f"  {C.BOLD}{b['name']}{C.RESET}: "
                      f"{C.DIM}{b.get('start', '?')} -> {b.get('end', '?')}{C.RESET}  "
                      f"{b['source_file']} -> {b['output']}{flag}")
        return

    font_path = find_font()
    print(f'{C.DIM}Font: {font_path or "ffmpeg built-in (no font file found)"}{C.RESET}')

    ok, failed = 0, []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for i, band in enumerate(bands, 1):
                print(f'\n{C.CYAN}{C.BOLD}[{i}/{len(bands)}] {band["name"]}{C.RESET}')
                if args.skip_existing and (output_dir / band['output']).exists():
                    print(f'  {C.DIM}skip (exists){C.RESET}')
                    ok += 1
                    continue
                if band.get('_review'):
                    print(f'  {C.YELLOW}WARNING: {band["_review"]}{C.RESET}')
                if process_band(band, config, output_dir, tmp_dir, font_path):
                    ok += 1
                else:
                    failed.append(band['name'])
    except KeyboardInterrupt:
        print(f'\n\n{C.YELLOW}Interrupted{C.RESET}')
        sys.exit(130)

    total = len(bands)
    color = C.GREEN if ok == total else C.YELLOW if ok > 0 else C.RED
    print(f'\n{color}{C.BOLD}{ok}/{total} succeeded{C.RESET}')
    if failed:
        print(f'{C.RED}Failed: {", ".join(failed)}{C.RESET}')


if __name__ == '__main__':
    main()
