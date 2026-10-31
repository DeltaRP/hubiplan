"""Pfade der Verwaltung in der App unter ``/api/app/v1/admin/u/<Einheit>/`` (Schritt B2).

Gleiche Unterpfade wie im Browser (``/api/orgs/<Einheit>/…``), damit die App dieselben
Antworten bekommt. Diese Felder sind damit Teil der App-Schnittstelle: Änderungen nur
abwärtskompatibel (neue Felder ja, umbenennen oder entfernen nein).
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from billing import views as billing_views
from cards import views as card_views
from changes import views as change_views
from customfields import views as field_views
from events import views as event_views
from finance import quittung_views
from finance import views as finance_views
from members import honorary as honorary_views
from members import jubilee_views, photo_views, workflow_views
from members import views as member_views
from organizations import views as org_views
from portal import views as portal_views

from . import admin_finance, admin_members
from .admin_api import for_app

org_router = SimpleRouter()
org_router.register(
    "member-types", for_app(member_views.MemberTypeViewSet, True), basename="app-admin-member-type"
)
org_router.register(
    "fields", for_app(field_views.FieldDefinitionViewSet, True), basename="app-admin-field"
)
org_router.register(
    "departments", for_app(org_views.DepartmentViewSet, True), basename="app-admin-department"
)
org_router.register(
    "honorary-titles",
    for_app(honorary_views.HonoraryTitleViewSet, True),
    basename="app-admin-honorary-title",
)
org_router.register(
    "billing/mandates", admin_members.AppMandateViewSet, basename="app-admin-mandate"
)
# B4 Kasse: Konten und Kategorien nur lesen, Buchungen lesen (neu nur mit Beleg, s. u.)
org_router.register(
    "finance/accounts", for_app(finance_views.AccountViewSet, True), basename="app-admin-account"
)
org_router.register(
    "finance/categories",
    for_app(finance_views.CategoryViewSet, True),
    basename="app-admin-category",
)
org_router.register(
    "finance/bookings", for_app(finance_views.BookingViewSet, True), basename="app-admin-booking"
)
# B5 Beiträge: Rechnungen suchen und lesen (Barzahlung über einen eigenen Pfad, s. u.)
org_router.register(
    "billing/invoices", for_app(billing_views.InvoiceViewSet, True), basename="app-admin-invoice"
)
# Quittung mit Unterschrift (konzepte/digitale-quittung.md): wie im Browser
org_router.register(
    "finance/cash-receipts",
    for_app(quittung_views.CashReceiptViewSet),
    basename="app-admin-cash-receipt",
)

member_router = SimpleRouter()
member_router.register("periods", for_app(member_views.PeriodViewSet), basename="app-admin-period")
member_router.register(
    "departments",
    for_app(member_views.DepartmentMembershipViewSet),
    basename="app-admin-member-department",
)
member_router.register(
    "department-roles",
    for_app(member_views.DepartmentRoleHolderViewSet),
    basename="app-admin-member-department-role",
)
member_router.register(
    "honorary-titles",
    for_app(honorary_views.MemberAwardViewSet),
    basename="app-admin-member-honorary-title",
)


def _p(route: str, view, name: str):
    return path(route, for_app(view).as_view(), name=f"app-admin-{name}")


urlpatterns = [
    _p("members/", member_views.MemberListView, "members"),
    _p("members/duplicates/", member_views.DuplicateView, "member-duplicates"),
    _p("members/admit/", member_views.AdmitView, "member-admit"),
    _p("members/<int:pk>/", member_views.MemberDetailView, "member"),
    _p("members/<int:pk>/history/", member_views.MemberHistoryView, "member-history"),
    _p("members/<int:pk>/change-type/", workflow_views.ChangeTypeView, "member-change-type"),
    _p("members/<int:pk>/exit/", workflow_views.ExitView, "member-exit"),
    _p("members/<int:pk>/reentry/", workflow_views.ReentryView, "member-reentry"),
    _p("members/<int:pk>/fields/", field_views.MemberFieldsView, "member-fields"),
    _p("members/<int:pk>/photo/", photo_views.MemberPhotoView, "member-photo"),
    _p("members/<int:pk>/photo/approve/", photo_views.PhotoApproveView, "member-photo-approve"),
    _p("members/<int:pk>/photo/rotate/", photo_views.PhotoRotateView, "member-photo-rotate"),
    _p("members/<int:pk>/photo/consent/", photo_views.PhotoConsentView, "member-photo-consent"),
    _p("members/<int:pk>/card/", card_views.MemberCardView, "member-card"),
    path(
        "members/<int:pk>/preview/",
        for_app(admin_members.MemberPreviewView).as_view(),
        name="app-admin-member-preview",
    ),
    path(
        "members/<int:pk>/move/",
        for_app(admin_members.MemberMoveView).as_view(),
        name="app-admin-member-move",
    ),
    path("members/<int:member_pk>/", include(member_router.urls)),
    _p("change-requests/", portal_views.ChangeRequestListView, "change-requests"),
    _p(
        "change-requests/<int:pk>/decide/",
        portal_views.ChangeRequestDecisionView,
        "change-request-decide",
    ),
    _p("changes/<uuid:set_id>/undo/", change_views.UndoView, "undo"),
    _p("birthdays/", jubilee_views.BirthdayView, "birthdays"),
    _p("jubilees/", jubilee_views.JubileeView, "jubilees"),
    path(
        "cards/check/",
        for_app(admin_members.CardCheckView).as_view(),
        name="app-admin-card-check",
    ),
    # B3: Termine der Einheit, Rückmeldungen (gleiche Rechte wie im Browser: events.manage)
    _p("events/", event_views.OrgEventListView, "events"),
    _p("events/<int:pk>/", event_views.OrgEventDetailView, "event"),
    _p("events/<int:pk>/notify/", event_views.OrgEventNotifyView, "event-notify"),
    _p("events/<int:pk>/occurrence/", event_views.OrgEventOccurrenceView, "event-occurrence"),
    _p("events/<int:pk>/responses/", event_views.OrgResponsesView, "event-responses"),
    _p(
        "events/<int:pk>/responses/<int:membership_id>/",
        event_views.OrgResponseDetailView,
        "event-response",
    ),
    # B4: Kasse
    _p("finance/overview/", finance_views.OverviewView, "finance-overview"),
    path(
        "finance/receipts/<int:pk>/",
        for_app(finance_views.ReceiptView, True).as_view(),
        name="app-admin-finance-receipt",
    ),
    _p(
        "finance/bookings/<int:pk>/receipts/",
        finance_views.ReceiptUploadView,
        "finance-receipt-upload",
    ),
    path(
        "finance/app-booking/",
        admin_finance.AppBookingView.as_view(),
        name="app-admin-finance-booking",
    ),
    # B5: Barzahlung und Quittung
    path(
        "billing/settings/",
        for_app(billing_views.BillingSettingsView, True).as_view(),
        name="app-admin-billing-settings",
    ),
    path(
        "billing/invoices/<int:pk>/cash/",
        admin_finance.AppCashPaymentView.as_view(),
        name="app-admin-invoice-cash",
    ),
    _p(
        "billing/payments/<int:pk>/receipt/",
        billing_views.PaymentReceiptView,
        "billing-payment-receipt",
    ),
    path("", include(org_router.urls)),
]
