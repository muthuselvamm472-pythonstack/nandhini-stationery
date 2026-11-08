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

BASE_DOMAIN = "http://127.0.0.1:8000"

TIER_CONFIGS = [
    {
        "tier": "50",
        "points": 50,
        "color_name": "PETAL_PINK",
        "chit_name": "Pink Chit",
        "bg_color": "#FFF0F3",
        "border_color": "#BE185D",
        "badge_bg": "#FCE7F3",
        "badge_border": "#BE185D",
        "badge_label": "PINK CHIT  •  STUDENT TIER",
        "sub_text": "Pens, Pencils & Erasers",
        "bill_text": "Rs.50+ Bill",
    },
    {
        "tier": "100",
        "points": 150,
        "color_name": "SKY_BLUE",
        "chit_name": "Blue Chit",
        "bg_color": "#F0F7FF",
        "border_color": "#0284C7",
        "badge_bg": "#E0F2FE",
        "badge_border": "#0284C7",
        "badge_label": "BLUE CHIT  •  1.5x BONUS",
        "sub_text": "Notebooks, Craft & Guides",
        "bill_text": "Rs.100+ Bill",
    },
    {
        "tier": "500",
        "points": 800,
        "color_name": "ROYAL_PURPLE",
        "chit_name": "Purple Chit",
        "bg_color": "#FAF5FF",
        "border_color": "#7E22CE",
        "badge_bg": "#F3E8FF",
        "badge_border": "#7E22CE",
        "badge_label": "PURPLE CHIT  •  1.6x BONUS",
        "sub_text": "School Kits & Geometry",
        "bill_text": "Rs.500+ Bill",
    },
    {
        "tier": "1000",
        "points": 2000,
        "color_name": "MINT_GOLD",
        "chit_name": "Green Chit",
        "bg_color": "#F0FDF4",
        "border_color": "#B45309",
        "badge_bg": "#FEF3C7",
        "badge_border": "#B45309",
        "badge_label": "GREEN CHIT  •  2x DOUBLE VIP",
        "sub_text": "Bulk Books & Office Supply",
        "bill_text": "Rs.1000+ Bill",
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


def render_slip_card(cfg, token, width=540, height=360):
    """Renders a single high-contrast slip card image with live QR code."""
    card = Image.new("RGB", (width, height), cfg["bg_color"])
    draw = ImageDraw.Draw(card)

    font_badge = get_font("arialbd.ttf", 15)
    font_store_name = get_font("georgiab.ttf", 25)
    font_sub = get_font("arialbd.ttf", 14)
    font_points_34 = get_font("impact.ttf", 34)
    font_points_32 = get_font("impact.ttf", 32)
    font_bill = get_font("arialbd.ttf", 17)
    font_token = get_font("arialbd.ttf", 16)
    font_rule = get_font("arialbd.ttf", 13)
    font_scan_tip = get_font("arialbd.ttf", 12)

    # 4px Outer Border
    draw.rectangle([0, 0, width - 1, height - 1], outline=cfg["border_color"], width=4)

    # Top Badge Bar
    draw.rectangle([8, 8, width - 8, 40], fill=cfg["badge_bg"], outline=cfg["border_color"], width=2)
    draw.text((16, 13), cfg["badge_label"], fill="#000000", font=font_badge)
    bbox_bill = draw.textbbox((0, 0), cfg["bill_text"], font=font_badge)
    bill_w = bbox_bill[2] - bbox_bill[0]
    draw.text((width - 16 - bill_w, 13), cfg["bill_text"], fill="#000000", font=font_badge)

    # Generate QR Code
    claim_url = f"{BASE_DOMAIN}/claim/{token}/"
    qr = qrcode.QRCode(
        version=2,
        error_correction=ERROR_CORRECT_M,
        box_size=6,
        border=1,
    )
    qr.add_data(claim_url)
    qr.make(fit=True)
    qr_pil = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")
    qr_img = qr_pil.get_image().convert("RGB").resize((210, 210))

    # QR Container with white frame
    qr_x = 16
    qr_y = 52
    draw.rectangle([qr_x - 3, qr_y - 3, qr_x + 213, qr_y + 213], fill="white", outline="#000000", width=2)
    card.paste(qr_img, (qr_x, qr_y))

    # Instructions under QR
    draw.text((qr_x + 4, qr_y + 224), "Scan with Phone Camera", fill="#000000", font=font_scan_tip)
    draw.text((qr_x + 4, qr_y + 246), "Or Enter Chit ID Below", fill="#000000", font=font_scan_tip)
    draw.text((qr_x + 4, qr_y + 268), "No App or PIN Needed", fill="#000000", font=font_scan_tip)

    # Right Content Area
    tx = qr_x + 230
    draw.text((tx, 52), "NANDHINI", fill="#000000", font=font_store_name)
    draw.text((tx, 80), "STATIONERY", fill="#000000", font=font_store_name)
    draw.text((tx, 112), cfg["sub_text"], fill="#000000", font=font_sub)

    # Points Badge Box
    pts_box = [tx - 4, 142, width - 16, 198]
    pts_text = f"+{cfg['points']} POINTS"
    f_p = font_points_32 if cfg['points'] >= 1000 else font_points_34
    draw.rectangle(pts_box, fill=cfg["badge_bg"], outline=cfg["border_color"], width=2)

    bbox_pts = draw.textbbox((0, 0), pts_text, font=f_p)
    pw = bbox_pts[2] - bbox_pts[0]
    ph = bbox_pts[3] - bbox_pts[1]
    px = pts_box[0] + (pts_box[2] - pts_box[0] - pw) // 2
    py = pts_box[1] + (pts_box[3] - pts_box[1] - ph) // 2 - 2
    draw.text((px, py), pts_text, fill="#000000", font=f_p)

    # Metadata & Rules
    draw.text((tx, 212), f"Bill: Rs.{cfg['tier']}+ Verified", fill="#000000", font=font_bill)
    draw.text((tx, 244), f"Chit ID: {token[:6]}", fill="#000000", font=font_token)
    draw.text((tx, 274), "1 Claim / Person / Day", fill="#000000", font=font_rule)
    draw.text((tx, 298), f"Token: {token}", fill="#475569", font=get_font("arial.ttf", 10))

    return card


def create_slip_record(tier, points):
    token = secrets.token_hex(6).upper()
    slip = QRSlip.objects.create(
        token=token,
        tier=str(tier),
        points_awarded=points,
        batch_number=999,
        is_used=False
    )
    return slip


def generate_all_test_assets():
    results = []

    # 1. Generate Individual Test PNGs for Each Tier - Try 1 (Primary Test Slip)
    for cfg in TIER_CONFIGS:
        slip = create_slip_record(cfg["tier"], cfg["points"])
        card = render_slip_card(cfg, slip.token, width=540, height=360)
        filename = f"test_qr_tier_{cfg['tier']}_{cfg['color_name'].lower()}_chit.png"
        card.save(filename, dpi=(300, 300))
        results.append({
            "filename": filename,
            "tier": cfg["tier"],
            "name": cfg["chit_name"],
            "points": cfg["points"],
            "token": slip.token,
            "try": 1,
            "url": f"{BASE_DOMAIN}/claim/{slip.token}/"
        })
        print(f"[OK] Generated: {filename} -> Token: {slip.token[:6]} (+{cfg['points']} Pts)")

    # 2. Generate Extra Test PNGs for Each Tier - Try 2 (Backup / Secondary Try)
    for cfg in TIER_CONFIGS:
        slip = create_slip_record(cfg["tier"], cfg["points"])
        card = render_slip_card(cfg, slip.token, width=540, height=360)
        filename = f"test_qr_tier_{cfg['tier']}_{cfg['color_name'].lower()}_try2.png"
        card.save(filename, dpi=(300, 300))
        results.append({
            "filename": filename,
            "tier": cfg["tier"],
            "name": cfg["chit_name"],
            "points": cfg["points"],
            "token": slip.token,
            "try": 2,
            "url": f"{BASE_DOMAIN}/claim/{slip.token}/"
        })
        print(f"[OK] Generated: {filename} -> Token: {slip.token[:6]} (+{cfg['points']} Pts)")

    # 3. Generate a combined 4-tier live test grid (Different name from original test_4_tiers_grid.png)
    grid_w = 1100
    grid_h = 760
    gap = 20
    margin = 20
    cw = (grid_w - (margin * 2) - gap) // 2
    ch = (grid_h - (margin * 2) - gap) // 2

    grid_img = Image.new("RGB", (grid_w, grid_h), "#F8FAFC")
    draw_grid = ImageDraw.Draw(grid_img)

    grid_tokens = []
    positions = [
        (margin, margin),
        (margin + cw + gap, margin),
        (margin, margin + ch + gap),
        (margin + cw + gap, margin + ch + gap),
    ]

    for idx, cfg in enumerate(TIER_CONFIGS):
        slip = create_slip_record(cfg["tier"], cfg["points"])
        card = render_slip_card(cfg, slip.token, width=cw, height=ch)
        pos = positions[idx]
        grid_img.paste(card, pos)
        grid_tokens.append({
            "tier": cfg["tier"],
            "name": cfg["chit_name"],
            "points": cfg["points"],
            "token": slip.token,
            "url": f"{BASE_DOMAIN}/claim/{slip.token}/"
        })

    grid_filename = "test_4_tiers_active_qrs_grid.png"
    grid_img.save(grid_filename, dpi=(300, 300))
    print(f"[OK] Generated Combined Grid: {grid_filename}")

    return results, grid_filename, grid_tokens


if __name__ == "__main__":
    generate_all_test_assets()
