from django.contrib import admin
from .models import Customer, QRSlip, RedemptionLog


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number', 'total_points', 'total_visits', 'last_scan_date', 'created_at')
    search_fields = ('name', 'phone_number')
    ordering = ('-created_at',)


@admin.register(QRSlip)
class QRSlipAdmin(admin.ModelAdmin):
    list_display = ('token', 'tier', 'points_awarded', 'is_used', 'claimed_by', 'claimed_at')
    list_filter = ('tier', 'is_used', 'claimed_at')
    search_fields = ('token', 'claimed_by__phone_number', 'claimed_by__name')
    ordering = ('-created_at',)


@admin.register(RedemptionLog)
class RedemptionLogAdmin(admin.ModelAdmin):
    list_display = ('customer', 'reward_name', 'points_spent', 'redeemed_at')
    search_fields = ('customer__name', 'customer__phone_number', 'reward_name')
    ordering = ('-redeemed_at',)
