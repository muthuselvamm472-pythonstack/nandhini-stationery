import csv
import json
import os
import re
import base64
import threading
import time
import logging
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.core.cache import cache
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.http import url_has_allowed_host_and_scheme
from .models import Customer, QRSlip, RedemptionLog, SlipTierConfig, GiftRewardItem, RewardItem, BroadcastNotification, SystemSetting, PushSubscription
from .sanitizer import sanitize_text
from py_vapid import Vapid
from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

DEFAULT_PURE_REWARDS = [
    {
        'points_required': 350,
        'icon': '✨',
        'name': 'Premium Gel Pen / Highlighter',
        'description': 'Smooth waterproof gel pen or pastel highlighter',
    },
    {
        'points_required': 1000,
        'icon': '📓',
        'name': '80-Page Long Notebook / Exam Pad',
        'description': 'High-quality ruled/unruled long notebook or exam board',
    },
    {
        'points_required': 2500,
        'icon': '📐',
        'name': 'Branded Geometry Box / Art & Sketch Kit',
        'description': 'Complete mathematical drawing set or color art kit',
    },
    {
        'points_required': 5000,
        'icon': '🎒',
        'name': 'VIP School Backpack / ₹300 Stationery Voucher',
        'description': 'Grand reward for our top regulars',
    },
]

# Legacy fallback (Pure stationery only, zero Xerox/binding)
REWARD_CATALOG = [
    {'name': 'Premium Gel Pen / Highlighter', 'points': 350, 'icon': '✨', 'desc': 'Smooth waterproof gel pen or pastel highlighter'},
    {'name': '80-Page Long Notebook / Exam Pad', 'points': 1000, 'icon': '📓', 'desc': 'High-quality ruled/unruled long notebook or exam board'},
    {'name': 'Branded Geometry Box / Art & Sketch Kit', 'points': 2500, 'icon': '📐', 'desc': 'Complete mathematical drawing set or color art kit'},
    {'name': 'VIP School Backpack / ₹300 Stationery Voucher', 'points': 5000, 'icon': '🎒', 'desc': 'Grand reward for our top regulars'},
]


def ensure_default_reward_items():
    """Ensure RewardItem model is seeded with default pure stationery tiers (50 Pts tier removed)"""
    # Clean up any legacy 50 Pts tier or items with Xerox/binding
    RewardItem.objects.filter(points_required=50).delete()
    RewardItem.objects.filter(Q(name__icontains='xerox') | Q(description__icontains='xerox') | Q(name__icontains='binding')).delete()
    
    if RewardItem.objects.count() == 0:
        for item in DEFAULT_PURE_REWARDS:
            RewardItem.objects.create(
                name=item['name'],
                points_required=item['points_required'],
                icon=item['icon'],
                description=item['description'],
                is_active=True
            )


# 9 Psychological Presets (Pure Stationery & Local Geo-Targeting: Pallavaram, Pammal, Anakaputhur)
PSYCHOLOGICAL_PRESETS = {
    'morning_reset': {
        'id': 'morning_reset',
        'name': '🪙 Morning "2nd Slip in Pouch" Reset (7:30 AM – 9:30 AM)',
        'title': '🪙 Your daily QR scan lock just reset!',
        'message': 'Got an extra Pink or Blue slip in your pouch from yesterday? Scan your saved Nandhini Stationery slip now in 5 seconds before heading to class! ✨',
        'haptic': 'pulse',
        'start_hour': 7,
        'start_min': 30,
        'end_hour': 9,
        'end_min': 30,
        'days': [0, 1, 2, 3, 4, 5, 6],
    },
    'break_time': {
        'id': 'break_time',
        'name': '☕ Afternoon Break (11:00 AM – 2:00 PM)',
        'title': '☕ Afternoon Break (11:00 AM – 2:00 PM) | நந்தினி ஸ்டேஷனரி',
        'message': 'Store break time is active from 11:00 AM to 2:00 PM across Pallavaram, Pammal & Anakaputhur. Gift rewards & chit scanning resume promptly at 2:00 PM! 🎁',
        'haptic': 'celebration',
        'start_hour': 11,
        'start_min': 0,
        'end_hour': 14,
        'end_min': 0,
        'days': [0, 1, 2, 3, 4, 5, 6],
    },
    'social_proof': {
        'id': 'social_proof',
        'name': '🏆 Pallavaram • Pammal • Anakaputhur Social Proof (9:30 AM – 11:00 AM)',
        'title': '🏆 Local students are claiming Free Stationery Gifts today!',
        'message': 'Shoppers across Pallavaram, Pammal & Anakaputhur are winning free pens, notebooks & geometry sets at நந்தினி ஸ்டேஷனரி! Check your points balance now!',
        'haptic': 'celebration',
        'start_hour': 9,
        'start_min': 30,
        'end_hour': 11,
        'end_min': 0,
        'days': [0, 1, 2, 3, 4],
    },
    'exam_week': {
        'id': 'exam_week',
        'name': '📚 Afternoon Exam Pad & Art Supplies (2:00 PM – 4:30 PM)',
        'title': '📝 Exam Pads, Geometry Sets & Fresh Art Supplies in Stock!',
        'message': 'Stock up on smooth pens, exam boards, sketchbooks, acrylic colors, and geometry boxes at Nandhini Stationery—and scan your slip for bonus points!',
        'haptic': 'pulse',
        'start_hour': 14,
        'start_min': 0,
        'end_hour': 16,
        'end_min': 30,
        'days': [0, 1, 2, 3, 4, 5, 6],
    },
    'after_school': {
        'id': 'after_school',
        'name': '🖊️ After-School "Reserved Gift" Alert (4:30 PM – 6:00 PM)',
        'title': '🖊️ Your FREE Gift is waiting at our counter!',
        'message': 'Walking home around Pallavaram, Pammal, or Anakaputhur? Stop by Nandhini Stationery to claim your unlocked Pen, Highlighter, or Notebook! 🎁',
        'haptic': 'celebration',
        'start_hour': 16,
        'start_min': 30,
        'end_hour': 18,
        'end_min': 0,
        'days': [0, 1, 2, 3, 4, 5],
    },
    'milestone_sprint': {
        'id': 'milestone_sprint',
        'name': '🎯 Evening Milestone Sprint (6:30 PM – 8:30 PM)',
        'title': '🔥 Almost Unlocked: Just 1 scan away from your Free Gift!',
        'message': 'Check your progress bar! Just one more QR slip pushes you to your next free stationery reward at Nandhini Stationery!',
        'haptic': 'pulse',
        'start_hour': 18,
        'start_min': 30,
        'end_hour': 20,
        'end_min': 30,
        'days': [0, 1, 2, 3, 4, 5, 6],
    },
    'sunday_check': {
        'id': 'sunday_check',
        'name': '🎒 Sunday Evening School-Bag Check (Sunday 5:45 PM – 9:00 PM)',
        'title': '🎒 10-Second Monday Check: Is your pencil box ready?',
        'message': 'Out of blue/black pens, graph sheets, map books, or long notebooks for Monday morning? Visit Nandhini Stationery tonight & grab your daily QR slip! 📐',
        'haptic': 'pulse',
        'start_hour': 17,
        'start_min': 45,
        'end_hour': 21,
        'end_min': 0,
        'days': [6],
    },
    'weekend_hack': {
        'id': 'weekend_hack',
        'name': '💡 Smart Student 3X Points Hack (Weekend 10:00 AM – 4:00 PM)',
        'title': '💡 Secret Hack: Get 3X Points on ₹100+ bills!',
        'message': 'A ₹50 Pink Slip gives +50 Pts, but a ₹100 Blue Slip gives +150 POINTS (50% Bonus)! Bundle your notebooks, pens & pouches today to unlock gifts 3x faster! 🚀',
        'haptic': 'celebration',
        'start_hour': 10,
        'start_min': 0,
        'end_hour': 16,
        'end_min': 0,
        'days': [5, 6],
    },
    'win_back': {
        'id': 'win_back',
        'name': '🔒 Inactive Customer Win-Back (3:00 PM – 6:00 PM)',
        'title': '🔒 Your Loyalty Points are safe & waiting for you!',
        'message': "Don't let your hard-earned points sit idle! Pop into Nandhini Stationery this week for your stationery refills and unlock your next free gift! ⭐",
        'haptic': 'pulse',
        'start_hour': 15,
        'start_min': 0,
        'end_hour': 18,
        'end_min': 0,
        'days': [1, 3, 5],
    },
}


