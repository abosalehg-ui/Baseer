"""ثوابت التطبيق — أنواع المخالفات وفئات الكشف."""

from __future__ import annotations

from enum import Enum
from typing import Final

# ============================================
# فئات الكشف للموديل (Detection Classes)
# ============================================
DETECTION_CLASSES: Final[dict[int, str]] = {
    0: "vehicle",
    1: "motorcycle",
    2: "person",
    3: "traffic_light_red",
    4: "traffic_light_yellow",
    5: "traffic_light_green",
    6: "helmet",
    7: "license_plate",
    8: "crosswalk",
    9: "lane_line_solid",
    10: "lane_line_dashed",
    11: "stop_line",
    12: "no_parking_sign",
}

CLASS_NAME_TO_ID: Final[dict[str, int]] = {v: k for k, v in DETECTION_CLASSES.items()}


# ============================================
# أنواع المخالفات
# ============================================
class ViolationType(str, Enum):
    """أنواع المخالفات المدعومة."""

    RED_LIGHT_RUNNING = "red_light_running"
    WRONG_DIRECTION = "wrong_direction"
    NO_HELMET = "no_helmet"
    ILLEGAL_PARKING = "illegal_parking"
    ILLEGAL_OVERTAKING = "illegal_overtaking"
    SPEEDING = "speeding"


VIOLATION_ARABIC_NAMES: Final[dict[ViolationType, str]] = {
    ViolationType.RED_LIGHT_RUNNING: "قطع الإشارة الحمراء",
    ViolationType.WRONG_DIRECTION: "السير بالاتجاه المعاكس",
    ViolationType.NO_HELMET: "عدم لبس الخوذة",
    ViolationType.ILLEGAL_PARKING: "الوقوف الخاطئ",
    ViolationType.ILLEGAL_OVERTAKING: "التجاوز الخاطئ",
    ViolationType.SPEEDING: "السرعة الزائدة",
}


# ============================================
# مصادر المقاطع
# ============================================
class SourceType(str, Enum):
    """مصادر المقاطع المدعومة."""

    DASHCAM = "dashcam"
    CCTV = "cctv"
    SOCIAL = "social"
    OTHER = "other"


SOURCE_ARABIC_NAMES: Final[dict[SourceType, str]] = {
    SourceType.DASHCAM: "كاميرا داشبورد",
    SourceType.CCTV: "كاميرا مراقبة ثابتة",
    SourceType.SOCIAL: "سوشل ميديا",
    SourceType.OTHER: "أخرى",
}


# ============================================
# حالات معالجة الفيديو
# ============================================
class VideoStatus(str, Enum):
    """حالات معالجة المقطع."""

    IMPORTED = "imported"
    PRELABELED = "prelabeled"
    REVIEWED = "reviewed"
    ANALYZED = "analyzed"


# ============================================
# حالات مراجعة المخالفات
# ============================================
class ReviewStatus(str, Enum):
    """حالة مراجعة المخالفة."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    UNCERTAIN = "uncertain"


# ============================================
# امتدادات الفيديو المدعومة
# ============================================
SUPPORTED_VIDEO_EXTENSIONS: Final[tuple[str, ...]] = (
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".webm",
    ".m4v",
    ".flv",
)


# ============================================
# عتبات افتراضية
# ============================================
DEFAULT_CONFIDENCE_THRESHOLD: Final[float] = 0.25
DEFAULT_IOU_THRESHOLD: Final[float] = 0.45
DEFAULT_FRAME_SAMPLE_RATE: Final[int] = 1
DEFAULT_THUMBNAIL_WIDTH: Final[int] = 320
LONG_VIDEO_THRESHOLD_SEC: Final[int] = 600
