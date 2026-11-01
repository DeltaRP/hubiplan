"""Adressen der Meldungen (eingebunden in core/urls.py)."""

from django.urls import path

from . import event_views, portal_views, views

C = "entries/calls/<int:call_id>/"

org_patterns = [
    path("entries/options/", views.OptionsView.as_view(), name="entries-options"),
    path("entries/calls/", views.CallsView.as_view(), name="entries-calls"),
    path(C, views.CallView.as_view(), name="entries-call"),
    path(f"{C}copy/", views.CallCopyView.as_view(), name="entries-call-copy"),
    path(f"{C}blocks/", views.BlocksView.as_view(), name="entries-blocks"),
    path(f"{C}blocks/<int:pk>/", views.BlockView.as_view(), name="entries-block"),
    path(f"{C}event/", event_views.CallEventView.as_view(), name="entries-call-event"),
    path(
        f"{C}event-candidates/",
        event_views.CallEventCandidatesView.as_view(),
        name="entries-call-event-candidates",
    ),
    path(f"{C}responses/", event_views.ResponsesView.as_view(), name="entries-responses"),
    path(f"{C}candidates/", views.CandidatesView.as_view(), name="entries-candidates"),
    path(f"{C}entry/", views.EntryView.as_view(), name="entries-entry"),
    path(f"{C}entry/discard/", views.EntryDeleteView.as_view(), name="entries-entry-discard"),
    path(f"{C}entry/teams/", views.TeamsView.as_view(), name="entries-teams"),
    path(f"{C}entry/teams/<int:pk>/", views.TeamView.as_view(), name="entries-team"),
    path(f"{C}entry/persons/", views.PersonsView.as_view(), name="entries-persons"),
    path(f"{C}entry/persons/<int:pk>/", views.PersonView.as_view(), name="entries-person"),
    path(f"{C}entry/answers/", views.AnswerView.as_view(), name="entries-answers"),
    path(f"{C}entry/submit/", views.SubmitView.as_view(), name="entries-submit"),
    path(f"{C}entry/confirm/", views.ConfirmView.as_view(), name="entries-confirm"),
    path(f"{C}entry/preview/", views.PreviewDownloadView.as_view(), name="entries-preview"),
    path(
        f"{C}entry/versions/<int:number>/",
        views.VersionDownloadView.as_view(),
        name="entries-version",
    ),
]

portal_patterns = [
    path(
        "portal/<int:access_id>/entries/",
        portal_views.PortalEntriesView.as_view(),
        name="portal-entries",
    ),
]