def get_current_active_broadcast():
    """Resolves current active broadcast considering manual priority and automated schedule"""
    # 1. Manual active broadcast takes instant top priority
    manual_broadcast = BroadcastNotification.objects.filter(is_active=True, is_automated=False).order_by('-created_at').first()
    if manual_broadcast:
        return manual_broadcast

    # 2. Check if Auto-Pilot is enabled
    autopilot_setting = SystemSetting.objects.filter(key='autopilot_enabled').first()
    autopilot_on = (autopilot_setting.value != 'false') if autopilot_setting else True

    if not autopilot_on:
        return BroadcastNotification.objects.filter(is_active=True).order_by('-created_at').first()

    # 3. Auto-Pilot schedule evaluation in local IST time
    now = timezone.localtime(timezone.now())
    current_hour = now.hour
    current_minute = now.minute
    current_weekday = now.weekday()  # Monday=0, Sunday=6
    current_time_dec = current_hour + (current_minute / 60.0)

    matched_preset_key = None
    for pkey, pcfg in PSYCHOLOGICAL_PRESETS.items():
        if current_weekday in pcfg['days']:
            start_dec = pcfg['start_hour'] + (pcfg['start_min'] / 60.0)
            end_dec = pcfg['end_hour'] + (pcfg['end_min'] / 60.0)
            if start_dec <= current_time_dec <= end_dec:
                matched_preset_key = pkey
                break

    if matched_preset_key:
        preset = PSYCHOLOGICAL_PRESETS[matched_preset_key]
        today = now.date()
        existing = BroadcastNotification.objects.filter(
            is_automated=True,
            preset_key=matched_preset_key,
            created_at__date=today
        ).first()

        if existing:
            return existing
        else:
            BroadcastNotification.objects.filter(is_automated=True).update(is_active=False)
            new_auto = BroadcastNotification.objects.create(
                title=preset['title'],
                message=preset['message'],
                haptic_style=preset['haptic'],
                is_active=True,
                is_automated=True,
                preset_key=matched_preset_key
            )
            # Instantly push WebPush to all registered devices (phones & computers) even if website is closed
            try:
                dispatch_webpush_to_all(new_auto.title, new_auto.message, new_auto.haptic_style)
            except Exception as e:
                logger.error(f"Auto-dispatch WebPush failed: {e}")
            return new_auto

    # Default fallback to latest active broadcast
    return BroadcastNotification.objects.filter(is_active=True).order_by('-created_at').first()


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def build_milestone_context(total_points):
    ensure_default_reward_items()
    # Dynamically pull active gifts from RewardItem model first
    db_rewards = list(RewardItem.objects.filter(is_active=True).order_by('points_required'))
    if db_rewards:
        catalog = [
            {'id': r.id, 'name': r.name, 'points': r.points_required, 'icon': r.icon, 'desc': r.description}
            for r in db_rewards
        ]
    else:
        # Fallback to GiftRewardItem or DEFAULT_PURE_REWARDS
        db_gifts = list(GiftRewardItem.objects.filter(is_active=True).order_by('points', 'sort_order'))
        if db_gifts:
            catalog = [
                {'id': g.id, 'name': g.name, 'points': g.points, 'icon': g.icon, 'desc': g.desc}
                for g in db_gifts
            ]
        else:
            catalog = REWARD_CATALOG

    # Milestones for tracker (dynamically adapts to all active configured gifts)
    milestones = []
    prev_threshold = 0
    for item in catalog:
        m_pts = item['points']
        if total_points >= m_pts:
            seg_pct = 100
        elif total_points > prev_threshold:
            diff = m_pts - prev_threshold
            seg_pct = max(0, min(100, int(((total_points - prev_threshold) / diff) * 100))) if diff > 0 else 0
        else:
            seg_pct = 0

        milestones.append({
            'points': item['points'],
            'name': item['name'],
            'icon': item['icon'],
            'unlocked': total_points >= item['points'],
            'segment_pct': seg_pct,
        })
        prev_threshold = m_pts

    next_reward = catalog[-1]
    for item in catalog:
        if total_points < item['points']:
            next_reward = item
            break

    points_needed = max(next_reward['points'] - total_points, 0)
    goal_pct = min(100, int((total_points / next_reward['points']) * 100)) if next_reward['points'] > 0 else 100

    return {
        'rewards': catalog,
        'next_reward': next_reward,
        'goal_pct': goal_pct,
        'points_needed': points_needed,
        'milestones': milestones,
    }


def check_phone_api(request):
    """Instant lookup to tell frontend if this is a returning customer or a first-time visitor"""
    phone = request.GET.get('phone', '').strip()
    if phone.isdigit() and len(phone) == 10:
        customer = Customer.objects.filter(phone_number=phone).first()
        if customer:
            return JsonResponse({'exists': True, 'name': customer.name})
        return JsonResponse({'exists': False})
    return JsonResponse({'exists': False, 'error': 'Invalid mobile number'})


_db_checked = False


def ensure_database_ready():
    global _db_checked
    if not _db_checked:
        try:
            from django.db import connection
            tables = connection.introspection.table_names()
            if 'rewards_customer' not in tables:
                from django.core.management import call_command
                call_command('migrate', interactive=False)
            _db_checked = True
        except Exception as e:
            logger.warning(f"ensure_database_ready notice: {e}")


def customer_login(request):
    ensure_database_ready()
    raw_next = request.GET.get('next', '/dashboard/')
    next_url = raw_next if url_has_allowed_host_and_scheme(raw_next, allowed_hosts={request.get_host()}) else '/dashboard/'

    if request.method == 'POST':
        phone = request.POST.get('phone_number', '').strip()
        name = sanitize_text(request.POST.get('name', ''), max_length=60)
        raw_post_next = request.POST.get('next', '/dashboard/')
        next_post = raw_post_next if url_has_allowed_host_and_scheme(raw_post_next, allowed_hosts={request.get_host()}) else '/dashboard/'

        if not (phone.isdigit() and len(phone) == 10):
            messages.error(request, 'Please enter a valid 10-digit mobile number.')
            return render(request, 'rewards/login.html', {'next': next_post, 'phone': phone, 'name': name})

        customer = Customer.objects.filter(phone_number=phone).first()

        if customer:
            # Returning customer: Frictionless instant login
            if name:
                # Check that name has letters only if updated
                clean_name = re.sub(r'[\s.]+', '', name)
                if clean_name and not clean_name.isalpha():
                    messages.error(request, 'Name should only contain letters.')
                    return render(request, 'rewards/login.html', {'next': next_post, 'phone': phone, 'name': name})
                if customer.name == 'Valued Customer' or not customer.name:
                    customer.name = name
                    customer.save(update_fields=['name'])
            request.session.cycle_key()
            request.session['customer_id'] = customer.id
            messages.success(request, f'Welcome back, {customer.name}!')
            return redirect(next_post)
        else:
            # First-time visitor: Name is strictly COMPULSORY!
            if not name:
                messages.error(request, 'First-time visitors must enter their name to register.')
                return render(request, 'rewards/login.html', {
                    'next': next_post,
                    'phone': phone,
                    'name': name,
                    'is_new_customer': True
                })

            # Check that name contains letters only
            clean_name = re.sub(r'[\s.]+', '', name)
            if not clean_name or not clean_name.isalpha():
                messages.error(request, 'Name should only contain letters.')
                return render(request, 'rewards/login.html', {
                    'next': next_post,
                    'phone': phone,
                    'name': name,
                    'is_new_customer': True
                })

            bonus_cfg = get_welcome_bonus_settings()
            initial_pts = bonus_cfg['points'] if bonus_cfg['enabled'] else 0

            customer = Customer.objects.create(
                phone_number=phone,
                name=name,
                pin_code='',
                total_points=initial_pts
            )
            request.session.cycle_key()
            request.session['customer_id'] = customer.id
            if initial_pts > 0:
                request.session['welcome_bonus_awarded'] = initial_pts
                messages.success(request, f'🎉 Welcome to Nandhini Stationery, {name}! You received +{initial_pts} Free Welcome Points!')
            else:
                messages.success(request, f'Welcome to Nandhini Stationery, {name}! Your loyalty account is active. Scan purchase slips to unlock free rewards!')
            return redirect(next_post)

    return render(request, 'rewards/login.html', {'next': next_url})


def customer_logout(request):
    request.session.flush()
    return redirect('/login/')


def scan_token_redirect(request):
    """Handles manual token entry or camera scanner redirect from the Dashboard"""
    raw_input = request.GET.get('token', '').strip()
    if not raw_input:
        messages.error(request, 'Please scan a valid QR slip or enter a token code.')
        return redirect('/dashboard/')

    # If the scanner read a full URL like http://.../claim/A1B2C3D4E5F6/, extract the token
    if '/claim/' in raw_input:
        clean_token = raw_input.split('/claim/')[-1].strip('/').upper()
    else:
        clean_token = raw_input.upper()

    # Also allow matching by 6-character printed slip ID prefix if unambiguous
    if len(clean_token) == 6:
        matched_slip = QRSlip.objects.filter(token__startswith=clean_token, is_used=False).first()
        if not matched_slip:
            matched_slip = QRSlip.objects.filter(token__startswith=clean_token).first()
        if matched_slip:
            clean_token = matched_slip.token

    return redirect(f'/claim/{clean_token}/')


DEFAULT_WHATSAPP_SHARE_TEMPLATE = (
    "Hey friends! 🎁 Collect free gift rewards and points every time you buy books and pens at Nandhini Stationery (Pallavaram)! "
    "I have {points} Points saved. Check it out: {link} ✨"
)

DEFAULT_SCRATCH_SHARE_TEMPLATE = (
    "Hey friends! 🎁 I just won +{points_won} Points at Nandhini Stationery (Pallavaram)! "
    "My balance is now {points} Pts. Collect your loyalty stamps every time you shop: {link} ✨"
)

DEFAULT_FOUNDER_TITLE = "Founder • Nandhini Stationery"
DEFAULT_FOUNDER_MOTTO = "Founded on trust, integrity, and a passion for learning — dedicated to serving students, schools, and families with excellence."
DEFAULT_FOUNDER_PHOTO_URL = "/founder-photo.jpg"


def get_founder_settings():
    """Retrieves dynamic Founder & Brand Identity settings with safe defaults"""
    try:
        enabled_s = SystemSetting.objects.filter(key='founder_enabled').first()
        title_s = SystemSetting.objects.filter(key='founder_title').first()
        motto_s = SystemSetting.objects.filter(key='founder_motto').first()
        photo_s = SystemSetting.objects.filter(key='founder_photo_url').first()
        map_s = SystemSetting.objects.filter(key='founder_map_enabled').first()

        return {
            'founder_enabled': (enabled_s.value != 'false') if enabled_s else True,
            'founder_title': title_s.value.strip() if title_s and title_s.value.strip() else DEFAULT_FOUNDER_TITLE,
            'founder_motto': motto_s.value.strip() if motto_s and motto_s.value.strip() else DEFAULT_FOUNDER_MOTTO,
            'founder_photo_url': photo_s.value.strip() if photo_s and photo_s.value.strip() else DEFAULT_FOUNDER_PHOTO_URL,
            'founder_map_enabled': (map_s.value != 'false') if map_s else True,
            'default_founder_title': DEFAULT_FOUNDER_TITLE,
            'default_founder_motto': DEFAULT_FOUNDER_MOTTO,
        }
    except Exception:
        return {
            'founder_enabled': True,
            'founder_title': DEFAULT_FOUNDER_TITLE,
            'founder_motto': DEFAULT_FOUNDER_MOTTO,
            'founder_photo_url': DEFAULT_FOUNDER_PHOTO_URL,
            'founder_map_enabled': True,
            'default_founder_title': DEFAULT_FOUNDER_TITLE,
            'default_founder_motto': DEFAULT_FOUNDER_MOTTO,
        }


