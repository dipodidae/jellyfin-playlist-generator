"""
Audio feature extraction using librosa.

Implements v4 optional audio integration:
- Analyze first 60 seconds only for performance
- Normalized audio vectors for scoring
- Fallback to metadata-only scoring if unavailable
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.database_pg import get_connection

logger = logging.getLogger(__name__)

# Lazy import librosa (heavy dependency)
_librosa = None


def get_librosa():
    """Lazy load librosa."""
    global _librosa
    if _librosa is None:
        try:
            import librosa
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Audio analysis requires librosa, but it is not installed in the backend environment."
            ) from exc
        _librosa = librosa
    return _librosa


@dataclass
class AudioFeatures:
    """Extracted audio features for a track."""
    track_id: str
    bpm: float | None = None
    loudness_rms: float | None = None
    loudness_lufs: float | None = None
    spectral_centroid: float | None = None
    spectral_flatness: float | None = None
    dynamic_range: float | None = None
    key_estimate: str | None = None

    # Normalized versions (0-1 scale)
    bpm_norm: float | None = None
    loudness_norm: float | None = None
    brightness_norm: float | None = None
    flatness_norm: float | None = None

    # Phase-A metrics (more-metrics)
    valence: float | None = None
    danceability: float | None = None
    pulse_clarity: float | None = None
    onset_rate: float | None = None
    onset_rate_norm: float | None = None
    instrumentalness: float | None = None
    acousticness: float | None = None
    mfcc: list | None = None  # 12 floats

    def as_vector(self) -> np.ndarray | None:
        """Return normalized features as vector for scoring."""
        if any(v is None for v in [self.bpm_norm, self.loudness_norm,
                                    self.brightness_norm, self.flatness_norm]):
            return None
        return np.array([
            self.bpm_norm,
            self.loudness_norm,
            self.brightness_norm,
            self.flatness_norm,
        ])


def to_python_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def normalize_bpm(bpm: float, min_bpm: float = 60, max_bpm: float = 200) -> float:
    """Normalize BPM to 0-1 scale."""
    return float(max(0.0, min(1.0, (bpm - min_bpm) / (max_bpm - min_bpm))))


def normalize_loudness(rms: float, min_db: float = -60, max_db: float = 0) -> float:
    """Normalize RMS loudness to 0-1 scale."""
    db = 20 * np.log10(rms + 1e-10)
    return float(max(0.0, min(1.0, (db - min_db) / (max_db - min_db))))


def normalize_spectral_centroid(centroid: float, min_hz: float = 500, max_hz: float = 8000) -> float:
    """Normalize spectral centroid to 0-1 scale."""
    return float(max(0.0, min(1.0, (centroid - min_hz) / (max_hz - min_hz))))


def normalize_spectral_flatness(flatness: float) -> float:
    """Normalize spectral flatness (already 0-1)."""
    return float(max(0.0, min(1.0, flatness)))


def clamp01(x: float) -> float:
    """Clamp to [0, 1]."""
    return float(max(0.0, min(1.0, x)))


def normalize_onset_rate(onsets_per_sec: float, max_rate: float = 8.0) -> float:
    """Normalize onset rate (onsets/sec) to 0-1 over [0, max_rate]."""
    return clamp01(onsets_per_sec / max_rate)


# Krumhansl-Schmuckler key profiles (major and minor), normalized.
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def majorness_from_chroma(chroma_mean: np.ndarray) -> float:
    """Estimate major-vs-minor 'majorness' in [0,1] from a 12-bin mean chroma vector.

    Correlates the (best-rotation) chroma against the major and minor KS profiles
    and returns a softmaxed major share. Heuristic — not a key/mode classifier.
    """
    c = np.asarray(chroma_mean, dtype=float)
    if c.shape[0] != 12 or float(np.sum(np.abs(c))) == 0.0:
        return 0.5
    c = c - c.mean()
    best_major = max(
        float(np.corrcoef(np.roll(c, -k), _KS_MAJOR - _KS_MAJOR.mean())[0, 1]) for k in range(12)
    )
    best_minor = max(
        float(np.corrcoef(np.roll(c, -k), _KS_MINOR - _KS_MINOR.mean())[0, 1]) for k in range(12)
    )
    gap = best_major - best_minor
    if not np.isfinite(gap):  # near-uniform/atonal chroma → corrcoef nan
        return 0.5
    # Map the (major - minor) correlation gap from [-1,1] to [0,1]
    return clamp01(0.5 + 0.5 * gap)


def valence_from_parts(majorness: float, bpm_norm: float, brightness_norm: float) -> float:
    """Heuristic valence (0-1): 0.5*majorness + 0.3*bpm + 0.2*brightness."""
    return clamp01(0.5 * majorness + 0.3 * bpm_norm + 0.2 * brightness_norm)


def analyze_audio_file(
    file_path: str,
    duration_limit: float = 60.0,
) -> AudioFeatures | None:
    """
    Analyze audio file and extract features.

    Args:
        file_path: Path to audio file
        duration_limit: Only analyze first N seconds (default 60)

    Returns:
        AudioFeatures or None if analysis fails
    """
    if not os.path.exists(file_path):
        logger.warning(f"Audio file not found: {file_path}")
        return None

    try:
        librosa = get_librosa()

        # Load audio (first 60 seconds only)
        y, sr = librosa.load(file_path, sr=22050, duration=duration_limit, mono=True)

        if len(y) == 0:
            logger.warning(f"Empty audio file: {file_path}")
            return None

        # BPM estimation
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(tempo) if isinstance(tempo, (int, float)) else float(tempo[0])

        # RMS loudness
        rms = float(np.sqrt(np.mean(y ** 2)))

        # Spectral centroid (brightness)
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
        avg_centroid = float(np.mean(centroid))

        # Spectral flatness (noise vs tonal)
        flatness = librosa.feature.spectral_flatness(y=y)
        avg_flatness = float(np.mean(flatness))

        # Dynamic range (difference between loud and quiet parts)
        rms_frames = librosa.feature.rms(y=y)[0]
        if len(rms_frames) > 1:
            dynamic_range = float(np.max(rms_frames) - np.min(rms_frames))
        else:
            dynamic_range = 0.0

        # Key estimation (optional, can be unreliable)
        key_estimate = None
        chroma = None
        try:
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            key_idx = int(np.argmax(np.mean(chroma, axis=1)))
            key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            key_estimate = key_names[key_idx]
        except Exception:
            pass  # Key estimation is optional

        # --- Phase-A metrics (heuristic proxies; see spec) ---
        bpm_n = normalize_bpm(bpm)
        brightness_n = normalize_spectral_centroid(avg_centroid)
        flatness_n = normalize_spectral_flatness(avg_flatness)

        # Onset envelope → rhythmic feel
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
        duration_sec = float(len(y) / sr) if sr else 0.0
        onset_rate = float(len(onsets) / duration_sec) if duration_sec > 0 else 0.0
        onset_rate_n = normalize_onset_rate(onset_rate)

        # Pulse clarity: prominence of the dominant autocorrelation lag of the onset envelope
        if onset_env.size > 1 and float(np.max(onset_env)) > 0:
            ac = librosa.autocorrelate(onset_env)
            ac = ac / (ac[0] + 1e-9)
            pulse_clarity = clamp01(float(np.max(ac[1:])) if ac.size > 1 else 0.0)
        else:
            pulse_clarity = 0.0
        if onset_env.size:
            beat_strength = clamp01(float(np.mean(onset_env)) / (float(np.max(onset_env)) + 1e-9))
        else:
            beat_strength = 0.0
        danceability = clamp01(0.6 * pulse_clarity + 0.4 * beat_strength)

        # HPSS → instrumentalness / acousticness proxies
        try:
            y_harm, y_perc = librosa.effects.hpss(y)
            harm_energy = float(np.sum(y_harm ** 2))
            perc_energy = float(np.sum(y_perc ** 2))
            harmonic_ratio = clamp01(harm_energy / (harm_energy + perc_energy + 1e-9))
            S = np.abs(librosa.stft(y_harm))
            freqs = librosa.fft_frequencies(sr=sr)
            vocal_band = (freqs >= 200) & (freqs <= 4000)
            band_energy = float(np.sum(S[vocal_band, :]))
            total_energy = float(np.sum(S)) + 1e-9
            vocal_band_ratio = clamp01(band_energy / total_energy)
            instrumentalness = clamp01(1.0 - vocal_band_ratio)
            acousticness = clamp01(
                0.5 * harmonic_ratio + 0.3 * (1 - brightness_n) + 0.2 * (1 - flatness_n)
            )
        except Exception:
            instrumentalness = None
            acousticness = None

        # MFCC timbre vector (coeffs 1..12, drop coeff 0 = energy)
        try:
            mfcc_full = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            mfcc_vec = [float(x) for x in np.mean(mfcc_full, axis=1)[1:13]]
        except Exception:
            mfcc_vec = None

        # Valence (heuristic): majorness + tempo + brightness
        try:
            chroma_mean = np.mean(chroma, axis=1)  # `chroma` computed in the key block above
            majorness = majorness_from_chroma(chroma_mean)
        except Exception:
            majorness = 0.5
        valence = valence_from_parts(majorness, bpm_n, brightness_n)

        # Create features with normalized values
        features = AudioFeatures(
            track_id="",  # Set by caller
            bpm=bpm,
            loudness_rms=rms,
            loudness_lufs=None,  # Would need pyloudnorm for proper LUFS
            spectral_centroid=avg_centroid,
            spectral_flatness=avg_flatness,
            dynamic_range=dynamic_range,
            key_estimate=key_estimate,
            bpm_norm=normalize_bpm(bpm),
            loudness_norm=normalize_loudness(rms),
            brightness_norm=normalize_spectral_centroid(avg_centroid),
            flatness_norm=normalize_spectral_flatness(avg_flatness),
            valence=valence,
            danceability=danceability,
            pulse_clarity=pulse_clarity,
            onset_rate=onset_rate,
            onset_rate_norm=onset_rate_n,
            instrumentalness=instrumentalness,
            acousticness=acousticness,
            mfcc=mfcc_vec,
        )

        return features

    except Exception as e:
        logger.error(f"Error analyzing {file_path}: {e}")
        return None


def save_audio_features(features: AudioFeatures) -> None:
    """Save audio features to database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO track_audio_features (
                    track_id, bpm, loudness_rms, loudness_lufs,
                    spectral_centroid, spectral_flatness, dynamic_range,
                    key_estimate, bpm_norm, loudness_norm, brightness_norm, flatness_norm,
                    valence, danceability, pulse_clarity, onset_rate, onset_rate_norm,
                    instrumentalness, acousticness, mfcc
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (track_id) DO UPDATE SET
                    bpm = EXCLUDED.bpm,
                    loudness_rms = EXCLUDED.loudness_rms,
                    loudness_lufs = EXCLUDED.loudness_lufs,
                    spectral_centroid = EXCLUDED.spectral_centroid,
                    spectral_flatness = EXCLUDED.spectral_flatness,
                    dynamic_range = EXCLUDED.dynamic_range,
                    key_estimate = EXCLUDED.key_estimate,
                    bpm_norm = EXCLUDED.bpm_norm,
                    loudness_norm = EXCLUDED.loudness_norm,
                    brightness_norm = EXCLUDED.brightness_norm,
                    flatness_norm = EXCLUDED.flatness_norm,
                    valence = EXCLUDED.valence,
                    danceability = EXCLUDED.danceability,
                    pulse_clarity = EXCLUDED.pulse_clarity,
                    onset_rate = EXCLUDED.onset_rate,
                    onset_rate_norm = EXCLUDED.onset_rate_norm,
                    instrumentalness = EXCLUDED.instrumentalness,
                    acousticness = EXCLUDED.acousticness,
                    mfcc = EXCLUDED.mfcc,
                    analyzed_at = now()
            """, (
                features.track_id,
                to_python_float(features.bpm),
                to_python_float(features.loudness_rms),
                to_python_float(features.loudness_lufs),
                to_python_float(features.spectral_centroid),
                to_python_float(features.spectral_flatness),
                to_python_float(features.dynamic_range),
                features.key_estimate,
                to_python_float(features.bpm_norm),
                to_python_float(features.loudness_norm),
                to_python_float(features.brightness_norm),
                to_python_float(features.flatness_norm),
                to_python_float(features.valence),
                to_python_float(features.danceability),
                to_python_float(features.pulse_clarity),
                to_python_float(features.onset_rate),
                to_python_float(features.onset_rate_norm),
                to_python_float(features.instrumentalness),
                to_python_float(features.acousticness),
                features.mfcc,
            ))
            conn.commit()


def get_audio_features(track_id: str) -> AudioFeatures | None:
    """Load audio features from database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT bpm, loudness_rms, loudness_lufs, spectral_centroid,
                       spectral_flatness, dynamic_range, key_estimate,
                       bpm_norm, loudness_norm, brightness_norm, flatness_norm,
                       valence, danceability, pulse_clarity, onset_rate, onset_rate_norm,
                       instrumentalness, acousticness, mfcc
                FROM track_audio_features
                WHERE track_id = %s
            """, (track_id,))

            row = cur.fetchone()
            if not row:
                return None

            return AudioFeatures(
                track_id=track_id,
                bpm=row[0],
                loudness_rms=row[1],
                loudness_lufs=row[2],
                spectral_centroid=row[3],
                spectral_flatness=row[4],
                dynamic_range=row[5],
                key_estimate=row[6],
                bpm_norm=row[7],
                loudness_norm=row[8],
                brightness_norm=row[9],
                flatness_norm=row[10],
                valence=row[11],
                danceability=row[12],
                pulse_clarity=row[13],
                onset_rate=row[14],
                onset_rate_norm=row[15],
                instrumentalness=row[16],
                acousticness=row[17],
                mfcc=row[18],
            )


def score_audio_transition(
    prev_features: AudioFeatures | None,
    curr_features: AudioFeatures | None,
    weight: float = 0.15,
) -> float:
    """
    Score audio transition between two tracks.

    Returns weighted score in [0, weight] where higher = smoother.
    """
    if prev_features is None or curr_features is None:
        return 0.0  # No penalty if features unavailable

    prev_vec = prev_features.as_vector()
    curr_vec = curr_features.as_vector()

    if prev_vec is None or curr_vec is None:
        return 0.0

    # Compute distance (lower = more similar = better transition)
    distance = float(np.linalg.norm(prev_vec - curr_vec))

    # Convert to similarity score
    # Max distance is sqrt(4) = 2 for 4D unit vectors
    similarity = max(0.0, 1.0 - distance / 2.0)

    return similarity * weight


def analyze_library(
    batch_size: int = 100,
    progress_callback: callable = None,
    stop_event=None,
) -> dict[str, int]:
    """
    Analyze audio features for all tracks in library.

    This is a long-running background job.
    """
    stats = {"processed": 0, "success": 0, "failed": 0, "skipped": 0}
    get_librosa()

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get tracks without audio features
            cur.execute("""
                SELECT t.id, tf.path
                FROM tracks t
                JOIN track_files tf ON t.id = tf.track_id
                LEFT JOIN track_audio_features taf ON t.id = taf.track_id
                WHERE (taf.track_id IS NULL OR taf.valence IS NULL OR taf.mfcc IS NULL)
                AND tf.path IS NOT NULL
                AND tf.missing_since IS NULL
            """)

            tracks = cur.fetchall()

    total = len(tracks)
    logger.info(f"Analyzing audio for {total} tracks")

    if progress_callback:
        progress_callback(0, total, f"Analyzing {total} tracks...")

    if total == 0:
        logger.info("Audio analysis complete: no tracks pending")
        return stats

    for i, (track_id, file_path) in enumerate(tracks):
        if stop_event and stop_event.is_set():
            logger.info("Audio analysis cancelled by client disconnect")
            break

        if not file_path or not os.path.exists(file_path):
            stats["skipped"] += 1
            continue

        features = analyze_audio_file(file_path)

        if features:
            features.track_id = str(track_id)
            save_audio_features(features)
            stats["success"] += 1
        else:
            stats["failed"] += 1

        stats["processed"] += 1

        # Emit progress every track so the SSE stream never idles long enough
        # to trip the reverse-proxy read timeout (a single slow file can take
        # ~20s; a 100-track batch can exceed 300s). Log less often.
        if progress_callback:
            progress_callback(i + 1, total, f"Analyzed {i + 1}/{total} tracks")
        if (i + 1) % batch_size == 0:
            logger.info(f"Audio analysis progress: {i + 1}/{total}")

    if progress_callback:
        progress_callback(total, total, "Audio analysis complete")

    logger.info(f"Audio analysis complete: {stats}")
    return stats
