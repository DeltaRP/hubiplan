from django.urls import include, path

from finance import quittung_views

from . import admin_api, send, views

urlpatterns = [
    path("instance/", views.InstanceView.as_view(), name="app-instance"),
    path("pairing/", views.PairingCodeView.as_view(), name="app-pairing"),
    path("pairing/<int:pk>/", views.PairingStatusView.as_view(), name="app-pairing-status"),
    path("pair/", views.PairView.as_view(), name="app-pair"),
    path("devices/", views.DeviceListView.as_view(), name="app-devices"),
    path("devices/current/push/", views.PushView.as_view(), name="app-device-push"),
    path("devices/current/key/", views.DeviceKeyView.as_view(), name="app-device-key"),
    path("devices/current/renew/", views.DeviceRenewView.as_view(), name="app-device-renew"),
    path("devices/<int:pk>/", views.DeviceDetailView.as_view(), name="app-device"),
    path("devices/<int:pk>/admin/", views.DeviceAdminLockView.as_view(), name="app-device-admin"),
    path("me/", views.MeView.as_view(), name="app-me"),
    path("me/language/", views.AppLanguageView.as_view(), name="app-language"),
    path("send/", send.SendersView.as_view(), name="app-senders"),
    path("send/<str:kind>/<int:pk>/", send.SendShortView.as_view(), name="app-send-short"),
    # Verwaltung (Schritt A8)
    path("admin/", admin_api.AdminOverviewView.as_view(), name="app-admin"),
    path("admin/unlock/", admin_api.AdminUnlockView.as_view(), name="app-admin-unlock"),
    path(
        "admin/signature/",
        admin_api.for_app(quittung_views.MySignatureView).as_view(),
        name="app-admin-signature",
    ),
    path("admin/u/<int:org_id>/tasks/", admin_api.AdminTasksView.as_view(), name="app-admin-tasks"),
    path("admin/u/<int:org_id>/", include("devices.admin_urls")),
    path("admin/d/<int:dept_id>/", include("devices.admin_dept_urls")),
]
