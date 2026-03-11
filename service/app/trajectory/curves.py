"""
Trajectory curve generation and interpolation.

Provides smooth multi-dimensional curves for playlist trajectory planning
using spline interpolation.
"""

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.interpolate import CubicSpline


@dataclass
class TrajectoryPoint:
    """A point on the 4D trajectory curve."""
    position: float  # 0.0 to 1.0
    energy: float
    tempo: float
    darkness: float
    texture: float
    phase_label: str = ""  # metadata only: intro/build/peak/resolve

    def as_array(self) -> np.ndarray:
        """Return dimensions as numpy array."""
        return np.array([self.energy, self.tempo, self.darkness, self.texture])

    def distance_to(self, other: "TrajectoryPoint") -> float:
        """Euclidean distance to another point."""
        return float(np.linalg.norm(self.as_array() - other.as_array()))


class TrajectoryCurve:
    """
    Multi-dimensional trajectory curve with spline interpolation.
    
    Generates smooth curves through key waypoints for energy, tempo,
    darkness, and texture dimensions.
    """

    def __init__(
        self,
        positions: list[float],
        energy: list[float],
        tempo: list[float],
        darkness: list[float],
        texture: list[float],
        phase_labels: list[str] | None = None,
    ):
        """
        Initialize trajectory curve from waypoint data.
        
        Args:
            positions: Normalized positions [0, 1] for each waypoint
            energy: Energy values at each waypoint
            tempo: Tempo values at each waypoint
            darkness: Darkness values at each waypoint
            texture: Texture values at each waypoint
            phase_labels: Optional phase labels for each waypoint
        """
        self.positions = np.array(positions)
        self._energy = np.array(energy)
        self._tempo = np.array(tempo)
        self._darkness = np.array(darkness)
        self._texture = np.array(texture)
        self._phase_labels = phase_labels or [""] * len(positions)

        # Create spline interpolators for each dimension
        # Use 'clamped' boundary condition for natural endpoints
        if len(positions) >= 4:
            self._spline_energy = CubicSpline(positions, energy, bc_type='clamped')
            self._spline_tempo = CubicSpline(positions, tempo, bc_type='clamped')
            self._spline_darkness = CubicSpline(positions, darkness, bc_type='clamped')
            self._spline_texture = CubicSpline(positions, texture, bc_type='clamped')
        else:
            # Fall back to linear interpolation for small waypoint counts
            self._spline_energy = lambda x: np.interp(x, positions, energy)
            self._spline_tempo = lambda x: np.interp(x, positions, tempo)
            self._spline_darkness = lambda x: np.interp(x, positions, darkness)
            self._spline_texture = lambda x: np.interp(x, positions, texture)

    def evaluate(self, t: float) -> TrajectoryPoint:
        """
        Evaluate the trajectory at position t.
        
        Args:
            t: Position along trajectory [0, 1]
            
        Returns:
            TrajectoryPoint with interpolated values
        """
        t = max(0.0, min(1.0, t))  # Clamp to valid range

        # Interpolate each dimension
        energy = float(np.clip(self._spline_energy(t), 0.0, 1.0))
        tempo = float(np.clip(self._spline_tempo(t), 0.0, 1.0))
        darkness = float(np.clip(self._spline_darkness(t), 0.0, 1.0))
        texture = float(np.clip(self._spline_texture(t), 0.0, 1.0))

        # Determine phase label
        phase_label = self._get_phase_label(t)

        return TrajectoryPoint(
            position=t,
            energy=energy,
            tempo=tempo,
            darkness=darkness,
            texture=texture,
            phase_label=phase_label,
        )

    def _get_phase_label(self, t: float) -> str:
        """Get phase label for position t."""
        if not self._phase_labels:
            return ""
        
        # Find the closest waypoint
        idx = int(np.argmin(np.abs(self.positions - t)))
        return self._phase_labels[idx]

    def sample(self, n_points: int) -> list[TrajectoryPoint]:
        """
        Sample the curve at n evenly-spaced points.
        
        Args:
            n_points: Number of points to sample
            
        Returns:
            List of TrajectoryPoints
        """
        if n_points <= 1:
            return [self.evaluate(0.5)]
        
        return [
            self.evaluate(i / (n_points - 1))
            for i in range(n_points)
        ]

    def deviation_from(self, actual_points: list[TrajectoryPoint]) -> float:
        """
        Calculate average deviation between this curve and actual points.
        
        Args:
            actual_points: List of actual trajectory points achieved
            
        Returns:
            Average Euclidean distance (0-1 normalized)
        """
        if not actual_points:
            return 0.0
        
        total_deviation = 0.0
        for point in actual_points:
            target = self.evaluate(point.position)
            total_deviation += point.distance_to(target)
        
        # Normalize by max possible distance (sqrt(4) = 2 for 4 dimensions)
        return total_deviation / (len(actual_points) * 2.0)


