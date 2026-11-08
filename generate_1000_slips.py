import os
import secrets
import django
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from qrcode.image.pil import PilImage
from PIL import Image, ImageDraw, ImageFont

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nandhini_stationery.settings')
django.setup()

from rewards.models import QRSlip

# Change this to your live domain when deployed (e.g., https://nandhinistationery.pythonanywhere.com)
BASE_DOMAIN = "http://127.0.0.1:8000"

# 300 DPI A4 Sheet Dimensions
A4_WIDTH = 2480
A4_HEIGHT = 3508
MARGIN_X = 90
MARGIN_Y = 104
COLS = 5
ROWS = 10
SLIPS_PER_SHEET = COLS * ROWS  # 50 QR Slips per A4 page

CELL_W = (A4_WIDTH - (2 * MARGIN_X)) // COLS   # 460 px (~3.9 cm)
CELL_H = (A4_HEIGHT - (2 * MARGIN_Y)) // ROWS  # 330 px (~2.8 cm)

# 4 Light Color Tiers with ULTRA-DARK, RICH-BLACK, HIGH-CONTRAST FONT COLORS
BATCH_CONFIG = [
    {
        "tier": "50",
        "points": 50,
        "count": 250,
        "color_name": "PETAL_PINK",
        "bg_color": "#FFF0F3",          # Light Petal Pink Background
        "border_color": "#BE185D",      # Crisp Dark Rose Border
        "badge_bg": "#FCE7F3",          # Soft Pink Badge Fill
        "badge_border": "#BE185D",
        "badge_label": "PINK CHIT  •  STUDENT TIER",
        "sub_text": "Pens, Pencils & Erasers",
    },
    {
        "tier": "100",
        "points": 150,
        "count": 250,
        "color_name": "SKY_BLUE",
        "bg_color": "#F0F7FF",          # Light Sky Blue Background
        "border_color": "#0284C7",      # Crisp Sky Blue Border
        "badge_bg": "#E0F2FE",          # Soft Sky Badge Fill
        "badge_border": "#0284C7",
        "badge_label": "BLUE CHIT  •  1.5x BONUS",
        "sub_text": "Notebooks, Craft & Guides",
    },
    {
        "tier": "500",
        "points": 800,
        "count": 250,
        "color_name": "ROYAL_PURPLE",
        "bg_color": "#FAF5FF",          # Light Royal Lavender Background
        "border_color": "#7E22CE",      # Crisp Purple Border
        "badge_bg": "#F3E8FF",          # Soft Lavender Badge Fill
        "badge_border": "#7E22CE",
        "badge_label": "PURPLE CHIT  •  1.6x BONUS",
        "sub_text": "School Kits & Geometry",
    },
    {
        "tier": "1000",
        "points": 2000,
        "count": 250,
        "color_name": "MINT_GOLD",
        "bg_color": "#F0FDF4",          # Light Sage Mint Background
        "border_color": "#B45309",      # Crisp Amber-Bronze Border
        "badge_bg": "#FEF3C7",          # Champagne Gold Badge Fill
        "badge_border": "#B45309",
        "badge_label": "GREEN CHIT  •  2x DOUBLE VIP",
        "sub_text": "Bulk Books & Office Supply",
    },
]


