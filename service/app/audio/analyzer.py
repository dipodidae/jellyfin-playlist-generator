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
        try:
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            key_idx = int(np.argmax(np.mean(chroma, axis=1)))
            key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            key_estimate = key_names[key_idx]
        except Exception:
            pass  # Key estimation is optional

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
                    key_estimate, bpm_norm, loudness_norm, brightness_norm, flatness_norm
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            ))
            conn.commit()


def get_audio_features(track_id: str) -> AudioFeatures | None:
    """Load audio features from database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT bpm, loudness_rms, loudness_lufs, spectral_centroid,
                       spectral_flatness, dynamic_range, key_estimate,
                       bpm_norm, loudness_norm, brightness_norm, flatness_norm
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


async def analyze_library(
    batch_size: int = 100,
    progress_callback: callable = None,
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
                WHERE taf.track_id IS NULL
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

        if (i + 1) % batch_size == 0:
            if progress_callback:
                progress_callback(i + 1, total, f"Analyzed {i + 1}/{total} tracks")
            logger.info(f"Audio analysis progress: {i + 1}/{total}")

    if progress_callback:
        progress_callback(total, total, "Audio analysis complete")

    logger.info(f"Audio analysis complete: {stats}")
    return stats