# Arc shape generators
def _steady_curve(t: float, base: float = 0.5) -> float:
    """Constant value."""
    return base


def _rise_curve(t: float, start: float = 0.2, end: float = 0.8) -> float:
    """Linear rise from start to end."""
    return start + (end - start) * t


def _fall_curve(t: float, start: float = 0.8, end: float = 0.2) -> float:
    """Linear fall from start to end."""
    return start + (end - start) * t


def _peak_curve(t: float, base: float = 0.3, peak: float = 1.0, peak_pos: float = 0.6) -> float:
    """Build to peak then resolve."""
    if t < peak_pos:
        # Build phase (60% of playlist by default)
        return base + (peak - base) * (t / peak_pos)
    else:
        # Resolve phase
        return peak - (peak - base * 0.8) * ((t - peak_pos) / (1 - peak_pos))


def _valley_curve(t: float, high: float = 0.7, low: float = 0.3) -> float:
    """Start high, dip to valley, return."""
    return high - (high - low) * (1 - abs(2 * t - 1))


def _wave_curve(t: float, center: float = 0.5, amplitude: float = 0.3) -> float:
    """Oscillating wave pattern."""
    return center + amplitude * math.sin(t * math.pi * 2)


def _journey_curve(t: float) -> float:
    """Narrative arc: intro → build → climax → denouement."""
    if t < 0.15:
        # Intro: gentle start
        return 0.3 + 0.1 * (t / 0.15)
    elif t < 0.6:
        # Build: steady rise
        return 0.4 + 0.4 * ((t - 0.15) / 0.45)
    elif t < 0.75:
        # Climax: peak
        return 0.8 + 0.2 * (1 - abs(2 * (t - 0.675) / 0.15))
    else:
        # Denouement: wind down
        return 0.7 - 0.4 * ((t - 0.75) / 0.25)


# Map arc types to curve generators
ARC_CURVES: dict[str, Callable[[float], float]] = {
    "steady": _steady_curve,
    "rise": _rise_curve,
    "fall": _fall_curve,
    "peak": _peak_curve,
    "valley": _valley_curve,
    "wave": _wave_curve,
    "journey": _journey_curve,
}


def generate_trajectory_curve(
    arc_type: str,
    playlist_length: int,
    base_energy: float = 0.5,
    base_darkness: float = 0.5,
    base_tempo: float = 0.5,
    base_texture: float = 0.5,
) -> TrajectoryCurve:
    """
    Generate a trajectory curve for the given arc type.
    
    The primary dimension (energy) follows the arc shape.
    Secondary dimensions have correlated but dampened variations.
    
    Args:
        arc_type: One of steady, rise, fall, peak, valley, wave, journey
        playlist_length: Number of tracks (affects resolution)
        base_*: Base values for each dimension (from prompt analysis)
        
    Returns:
        TrajectoryCurve instance
    """
    # Resolution scales with playlist length
    n_waypoints = max(5, min(playlist_length, 20))
    
    curve_fn = ARC_CURVES.get(arc_type.lower(), _steady_curve)
    
    positions = []
    energy_vals = []
    tempo_vals = []
    darkness_vals = []
    texture_vals = []
    phase_labels = []
    
    for i in range(n_waypoints):
        t = i / (n_waypoints - 1) if n_waypoints > 1 else 0.5
        positions.append(t)
        
        # Primary dimension follows arc
        arc_value = curve_fn(t)
        
        # Energy follows arc directly
        energy_vals.append(arc_value)
        
        # Tempo correlates with energy (dampened)
        tempo_delta = (arc_value - 0.5) * 0.6
        tempo_vals.append(max(0.0, min(1.0, base_tempo + tempo_delta)))
        
        # Darkness inversely correlates with energy for some arcs
        if arc_type in ("rise", "peak"):
            darkness_delta = (arc_value - 0.5) * -0.3
        else:
            darkness_delta = 0
        darkness_vals.append(max(0.0, min(1.0, base_darkness + darkness_delta)))
        
        # Texture correlates with energy (dampened)
        texture_delta = (arc_value - 0.5) * 0.4
        texture_vals.append(max(0.0, min(1.0, base_texture + texture_delta)))
        
        # Assign phase labels
        if t < 0.15:
            phase_labels.append("intro")
        elif t < 0.6:
            phase_labels.append("build")
        elif t < 0.8:
            phase_labels.append("peak")
        else:
            phase_labels.append("resolve")
    
    return TrajectoryCurve(
        positions=positions,
        energy=energy_vals,
        tempo=tempo_vals,
        darkness=darkness_vals,
        texture=texture_vals,
        phase_labels=phase_labels,
    )
