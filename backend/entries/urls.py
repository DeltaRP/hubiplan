"""Adressen der Meldungen (eingebunden in core/urls.py).

Die Pfade der Meldung gibt es dreimal (Schritt 3): für die Einheit selbst, für den
Veranstalter, der die Meldung einer Untereinheit bearbeitet (``entries/units/<unit>/``), und
im Bereich der Untereinheit (``/depts/<dept>/entries/``).
"""

from django.urls import include, path

from . import event_views, portal_views, views

C = "calls/<int:call_id>/"

# Meldung zusammenstellen und abgeben (auch für Untereinheiten)
entry_paths = [
    path("options/", views.OptionsView.as_view()),
    path("calls/", views.CallsView.as_view()),
    path(C, views.CallView.as_view()),
    path(f"{C}responses/", event_views.ResponsesView.as_view()),
    path(f"{C}candidates/", views.CandidatesView.as_view()),
    path(f"{C}entry/", views.EntryView.as_view()),
    path(f"{C}entry/discard/", views.EntryDeleteView.as_view()),
    path(f"{C}entry/reopen/", views.EntryReopenView.as_view()),
    path(f"{C}entry/teams/", views.TeamsView.as_view()),
    path(f"{C}entry/teams/<int:pk>/", views.TeamView.as_view()),
    path(f"{C}entry/persons/", views.PersonsView.as_view()),
    path(f"{C}entry/persons/<int:pk>/", views.PersonView.as_view()),
    path(f"{C}entry/answers/", views.AnswerView.as_view()),
    path(f"{C}entry/submit/", views.SubmitView.as_view()),
    path(f"{C}entry/confirm/", views.ConfirmView.as_view()),
    path(f"{C}entry/return/", views.ReturnView.as_view()),
    path(f"{C}entry/preview/", views.PreviewDownloadView.as_view()),
    path(f"{C}entry/versions/<int:number>/", views.VersionDownloadView.as_view()),
]

E = "entries/calls/<int:call_id>/"

org_patterns = [
    path("entries/options/", views.OptionsView.as_view(), name="entries-options"),
    path("entries/calls/", views.CallsView.as_view(), name="entries-calls"),
    path(E, views.CallView.as_view(), name="entries-call"),
    path(f"{E}copy/", views.CallCopyView.as_view(), name="entries-call-copy"),
    path(f"{E}blocks/", views.BlocksView.as_view(), name="entries-blocks"),
    path(f"{E}blocks/<int:pk>/", views.BlockView.as_view(), name="entries-block"),
    path(f"{E}event/", event_views.CallEventView.as_view(), name="entries-call-event"),
    path(
        f"{E}event-candidates/",
        event_views.CallEventCandidatesView.as_view(),
        name="entries-call-event-candidates",
    ),
    path(f"{E}units/", views.UnitsOverviewView.as_view(), name="entries-units"),
    path(f"{E}remind/", views.RemindView.as_view(), name="entries-remind"),
    path(f"{E}list/", views.UnitsListDownloadView.as_view(), name="entries-units-list"),
    path(f"{E}responses/", event_views.ResponsesView.as_view(), name="entries-responses"),
    path(f"{E}candidates/", views.CandidatesView.as_view(), name="entries-candidates"),
    path(f"{E}entry/", views.EntryView.as_view(), name="entries-entry"),
    path(f"{E}entry/discard/", views.EntryDeleteView.as_view(), name="entries-entry-discard"),
    path(f"{E}entry/reopen/", views.EntryReopenView.as_view(), name="entries-entry-reopen"),
    path(f"{E}entry/teams/", views.TeamsView.as_view(), name="entries-teams"),
    path(f"{E}entry/teams/<int:pk>/", views.TeamView.as_view(), name="entries-team"),
    path(f"{E}entry/persons/", views.PersonsView.as_view(), name="entries-persons"),
    path(f"{E}entry/persons/<int:pk>/", views.PersonView.as_view(), name="entries-person"),
    path(f"{E}entry/answers/", views.AnswerView.as_view(), name="entries-answers"),
    path(f"{E}entry/submit/", views.SubmitView.as_view(), name="entries-submit"),
    path(f"{E}entry/confirm/", views.ConfirmView.as_view(), name="entries-confirm"),
    path(f"{E}entry/preview/", views.PreviewDownloadView.as_view(), name="entries-preview"),
    path(
        f"{E}entry/versions/<int:number>/",
        views.VersionDownloadView.as_view(),
        name="entries-version",
    ),
    # Veranstalter bearbeitet die Meldung einer Untereinheit
    path("entries/units/<int:unit_id>/", include(entry_paths)),
]

# Bereich der Untereinheit
dept_patterns = [path("entries/", include(entry_paths))]

portal_patterns = [
    path(
        "portal/<int:access_id>/entries/",
        portal_views.PortalEntriesView.as_view(),
        name="portal-entries",
    ),
]
