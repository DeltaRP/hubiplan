from django.urls import include, path
from rest_framework.routers import SimpleRouter

from access import office_views
from access import views as access_views
from accounts import language, learning, self_service
from billing import portal_views as billing_portal_views
from billing import views as billing_views
from cards import views as card_views
from changes import views as change_views
from circulars import urls as circular_urls
from competitions import urls as competition_urls
from customfields import views as field_views
from datatransfer import views as transfer_views
from documents import views as doc_views
from entries import urls as entry_urls
from events import views as event_views
from exchange import views as exchange_views
from finance import bank_views, cash_count_views, donation_views, quittung_views, reserve_views
from finance import views as finance_views
from honors import urls as honors_urls
from letterhead import views as letterhead_views
from members import (
    federation_views,
    jubilee_views,
    open_tasks,
    photo_views,
    statistics_views,
    workflow_views,
)
from members import honorary as honorary_views
from members import views as member_views
from organizations import imprint_views, social_views
from organizations import views as org_views
from outbox import views as outbox_views
from peering import urls as peering_urls
from portal import views as portal_views
from statutes import views as statute_views
from website import urls as website_urls

from . import views

org_router = SimpleRouter()
org_router.register("departments", org_views.DepartmentViewSet, basename="department")
org_router.register("finance/accounts", finance_views.AccountViewSet, basename="finance-account")
org_router.register(
    "finance/categories", finance_views.CategoryViewSet, basename="finance-category"
)
org_router.register("finance/bookings", finance_views.BookingViewSet, basename="finance-booking")
org_router.register("finance/projects", finance_views.ProjectViewSet, basename="finance-project")
org_router.register("finance/series", finance_views.ProjectSeriesViewSet, basename="finance-series")
org_router.register(
    "finance/cash-receipts", quittung_views.CashReceiptViewSet, basename="finance-cash-receipt"
)
org_router.register(
    "finance/donations", donation_views.DonationViewSet, basename="finance-donation"
)
org_router.register(
    "finance/bank-statements", bank_views.BankStatementViewSet, basename="finance-bank-statement"
)
org_router.register("finance/bank-lines", bank_views.BankLineViewSet, basename="finance-bank-line")
org_router.register(
    "finance/cash-counts", cash_count_views.CashCountViewSet, basename="finance-cash-count"
)
org_router.register("finance/reserves", reserve_views.ReserveViewSet, basename="finance-reserve")
org_router.register(
    "finance/donation-statements",
    donation_views.DonationStatementViewSet,
    basename="finance-donation-statement",
)
org_router.register("billing/age-rates", billing_views.AgeRateViewSet, basename="billing-age-rate")
org_router.register("billing/runs", billing_views.FeeRunViewSet, basename="billing-run")
org_router.register("billing/invoices", billing_views.InvoiceViewSet, basename="billing-invoice")
org_router.register(
    "billing/dunning-levels", billing_views.DunningLevelViewSet, basename="billing-dunning-level"
)
org_router.register("billing/mandates", billing_views.MandateViewSet, basename="billing-mandate")
org_router.register("billing/debits", billing_views.DebitRunViewSet, basename="billing-debit")
org_router.register("clubs", org_views.FederationClubViewSet, basename="federation-club")
org_router.register("department-roles", org_views.DepartmentRoleViewSet, basename="department-role")
org_router.register("roles", access_views.RoleViewSet, basename="role")
org_router.register("assignments", access_views.AssignmentViewSet, basename="assignment")
org_router.register("member-types", member_views.MemberTypeViewSet, basename="member-type")
org_router.register(
    "honorary-titles", honorary_views.HonoraryTitleViewSet, basename="honorary-title"
)
org_router.register("fields", field_views.FieldDefinitionViewSet, basename="field")
org_router.register("social-links", social_views.SocialLinkViewSet, basename="social-link")
org_router.register("exports", exchange_views.ExportJobViewSet, basename="export")
org_router.register(
    "export-templates", exchange_views.ExportTemplateViewSet, basename="export-template"
)
org_router.register("imports", exchange_views.ImportJobViewSet, basename="import")
org_router.register(
    "import-templates", exchange_views.ImportTemplateViewSet, basename="import-template"
)

