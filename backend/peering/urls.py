from django.urls import path

from . import api, server, sso_views, views

urlpatterns = [
    path("peering/v1/instance/", views.InstanceInfoView.as_view(), name="peering-instance"),
    path("peering/v1/pair/inspect/", server.inspect_view, name="peering-pair-inspect"),
    path("peering/v1/pair/request/", server.request_view, name="peering-pair-request"),
    path("peering/v1/inbox/", server.inbox_view, name="peering-inbox"),
    path("peering/v1/status/", server.status_view, name="peering-status"),
    path("peering/v1/query/", server.query_view, name="peering-query"),
    path("peering/v1/keys/", server.keys_view, name="peering-keys"),
    # Anmelden über eine gekoppelte Instanz (Schritt 7)
    path("peering/sso/choices/", sso_views.ChoicesView.as_view(), name="peering-sso-choices"),
    path("peering/sso/start/", sso_views.StartView.as_view(), name="peering-sso-start"),
    path("peering/sso/finish/", sso_views.FinishView.as_view(), name="peering-sso-finish"),
    path("peering/sso/describe/", sso_views.DescribeView.as_view(), name="peering-sso-describe"),
    path("peering/sso/issue/", sso_views.IssueView.as_view(), name="peering-sso-issue"),
    path("peering/sso/account/", sso_views.AccountView.as_view(), name="peering-sso-account"),
    path(
        "peering/sso/links/<int:pk>/",
        sso_views.LinkDeleteView.as_view(),
        name="peering-sso-link",
    ),
    path(
        "peering/sso/accounts/<int:pk>/",
        sso_views.RemoteAccountDeleteView.as_view(),
        name="peering-sso-remote-account",
    ),
    # Oberfläche (angemeldete Vorstände)
    path("orgs/<int:org_id>/peering/", api.OverviewView.as_view(), name="peering-overview"),
    path("orgs/<int:org_id>/peering/move/", api.MoveView.as_view(), name="peering-move"),
    path("orgs/<int:org_id>/peering/codes/", api.CodeView.as_view(), name="peering-codes"),
    path(
        "orgs/<int:org_id>/peering/spin-offs/", api.SpinOffsView.as_view(), name="peering-spin-offs"
    ),
    path(
        "orgs/<int:org_id>/peering/spin-offs/<int:pk>/cancel/",
        api.SpinOffCancelView.as_view(),
        name="peering-spin-off-cancel",
    ),
    path(
        "orgs/<int:org_id>/peering/spin-offs/<int:pk>/exit/",
        api.SpinOffExitView.as_view(),
        name="peering-spin-off-exit",
    ),
    path("orgs/<int:org_id>/peering/inspect/", api.InspectView.as_view(), name="peering-inspect"),
    path("orgs/<int:org_id>/peering/couplings/", api.JoinView.as_view(), name="peering-join"),
    path(
        "orgs/<int:org_id>/peering/couplings/<int:pk>/",
        api.CouplingView.as_view(),
        name="peering-coupling",
    ),
    path(
        "orgs/<int:org_id>/peering/couplings/<int:pk>/files/<str:key>/",
        api.CouplingFileView.as_view(),
        name="peering-coupling-file",
    ),
    path(
        "orgs/<int:org_id>/peering/couplings/<int:pk>/invoices/<int:invoice_id>/file/",
        api.InvoiceFileView.as_view(),
        name="peering-invoice-file",
    ),
    path(
        "orgs/<int:org_id>/peering/couplings/<int:pk>/invoices/<int:invoice_id>/paid/",
        api.InvoicePaidView.as_view(),
        name="peering-invoice-paid",
    ),
    path(
        "orgs/<int:org_id>/peering/couplings/<int:pk>/members/<int:member_id>/resolve/",
        api.RegisterResolveView.as_view(),
        name="peering-register-resolve",
    ),
    path(
        "orgs/<int:org_id>/peering/couplings/<int:pk>/transfers/",
        api.TransferCreateView.as_view(),
        name="peering-transfer-create",
    ),
    path(
        "orgs/<int:org_id>/peering/couplings/<int:pk>/transfers/<int:transfer_id>/decide/",
        api.TransferDecideView.as_view(),
        name="peering-transfer-decide",
    ),
    path(
        "orgs/<int:org_id>/peering/couplings/<int:pk>/<str:action>/",
        api.CouplingActionView.as_view(),
        name="peering-coupling-action",
    ),
    path(
        "orgs/<int:org_id>/peering/members/<int:membership_id>/suggest/",
        api.RegisterSuggestView.as_view(),
        name="peering-register-suggest",
    ),
    path("platform/peering/", api.PlatformPeeringView.as_view(), name="platform-peering"),
    path("platform/peering/keys/", api.PlatformKeysView.as_view(), name="platform-peering-keys"),
    path(
        "platform/peering/peers/<int:pk>/keys/",
        api.PlatformPeerKeysView.as_view(),
        name="platform-peering-peer-keys",
    ),
]
