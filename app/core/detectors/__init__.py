"""كواشف المخالفات — كل كاشف في ملف مستقل.

كانت الكواشف الستة الأصلية داخل `rules.py` (622 سطراً) والثلاثة الإضافية هنا،
فصار مكان الكاشف يعتمد على تاريخ كتابته لا على طبيعته. الآن كلها في مكان واحد،
و`rules.py` هو الـpipeline والواجهة فقط.
"""

from app.core.detectors.following_distance import FollowingDistanceDetector
from app.core.detectors.high_beam import HighBeamDetector
from app.core.detectors.illegal_overtaking import IllegalOvertakingDetector
from app.core.detectors.illegal_parking import IllegalParkingDetector
from app.core.detectors.lane_keeping import LaneKeepingDetector
from app.core.detectors.no_helmet import NoHelmetDetector
from app.core.detectors.red_light import RedLightDetector
from app.core.detectors.speeding import SpeedingDetector
from app.core.detectors.wrong_direction import WrongDirectionDetector

__all__ = [
    "FollowingDistanceDetector",
    "HighBeamDetector",
    "IllegalOvertakingDetector",
    "IllegalParkingDetector",
    "LaneKeepingDetector",
    "NoHelmetDetector",
    "RedLightDetector",
    "SpeedingDetector",
    "WrongDirectionDetector",
]
