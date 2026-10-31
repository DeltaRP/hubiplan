"""Adressen der Rundschreiben (eingebunden in core/urls.py)."""

from django.urls import path

from . import views


def _patterns(v: dict, prefix: str) -> list:
    return [
        path("circulars/", v["List"].as_view(), name=f"{prefix}circulars"),
        path("circulars/options/", v["Options"].as_view(), name=f"{prefix}circular-options"),
        path("circulars/templates/", v["Templates"].as_view(), name=f"{prefix}circular-templates"),
        path(
            "circulars/templates/<int:tpl_id>/",
            v["Template"].as_view(),
            name=f"{prefix}circular-template",
        ),
        path("circulars/lists/", v["Lists"].as_view(), name=f"{prefix}circular-lists"),
        path(
            "circulars/lists/<int:list_id>/",
            v["ListDetail"].as_view(),
            name=f"{prefix}circular-list",
        ),
        path(
            "circulars/lists/<int:list_id>/inbound/",
            v["ListInbound"].as_view(),
            name=f"{prefix}circular-list-inbound",
        ),
        path(
            "circulars/lists/<int:list_id>/probe/",
            v["ListProbe"].as_view(),
            name=f"{prefix}circular-list-probe",
        ),
        path("circulars/<int:pk>/", v["Detail"].as_view(), name=f"{prefix}circular"),
        path(
            "circulars/<int:pk>/recipients/",
            v["Recipients"].as_view(),
            name=f"{prefix}circular-recipients",
        ),
        path("circulars/<int:pk>/search/", v["Search"].as_view(), name=f"{prefix}circular-search"),
        path("circulars/<int:pk>/send/", v["Send"].as_view(), name=f"{prefix}circular-send"),
        path("circulars/<int:pk>/test/", v["Test"].as_view(), name=f"{prefix}circular-test"),
        path("circulars/<int:pk>/resend/", v["Resend"].as_view(), name=f"{prefix}circular-resend"),
        path(
            "circulars/<int:pk>/letters/", v["Letters"].as_view(), name=f"{prefix}circular-letters"
        ),
        path(
            "circulars/<int:pk>/attachments/",
            v["AttachmentList"].as_view(),
            name=f"{prefix}circular-attachments",
        ),
        path(
            "circulars/<int:pk>/attachments/<int:att_id>/",
            v["Attachment"].as_view(),
            name=f"{prefix}circular-attachment",
        ),
    ]


org_patterns = [
    path("circulars/received/", views.ReceivedListView.as_view(), name="org-circulars-received"),
    path(
        "circulars/received/<int:pk>/",
        views.ReceivedDetailView.as_view(),
        name="org-circular-received",
    ),
    path(
        "circulars/received/<int:pk>/attachments/<int:att_id>/",
        views.ReceivedAttachmentView.as_view(),
        name="org-circular-received-attachment",
    ),
    *_patterns(views.ORG_VIEWS, "org-"),
]
dept_patterns = _patterns(views.DEPT_VIEWS, "dept-")

portal_patterns = [
    path("circulars/", views.PortalCircularListView.as_view(), name="portal-circulars"),
    path(
        "circulars/settings/",
        views.PortalCircularSettingsView.as_view(),
        name="portal-circular-settings",
    ),
    path("circulars/<int:pk>/", views.PortalCircularDetailView.as_view(), name="portal-circular"),
    path(
        "circulars/<int:pk>/attachments/<int:att_id>/",
        views.PortalCircularAttachmentView.as_view(),
        name="portal-circular-attachment",
    ),
]

public_patterns = [
    path(
        "public/circulars/optout/<str:token>/",
        views.PublicOptOutView.as_view(),
        name="public-circular-optout",
    ),
    path(
        "public/circulars/confirm/<str:token>/",
        views.PublicConfirmView.as_view(),
        name="public-circular-confirm",
    ),
]