def get_font(font_name, size):
    try:
        return ImageFont.truetype(font_name, size)
    except Exception:
        pass
    for fallback in ["georgiab.ttf", "arialbd.ttf", "georgia.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(fallback, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def generate_1000_slips_on_a4():
    output_dir = "printable_a4_sheets"
    os.makedirs(output_dir, exist_ok=True)

    # High-legibility Fonts: Editorial Georgia Bold + Arial Bold + Impact
    font_page_header = get_font("georgiab.ttf", 34)
    font_badge = get_font("arialbd.ttf", 15)
    font_store_name = get_font("georgiab.ttf", 25)
    font_sub = get_font("arialbd.ttf", 14)
    font_points_34 = get_font("impact.ttf", 34)
    font_points_32 = get_font("impact.ttf", 32)
    font_bill = get_font("arialbd.ttf", 17)
    font_token = get_font("arialbd.ttf", 16)
    font_rule = get_font("arialbd.ttf", 13)
    font_scan_tip = get_font("arialbd.ttf", 12)

    # Clean up existing unused slips to generate fresh slips
    QRSlip.objects.filter(is_used=False).delete()
    print("Cleaned existing unused slips to generate fresh ultra-dark high-contrast set.")

    total_slips_created = 0

    for cfg in BATCH_CONFIG:
        tier = cfg["tier"]
        points = cfg["points"]
        pages = cfg["count"] // SLIPS_PER_SHEET  # 250 / 50 = 5 A4 sheets per tier

        for page_num in range(1, pages + 1):
            sheet = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), "#FFFFFF")
            draw = ImageDraw.Draw(sheet)

            # Elegant High-Contrast Page Header
            header_note = (
                f"NANDHINI STATIONERY  •  TIER Rs.{tier}+ (+{points} PTS)  •  "
                f"{cfg['color_name']} COLOR SLIPS  •  PAGE {page_num} OF {pages}"
            )
            draw.text((MARGIN_X, 42), header_note, fill="#000000", font=font_page_header)
            draw.line([(MARGIN_X, 86), (A4_WIDTH - MARGIN_X, 86)], fill=cfg["border_color"], width=3)

            for idx in range(SLIPS_PER_SHEET):
                r = idx // COLS
                c = idx % COLS
                x1 = MARGIN_X + (c * CELL_W)
                y1 = MARGIN_Y + (r * CELL_H)
                x2 = x1 + CELL_W
                y2 = y1 + CELL_H

                # Draw cell with exact tier light background and crisp 4px border
                draw.rectangle([x1, y1, x2, y2], fill=cfg["bg_color"], outline=cfg["border_color"], width=4)

                # Top Badge Banner with deep dark high-contrast text
                draw.rectangle([x1 + 8, y1 + 8, x2 - 8, y1 + 38], fill=cfg["badge_bg"], outline=cfg["border_color"], width=2)
                draw.text((x1 + 14, y1 + 12), cfg["badge_label"], fill="#000000", font=font_badge)
                bill_label = f"Rs.{tier}+ Bill"
                bbox_bill = draw.textbbox((0, 0), bill_label, font=font_badge)
                draw.text((x2 - 14 - (bbox_bill[2] - bbox_bill[0]), y1 + 12), bill_label, fill="#000000", font=font_badge)

                # Create DB record with 12-char cryptographic token
                token = secrets.token_hex(6).upper()
                QRSlip.objects.create(
                    token=token,
                    tier=tier,
                    points_awarded=points,
                    batch_number=1
                )
                total_slips_created += 1

                # Generate compact QR code (200x200)
                claim_url = f"{BASE_DOMAIN}/claim/{token}/"
                qr = qrcode.QRCode(
                    version=2,
                    error_correction=ERROR_CORRECT_M,
                    box_size=5,
                    border=1,
                )
                qr.add_data(claim_url)
                qr.make(fit=True)
                qr_pil = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")
                qr_img = qr_pil.get_image().convert("RGB").resize((200, 200))

                # Paste QR code with solid white background frame
                qr_x = x1 + 16
                qr_y = y1 + 48
                draw.rectangle([qr_x - 3, qr_y - 3, qr_x + 203, qr_y + 203], fill="white", outline="#000000", width=2)
                sheet.paste(qr_img, (qr_x, qr_y))

                # Helper tips under QR code
                draw.text((qr_x + 4, qr_y + 212), "Scan with Phone Camera", fill="#000000", font=font_scan_tip)
                draw.text((qr_x + 4, qr_y + 232), "No App or PIN Needed", fill="#000000", font=font_scan_tip)

                # Text positioning on right side: 100% PITCH BLACK, ULTRA CONTRAST
                tx = qr_x + 218
                draw.text((tx, y1 + 46), "NANDHINI", fill="#000000", font=font_store_name)
                draw.text((tx, y1 + 72), "STATIONERY", fill="#000000", font=font_store_name)
                draw.text((tx, y1 + 100), cfg["sub_text"], fill="#000000", font=font_sub)

                # High-Impact Points Box with centered text
                pts_box = [tx - 4, y1 + 126, x2 - 12, y1 + 178]
                pts_text = f"+{points} POINTS"
                f_p = font_points_32 if points >= 1000 else font_points_34
                draw.rectangle(pts_box, fill=cfg["badge_bg"], outline=cfg["border_color"], width=2)

                bbox = draw.textbbox((0, 0), pts_text, font=f_p)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                px = pts_box[0] + (pts_box[2] - pts_box[0] - tw) // 2
                py = pts_box[1] + (pts_box[3] - pts_box[1] - th) // 2 - 2
                draw.text((px, py), pts_text, fill="#000000", font=f_p)

                # Verification details in solid black
                draw.text((tx, y1 + 192), f"Bill: Rs.{tier}+ Verified", fill="#000000", font=font_bill)
                draw.text((tx, y1 + 222), f"Token: {token[:6]}", fill="#000000", font=font_token)
                draw.text((tx, y1 + 248), "1 Claim / Person / Day", fill="#000000", font=font_rule)

            filename = f"{output_dir}/Tier_{tier}_{cfg['color_name']}_Page_{page_num}.png"
            sheet.save(filename, dpi=(300, 300))
            print(f"Created A4 Sheet ({cfg['color_name']}): {filename}")

    print(f"\nSUCCESS: {total_slips_created} slips regenerated with ultra-dark, high-contrast text across 20 A4 sheets!")


if __name__ == "__main__":
    generate_1000_slips_on_a4()

