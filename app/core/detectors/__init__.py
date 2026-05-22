"""كواشف المخالفات الإضافية (lane keeping, following distance, high beam)."""

from app.core.detectors.following_distance import FollowingDistanceDetector
from app.core.detectors.high_beam import HighBeamDetector
from app.core.detectors.lane_keeping import LaneKeepingDetector

__all__ = ["FollowingDistanceDetector", "HighBeamDetector", "LaneKeepingDetector"]
