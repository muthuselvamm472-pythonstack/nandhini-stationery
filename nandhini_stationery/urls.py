from django.contrib import admin
from django.urls import path
from rewards import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.customer_dashboard, name='home'),
    path('login/', views.customer_login, name='login'),
    path('logout/', views.customer_logout, name='logout'),
    path('scan-token/', views.scan_token_redirect, name='scan_token_redirect'),
    path('claim/<str:token>/', views.claim_qr_slip, name='claim_slip'),
    path('dashboard/', views.customer_dashboard, name='dashboard'),
    path('api/check-phone/', views.check_phone_api, name='check_phone_api'),
    path('nandhini-admin/', views.owner_admin_dashboard, name='owner_admin'),
    path('nandhini-admin/export-customers/', views.export_customers_csv, name='owner_export_customers_csv'),
    path('nandhini-admin/backup/download/', views.download_db_backup, name='owner_download_db_backup'),
    path('nandhini-admin/redeem/', views.redeem_reward_reset_points, name='owner_redeem_reward'),
    path('nandhini-admin/customer/<int:customer_id>/delete/', views.delete_customer, name='owner_delete_customer'),
    path('nandhini-admin/customer/<int:customer_id>/restore/', views.restore_customer, name='owner_restore_customer'),
    path('nandhini-admin/customer/<int:customer_id>/permanent-delete/', views.permanent_delete_customer, name='owner_permanent_delete_customer'),
    path('nandhini-admin/customer/undo-permanent-delete/', views.undo_permanent_delete_customer, name='owner_undo_permanent_delete_customer'),
    path('nandhini-admin/settings/tier/update/', views.update_tier_settings, name='owner_update_tier_settings'),
    path('nandhini-admin/settings/gift/save/', views.save_gift_setting, name='owner_save_gift_setting'),
    path('nandhini-admin/settings/gift/<int:gift_id>/delete/', views.delete_gift_setting, name='owner_delete_gift_setting'),
    path('nandhini-admin/settings/gift/undo/', views.undo_delete_gift_setting, name='owner_undo_delete_gift_setting'),
    path('nandhini-admin/settings/whatsapp/save/', views.save_whatsapp_share_setting, name='owner_save_whatsapp_share_setting'),
    path('nandhini-admin/settings/founder/save/', views.save_founder_settings, name='owner_save_founder_settings'),
    path('nandhini-admin/settings/welcome-bonus/save/', views.save_welcome_bonus_settings, name='owner_save_welcome_bonus_settings'),
    path('nandhini-admin/settings/daily-limit/save/', views.save_daily_limit_settings, name='owner_save_daily_limit_settings'),
    path('api/member-pass-qr/', views.member_pass_qr_view, name='member_pass_qr'),
    path('api/counter-customer-lookup/', views.counter_customer_lookup_api, name='counter_customer_lookup_api'),
    path('founder-photo.jpg', views.founder_photo_view, name='founder_photo'),
    # Dynamic RewardItem Studio routes
    path('nandhini-admin/reward-item/save/', views.save_reward_item, name='owner_save_reward_item'),
    path('nandhini-admin/reward-item/<int:item_id>/delete/', views.delete_reward_item, name='owner_delete_reward_item'),
    path('nandhini-admin/reward-item/<int:item_id>/toggle/', views.toggle_reward_item, name='owner_toggle_reward_item'),
    # Broadcast & Push Notification Engine routes
    path('api/latest-broadcast/', views.latest_broadcast_api, name='latest_broadcast_api'),
    path('nandhini-admin/broadcast/send/', views.send_broadcast_notification, name='send_broadcast_notification'),
    path('nandhini-admin/broadcast/<int:broadcast_id>/edit/', views.edit_broadcast_notification, name='edit_broadcast_notification'),
    path('nandhini-admin/broadcast/<int:broadcast_id>/delete/', views.delete_broadcast_notification, name='delete_broadcast_notification'),
    path('nandhini-admin/broadcast/toggle-autopilot/', views.toggle_autopilot_setting, name='toggle_autopilot_setting'),
    # Service Worker & Background Web Push endpoints
    path('sw.js', views.service_worker, name='service_worker'),
    path('api/vapid-public-key/', views.vapid_public_key_api, name='vapid_public_key_api'),
    path('api/save-subscription/', views.save_push_subscription, name='save_push_subscription'),
]

# Fail-safe custom error handlers
handler400 = 'rewards.views.custom_bad_request_view'
handler403 = 'rewards.views.custom_permission_denied_view'
handler404 = 'rewards.views.custom_page_not_found_view'
handler500 = 'rewards.views.custom_server_error_view'