DEFAULT_WELCOME_BONUS_POINTS = 50
DEFAULT_DAILY_SCAN_LIMIT = 3


def get_daily_scan_limit_settings():
    """Retrieves dynamic daily chit scan limit settings with safe defaults"""
    try:
        enabled_s = SystemSetting.objects.filter(key='daily_scan_limit_enabled').first()
        limit_s = SystemSetting.objects.filter(key='daily_scan_limit_count').first()
        is_enabled = (enabled_s.value != 'false') if enabled_s else True
        limit_val = int(limit_s.value) if limit_s and limit_s.value.isdigit() else DEFAULT_DAILY_SCAN_LIMIT
        return {
            'enabled': is_enabled,
            'limit': limit_val,
        }
    except Exception:
        return {
            'enabled': True,
            'limit': DEFAULT_DAILY_SCAN_LIMIT,
        }


def get_welcome_bonus_settings():
    """Retrieves dynamic Welcome Bonus settings with safe defaults"""
    try:
        enabled_s = SystemSetting.objects.filter(key='welcome_bonus_enabled').first()
        pts_s = SystemSetting.objects.filter(key='welcome_bonus_points').first()
        is_enabled = (enabled_s.value != 'false') if enabled_s else True
        pts = int(pts_s.value) if pts_s and pts_s.value.isdigit() else DEFAULT_WELCOME_BONUS_POINTS
        return {
            'enabled': is_enabled,
            'points': pts,
        }
    except Exception:
        return {
            'enabled': True,
            'points': DEFAULT_WELCOME_BONUS_POINTS,
        }


def founder_context_processor(request):
    """Context processor making founder_settings, welcome_bonus_settings, and daily_scan_limit_settings globally available to all templates"""
    return {
        'founder_settings': get_founder_settings(),
        'welcome_bonus_settings': get_welcome_bonus_settings(),
        'daily_scan_limit_settings': get_daily_scan_limit_settings(),
    }


def get_whatsapp_settings(request=None):
    template_setting = SystemSetting.objects.filter(key='whatsapp_share_template').first()
    scratch_setting = SystemSetting.objects.filter(key='whatsapp_scratch_template').first()
    link_setting = SystemSetting.objects.filter(key='whatsapp_store_link').first()

    template = template_setting.value.strip() if template_setting and template_setting.value.strip() else DEFAULT_WHATSAPP_SHARE_TEMPLATE
    scratch_template = scratch_setting.value.strip() if scratch_setting and scratch_setting.value.strip() else DEFAULT_SCRATCH_SHARE_TEMPLATE

    if link_setting and link_setting.value.strip():
        store_link = link_setting.value.strip()
    elif request:
        store_link = request.build_absolute_uri('/')
    else:
        store_link = "http://127.0.0.1:8000/"

    return template, scratch_template, store_link


def format_whatsapp_share_url(customer, request=None, points_won=None):
    import urllib.parse
    template, scratch_template, store_link = get_whatsapp_settings(request)
    chosen_template = scratch_template if points_won is not None else template

    points_val = str(customer.total_points if customer else 250)
    name_val = str(customer.name if customer else 'Friend')

    msg = chosen_template.replace('{points}', points_val)
    msg = msg.replace('{name}', name_val)
    msg = msg.replace('{link}', store_link)
    if points_won is not None:
        msg = msg.replace('{points_won}', str(points_won))

    # Safety check: if admin forgot {link} placeholder in custom message, append it cleanly
    if store_link and store_link not in msg:
        msg = f"{msg.strip()} {store_link}".strip()

    return f"https://api.whatsapp.com/send?text={urllib.parse.quote(msg)}"


def format_sample_whatsapp_message(chosen_template, store_link, customer=None, points_won=None):
    points_val = str(customer.total_points if customer else 250)
    name_val = str(customer.name if customer else 'Muthu selvam')

    msg = chosen_template.replace('{points}', points_val)
    msg = msg.replace('{name}', name_val)
    msg = msg.replace('{link}', store_link)
    if points_won is not None:
        msg = msg.replace('{points_won}', str(points_won))
    if store_link and store_link not in msg:
        msg = f"{msg.strip()} {store_link}".strip()
    return msg


def claim_qr_slip(request, token):
    # 1. IP Brute-Force Protection (Loophole #3 Solution)
    client_ip = get_client_ip(request)
    block_key = f"ip_fail_count_{client_ip}"
    fail_count = cache.get(block_key, 0)

    if fail_count >= 5:
        return render(request, 'rewards/error.html', {
            'title': 'Security Lock Activated',
            'message': 'Too many invalid QR attempts from your device. Access is paused for 24 hours. If this was a mistake, please speak to the shop counter.',
            'code': 'ERR_RATE_LIMIT',
            'show_contact_buttons': True
        }, status=429)

    # 2. Require Customer Session
    customer_id = request.session.get('customer_id')
    if not customer_id:
        return redirect(f"/login/?next=/claim/{token}/")

    today = timezone.localdate()
    clean_token = token.strip().upper()

    # 3. Atomic Row-Level Database Lock (Prevents Race Condition Double Scans)
    try:
        with transaction.atomic():  # type: ignore
            customer = Customer.objects.select_for_update().filter(id=customer_id).first()
            if not customer:
                request.session.flush()
                return redirect(f"/login/?next=/claim/{clean_token}/")

            slip = QRSlip.objects.select_for_update().filter(token=clean_token).first()

            # Gate A: Invalid Token Check
            if not slip:
                cache.set(block_key, fail_count + 1, timeout=86400)  # 24-hour counter
                return render(request, 'rewards/error.html', {
                    'title': 'Invalid QR Code',
                    'message': f'This QR slip is not recognized. Please verify the code printed on your paper chit ({4 - fail_count} attempts remaining).',
                    'code': 'ERR_INVALID_TOKEN',
                    'show_contact_buttons': True
                }, status=404)

            # Gate B: Already Claimed Check (Resilient Grace Window for Network Interruption & Disconnects)
            if slip.is_used:
                local_claimed_time = timezone.localtime(slip.claimed_at)

                # Check if this exact customer claimed this slip
                if slip.claimed_by and slip.claimed_by.id == customer.id:
                    time_diff = (timezone.now() - slip.claimed_at).total_seconds()
                    # Grace window: If claimed within last 15 minutes, re-show celebratory card!
                    if time_diff <= 900:
                        context = {
                            'customer': customer,
                            'slip': slip,
                            'points_won': slip.points_awarded,
                            'is_revisit': True,
                            'claimed_time_str': local_claimed_time.strftime("%I:%M %p"),
                            'whatsapp_share_url': format_whatsapp_share_url(customer, request=request, points_won=slip.points_awarded),
                            **build_milestone_context(customer.total_points),
                        }
                        return render(request, 'rewards/scratch_card.html', context)
                    else:
                        # Re-scanned days or hours later: Reassuring confirmation
                        return render(request, 'rewards/error.html', {
                            'title': 'Chit Already Claimed by You',
                            'message': (
                                f'You already claimed this purchase chit on {local_claimed_time.strftime("%d %b %Y at %I:%M %p")}. '
                                f'+{slip.points_awarded} Points are already in your balance ({customer.total_points} Pts total). '
                                f'Each printed chit can only be used once.'
                            ),
                            'code': 'INFO_ALREADY_CLAIMED',
                            'is_friendly_info': True
                        })

                # Claimed by someone else:
                masked_phone = "******" + slip.claimed_by.phone_number[-4:] if slip.claimed_by else "Unknown"
                return render(request, 'rewards/error.html', {
                    'title': 'QR Slip Already Claimed',
                    'message': (
                        f'This slip was claimed on {local_claimed_time.strftime("%d %b %Y at %I:%M %p")} '
                        f'by another member ({masked_phone}). Each purchase chit can only be used once. '
                        f'If you just made a fresh purchase at the counter, please ask shop staff for a new chit.'
                    ),
                    'code': 'ERR_ALREADY_USED',
                    'show_contact_buttons': True
                })

            # Gate C: Daily Chit Scan Ceiling (Fair-Use Protection)
            daily_limit_cfg = get_daily_scan_limit_settings()
            if daily_limit_cfg['enabled']:
                today_claimed_count = customer.claimed_slips.filter(claimed_at__date=today).count()
                if today_claimed_count >= daily_limit_cfg['limit']:
                    return render(request, 'rewards/error.html', {
                        'title': 'Daily Chit Limit Reached',
                        'message': (
                            f"You have already claimed {today_claimed_count} purchase chit{'s' if today_claimed_count != 1 else ''} today! "
                            f"Your paper chit is 100% safe and valid. Please keep it in your pouch "
                            f"and scan it tomorrow morning to claim your points! ✨"
                        ),
                        'code': 'INFO_DAILY_LIMIT_REACHED',
                        'is_friendly_info': True,
                    })

            # All Checks Passed -> Expire Slip & Award Points
            slip.is_used = True
            slip.claimed_by = customer
            slip.claimed_at = timezone.now()
            slip.save()

            customer.total_points += slip.points_awarded
            # Increment visit count once per calendar day (no visit inflation on multiple scans)
            if customer.last_scan_date != today:
                customer.total_visits += 1
                customer.last_scan_date = today
            customer.save()

    except Exception:
        return render(request, 'rewards/error.html', {
            'title': 'Temporary Network Busy',
            'message': 'Please wait 2 seconds and scan the QR slip again.',
            'code': 'ERR_CONCURRENCY',
            'show_contact_buttons': True
        })

    context = {
        'customer': customer,
        'slip': slip,
        'points_won': slip.points_awarded,
        'is_revisit': False,
        'whatsapp_share_url': format_whatsapp_share_url(customer, request=request, points_won=slip.points_awarded),
        **build_milestone_context(customer.total_points),
    }
    return render(request, 'rewards/scratch_card.html', context)


