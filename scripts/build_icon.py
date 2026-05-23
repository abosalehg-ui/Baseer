"""يولّد أيقونة Baseer كـ ICO متعدد الأحجام + PNG عالي الدقة.

التصميم: مربع بخلفية كحلية متدرّجة، عين بيضاء مع بؤبؤ يحوي إشارة مرور
(دوائر حمراء/صفراء/خضراء) — رمز لـ"العين البصيرة التي تراقب المرور".

الاستخدام:
    python scripts/build_icon.py

يُنتج:
    assets/icon.ico   (16, 24, 32, 48, 64, 128, 256)
    assets/icon.png   (1024×1024)
    assets/icon_64.png (64×64 لاستخدامات UI)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

# ============================================
# لوحة الألوان
# ============================================
BG_TOP = (15, 42, 79)  # كحلي عميق
BG_BOTTOM = (28, 75, 138)  # أزرق متوسط
EYE_WHITE = (245, 248, 252)
EYE_OUTLINE = (10, 25, 50)
PUPIL = (15, 25, 45)
TL_RED = (231, 76, 60)
TL_YELLOW = (241, 196, 15)
TL_GREEN = (46, 204, 113)
SHINE = (255, 255, 255, 180)


def _gradient_background(size: int) -> Image.Image:
    """خلفية متدرّجة عمودياً مع زوايا دائرية."""
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        grad.putpixel((0, y), (r, g, b))
    grad = grad.resize((size, size))

    # قناع زوايا دائرية
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    radius = int(size * 0.22)
    md.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)

    bg.paste(grad, (0, 0), mask)
    return bg


def _draw_eye(img: Image.Image) -> None:
    """يرسم العين البيضاء مع بؤبؤ وإشارة مرور بداخله."""
    size = img.size[0]
    d = ImageDraw.Draw(img, "RGBA")

    cx, cy = size // 2, size // 2
    eye_w = int(size * 0.72)
    eye_h = int(size * 0.45)

    # شكل العين (قطع ناقص)
    eye_box = (cx - eye_w // 2, cy - eye_h // 2, cx + eye_w // 2, cy + eye_h // 2)
    d.ellipse(eye_box, fill=EYE_WHITE)
    # خط محيط رفيع
    outline_w = max(2, size // 64)
    d.ellipse(eye_box, outline=EYE_OUTLINE, width=outline_w)

    # بؤبؤ
    pupil_r = int(eye_h * 0.42)
    pupil_box = (cx - pupil_r, cy - pupil_r, cx + pupil_r, cy + pupil_r)
    d.ellipse(pupil_box, fill=PUPIL)

    # ====== إشارة مرور داخل البؤبؤ ======
    light_r = int(pupil_r * 0.22)
    gap = int(light_r * 0.6)
    total_h = light_r * 6 + gap * 2  # 3 دوائر
    top_y = cy - total_h // 2 + light_r

    for color, offset in (
        (TL_RED, 0),
        (TL_YELLOW, light_r * 2 + gap),
        (TL_GREEN, (light_r * 2 + gap) * 2),
    ):
        ly = top_y + offset
        d.ellipse((cx - light_r, ly - light_r, cx + light_r, ly + light_r), fill=color)

    # لمعة العين (نصف هلال أبيض شفاف أعلى اليسار)
    shine_w = int(eye_w * 0.28)
    shine_h = int(eye_h * 0.30)
    shine_x = cx - eye_w // 3
    shine_y = cy - eye_h // 3
    d.ellipse(
        (shine_x, shine_y, shine_x + shine_w, shine_y + shine_h),
        fill=SHINE,
    )


def _draw_road_arc(img: Image.Image) -> None:
    """قوس طريق أسفل العين — رمز للحركة المرورية."""
    size = img.size[0]
    d = ImageDraw.Draw(img, "RGBA")
    cx = size // 2
    bottom = int(size * 0.88)
    arc_w = int(size * 0.70)
    arc_h = int(size * 0.18)
    box = (cx - arc_w // 2, bottom - arc_h, cx + arc_w // 2, bottom + arc_h)
    line_w = max(3, size // 48)
    # قوس الطريق
    d.arc(box, start=190, end=350, fill=(220, 230, 245, 220), width=line_w)
    # خط متقطع (دوران فاصل المسار)
    dash_count = 5
    arc_len = 160
    for i in range(dash_count):
        a = 190 + (arc_len / dash_count) * (i + 0.3)
        b = a + (arc_len / dash_count) * 0.4
        d.arc(box, start=a, end=b, fill=(241, 196, 15, 230), width=line_w)


def make_icon(size: int) -> Image.Image:
    img = _gradient_background(size)
    _draw_eye(img)
    _draw_road_arc(img)
    # شحذ خفيف للأحجام الصغيرة
    if size <= 64:
        img = img.filter(ImageFilter.SHARPEN)
    return img


def main() -> None:
    sizes_ico = [16, 24, 32, 48, 64, 128, 256]
    images = [make_icon(s) for s in sizes_ico]

    ico_path = ASSETS / "icon.ico"
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes_ico],
        append_images=images[1:],
    )
    print(f"✅ {ico_path}  ({len(sizes_ico)} أحجام)")

    png_hi = make_icon(1024)
    png_path = ASSETS / "icon.png"
    png_hi.save(png_path, format="PNG", optimize=True)
    print(f"✅ {png_path}  (1024×1024)")

    png_ui = make_icon(64)
    ui_path = ASSETS / "icon_64.png"
    png_ui.save(ui_path, format="PNG", optimize=True)
    print(f"✅ {ui_path}  (64×64 للواجهة)")


if __name__ == "__main__":
    main()