member_router = SimpleRouter()
member_router.register("periods", member_views.PeriodViewSet, basename="member-period")
member_router.register(
    "departments", member_views.DepartmentMembershipViewSet, basename="member-department"
)
member_router.register(
    "department-roles", member_views.DepartmentRoleHolderViewSet, basename="member-department-role"
)
member_router.register(
    "honorary-titles", honorary_views.MemberAwardViewSet, basename="member-honorary-title"
)

federation_member_router = SimpleRouter()
federation_member_router.register(
    "honorary-titles",
    honorary_views.FederationAwardViewSet,
    basename="federation-member-honorary-title",
)

platform_router = SimpleRouter()
platform_router.register("orgs", org_views.PlatformOrganizationViewSet, basename="platform-org")

org_patterns = [
    path("", org_views.OrganizationDetailView.as_view(), name="org-detail"),
    path("theme/", org_views.ThemeView.as_view(), name="org-theme"),
    path("imprint/", imprint_views.OrgImprintView.as_view(), name="org-imprint"),
    path(
        "imprint/units/<int:unit_id>/",
        imprint_views.UnitImprintView.as_view(),
        name="unit-imprint",
    ),
    path("letterhead/", letterhead_views.OrgLetterheadView.as_view(), name="org-letterhead"),
    path(
        "letterhead/units/<int:unit_id>/",
        letterhead_views.UnitLetterheadView.as_view(),
        name="unit-letterhead",
    ),
    path(
        "letterhead/preview/",
        letterhead_views.OrgLetterheadPreviewView.as_view(),
        name="org-letterhead-preview",
    ),
    path(
        "letterhead/download/",
        letterhead_views.OrgLetterheadDownloadView.as_view(),
        name="org-letterhead-download",
    ),
    path(
        "letterhead/publish/",
        letterhead_views.OrgLetterheadPublishView.as_view(),
        name="org-letterhead-publish",
    ),
    path("logo/", org_views.OrganizationLogoView.as_view(), name="org-logo"),
    path(
        "departments/<int:pk>/logo/",
        org_views.DepartmentLogoView.as_view(),
        name="department-logo",
    ),
    path(
        "departments/<int:pk>/homepage-image/",
        org_views.DepartmentHomepageImageView.as_view(),
        name="department-homepage-image",
    ),
    path("ansicht/", access_views.RolePreviewView.as_view(), name="org-role-preview"),
    path("audit/", access_views.AuditListView.as_view(), name="org-audit"),
    path("audit/kette/", access_views.AuditChainView.as_view(), name="org-audit-chain"),
    path("changes/<uuid:set_id>/undo/", change_views.UndoView.as_view(), name="org-change-undo"),
    path("members/", member_views.MemberListView.as_view(), name="member-list"),
    path("members/duplicates/", member_views.DuplicateView.as_view(), name="member-duplicates"),
    path("members/admit/", member_views.AdmitView.as_view(), name="member-admit"),
    path("members/<int:pk>/", member_views.MemberDetailView.as_view(), name="member-detail"),
    path(
        "members/<int:pk>/federation/",
        member_views.FederationEntryView.as_view(),
        name="member-federation",
    ),
    path(
        "members/<int:pk>/history/", member_views.MemberHistoryView.as_view(), name="member-history"
    ),
    path(
        "members/<int:pk>/change-type/",
        workflow_views.ChangeTypeView.as_view(),
        name="member-change-type",
    ),
    path("members/<int:pk>/exit/", workflow_views.ExitView.as_view(), name="member-exit"),
    path(
        "members/<int:pk>/auskunft/",
        member_views.MemberDisclosureView.as_view(),
        name="member-disclosure",
    ),
    path("members/<int:pk>/erase/", member_views.MemberErasureView.as_view(), name="member-erase"),
    path("members/<int:pk>/reentry/", workflow_views.ReentryView.as_view(), name="member-reentry"),
    path("members/<int:pk>/fields/", field_views.MemberFieldsView.as_view(), name="member-fields"),
    path("jubilees/", jubilee_views.JubileeView.as_view(), name="jubilees"),
    path("unit-jubilees/", jubilee_views.UnitJubileeView.as_view(), name="unit-jubilees"),
    path("birthdays/", jubilee_views.BirthdayView.as_view(), name="birthdays"),
    path(
        "members/statistics/",
        statistics_views.ClubStatisticsView.as_view(),
        name="member-statistics",
    ),
    path(
        "federation/statistics/",
        statistics_views.FederationStatisticsView.as_view(),
        name="federation-statistics",
    ),
    path(
        "federation/members/",
        federation_views.FederationMemberListView.as_view(),
        name="federation-members",
    ),
    path(
        "federation/members/<int:pk>/",
        federation_views.FederationMemberDetailView.as_view(),
        name="federation-member",
    ),
    path(
        "federation/clubs/", federation_views.FederationClubsView.as_view(), name="federation-clubs"
    ),
    path("export-columns/", exchange_views.ColumnsView.as_view(), name="export-columns"),
    path(
        "exports/<int:pk>/download/",
        exchange_views.ExportDownloadView.as_view(),
        name="export-download",
    ),
    path("import-targets/", exchange_views.ImportTargetsView.as_view(), name="import-targets"),
    path(
        "imports/<int:pk>/values/", exchange_views.ImportValuesView.as_view(), name="import-values"
    ),
    path(
        "imports/<int:pk>/validate/",
        exchange_views.ImportValidateView.as_view(),
        name="import-validate",
    ),
    path("imports/<int:pk>/run/", exchange_views.ImportRunView.as_view(), name="import-run"),
    path("imports/<int:pk>/undo/", exchange_views.ImportUndoView.as_view(), name="import-undo"),
    path(
        "imports/<int:pk>/errors/",
        exchange_views.ImportErrorFileView.as_view(),
        name="import-errors",
    ),
    path("members/<int:pk>/photo/", photo_views.MemberPhotoView.as_view(), name="member-photo"),
    path(
        "members/<int:pk>/photo/rotate/",
        photo_views.PhotoRotateView.as_view(),
        name="member-photo-rotate",
    ),
    path(
        "members/<int:pk>/photo/approve/",
        photo_views.PhotoApproveView.as_view(),
        name="member-photo-approve",
    ),
    path(
        "members/<int:pk>/photo/consent/",
        photo_views.PhotoConsentView.as_view(),
        name="member-photo-consent",
    ),
    path("members/<int:pk>/photo-links/", photo_views.PhotoLinkView.as_view(), name="photo-links"),
    path(
        "members/<int:pk>/photo-links/<int:link_id>/revoke/",
        photo_views.PhotoLinkRevokeView.as_view(),
        name="photo-link-revoke",
    ),
    path("members/<int:member_pk>/", include(member_router.urls)),
    path("federation/members/<int:member_pk>/", include(federation_member_router.urls)),
    path("transfers/", workflow_views.TransferListView.as_view(), name="transfer-list"),
    path(
        "transfers/<int:pk>/decide/",
        workflow_views.TransferDecisionView.as_view(),
        name="transfer-decide",
    ),
    path(
        "transfers/<int:pk>/cancel/",
        workflow_views.TransferCancelView.as_view(),
        name="transfer-cancel",
    ),
    path("members/<int:pk>/access/", portal_views.MemberAccessView.as_view(), name="member-access"),
    path("change-requests/", portal_views.ChangeRequestListView.as_view(), name="change-requests"),
    path("open-tasks/", open_tasks.OpenTasksView.as_view(), name="open-tasks"),
    path(
        "change-requests/<int:pk>/decide/",
        portal_views.ChangeRequestDecisionView.as_view(),
        name="change-request-decide",
    ),
    path("outbox/", outbox_views.OrgOutboxView.as_view(), name="org-outbox"),
    path(
        "outbox/<int:pk>/attachments/<int:index>/",
        outbox_views.OrgOutboxAttachmentView.as_view(),
        name="org-outbox-attachment",
    ),
    path("members/<int:pk>/card/", card_views.MemberCardView.as_view(), name="member-card"),
    path("cards/pdf/", card_views.OrgCardsPdfView.as_view(), name="cards-pdf"),
    path("finance/overview/", finance_views.OverviewView.as_view(), name="finance-overview"),
    path("finance/statistics/", finance_views.StatisticsView.as_view(), name="finance-statistics"),
    path("finance/settings/", finance_views.FinanceSettingsView.as_view(), name="finance-settings"),
    path(
        "finance/donation-settings/",
        donation_views.DonationSettingsView.as_view(),
        name="finance-donation-settings",
    ),
    path("finance/closings/", finance_views.YearClosingView.as_view(), name="finance-closings"),
    path(
        "finance/closings/aufbewahrung/",
        finance_views.RetentionView.as_view(),
        name="finance-retention",
    ),
    path("finance/report/", finance_views.CashReportView.as_view(), name="finance-report"),
    path("finance/export/", finance_views.ExportView.as_view(), name="finance-export"),
    path("finance/einvoice/", finance_views.EInvoiceReadView.as_view(), name="finance-einvoice"),
    path("finance/datev/", finance_views.DatevExportView.as_view(), name="finance-datev"),
    path(
        "finance/bookings/<int:pk>/receipts/",
        finance_views.ReceiptUploadView.as_view(),
        name="finance-receipt-upload",
    ),
    path(
        "finance/receipts/<int:pk>/",
        finance_views.ReceiptView.as_view(),
        name="finance-receipt",
    ),
    path("billing/settings/", billing_views.BillingSettingsView.as_view(), name="billing-settings"),
    path("billing/fees/", billing_views.FeeRatesView.as_view(), name="billing-fees"),
    path("billing/payments/<int:pk>/", billing_views.PaymentView.as_view(), name="billing-payment"),
    path(
        "billing/payments/<int:pk>/receipt/",
        billing_views.PaymentReceiptView.as_view(),
        name="billing-payment-receipt",
    ),
    path("billing/overview/", billing_views.BillingOverviewView.as_view(), name="billing-overview"),
    path("billing/members/", billing_views.BillingMembersView.as_view(), name="billing-members"),
    path("billing/dunnings/", billing_views.DunningsView.as_view(), name="billing-dunnings"),
    path(
        "billing/dunnings/pdf/", billing_views.DunningPdfView.as_view(), name="billing-dunning-pdf"
    ),
    path(
        "billing/received/",
        billing_views.ReceivedInvoicesView.as_view(),
        name="billing-received",
    ),
    path(
        "billing/received/<int:pk>/pdf/",
        billing_views.ReceivedInvoicePdfView.as_view(),
        name="billing-received-pdf",
    ),
    path("datatransfer/exports/", transfer_views.OrgExportView.as_view(), name="dt-exports"),
    path(
        "datatransfer/exports/<int:pk>/",
        transfer_views.OrgExportDetailView.as_view(),
        name="dt-export",
    ),
    path(
        "datatransfer/exports/<int:pk>/download/",
        transfer_views.OrgExportDownloadView.as_view(),
        name="dt-export-download",
    ),
    path("datatransfer/imports/", transfer_views.OrgImportView.as_view(), name="dt-imports"),
    path(
        "datatransfer/imports/<int:pk>/",
        transfer_views.OrgImportDetailView.as_view(),
        name="dt-import",
    ),
    path(
        "datatransfer/imports/<int:pk>/run/",
        transfer_views.OrgImportRunView.as_view(),
        name="dt-import-run",
    ),
    path(
        "federation/clubs/new/",
        transfer_views.FederationClubCreateView.as_view(),
        name="federation-club-create",
    ),
    path("documents/", doc_views.OrgOverviewView.as_view(), name="documents"),
    path("documents/trash/", doc_views.OrgTrashView.as_view(), name="documents-trash"),
    path("documents/folders/", doc_views.OrgFoldersView.as_view(), name="doc-folders"),
    path(
        "documents/folders/<int:pk>/",
        doc_views.OrgFolderDetailView.as_view(),
        name="doc-folder",
    ),
    path(
        "documents/folders/<int:pk>/documents/",
        doc_views.OrgFolderDocumentsView.as_view(),
        name="doc-folder-documents",
    ),
    path(
        "documents/<int:pk>/",
        doc_views.OrgDocumentDetailView.as_view(),
        name="document",
    ),
    path(
        "documents/<int:pk>/restore/",
        doc_views.OrgDocumentRestoreView.as_view(),
        name="document-restore",
    ),
    path(
        "documents/<int:pk>/versions/",
        doc_views.OrgDocumentVersionsView.as_view(),
        name="document-versions",
    ),
    path(
        "documents/versions/<int:pk>/",
        doc_views.OrgVersionView.as_view(),
        name="document-version",
    ),
    path("statutes/", statute_views.StatuteListView.as_view(), name="statutes"),
    path(
        "statutes/publication/",
        statute_views.StatutePublicationView.as_view(),
        name="statute-publication",
    ),
    path("statutes/<int:pk>/", statute_views.StatuteDetailView.as_view(), name="statute"),
    path("events/", event_views.OrgEventListView.as_view(), name="events"),
    path("events/program/", event_views.OrgProgramView.as_view(), name="events-program"),
    path("events/sharing/", event_views.OrgSharingView.as_view(), name="events-sharing"),
    path(
        "events/publication/",
        event_views.OrgPublicationView.as_view(),
        name="events-publication",
    ),
    path("events/categories/", event_views.OrgCategoriesView.as_view(), name="event-categories"),
    path(
        "events/categories/<int:pk>/",
        event_views.OrgCategoryDetailView.as_view(),
        name="event-category",
    ),
    path("events/<int:pk>/", event_views.OrgEventDetailView.as_view(), name="event"),
    path("events/<int:pk>/notify/", event_views.OrgEventNotifyView.as_view(), name="event-notify"),
    path(
        "events/<int:pk>/project/", event_views.OrgEventProjectView.as_view(), name="event-project"
    ),
    path(
        "events/<int:pk>/occurrence/",
        event_views.OrgEventOccurrenceView.as_view(),
        name="event-occurrence",
    ),
    path(
        "events/<int:pk>/attachments/",
        event_views.OrgAttachmentListView.as_view(),
        name="event-attachments",
    ),
    path(
        "events/<int:pk>/attachments/<int:att_id>/",
        event_views.OrgAttachmentView.as_view(),
        name="event-attachment",
    ),
    path(
        "events/<int:pk>/responses/",
        event_views.OrgResponsesView.as_view(),
        name="event-responses",
    ),
    path(
        "events/<int:pk>/responses/export/",
        event_views.OrgResponseExportView.as_view(),
        name="event-responses-export",
    ),
    path(
        "events/<int:pk>/responses/<int:membership_id>/",
        event_views.OrgResponseDetailView.as_view(),
        name="event-response",
    ),
    path("events/<int:pk>/ics/", event_views.OrgEventIcsView.as_view(), name="event-ics"),
    *circular_urls.org_patterns,
    *website_urls.org_patterns,
    *honors_urls.org_patterns,
    *competition_urls.org_patterns,
    *entry_urls.org_patterns,
    path("offices/", office_views.OfficesView.as_view(), name="offices"),
    path("offices/<int:pk>/", office_views.OfficeEntryView.as_view(), name="office-entry"),
    path(
        "offices/import/preview/",
        office_views.ImportPreviewView.as_view(),
        name="offices-import-preview",
    ),
    path("offices/import/", office_views.ImportView.as_view(), name="offices-import"),
    *org_router.urls,
]