def customer_dashboard(request):
    customer_id = request.session.get('customer_id')
    if not customer_id:
        return redirect('/login/')

    customer = Customer.objects.filter(id=customer_id).first()
    if not customer:
        request.session.flush()
        return redirect('/login/')

    recent_scans = customer.claimed_slips.order_by('-claimed_at')[:10]
    recent_redemptions = customer.redemptions.order_by('-redeemed_at')[:10]
    tiers = SlipTierConfig.objects.all().order_by('sort_order', 'min_spend')

    welcome_bonus_awarded = request.session.pop('welcome_bonus_awarded', None)

    context = {
        'customer': customer,
        'recent_scans': recent_scans,
        'recent_redemptions': recent_redemptions,
        'tiers': tiers,
        'active_broadcast': get_current_active_broadcast(),
        'whatsapp_share_url': format_whatsapp_share_url(customer, request=request),
        'welcome_bonus_awarded': welcome_bonus_awarded,
        **build_milestone_context(customer.total_points),
    }
    return render(request, 'rewards/dashboard.html', context)


@staff_member_required(login_url='/admin/login/')
def owner_admin_dashboard(request):
    """Owner's Live Monitoring & Customer Directory (/nandhini-admin/)"""
    today = timezone.localdate()
    search_query = request.GET.get('q', '').strip()

    ensure_default_reward_items()
    # Dynamic Tiers & Gifts Configuration
    tier_configs = list(SlipTierConfig.objects.all().order_by('sort_order', 'min_spend'))
    reward_items = list(RewardItem.objects.all().order_by('points_required'))
    active_rewards = [r for r in reward_items if r.is_active]
    gift_items = list(GiftRewardItem.objects.all().order_by('points', 'sort_order'))
    catalog = [
        {'id': r.id, 'name': r.name, 'points': r.points_required, 'icon': r.icon, 'desc': r.description}
        for r in active_rewards
    ] or [
        {'id': g.id, 'name': g.name, 'points': g.points, 'icon': g.icon, 'desc': g.desc}
        for g in gift_items if g.is_active
    ] or [
        {'id': idx, 'name': d['name'], 'points': d['points_required'], 'icon': d['icon'], 'desc': d['description']}
        for idx, d in enumerate(DEFAULT_PURE_REWARDS, start=1)
    ]

    # All-Time Slip Scans Metric & All-Time Tier Breakdown
    all_time_used_slips = QRSlip.objects.filter(is_used=True)
    all_time_slip_count = all_time_used_slips.count()

    # Accurate All-Time Points Calculations:
    # 1. Total active customer balance currently in circulation
    total_customer_balance = Customer.objects.filter(is_deleted=False).aggregate(total=Sum('total_points'))['total'] or 0
    # 2. Total points redeemed by customers for physical gifts at the counter
    total_redeemed_points = RedemptionLog.objects.aggregate(total=Sum('points_spent'))['total'] or 0
    # 3. True Total Points Ever Given All Time (Active Balances + Redeemed Points)
    all_time_points_given = total_customer_balance + total_redeemed_points
    # Fallback to slip sum if greater (e.g. if any customers were deleted)
    slip_points_sum = all_time_used_slips.aggregate(total=Sum('points_awarded'))['total'] or 0
    if slip_points_sum > all_time_points_given:
        all_time_points_given = slip_points_sum

    all_time_points = all_time_points_given

    tier_counts = {
        '50': all_time_used_slips.filter(tier='50').count(),
        '100': all_time_used_slips.filter(tier='100').count(),
        '500': all_time_used_slips.filter(tier='500').count(),
        '1000': all_time_used_slips.filter(tier='1000').count(),
    }

    # Today's Slip Scans Metric
    todays_slips = all_time_used_slips.filter(
        claimed_at__date=today
    )
    todays_slip_count = todays_slips.count()
    todays_points = todays_slips.aggregate(total=Sum('points_awarded'))['total'] or 0
    todays_tier_counts = {
        '50': todays_slips.filter(tier='50').count(),
        '100': todays_slips.filter(tier='100').count(),
        '500': todays_slips.filter(tier='500').count(),
        '1000': todays_slips.filter(tier='1000').count(),
    }

    # Dynamically ensure any configured tier keys are accounted for safely
    for cfg in tier_configs:
        k = str(cfg.tier_key)
        if k not in tier_counts:
            tier_counts[k] = all_time_used_slips.filter(tier=k).count()
        if k not in todays_tier_counts:
            todays_tier_counts[k] = todays_slips.filter(tier=k).count()

    def build_phone_q(field_name: str, query_str: str):
        clean_digits = re.sub(r'\D', '', query_str)
        lookup = f"{field_name}__icontains"
        q = Q(**{lookup: query_str})
        if clean_digits:
            q = q | Q(**{lookup: clean_digits})
        return q

    # Searchable Live Scan Feed (Latest 50 Scans Across All Days)
    scan_query = request.GET.get('sq', '').strip()
    recent_scans = all_time_used_slips.select_related('claimed_by').order_by('-claimed_at')
    if scan_query:
        sq_filter = (
            Q(claimed_by__name__icontains=scan_query) |
            build_phone_q('claimed_by__phone_number', scan_query) |
            Q(token__icontains=scan_query) |
            Q(tier__icontains=scan_query)
        )
        recent_scans = recent_scans.filter(sq_filter)

    # Searchable Customer Directory (Excludes Soft-Deleted Customers)
    customers = Customer.objects.filter(is_deleted=False).order_by('-total_points', '-last_scan_date')
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) | build_phone_q('phone_number', search_query)
        )

    # Recycle Bin (Deleted Customers with Search)
    deleted_query = request.GET.get('dq', '').strip()
    deleted_customers = Customer.objects.filter(is_deleted=True).order_by('-id')
    if deleted_query:
        deleted_customers = deleted_customers.filter(
            Q(name__icontains=deleted_query) | build_phone_q('phone_number', deleted_query)
        )
    deleted_customers_count = Customer.objects.filter(is_deleted=True).count()

    # Searchable Gift Redemptions Log (Latest 50)
    recent_redemptions = RedemptionLog.objects.select_related('customer').order_by('-redeemed_at')
    redemption_query = request.GET.get('rq', '').strip()
    if redemption_query:
        rq_filter = (
            Q(customer__name__icontains=redemption_query) |
            build_phone_q('customer__phone_number', redemption_query) |
            Q(reward_name__icontains=redemption_query) |
            Q(notes__icontains=redemption_query)
        )
        recent_redemptions = recent_redemptions.filter(rq_filter)

    total_redemptions_count = RedemptionLog.objects.count()

    # One-time flash Undo banners: visible immediately after delete, but disappear after page refresh!
    show_undo_customer = request.session.pop('show_undo_customer', False)
    last_deleted_customer = None
    if show_undo_customer:
        last_deleted_id = request.session.get('last_deleted_customer_id')
        if last_deleted_id:
            last_deleted_customer = Customer.objects.filter(id=last_deleted_id, is_deleted=True).first()

    show_undo_perm = request.session.pop('show_undo_perm_delete', False)
    last_permanently_deleted = None
    if show_undo_perm:
        last_permanently_deleted = request.session.get('last_permanently_deleted')

    show_undo_gift = request.session.pop('show_undo_gift', False)
    last_deleted_gift = None
    if show_undo_gift:
        last_deleted_gift = request.session.get('last_deleted_gift')

    # Serialized Data for Drill-Down Cards (Instant responsive popups)
    all_scans_data = []
    for s in all_time_used_slips.select_related('claimed_by').order_by('-claimed_at')[:200]:
        local_time = timezone.localtime(s.claimed_at) if s.claimed_at else None
        all_scans_data.append({
            'name': s.claimed_by.name if s.claimed_by else 'Unknown Customer',
            'phone': s.claimed_by.phone_number if s.claimed_by else '—',
            'tier': s.tier,
            'points': s.points_awarded,
            'claimed_at': local_time.strftime('%d %b %Y, %I:%M:%S %p') if local_time else '—',
            'token': s.token,
            'is_today': local_time.date() == today if local_time else False,
        })

    todays_scans_data = [s for s in all_scans_data if s['is_today']]

    customers_points_data = []
    for c in Customer.objects.filter(is_deleted=False).order_by('-total_points', '-last_scan_date'):
        c_redeemed = c.redemptions.aggregate(total=Sum('points_spent'))['total'] or 0
        c_lifetime = c.total_points + c_redeemed
        customers_points_data.append({
            'name': c.name,
            'phone': c.phone_number,
            'points': c.total_points,       # Current Active Balance
            'redeemed': c_redeemed,         # Points spent on gifts
            'lifetime': c_lifetime,         # Total points given all time to this customer
            'visits': c.total_visits,
            'last_scan': c.last_scan_date.strftime('%d %b %Y') if c.last_scan_date else 'No scans yet'
        })

    tier_configs_dict = {
        cfg.tier_key: {
            'min_spend': cfg.min_spend,
            'chit_name': cfg.chit_name,
            'points': cfg.points,
            'chit_color': cfg.chit_color,
            'subtitle': cfg.subtitle,
            'badge_label': cfg.badge_label,
        }
        for cfg in tier_configs
    }

    wt_template, wt_scratch, wt_link = get_whatsapp_settings(request)
    sample_customer = Customer.objects.filter(is_deleted=False).order_by('-total_points').first()

    return render(request, 'rewards/admin_dashboard.html', {
        'today': today,
        'todays_slip_count': todays_slip_count,
        'todays_points': todays_points,
        'todays_tier_counts': todays_tier_counts,
        'all_time_slip_count': all_time_slip_count,
        'all_time_points': all_time_points,
        'all_time_points_given': all_time_points_given,
        'total_customer_balance': total_customer_balance,
        'total_redeemed_points': total_redeemed_points,
        'tier_counts': tier_counts,
        'recent_scans': recent_scans[:50],
        'scan_query': scan_query,
        'customers': customers[:100],
        'search_query': search_query,
        'total_registered_customers': Customer.objects.filter(is_deleted=False).count(),
        'deleted_customers': deleted_customers,
        'deleted_customers_count': deleted_customers_count,
        'deleted_query': deleted_query,
        'catalog': catalog,
        'reward_items': reward_items,
        'active_rewards': active_rewards,
        'gift_items': gift_items,
        'tier_configs': tier_configs,
        'recent_redemptions': recent_redemptions[:50],
        'redemption_query': redemption_query,
        'total_redemptions_count': total_redemptions_count,
        'last_deleted_customer': last_deleted_customer,
        'last_permanently_deleted': last_permanently_deleted,
        'last_deleted_gift': last_deleted_gift,
        'broadcasts': BroadcastNotification.objects.all().order_by('-created_at')[:30],
        'active_broadcast': get_current_active_broadcast(),
        'autopilot_on': (SystemSetting.objects.filter(key='autopilot_enabled').first().value != 'false') if SystemSetting.objects.filter(key='autopilot_enabled').exists() else True,
        'psychological_presets': list(PSYCHOLOGICAL_PRESETS.values()),
        'whatsapp_share_template': wt_template,
        'whatsapp_scratch_template': wt_scratch,
        'whatsapp_store_link': wt_link,
        'sample_whatsapp_message': format_sample_whatsapp_message(wt_template, wt_link, customer=sample_customer),
        'sample_scratch_message': format_sample_whatsapp_message(wt_scratch, wt_link, customer=sample_customer, points_won=150),
        'default_whatsapp_share_template': DEFAULT_WHATSAPP_SHARE_TEMPLATE,
        'default_scratch_share_template': DEFAULT_SCRATCH_SHARE_TEMPLATE,
        'welcome_bonus_settings': get_welcome_bonus_settings(),
        # Serialized JSON payloads for client-side drill-down modals
        'all_scans_json': json.dumps(all_scans_data),
        'todays_scans_json': json.dumps(todays_scans_data),
        'customers_points_json': json.dumps(customers_points_data),
        'tier_configs_json': json.dumps(tier_configs_dict),
    })


