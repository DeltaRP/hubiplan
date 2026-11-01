"""Adressen der Wettbewerbe (eingebunden in core/urls.py)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("competitions", views.CompetitionViewSet, basename="competition")
router.register(
    r"competitions/(?P<competition_id>\d+)/scorings",
    views.ScoringViewSet,
    basename="competition-scoring",
)

C = "competitions/<int:competition_id>/"

org_patterns = [
    path(f"{C}starters/", views.StartersView.as_view(), name="competition-starters"),
    path(f"{C}starters/<int:pk>/", views.StarterView.as_view(), name="competition-starter"),
    path(f"{C}scores/", views.ScoreView.as_view(), name="competition-score"),
    path(f"{C}sync/", views.SyncView.as_view(), name="competition-sync"),
    path(f"{C}members/", views.MemberListView.as_view(), name="competition-members"),
    path(f"{C}candidates/", views.CandidatesView.as_view(), name="competition-candidates"),
    path(f"{C}unit-members/", views.UnitMembersView.as_view(), name="competition-unit-members"),
    path(f"{C}standings/", views.StandingsView.as_view(), name="competition-standings"),
    path(f"{C}status/", views.StatusView.as_view(), name="competition-status"),
    path(f"{C}copy/", views.CopyView.as_view(), name="competition-copy"),
    path(f"{C}export/", views.ExportView.as_view(), name="competition-export"),
    path(f"{C}shootoffs/", views.ShootOffsView.as_view(), name="competition-shootoffs"),
    path(f"{C}shootoffs/<int:pk>/", views.ShootOffView.as_view(), name="competition-shootoff"),
    path(
        f"{C}shootoff-entries/<int:pk>/",
        views.ShootOffEntryView.as_view(),
        name="competition-shootoff-entry",
    ),
    *router.urls,
]