dept_patterns = [
    *entry_urls.dept_patterns,
    path(
        "changes/<uuid:set_id>/undo/",
        change_views.DeptUndoView.as_view(),
        name="dept-change-undo",
    ),
    path("datatransfer/exports/", transfer_views.DeptExportView.as_view(), name="dept-dt-exports"),
    path(
        "datatransfer/exports/<int:pk>/",
        transfer_views.DeptExportDetailView.as_view(),
        name="dept-dt-export",
    ),
    path(
        "datatransfer/exports/<int:pk>/download/",
        transfer_views.DeptExportDownloadView.as_view(),
        name="dept-dt-export-download",
    ),
    path("", portal_views.DepartmentInfoView.as_view(), name="dept-info"),
    path("members/", portal_views.DepartmentMemberListView.as_view(), name="dept-members"),
    path(
        "statistics/",
        statistics_views.DepartmentStatisticsView.as_view(),
        name="dept-statistics",
    ),
    path(
        "members/<int:pk>/",
        portal_views.DepartmentMemberDetailView.as_view(),
        name="dept-member",
    ),
    path(
        "members/<int:pk>/access/",
        portal_views.DepartmentMemberAccessView.as_view(),
        name="dept-member-access",
    ),
    path("invoices/", billing_portal_views.DepartmentInvoicesView.as_view(), name="dept-invoices"),
    path(
        "invoices/<int:pk>/pdf/",
        billing_portal_views.DepartmentInvoicePdfView.as_view(),
        name="dept-invoice-pdf",
    ),
    path(
        "members/<int:pk>/card/", card_views.DeptMemberCardView.as_view(), name="dept-member-card"
    ),
    path("cards/pdf/", card_views.DeptCardsPdfView.as_view(), name="dept-cards-pdf"),
    path("events/", event_views.DeptEventListView.as_view(), name="dept-events"),
    path("events/program/", event_views.DeptProgramView.as_view(), name="dept-events-program"),
    path("events/sharing/", event_views.DeptSharingView.as_view(), name="dept-events-sharing"),
    path(
        "events/publication/",
        event_views.DeptPublicationView.as_view(),
        name="dept-events-publication",
    ),
    path("events/<int:pk>/", event_views.DeptEventDetailView.as_view(), name="dept-event"),
    path(
        "events/<int:pk>/notify/",
        event_views.DeptEventNotifyView.as_view(),
        name="dept-event-notify",
    ),
    path(
        "events/<int:pk>/occurrence/",
        event_views.DeptEventOccurrenceView.as_view(),
        name="dept-event-occurrence",
    ),
    path(
        "events/<int:pk>/attachments/",
        event_views.DeptAttachmentListView.as_view(),
        name="dept-event-attachments",
    ),
    path(
        "events/<int:pk>/attachments/<int:att_id>/",
        event_views.DeptAttachmentView.as_view(),
        name="dept-event-attachment",
    ),
    path(
        "events/<int:pk>/responses/",
        event_views.DeptResponsesView.as_view(),
        name="dept-event-responses",
    ),
    path(
        "events/<int:pk>/responses/export/",
        event_views.DeptResponseExportView.as_view(),
        name="dept-event-responses-export",
    ),
    path(
        "events/<int:pk>/responses/<int:membership_id>/",
        event_views.DeptResponseDetailView.as_view(),
        name="dept-event-response",
    ),
    path("events/<int:pk>/ics/", event_views.DeptEventIcsView.as_view(), name="dept-event-ics"),
    path("roles/", portal_views.DepartmentRolesView.as_view(), name="dept-roles"),
    path(
        "roles/reorder/", portal_views.DepartmentRoleOrderView.as_view(), name="dept-roles-reorder"
    ),
    path("roles/<int:pk>/", portal_views.DepartmentRoleDetailView.as_view(), name="dept-role"),
    path("documents/", doc_views.DeptOverviewView.as_view(), name="dept-documents"),
    path("documents/trash/", doc_views.DeptTrashView.as_view(), name="dept-documents-trash"),
    path("documents/folders/", doc_views.DeptFoldersView.as_view(), name="dept-doc-folders"),
    path(
        "documents/folders/<int:pk>/",
        doc_views.DeptFolderDetailView.as_view(),
        name="dept-doc-folder",
    ),
    path(
        "documents/folders/<int:pk>/documents/",
        doc_views.DeptFolderDocumentsView.as_view(),
        name="dept-doc-folder-documents",
    ),
    path(
        "documents/<int:pk>/",
        doc_views.DeptDocumentDetailView.as_view(),
        name="dept-document",
    ),
    path(
        "documents/<int:pk>/restore/",
        doc_views.DeptDocumentRestoreView.as_view(),
        name="dept-document-restore",
    ),
    path(
        "documents/<int:pk>/versions/",
        doc_views.DeptDocumentVersionsView.as_view(),
        name="dept-document-versions",
    ),
    path(
        "documents/versions/<int:pk>/",
        doc_views.DeptVersionView.as_view(),
        name="dept-document-version",
    ),
    path("holders/", portal_views.DepartmentHoldersView.as_view(), name="dept-holders"),
    path(
        "holders/<int:pk>/end/",
        portal_views.DepartmentHolderEndView.as_view(),
        name="dept-holder-end",
    ),
    *circular_urls.dept_patterns,
]