@staff_member_required(login_url='/admin/login/')
def redeem_reward_reset_points(request):
    """
    Owner Admin Action: Hand over reward item and dynamically deduct reward points from customer's balance.
    Logs the event in RedemptionLog with timestamp and points spent.
    """
    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        reward_name = request.POST.get('reward_name', '').strip()
        notes = request.POST.get('notes', '').strip()

        is_ajax = (
            request.headers.get('x-requested-with') == 'XMLHttpRequest' or
            request.POST.get('format') == 'json' or
            'application/json' in request.headers.get('accept', '')
        )

        customer = Customer.objects.filter(id=customer_id, is_deleted=False).first()
        if not customer:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Customer not found.'}, status=404)
            messages.error(request, 'Customer not found.')
            return redirect('/nandhini-admin/')

        if not reward_name:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Please select a reward option.'}, status=400)
            messages.error(request, 'Please select a reward option from the dropdown.')
            return redirect('/nandhini-admin/')

        # Find reward cost dynamically from RewardItem first, then GiftRewardItem, then fallback
        reward_cost = None
        db_reward = RewardItem.objects.filter(name=reward_name, is_active=True).first()
        if db_reward:
            reward_cost = db_reward.points_required
        else:
            db_gift = GiftRewardItem.objects.filter(name=reward_name, is_active=True).first()
            if db_gift:
                reward_cost = db_gift.points
            else:
                for item in DEFAULT_PURE_REWARDS:
                    if item['name'] == reward_name:
                        reward_cost = item['points_required']
                        break

        if reward_cost is None:
            try:
                reward_cost = int(request.POST.get('reward_points', 350))
            except (ValueError, TypeError):
                reward_cost = 350

        # Atomic Row-Level Database Lock (Guarantees zero double-spend on counter redemptions)
        with transaction.atomic():
            customer = Customer.objects.select_for_update().filter(id=customer_id, is_deleted=False).first()
            if not customer:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'Customer not found.'}, status=404)
                messages.error(request, 'Customer not found.')
                return redirect('/nandhini-admin/')

            old_points = customer.total_points
            if old_points < reward_cost:
                msg = f"⚠️ Insufficient points: {customer.name} only has {old_points} Pts, but '{reward_name}' costs {reward_cost} Pts."
                if is_ajax:
                    return JsonResponse({'success': False, 'error': msg}, status=400)
                messages.warning(request, msg)
                return redirect('/nandhini-admin/')

            new_balance = old_points - reward_cost

            # 1. Create Redemption Log
            RedemptionLog.objects.create(
                customer=customer,
                reward_name=reward_name,
                points_spent=reward_cost,
                notes=notes or f"Redeemed {reward_name}. Deducted {reward_cost} Pts (Balance: {new_balance} Pts)."
            )

            # 2. Deduct points from Customer atomically
            customer.total_points = new_balance
            customer.save(update_fields=['total_points'])

        success_msg = f"🎉 Successfully redeemed '{reward_name}' for {customer.name}! Deducted {reward_cost} Pts. Remaining Balance: {new_balance} Pts."
        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': success_msg,
                'customer_id': customer.id,
                'customer_name': customer.name,
                'reward_name': reward_name,
                'points_spent': reward_cost,
                'new_balance': new_balance,
            })

        messages.success(request, success_msg)
        return redirect('/nandhini-admin/')

    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def delete_customer(request, customer_id):
    """
    Owner Admin Action: Soft-delete customer so it can be undone.
    """
    if request.method == 'POST':
        customer = Customer.objects.filter(id=customer_id, is_deleted=False).first()
        if customer:
            customer.is_deleted = True
            customer.save(update_fields=['is_deleted'])
            request.session['last_deleted_customer_id'] = customer.id
            request.session['show_undo_customer'] = True
            request.session.modified = True
            messages.success(
                request,
                f"🗑️ Customer '{customer.name}' (+91 {customer.phone_number}) moved to Recycle Bin. You can undo this action below."
            )
        else:
            messages.error(request, "Customer not found.")
    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def restore_customer(request, customer_id):
    """
    Owner Admin Action: Undo deletion and restore customer.
    """
    if request.method == 'POST':
        customer = Customer.objects.filter(id=customer_id, is_deleted=True).first()
        if customer:
            customer.is_deleted = False
            customer.save(update_fields=['is_deleted'])
            if request.session.get('last_deleted_customer_id') == customer.id:
                del request.session['last_deleted_customer_id']
                request.session.modified = True
            messages.success(
                request,
                f"↩️ Successfully restored customer '{customer.name}' (+91 {customer.phone_number}) with {customer.total_points} Pts!"
            )
        else:
            messages.error(request, "Customer not found or already active.")
    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def permanent_delete_customer(request, customer_id):
    """
    Owner Admin Action: Permanently delete customer from database.
    Saves complete snapshot in session so it can be restored with 1-click Undo.
    """
    if request.method == 'POST':
        customer = Customer.objects.filter(id=customer_id, is_deleted=True).first()
        if customer:
            name = customer.name
            phone = customer.phone_number
            points = customer.total_points

            # Snapshot complete customer state before database deletion
            request.session['last_permanently_deleted'] = {
                'name': customer.name,
                'phone_number': customer.phone_number,
                'total_points': customer.total_points,
                'total_visits': customer.total_visits,
                'last_scan_date': str(customer.last_scan_date) if customer.last_scan_date else None,
                'claimed_slip_tokens': list(customer.claimed_slips.values_list('token', flat=True)),
                'redemptions': [
                    {
                        'reward_name': r.reward_name,
                        'points_spent': r.points_spent,
                        'notes': r.notes,
                        'redeemed_at': r.redeemed_at.isoformat()
                    }
                    for r in customer.redemptions.all()
                ]
            }
            request.session['show_undo_perm_delete'] = True
            request.session.modified = True

            customer.delete()
            messages.success(
                request,
                f"🗑️ Customer '{name}' (+91 {phone}) permanently purged from Recycle Bin. An Undo option is provided above if you need to restore!"
            )
        else:
            messages.error(request, "Customer not found in Recycle Bin.")
    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def undo_permanent_delete_customer(request):
    """
    Owner Admin Action: Undo permanent delete and restore customer with all points and history.
    """
    if request.method == 'POST':
        snapshot = request.session.get('last_permanently_deleted')
        if not snapshot:
            messages.error(request, "No recently permanently deleted customer found to restore.")
            return redirect('/nandhini-admin/')

        # Prevent restoring over another active user registered with the same phone
        existing = Customer.objects.filter(phone_number=snapshot['phone_number']).first()
        if existing:
            messages.error(
                request,
                f"Cannot restore: mobile number +91 {snapshot['phone_number']} is currently registered to '{existing.name}'."
            )
            return redirect('/nandhini-admin/')

        customer = Customer.objects.create(
            name=snapshot['name'],
            phone_number=snapshot['phone_number'],
            total_points=snapshot['total_points'],
            total_visits=snapshot['total_visits'],
            last_scan_date=snapshot['last_scan_date'],
            is_deleted=True  # Restores into Recycle Bin safely
        )
        # Re-link claimed slips
        if snapshot.get('claimed_slip_tokens'):
            QRSlip.objects.filter(token__in=snapshot['claimed_slip_tokens']).update(claimed_by=customer)

        # Restore redemption logs
        for red in snapshot.get('redemptions', []):
            RedemptionLog.objects.create(
                customer=customer,
                reward_name=red.get('reward_name', ''),
                points_spent=red.get('points_spent', 0),
                notes=red.get('notes', '')
            )

        del request.session['last_permanently_deleted']
        request.session.modified = True
        messages.success(
            request,
            f"↩️ Successfully restored permanently deleted customer '{customer.name}' (+91 {customer.phone_number}) with {customer.total_points} Pts back into the Recycle Bin!"
        )
    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def update_tier_settings(request):
    """Save updated prices and points for Purchase Slips"""
    if request.method == 'POST':
        tier_keys = request.POST.getlist('tier_key')
        for k in tier_keys:
            cfg = SlipTierConfig.objects.filter(tier_key=k).first()
            if cfg:
                min_spend = request.POST.get(f"min_spend_{k}")
                pts = request.POST.get(f"points_{k}")
                chit_name = request.POST.get(f"chit_name_{k}")
                subtitle = request.POST.get(f"subtitle_{k}")
                if min_spend:
                    try:
                        cfg.min_spend = int(min_spend)
                    except ValueError:
                        pass
                if pts:
                    try:
                        cfg.points = int(pts)
                    except ValueError:
                        pass
                if chit_name:
                    cfg.chit_name = chit_name.strip()
                if subtitle is not None:
                    cfg.subtitle = subtitle.strip()
                cfg.save()
        messages.success(request, "⚙️ Purchase Slip Tiers & Points updated successfully! Changes are live across customer and admin pages.")
    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def save_gift_setting(request):
    """Add or update an Available Free Gift in catalog"""
    if request.method == 'POST':
        gift_id = request.POST.get('gift_id')
        name = request.POST.get('name', '').strip()
        points = request.POST.get('points', '').strip()
        icon = request.POST.get('icon', '🎁').strip() or '🎁'
        desc = request.POST.get('desc', '').strip()

        if not name or not points:
            messages.error(request, "Gift name and points are required.")
            return redirect('/nandhini-admin/')

        try:
            pts_val = int(points)
        except ValueError:
            messages.error(request, "Points must be a valid number.")
            return redirect('/nandhini-admin/')

        if gift_id:
            gift = GiftRewardItem.objects.filter(id=gift_id).first()
            if gift:
                gift.name = name
                gift.points = pts_val
                gift.icon = icon
                gift.desc = desc
                gift.save()
                messages.success(request, f"🎁 Updated reward gift '{name}' ({pts_val} Pts)!")
        else:
            GiftRewardItem.objects.create(
                name=name,
                points=pts_val,
                icon=icon,
                desc=desc,
                sort_order=pts_val // 100
            )
            messages.success(request, f"🎁 Added new reward gift '{name}' ({pts_val} Pts) to Available Free Gifts!")

    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def delete_gift_setting(request, gift_id):
    """Remove a gift reward from catalog with instant Undo snapshot preserved in session"""
    if request.method == 'POST':
        gift = GiftRewardItem.objects.filter(id=gift_id).first()
        if gift:
            name = gift.name
            points = gift.points
            request.session['last_deleted_gift'] = {
                'id': gift.id,
                'name': gift.name,
                'points': gift.points,
                'icon': gift.icon,
                'desc': gift.desc,
                'sort_order': gift.sort_order,
            }
            request.session['show_undo_gift'] = True
            request.session.modified = True
            gift.delete()
            messages.success(
                request,
                f"🗑️ Removed '{name}' ({points} Pts) from Available Free Gifts. An Undo option is available below to restore it!"
            )
        else:
            messages.error(request, "Gift item not found.")
    return redirect('/nandhini-admin/#storeSettingsSection')


