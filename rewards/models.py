import secrets
from django.db import models
from django.utils import timezone


class Customer(models.Model):
    objects = models.Manager()
    phone_number = models.CharField(max_length=10, unique=True, db_index=True)
    name = models.CharField(max_length=60)
    pin_code = models.CharField(max_length=4, blank=True, default='')  # PIN removed from customer flow
    total_points = models.IntegerField(default=0)  # type: ignore[reportArgumentType]
    total_visits = models.IntegerField(default=0)  # type: ignore[reportArgumentType]
    last_scan_date = models.DateField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)  # type: ignore[reportArgumentType]
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Strict Floor Protection: Points can NEVER drop below zero
        if self.total_points < 0:
            self.total_points = 0
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.phone_number}) - {self.total_points} Pts"


class SlipTierConfig(models.Model):
    objects = models.Manager()
    tier_key = models.CharField(max_length=10, unique=True)  # '50', '100', '500', '1000'
    min_spend = models.IntegerField(default=50)  # type: ignore[reportArgumentType]
    chit_name = models.CharField(max_length=60, default='Pink Chit')
    chit_color = models.CharField(max_length=20, default='rose')  # rose, sky, purple, emerald
    points = models.IntegerField(default=50)  # type: ignore[reportArgumentType]
    subtitle = models.CharField(max_length=150, blank=True, default='')
    badge_label = models.CharField(max_length=40, blank=True, default='1x Base')
    sort_order = models.IntegerField(default=1)  # type: ignore[reportArgumentType]

    class Meta:
        ordering = ['sort_order', 'min_spend']

    def __str__(self):
        return f"{self.chit_name} (₹{self.min_spend}+ -> +{self.points} Pts)"


class GiftRewardItem(models.Model):
    objects = models.Manager()
    name = models.CharField(max_length=140)
    points = models.IntegerField(default=350)  # type: ignore[reportArgumentType]
    icon = models.CharField(max_length=20, default='🎁')
    desc = models.CharField(max_length=250, blank=True, default='')
    is_active = models.BooleanField(default=True)  # type: ignore[reportArgumentType]
    sort_order = models.IntegerField(default=1)  # type: ignore[reportArgumentType]

    class Meta:
        ordering = ['points', 'sort_order']

    def __str__(self):
        return f"{self.icon} {self.name} ({self.points} Pts)"


class RewardItem(models.Model):
    objects = models.Manager()
    name = models.CharField(max_length=140)
    points_required = models.PositiveIntegerField(db_index=True)
    icon = models.CharField(max_length=20, default='🎁')
    description = models.CharField(max_length=250, blank=True, default='')
    is_active = models.BooleanField(default=True, db_index=True)  # type: ignore[reportArgumentType]
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['points_required']

    def __str__(self):
        return f"{self.icon} {self.name} ({self.points_required} Pts)"


class BroadcastNotification(models.Model):
    objects = models.Manager()
    HAPTIC_CHOICES = (
        ('pulse', 'Gentle Pulse ([80, 50, 160])'),
        ('celebration', 'Celebration Double-Beat ([100, 40, 100, 40, 220])'),
        ('silent', 'Silent Visual Only'),
    )

    title = models.CharField(max_length=150)
    message = models.TextField()
    haptic_style = models.CharField(max_length=20, choices=HAPTIC_CHOICES, default='pulse')
    is_active = models.BooleanField(default=True, db_index=True)  # type: ignore[reportArgumentType]
    is_automated = models.BooleanField(default=False)  # type: ignore[reportArgumentType]
    preset_key = models.CharField(max_length=60, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.created_at.strftime('%d %b %I:%M %p')}] {self.title}"


class SystemSetting(models.Model):
    objects = models.Manager()
    key = models.CharField(max_length=60, unique=True)
    value = models.TextField(default='')

    def __str__(self):
        return f"{self.key}: {self.value}"


class QRSlip(models.Model):
    objects = models.Manager()
    TIER_CHOICES = (
        ('50', 'Tier Rs.50+ (Pink - 50 Pts)'),
        ('100', 'Tier Rs.100+ (Blue - 150 Pts)'),
        ('500', 'Tier Rs.500+ (Purple - 800 Pts)'),
        ('1000', 'Tier Rs.1000+ (Green - 2000 Pts)'),
    )

    TIER_POINTS_MAP = {
        '50': 50,
        '100': 150,
        '500': 800,
        '1000': 2000,
    }

    token = models.CharField(max_length=12, unique=True, db_index=True, editable=False)
    tier = models.CharField(max_length=10, choices=TIER_CHOICES)
    points_awarded = models.IntegerField()
    batch_number = models.IntegerField(default=1)  # type: ignore[reportArgumentType]
    is_used = models.BooleanField(default=False, db_index=True)  # type: ignore[reportArgumentType]
    claimed_by = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='claimed_slips'
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_hex(6).upper()
        if not self.points_awarded:
            # Check dynamic tier configuration first if available
            tier_cfg = SlipTierConfig.objects.filter(tier_key=str(self.tier)).first()
            if tier_cfg:
                self.points_awarded = tier_cfg.points
            else:
                self.points_awarded = self.TIER_POINTS_MAP.get(str(self.tier), 50)
        super().save(*args, **kwargs)

    def __str__(self):
        status = "USED" if self.is_used else "ACTIVE"
        return f"[Rs.{self.tier}] {self.token} ({status})"


class RedemptionLog(models.Model):
    objects = models.Manager()
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='redemptions')
    reward_name = models.CharField(max_length=120)
    points_spent = models.IntegerField(default=0)  # type: ignore[reportArgumentType]
    redeemed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default='')

    def __str__(self):
        return f"{self.customer.name} - {self.reward_name} ({self.points_spent} Pts)"


class PushSubscription(models.Model):
    objects = models.Manager()
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='push_subscriptions')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PushSubscription ({str(self.endpoint)[:35]}...)"