urlpatterns = [
    path("health/", views.health, name="health"),
    # Android-App (Anmeldung, Geräte); Inhalte über /api/portal/…
    path("app/v1/", include("devices.urls")),
    path(
        "public/imprint/",
        imprint_views.PublicPlatformImprintView.as_view(),
        name="public-platform-imprint",
    ),
    path(
        "public/imprint/<str:key>/",
        imprint_views.PublicImprintView.as_view(),
        name="public-imprint",
    ),
    *circular_urls.public_patterns,
    *website_urls.public_patterns,
    path("portal/<int:access_id>/", include(circular_urls.portal_patterns)),
    path(
        "public/photo/<str:token>/",
        photo_views.PublicPhotoUploadView.as_view(),
        name="public-photo-upload",
    ),
    path("", include(peering_urls)),
    path("public/card/<str:token>/", card_views.PublicCardView.as_view(), name="public-card"),
    *competition_urls.public_patterns,
    path(
        "public/card/<str:token>/photo/",
        card_views.PublicCardPhotoView.as_view(),
        name="public-card-photo",
    ),
    path(
        "public/login-link/",
        portal_views.LoginLinkRequestView.as_view(),
        name="login-link-request",
    ),
    path(
        "public/login-link/<str:token>/",
        portal_views.LoginLinkUseView.as_view(),
        name="login-link-use",
    ),
    path(
        "public/statutes/<str:key>/",
        statute_views.PublicStatuteView.as_view(),
        name="public-statute",
    ),
    path(
        "public/statutes/<str:key>/info/",
        statute_views.PublicStatuteInfoView.as_view(),
        name="public-statute-info",
    ),
    path(
        "public/statutes/<str:key>/<int:pk>/",
        statute_views.PublicStatuteVersionView.as_view(),
        name="public-statute-version",
    ),
    path(
        "public/calendar/<str:key>/",
        event_views.PublicCalendarView.as_view(),
        name="public-calendar",
    ),
    path(
        "public/calendar/<str:key>/termine.ics",
        event_views.PublicCalendarIcsView.as_view(),
        name="public-calendar-ics",
    ),
    path(
        "public/feed/<str:key>/termine.ics",
        event_views.PersonalCalendarIcsView.as_view(),
        name="personal-calendar-ics",
    ),
    path("csrf/", views.csrf, name="csrf"),
    path("me/", views.me, name="me"),
    path("me/account/", self_service.AccountView.as_view(), name="my-account"),
    path("me/signature/", quittung_views.MySignatureView.as_view(), name="my-signature"),
    path("me/letterheads/", letterhead_views.MyLetterheadsView.as_view(), name="my-letterheads"),
    path(
        "me/letterheads/preview/",
        letterhead_views.MyLetterheadPreviewView.as_view(),
        name="my-letterhead-preview",
    ),
    path(
        "me/letterheads/download/",
        letterhead_views.MyLetterheadDownloadView.as_view(),
        name="my-letterhead-download",
    ),
    path(
        "me/letterheads/dismiss/",
        letterhead_views.MyLetterheadDismissView.as_view(),
        name="my-letterhead-dismiss",
    ),
    path("me/password/", self_service.PasswordView.as_view(), name="my-password"),
    path("me/email/", self_service.EmailChangeView.as_view(), name="my-email"),
    path("me/language/", language.MyLanguageView.as_view(), name="my-language"),
    path("public/languages/", language.PublicLanguagesView.as_view(), name="public-languages"),
    path("me/learning/", learning.LearningView.as_view(), name="my-learning"),
    path("me/learning/<slug:key>/hide/", learning.LearningHideView.as_view(), name="learning-hide"),
    path("me/learning/<slug:key>/show/", learning.LearningShowView.as_view(), name="learning-show"),
    path(
        "public/email-confirm/<str:token>/",
        self_service.EmailConfirmView.as_view(),
        name="email-confirm",
    ),
    path("me/organizations/", access_views.my_organizations, name="my-organizations"),
    path("permissions/", access_views.permission_catalog, name="permission-catalog"),
    path("me/contexts/", portal_views.MyContextsView.as_view(), name="my-contexts"),
    path("orgs/<int:org_id>/", include(org_patterns)),
    path("depts/<int:dept_id>/", include(dept_patterns)),
    path("portal/<int:access_id>/", portal_views.PortalDetailView.as_view(), name="portal"),
    *entry_urls.portal_patterns,
    *competition_urls.portal_patterns,
    path(
        "portal/<int:access_id>/invoices/",
        billing_portal_views.PortalInvoicesView.as_view(),
        name="portal-invoices",
    ),
    path(
        "portal/<int:access_id>/invoices/<int:pk>/pdf/",
        billing_portal_views.PortalInvoicePdfView.as_view(),
        name="portal-invoice-pdf",
    ),
    path(
        "portal/<int:access_id>/mandate/",
        billing_portal_views.PortalMandateView.as_view(),
        name="portal-mandate",
    ),
    path(
        "portal/<int:access_id>/change-requests/",
        portal_views.PortalChangeRequestView.as_view(),
        name="portal-change-request",
    ),
    path(
        "portal/<int:access_id>/documents/",
        doc_views.PortalOverviewView.as_view(),
        name="portal-documents",
    ),
    path(
        "portal/<int:access_id>/documents/versions/<int:pk>/",
        doc_views.PortalVersionView.as_view(),
        name="portal-document-version",
    ),
    path(
        "public/documents/<str:key>/",
        doc_views.PublicFolderView.as_view(),
        name="public-documents",
    ),
    path(
        "public/documents/<str:key>/<int:pk>/",
        doc_views.PublicDocumentView.as_view(),
        name="public-document",
    ),
    path(
        "portal/<int:access_id>/events/",
        event_views.PortalEventListView.as_view(),
        name="portal-events",
    ),
    path(
        "portal/<int:access_id>/events/program/",
        event_views.PortalProgramView.as_view(),
        name="portal-events-program",
    ),
    path(
        "portal/<int:access_id>/events/<int:pk>/",
        event_views.PortalEventDetailView.as_view(),
        name="portal-event",
    ),
    path(
        "portal/<int:access_id>/events/<int:pk>/attachments/<int:att_id>/",
        event_views.PortalAttachmentView.as_view(),
        name="portal-event-attachment",
    ),
    path(
        "portal/<int:access_id>/events/feed/",
        event_views.PortalFeedView.as_view(),
        name="portal-events-feed",
    ),
    path(
        "portal/<int:access_id>/events/<int:pk>/response/",
        event_views.PortalMyResponseView.as_view(),
        name="portal-event-response",
    ),
    path(
        "portal/<int:access_id>/events/<int:pk>/ics/",
        event_views.PortalEventIcsView.as_view(),
        name="portal-event-ics",
    ),
    path("portal/<int:access_id>/card/", card_views.PortalCardView.as_view(), name="portal-card"),
    path(
        "portal/<int:access_id>/photo/", photo_views.PortalPhotoView.as_view(), name="portal-photo"
    ),
    path(
        "portal/<int:access_id>/photo/image/",
        photo_views.PortalPhotoImageView.as_view(),
        name="portal-photo-image",
    ),
    path(
        "portal/<int:access_id>/card/pdf/",
        card_views.PortalCardPdfView.as_view(),
        name="portal-card-pdf",
    ),
    path("platform/outbox/", outbox_views.PlatformOutboxView.as_view(), name="platform-outbox"),
    path(
        "platform/outbox/<int:pk>/attachments/<int:index>/",
        outbox_views.PlatformOutboxAttachmentView.as_view(),
        name="platform-outbox-attachment",
    ),
    path("platform/settings/", org_views.PlatformSettingsView.as_view(), name="platform-settings"),
    path("platform/imprint/", imprint_views.PlatformImprintView.as_view(), name="platform-imprint"),
    path(
        "platform/orgs/<int:pk>/board/",
        org_views.PlatformBoardView.as_view(),
        name="platform-board",
    ),
    path(
        "platform/datatransfer/exports/",
        transfer_views.PlatformExportView.as_view(),
        name="platform-dt-exports",
    ),
    path(
        "platform/datatransfer/exports/<int:pk>/",
        transfer_views.PlatformExportDetailView.as_view(),
        name="platform-dt-export",
    ),
    path(
        "platform/datatransfer/exports/<int:pk>/download/",
        transfer_views.PlatformExportDownloadView.as_view(),
        name="platform-dt-export-download",
    ),
    path(
        "platform/datatransfer/imports/",
        transfer_views.PlatformImportView.as_view(),
        name="platform-dt-imports",
    ),
    path(
        "platform/datatransfer/imports/<int:pk>/",
        transfer_views.PlatformImportDetailView.as_view(),
        name="platform-dt-import",
    ),
    path(
        "platform/datatransfer/imports/<int:pk>/run/",
        transfer_views.PlatformImportRunView.as_view(),
        name="platform-dt-import-run",
    ),
    path("platform/", include(platform_router.urls)),
]