@staff_member_required(login_url='/admin/login/')
def undo_delete_gift_setting(request):
    """Restore the most recently deleted Free Gift item back into Available Free Gifts"""
    if request.method == 'POST':
        snapshot = request.session.get('last_deleted_gift')
        if not snapshot:
            messages.error(request, "No recently deleted gift reward found to restore.")
            return redirect('/nandhini-admin/#storeSettingsSection')

        gift = GiftRewardItem.objects.create(
            name=snapshot['name'],
            points=snapshot['points'],
            icon=snapshot.get('icon', '🎁'),
            desc=snapshot.get('desc', ''),
            sort_order=snapshot.get('sort_order', 1),
            is_active=True
        )
        del request.session['last_deleted_gift']
        request.session.modified = True
        messages.success(
            request,
            f"↩️ Successfully restored Free Gift '{gift.name}' ({gift.points} Pts) back into Store Loyalty & Rewards catalog!"
        )
    return redirect('/nandhini-admin/#storeSettingsSection')


@staff_member_required(login_url='/admin/login/')
def save_reward_item(request):
    """Add or update a RewardItem in the dynamic catalog"""
    if request.method == 'POST':
        item_id = request.POST.get('item_id') or request.POST.get('gift_id')
        name = request.POST.get('name', '').strip()
        points_str = (request.POST.get('points_required') or request.POST.get('points', '')).strip()
        icon = request.POST.get('icon', '🎁').strip() or '🎁'
        desc = (request.POST.get('description') or request.POST.get('desc', '')).strip()

        if not name or not points_str:
            messages.error(request, "Reward item name and points required are compulsory.")
            return redirect('/nandhini-admin/#rewardCatalogSection')

        try:
            pts_val = int(points_str)
            if pts_val <= 0:
                raise ValueError
        except ValueError:
            messages.error(request, "Points required must be a positive number.")
            return redirect('/nandhini-admin/#rewardCatalogSection')

        if item_id:
            item = RewardItem.objects.filter(id=item_id).first()
            if item:
                item.name = name
                item.points_required = pts_val
                item.icon = icon
                item.description = desc
                item.save()
                messages.success(request, f"🎁 Updated Reward Item '{name}' ({pts_val} Pts)!")
            else:
                messages.error(request, "Reward item not found.")
        else:
            RewardItem.objects.create(
                name=name,
                points_required=pts_val,
                icon=icon,
                description=desc,
                is_active=True
            )
            messages.success(request, f"✨ Added New Reward Item '{name}' ({pts_val} Pts) to catalog!")

    return redirect('/nandhini-admin/#rewardCatalogSection')


@staff_member_required(login_url='/admin/login/')
def delete_reward_item(request, item_id):
    """Delete a RewardItem from dynamic catalog"""
    if request.method == 'POST':
        item = RewardItem.objects.filter(id=item_id).first()
        if item:
            name = item.name
            pts = item.points_required
            item.delete()
            messages.success(request, f"🗑️ Deleted reward '{name}' ({pts} Pts) from catalog.")
        else:
            messages.error(request, "Reward item not found.")
    return redirect('/nandhini-admin/#rewardCatalogSection')


@staff_member_required(login_url='/admin/login/')
def toggle_reward_item(request, item_id):
    """Toggle active/inactive status of a RewardItem (e.g. out of stock)"""
    if request.method == 'POST':
        item = RewardItem.objects.filter(id=item_id).first()
        if item:
            item.is_active = not item.is_active
            item.save(update_fields=['is_active'])
            status_text = "Active" if item.is_active else "Hidden (Out of Stock)"
            messages.success(request, f"🔄 '{item.name}' is now {status_text}.")
        else:
            messages.error(request, "Reward item not found.")
    return redirect('/nandhini-admin/#rewardCatalogSection')


@staff_member_required(login_url='/admin/login/')
def send_broadcast_notification(request):
    """Send an instant manual broadcast notification to all customers"""
    if request.method == 'POST':
        title = sanitize_text(request.POST.get('title', ''), max_length=150)
        message = sanitize_text(request.POST.get('message', ''), max_length=500)
        haptic_style = sanitize_text(request.POST.get('haptic_style', 'pulse'), max_length=30)
        preset_key = sanitize_text(request.POST.get('preset_key', ''), max_length=60)

        if not title or not message:
            messages.error(request, "Notification Title and Message cannot be empty.")
            return redirect('/nandhini-admin/#broadcastSection')

        # Deactivate previous manual broadcasts so the newest message takes priority
        BroadcastNotification.objects.filter(is_automated=False).update(is_active=False)
        BroadcastNotification.objects.create(
            title=title,
            message=message,
            haptic_style=haptic_style,
            is_active=True,
            is_automated=False,
            preset_key=preset_key
        )
        # Dispatch Web Push alerts even when customer's site is closed
        offline_sent = dispatch_webpush_to_all(title, message, haptic_style)
        extra_info = f" ({offline_sent} offline device{'s' if offline_sent != 1 else ''} alerted)" if offline_sent > 0 else ""
        messages.success(request, f"🚀 Push Notification dispatched! All active and background devices notified{extra_info}.")

    return redirect('/nandhini-admin/#broadcastSection')


@staff_member_required(login_url='/admin/login/')
def edit_broadcast_notification(request, broadcast_id):
    """Edit an existing broadcast notification if sent wrongly"""
    b = BroadcastNotification.objects.filter(id=broadcast_id).first()
    if not b:
        messages.error(request, "Broadcast notification not found or already removed.")
        return redirect('/nandhini-admin/#broadcastSection')

    if request.method == 'POST':
        title = sanitize_text(request.POST.get('title', ''), max_length=150)
        message = sanitize_text(request.POST.get('message', ''), max_length=500)
        haptic_style = sanitize_text(request.POST.get('haptic_style', 'pulse'), max_length=30)

        if not title or not message:
            messages.error(request, "Notification Title and Message cannot be empty.")
            return redirect('/nandhini-admin/#broadcastSection')

        b.title = title
        b.message = message
        b.haptic_style = haptic_style
        b.is_active = True
        b.save()

        # If manual, ensure this updated broadcast takes priority
        if not b.is_automated:
            BroadcastNotification.objects.filter(is_automated=False).exclude(id=b.id).update(is_active=False)

        # Dispatch Web Push for corrected broadcast
        dispatch_webpush_to_all(title, message, haptic_style)
        messages.success(request, f"✏️ Push Notification '{b.title[:30]}...' successfully updated! Corrected alert sent to all customer devices.")
        return redirect('/nandhini-admin/#broadcastSection')

    return redirect('/nandhini-admin/#broadcastSection')


@staff_member_required(login_url='/admin/login/')
def delete_broadcast_notification(request, broadcast_id):
    """Delete a broadcast notification without any error"""
    b = BroadcastNotification.objects.filter(id=broadcast_id).first()
    if b:
        title_snippet = b.title[:30] + ('...' if len(b.title) > 30 else '')
        b.delete()
        messages.success(request, f"🗑️ Push Notification '{title_snippet}' deleted successfully from feed.")
    else:
        messages.error(request, "Broadcast notification not found or already deleted.")
    return redirect('/nandhini-admin/#broadcastSection')


@staff_member_required(login_url='/admin/login/')
def toggle_autopilot_setting(request):
    """Toggle Time-Based Auto-Pilot Broadcasts ON or OFF"""
    if request.method == 'POST':
        setting, _ = SystemSetting.objects.get_or_create(key='autopilot_enabled', defaults={'value': 'true'})
        current_val = (setting.value != 'false')
        new_val = 'false' if current_val else 'true'
        setting.value = new_val
        setting.save()

        status_text = "ENABLED (Auto notifications active on schedule)" if new_val == 'true' else "PAUSED (Automated pushes paused)"
        messages.success(request, f"🤖 Auto-Pilot Notification Engine is now {status_text}.")
    return redirect('/nandhini-admin/#broadcastSection')


