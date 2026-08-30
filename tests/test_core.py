"""
Unit tests for pure functions in analyze.py and process.py.
Run with: pytest tests/
"""
import sys
from pathlib import Path
import pytest

# Make project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import analyze
import process


# ── analyze.py ────────────────────────────────────────────────────────────────

class TestFmt:
    def test_zero(self):
        assert analyze.fmt(0) == '00:00:00.000'

    def test_minutes(self):
        assert analyze.fmt(90) == '00:01:30.000'

    def test_hours(self):
        assert analyze.fmt(3661.5) == '01:01:01.500'


class TestSlugify:
    def test_basic(self):
        assert analyze.slugify('Buckhorn Percussion') == 'buckhorn_percussion'

    def test_special_chars(self):
        assert analyze.slugify('Greenfield-Central HS') == 'greenfield_central_hs'

    def test_already_slug(self):
        assert analyze.slugify('rcc') == 'rcc'


class TestParseNames:
    def test_single(self):
        assert analyze.parse_names('01_buckhorn_percussion_WGI') == ['Buckhorn Percussion']

    def test_multi(self):
        result = analyze.parse_names('02_franklin__greenfield-central__auburn_WGI')
        assert result == ['Franklin', 'Greenfield Central', 'Auburn']

    def test_strips_numeric_prefix(self):
        assert analyze.parse_names('05_rcc_WGI') == ['Rcc']

    def test_strips_wgi_suffix_case_insensitive(self):
        assert analyze.parse_names('01_matrix_wgi') == ['Matrix']


class TestFindCuts:
    def test_no_bands(self):
        assert analyze.find_cuts([], 600, 1) == []

    def test_even_split_fallback(self):
        cuts = analyze.find_cuts([], 600, 3)
        assert len(cuts) == 2
        assert cuts[0] == pytest.approx(200)
        assert cuts[1] == pytest.approx(400)

    def test_gap_based(self):
        # Two clear gaps at ~120s and ~360s
        ts = list(range(100, 140)) + list(range(340, 380))
        cuts = analyze.find_cuts(ts, 500, 3, min_gap=60)
        assert len(cuts) == 2


# ── process.py ────────────────────────────────────────────────────────────────

class TestTsToSecs:
    def test_hhmmss(self):
        assert process.ts_to_secs('00:01:30.000') == pytest.approx(90.0)

    def test_mmss(self):
        assert process.ts_to_secs('01:30.5') == pytest.approx(90.5)

    def test_seconds_only(self):
        assert process.ts_to_secs('45.25') == pytest.approx(45.25)


class TestParseFps:
    def test_fraction(self):
        assert process._parse_fps('30000/1001') == pytest.approx(29.97, rel=1e-3)

    def test_integer_string(self):
        assert process._parse_fps('60') == pytest.approx(60.0)

    def test_bad_input(self):
        assert process._parse_fps('not/valid') == 0.0


class TestSnapFps:
    def test_snaps_2997(self):
        assert process._snap_fps(29.97) == '30000/1001'

    def test_snaps_30(self):
        assert process._snap_fps(30.0) == '30/1'

    def test_snaps_60(self):
        assert process._snap_fps(60.0) == '60/1'


class TestValidateConfig:
    def _good(self):
        return {
            'input_dir': '/videos',
            'output_dir': '/videos/output',
            'bands': [{
                'name': 'Test Band',
                'output': 'test.mp4',
                'source_file': 'file.mp4',
                'start': '00:00:00.000',
                'end': '00:06:00.000',
            }],
        }

    def test_valid_passes(self, capsys):
        process.validate_config(self._good(), 'config.json')

    def test_missing_top_key(self):
        cfg = self._good()
        del cfg['bands']
        with pytest.raises(SystemExit):
            process.validate_config(cfg, 'config.json')

    def test_missing_output(self):
        cfg = self._good()
        del cfg['bands'][0]['output']
        with pytest.raises(SystemExit):
            process.validate_config(cfg, 'config.json')

    def test_both_source_and_segments(self):
        cfg = self._good()
        cfg['bands'][0]['segments'] = [
            {'source_file': 'f.mp4', 'start': '00:00:00', 'end': '00:01:00'}
        ]
        with pytest.raises(SystemExit):
            process.validate_config(cfg, 'config.json')

    def test_neither_source_nor_segments(self):
        cfg = self._good()
        del cfg['bands'][0]['source_file']
        del cfg['bands'][0]['start']
        del cfg['bands'][0]['end']
        with pytest.raises(SystemExit):
            process.validate_config(cfg, 'config.json')

    def test_segment_missing_field(self):
        cfg = self._good()
        del cfg['bands'][0]['source_file']
        del cfg['bands'][0]['start']
        del cfg['bands'][0]['end']
        cfg['bands'][0]['segments'] = [{'source_file': 'f.mp4', 'start': '00:00:00'}]
        with pytest.raises(SystemExit):
            process.validate_config(cfg, 'config.json')
