import numpy as np

from app.audio.analyzer import (
    normalize_onset_rate,
    majorness_from_chroma,
    valence_from_parts,
    clamp01,
)


def test_clamp01():
    assert clamp01(-0.5) == 0.0
    assert clamp01(1.7) == 1.0
    assert clamp01(0.42) == 0.42


def test_normalize_onset_rate():
    assert normalize_onset_rate(0.0) == 0.0
    assert normalize_onset_rate(8.0) == 1.0
    assert normalize_onset_rate(4.0) == 0.5
    assert normalize_onset_rate(20.0) == 1.0  # clamped


def test_valence_from_parts_blend():
    # 0.5*major + 0.3*bpm + 0.2*brightness
    v = valence_from_parts(majorness=1.0, bpm_norm=1.0, brightness_norm=1.0)
    assert abs(v - 1.0) < 1e-9
    v0 = valence_from_parts(majorness=0.0, bpm_norm=0.0, brightness_norm=0.0)
    assert abs(v0 - 0.0) < 1e-9
    vmid = valence_from_parts(majorness=1.0, bpm_norm=0.0, brightness_norm=0.0)
    assert abs(vmid - 0.5) < 1e-9


def test_majorness_from_chroma_major_vs_minor():
    # A clearly C-major-ish chroma (strong C,E,G) should score higher than a minor-ish one (C,Eb,G)
    major = np.zeros(12); major[[0, 4, 7]] = 1.0          # C E G
    minor = np.zeros(12); minor[[0, 3, 7]] = 1.0          # C Eb G
    assert majorness_from_chroma(major) > majorness_from_chroma(minor)
    # output is in [0,1]
    assert 0.0 <= majorness_from_chroma(major) <= 1.0
    assert 0.0 <= majorness_from_chroma(minor) <= 1.0