def latest_broadcast_api(request):
    """Real-time JSON polling endpoint for customer dashboards"""
    b = get_current_active_broadcast()
    if b and b.is_active:
        return JsonResponse({
            'has_active': True,
            'id': b.id,
            'title': b.title,
            'message': b.message,
            'haptic_style': b.haptic_style,
            'is_automated': b.is_automated,
            'created_at': timezone.localtime(b.created_at).strftime('%d %b %I:%M %p'),
            'updated_at': timezone.localtime(b.updated_at).strftime('%d %b %I:%M:%S %p'),
            'version': f"{b.id}_{int(b.updated_at.timestamp())}"
        })
    return JsonResponse({'has_active': False})


def get_or_create_vapid_keys():
    """Retrieves or creates persistent VAPID EC keypair in SystemSetting"""
    priv_setting = SystemSetting.objects.filter(key='vapid_private_pem').first()
    pub_setting = SystemSetting.objects.filter(key='vapid_public_b64').first()

    if priv_setting and pub_setting:
        return priv_setting.value, pub_setting.value

    # Generate fresh persistent VAPID keys
    v = Vapid()
    v.generate_keys()
    priv_pem = v.private_pem().decode('utf-8')

    if v.public_key is None:
        raise ValueError("Failed to generate VAPID public key")

    raw_pub = v.public_key.public_bytes(
        encoding=__import__('cryptography.hazmat.primitives.serialization', fromlist=['Encoding']).Encoding.X962,
        format=__import__('cryptography.hazmat.primitives.serialization', fromlist=['PublicFormat']).PublicFormat.UncompressedPoint
    )
    pub_b64 = base64.urlsafe_b64encode(raw_pub).decode('utf-8').rstrip('=')

    SystemSetting.objects.update_or_create(key='vapid_private_pem', defaults={'value': priv_pem})
    SystemSetting.objects.update_or_create(key='vapid_public_b64', defaults={'value': pub_b64})

    return priv_pem, pub_b64


def dispatch_webpush_to_all(title, message, haptic_style='pulse'):
    """Dispatches Web Push notifications to all subscribed devices even when website is closed"""
    subs = list(PushSubscription.objects.all())
    if not subs:
        return 0

    try:
        priv_pem, _ = get_or_create_vapid_keys()
        v = Vapid.from_pem(priv_pem.encode('utf-8'))
        claims = {"sub": "mailto:nandhinistationery@gmail.com"}

        payload = json.dumps({
            'title': title,
            'message': message,
            'haptic': haptic_style,
            'url': '/dashboard/',
            'timestamp': timezone.now().strftime('%d %b %I:%M %p')
        })

        sent_count = 0
        for sub in subs:
            try:
                resp = webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh,
                            "auth": sub.auth
                        }
                    },
                    data=payload,
                    vapid_private_key=v,
                    vapid_claims=claims.copy(),
                    ttl=86400,
                    timeout=10
                )
                if hasattr(resp, 'status_code') and resp.status_code in (200, 201, 202):
                    sent_count += 1
            except WebPushException as ex:
                if hasattr(ex, 'response') and ex.response and ex.response.status_code in (404, 410):
                    sub.delete()
            except Exception:
                pass

        return sent_count
    except Exception as e:
        return 0


def vapid_public_key_api(request):
    """Returns public VAPID key for frontend push subscription"""
    _, pub_b64 = get_or_create_vapid_keys()
    return JsonResponse({'publicKey': pub_b64})


@csrf_exempt
def save_push_subscription(request):
    """Registers device push subscription endpoint and encryption keys"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            endpoint = data.get('endpoint')
            keys = data.get('keys', {})
            p256dh = keys.get('p256dh')
            auth = keys.get('auth')

            if endpoint and p256dh and auth:
                # Payload validation: strict HTTPS endpoint & reasonable length limits to prevent DB bloat
                if not (isinstance(endpoint, str) and endpoint.startswith('https://') and len(endpoint) <= 500 and
                        isinstance(p256dh, str) and len(p256dh) <= 200 and
                        isinstance(auth, str) and len(auth) <= 100):
                    return JsonResponse({'success': False, 'error': 'Invalid subscription parameters'}, status=400)

                customer = None
                phone = request.session.get('customer_phone')
                if phone:
                    customer = Customer.objects.filter(phone_number=phone, is_deleted=False).first()

                PushSubscription.objects.update_or_create(
                    endpoint=endpoint,
                    defaults={
                        'p256dh': p256dh,
                        'auth': auth,
                        'customer': customer
                    }
                )
                return JsonResponse({'success': True, 'message': 'Subscribed to background push notifications.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'POST required'}, status=405)


def service_worker(request):
    """Serves the service worker script from root /sw.js scope"""
    sw_content = render_to_string('rewards/sw.js')
    response = HttpResponse(sw_content, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    return response


# Background Auto-Pilot Worker Daemon
# Monitors time schedule every 30 seconds to automatically trigger Break Time (11:00 AM - 2:00 PM)
# and all scheduled store alerts to offline devices without requiring website traffic
_autopilot_worker_started = False
_autopilot_lock = threading.Lock()

def start_autopilot_worker():
    global _autopilot_worker_started
    with _autopilot_lock:
        if _autopilot_worker_started:
            return
        _autopilot_worker_started = True

    def autopilot_loop():
        time.sleep(3)
        while True:
            try:
                setting = SystemSetting.objects.filter(key='autopilot_enabled').first()
                if not setting or setting.value != 'false':
                    get_current_active_broadcast()
            except Exception:
                pass
            time.sleep(30)

    t = threading.Thread(target=autopilot_loop, daemon=True, name="NandhiniAutopilotWorker")
    t.start()

start_autopilot_worker()


# ==============================================================================
# FAIL-SAFE CUSTOM ERROR HANDLERS (Prevents sensitive debug / stacktrace leaks)
# ==============================================================================
def custom_bad_request_view(request, exception=None):
    return render(request, 'rewards/error.html', {
        'title': 'Bad Request',
        'message': 'The request could not be processed. Please try again.',
        'code': '400'
    }, status=400)


def custom_permission_denied_view(request, exception=None):
    return render(request, 'rewards/error.html', {
        'title': 'Access Restricted',
        'message': 'You do not have permission to view this page.',
        'code': '403'
    }, status=403)


def custom_page_not_found_view(request, exception=None):
    return render(request, 'rewards/error.html', {
        'title': 'Page Not Found',
        'message': 'The page or QR chit you are looking for does not exist or has already been used.',
        'code': '404'
    }, status=404)


def custom_server_error_view(request):
    import traceback
    logger.error(f"500 Internal Error at {getattr(request, 'path', '?')}:\n{traceback.format_exc()}")
    return render(request, 'rewards/error.html', {
        'title': 'Something Went Wrong',
        'message': 'We experienced a temporary glitch. Please refresh or try again.',
        'code': '500'
    }, status=500)


@staff_member_required(login_url='/admin/login/')
def export_customers_csv(request):
    """Generates and downloads a clean UTF-8 CSV containing all registered customers"""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    today_str = timezone.localdate().strftime('%Y-%m-%d')
    response['Content-Disposition'] = f'attachment; filename="nandhini_stationery_customers_{today_str}.csv"'

    # Include BOM for proper Excel UTF-8 display
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow([
        'Customer ID',
        'Customer Name',
        'Mobile Number',
        'Total Loyalty Points',
        'Total Store Visits',
        'Last Scan Date',
        'Account Status'
    ])

    customers = Customer.objects.filter(is_deleted=False).order_by('-total_points', '-last_scan_date')
    for c in customers:
        # CSV Formula Injection Defense: neutralize cells starting with =, +, -, @
        safe_name = str(c.name)
        if safe_name.startswith(('=', '+', '-', '@')):
            safe_name = f"'{safe_name}"

        writer.writerow([
            c.id,
            safe_name,
            f"+91 {c.phone_number}",
            c.total_points,
            c.total_visits,
            c.last_scan_date.strftime('%Y-%m-%d') if c.last_scan_date else 'Never',
            'Active'
        ])

    return response


@staff_member_required(login_url='/admin/login/')
def download_db_backup(request):
    """
    Staff-Only Disaster Recovery: Generates a live, zero-downtime database snapshot
    and serves it directly as a download to the shop owner's device.
    """
    from backup_db import perform_db_backup
    backup_path = perform_db_backup(keep_latest=15)
    if backup_path and os.path.exists(backup_path):
        filename = os.path.basename(backup_path)
        with open(backup_path, 'rb') as f:
            content = f.read()
        response = HttpResponse(content, content_type='application/x-sqlite3')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    messages.error(request, "Failed to create database snapshot. Please check server logs.")
    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def save_whatsapp_share_setting(request):
    """Saves customized WhatsApp share templates and store link"""
    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        if action == 'reset':
            SystemSetting.objects.filter(key__in=['whatsapp_share_template', 'whatsapp_scratch_template', 'whatsapp_store_link']).delete()
            messages.success(request, 'WhatsApp share messages & store link reset to defaults.')
        else:
            share_template = sanitize_text(request.POST.get('whatsapp_share_template', ''), max_length=500)
            scratch_template = sanitize_text(request.POST.get('whatsapp_scratch_template', ''), max_length=500)
            store_link = sanitize_text(request.POST.get('whatsapp_store_link', ''), max_length=200)

            if not share_template:
                share_template = DEFAULT_WHATSAPP_SHARE_TEMPLATE
            if not scratch_template:
                scratch_template = DEFAULT_SCRATCH_SHARE_TEMPLATE

            SystemSetting.objects.update_or_create(key='whatsapp_share_template', defaults={'value': share_template})
            SystemSetting.objects.update_or_create(key='whatsapp_scratch_template', defaults={'value': scratch_template})
            if store_link:
                SystemSetting.objects.update_or_create(key='whatsapp_store_link', defaults={'value': store_link})
            else:
                SystemSetting.objects.filter(key='whatsapp_store_link').delete()

            messages.success(request, 'WhatsApp viral share messages and store link saved successfully!')

    return redirect('/nandhini-admin/#whatsappSettingsSection')


def founder_photo_view(request):
    """Serves the official Founder photo directly from disk with caching"""
    photo_paths = [
        settings.BASE_DIR / 'rewards' / 'static' / 'rewards' / 'img' / 'founder.jpg',
        settings.BASE_DIR / 'static' / 'img' / 'founder.jpg',
    ]
    for p in photo_paths:
        if p.exists():
            try:
                with open(p, 'rb') as f:
                    content = f.read()
                response = HttpResponse(content, content_type='image/jpeg')
                response['Cache-Control'] = 'public, max-age=86400'
                return response
            except Exception as e:
                logger.error(f"Error serving founder photo: {e}")
    return HttpResponse(status=404)


@staff_member_required(login_url='/admin/login/')
def save_founder_settings(request):
    """Saves or updates Founder & Brand Identity settings from the Admin Panel"""
    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        if action == 'reset':
            SystemSetting.objects.filter(key__in=[
                'founder_enabled', 'founder_title', 'founder_motto', 'founder_photo_url', 'founder_map_enabled'
            ]).delete()
            messages.success(request, "🔄 Founder & Brand Identity settings reset to default.")
            return redirect('/nandhini-admin/#founderBrandStudio')

        founder_enabled = 'true' if request.POST.get('founder_enabled') == 'on' else 'false'
        founder_map_enabled = 'true' if request.POST.get('founder_map_enabled') == 'on' else 'false'
        founder_title = sanitize_text(request.POST.get('founder_title', '').strip(), max_length=120) or DEFAULT_FOUNDER_TITLE
        founder_motto = sanitize_text(request.POST.get('founder_motto', '').strip(), max_length=200) or DEFAULT_FOUNDER_MOTTO

        SystemSetting.objects.update_or_create(key='founder_enabled', defaults={'value': founder_enabled})
        SystemSetting.objects.update_or_create(key='founder_map_enabled', defaults={'value': founder_map_enabled})
        SystemSetting.objects.update_or_create(key='founder_title', defaults={'value': founder_title})
        SystemSetting.objects.update_or_create(key='founder_motto', defaults={'value': founder_motto})

        # Handle uploaded photo file if provided with deep verification & sanitization
        if 'founder_photo' in request.FILES:
            photo_file = request.FILES['founder_photo']
            if photo_file.size > 2.5 * 1024 * 1024:
                messages.error(request, "⚠️ Uploaded image must be under 2.5MB.")
                return redirect('/nandhini-admin/#founderBrandStudio')

            ext = os.path.splitext(photo_file.name)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                try:
                    from PIL import Image
                    img = Image.open(photo_file)
                    img.verify()  # Verify image integrity

                    # Re-open stream for processing (verify closes/consumes stream)
                    photo_file.seek(0)
                    img = Image.open(photo_file)
                    img = img.convert('RGB')  # Strip alpha/metadata/polyglot scripts

                    target1 = settings.BASE_DIR / 'rewards' / 'static' / 'rewards' / 'img' / 'founder.jpg'
                    target2 = settings.BASE_DIR / 'static' / 'img' / 'founder.jpg'
                    target1.parent.mkdir(parents=True, exist_ok=True)
                    target2.parent.mkdir(parents=True, exist_ok=True)

                    # Re-encode as clean JPEG stripping any malicious EXIF or embedded code
                    img.save(target1, 'JPEG', quality=88, optimize=True)
                    img.save(target2, 'JPEG', quality=88, optimize=True)

                    # Cache-busting URL with epoch timestamp
                    timestamp = int(time.time())
                    photo_url = f"/founder-photo.jpg?v={timestamp}"
                    SystemSetting.objects.update_or_create(key='founder_photo_url', defaults={'value': photo_url})
                except Exception as img_err:
                    logger.error(f"Image validation error: {img_err}")
                    messages.error(request, "⚠️ Invalid or corrupted image file detected.")
                    return redirect('/nandhini-admin/#founderBrandStudio')
            else:
                messages.error(request, "⚠️ Please upload a valid image file (.jpg, .jpeg, .png, or .webp).")
                return redirect('/nandhini-admin/#founderBrandStudio')

        messages.success(request, "👑 Founder & Brand Identity settings saved successfully!")
        return redirect('/nandhini-admin/#founderBrandStudio')

    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def save_welcome_bonus_settings(request):
    """Saves first-time customer welcome bonus settings (Enabled toggle and bonus points)"""
    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        if action == 'reset':
            SystemSetting.objects.filter(key__in=['welcome_bonus_enabled', 'welcome_bonus_points']).delete()
            messages.success(request, '🔄 Welcome Bonus settings reset to default (+50 Points Enabled).')
            return redirect('/nandhini-admin/#welcomeBonusStudio')

        is_enabled = 'true' if request.POST.get('welcome_bonus_enabled') == 'on' else 'false'
        pts_str = request.POST.get('welcome_bonus_points', '50').strip()
        try:
            pts = int(pts_str)
            if pts < 0:
                raise ValueError
        except ValueError:
            pts = DEFAULT_WELCOME_BONUS_POINTS

        SystemSetting.objects.update_or_create(key='welcome_bonus_enabled', defaults={'value': is_enabled})
        SystemSetting.objects.update_or_create(key='welcome_bonus_points', defaults={'value': str(pts)})
        status_text = f"Active (+{pts} Pts)" if is_enabled == 'true' else "Disabled"
        messages.success(request, f'🎁 First-Time Member Welcome Bonus is now {status_text}!')
        return redirect('/nandhini-admin/#welcomeBonusStudio')

    return redirect('/nandhini-admin/')


@staff_member_required(login_url='/admin/login/')
def save_daily_limit_settings(request):
    """Saves daily scan ceiling settings (number stepper value & enabled toggle)"""
    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        if action == 'reset':
            SystemSetting.objects.filter(key__in=['daily_scan_limit_enabled', 'daily_scan_limit_count']).delete()
            messages.success(request, '🔄 Daily Chit Limit reset to default (3 Chits/Day Enabled).')
            return redirect('/nandhini-admin/#dailyLimitStudio')

        is_enabled = 'true' if request.POST.get('daily_scan_limit_enabled') == 'on' else 'false'
        limit_str = request.POST.get('daily_scan_limit_count', '3').strip()
        try:
            limit_val = int(limit_str)
            if limit_val <= 0:
                limit_val = DEFAULT_DAILY_SCAN_LIMIT
        except ValueError:
            limit_val = DEFAULT_DAILY_SCAN_LIMIT

        SystemSetting.objects.update_or_create(key='daily_scan_limit_enabled', defaults={'value': is_enabled})
        SystemSetting.objects.update_or_create(key='daily_scan_limit_count', defaults={'value': str(limit_val)})
        status_text = f"Active ({limit_val} Chits/Day)" if is_enabled == 'true' else "Disabled (Unlimited Scans)"
        messages.success(request, f'🛡️ Daily Chit Scan Ceiling is now {status_text}!')
        return redirect('/nandhini-admin/#dailyLimitStudio')

    return redirect('/nandhini-admin/')


def member_pass_qr_view(request):
    """Generates a high-contrast vector SVG QR code for the customer's counter member pass (100% free locally)"""
    phone = request.GET.get('phone', '').strip()
    customer = Customer.objects.filter(phone_number=phone, is_deleted=False).first()
    if not customer:
        return HttpResponse(status=404)

    import qrcode
    import qrcode.image.svg
    from io import BytesIO

    qr_data = f"NS-{customer.phone_number}"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    factory = qrcode.image.svg.SvgPathImage
    img = qr.make_image(image_factory=factory)

    stream = BytesIO()
    img.save(stream)
    svg_text = stream.getvalue().decode('utf-8')
    # Guarantee crisp pure-white background for Dark Mode compatibility
    svg_tag_end = svg_text.find('>', svg_text.find('<svg')) + 1
    if svg_tag_end > 0:
        svg_text = svg_text[:svg_tag_end] + '<rect width="100%" height="100%" fill="#FFFFFF"/>' + svg_text[svg_tag_end:]
    svg_data = svg_text.encode('utf-8')
    response = HttpResponse(svg_data, content_type='image/svg+xml')
    response['Cache-Control'] = 'public, max-age=86400'
    return response


@staff_member_required(login_url='/admin/login/')
def counter_customer_lookup_api(request):
    """Instant Counter Verification: Looks up customer by QR code or barcode scan string (e.g. NS-8678922362 or 8678922362)"""
    raw_query = request.GET.get('query', '').strip()
    if not raw_query:
        return JsonResponse({'success': False, 'error': 'No barcode or phone provided.'})

    clean_digits = re.sub(r'\D', '', raw_query)
    clean_phone = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits

    customer = None
    if clean_phone:
        customer = Customer.objects.filter(phone_number=clean_phone, is_deleted=False).first()
    if not customer and raw_query:
        customer = Customer.objects.filter(name__icontains=raw_query, is_deleted=False).first()

    if not customer:
        return JsonResponse({'success': False, 'error': f'No customer found matching "{raw_query}".'})

    ensure_default_reward_items()
    db_rewards = list(RewardItem.objects.filter(is_active=True).order_by('points_required'))
    if not db_rewards:
        db_rewards = list(GiftRewardItem.objects.filter(is_active=True).order_by('points'))

    rewards_list = []
    for r in db_rewards:
        pts = getattr(r, 'points_required', getattr(r, 'points', 350))
        rewards_list.append({
            'id': r.id,
            'name': r.name,
            'points': pts,
            'icon': r.icon,
            'can_redeem': customer.total_points >= pts,
            'points_needed': max(0, pts - customer.total_points),
        })

    return JsonResponse({
        'success': True,
        'customer': {
            'id': customer.id,
            'name': customer.name,
            'phone': customer.phone_number,
            'points': customer.total_points,
            'visits': customer.total_visits,
            'last_scan': customer.last_scan_date.strftime('%d %b %Y') if customer.last_scan_date else 'Never',
        },
        'rewards': rewards_list,
    })
