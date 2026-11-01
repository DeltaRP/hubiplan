"""Adressen der Wettbewerbe (eingebunden in core/urls.py)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import bird_views, event_views, foreign_views, stand_views, target_views, views

router = SimpleRouter()
router.register("competitions", views.CompetitionViewSet, basename="competition")
router.register(
    r"competitions/(?P<competition_id>\d+)/scorings",
    views.ScoringViewSet,
    basename="competition-scoring",
)

C = "competitions/<int:competition_id>/"

org_patterns = [
    path(
        "competitions/event-candidates/",
        event_views.EventCandidatesView.as_view(),
        name="competition-event-candidates",
    ),
    path(
        "competitions/targets/",
        target_views.TargetCatalogView.as_view(),
        name="competition-targets",
    ),
    path(f"{C}hits/", target_views.HitsView.as_view(), name="competition-hits"),
    path(f"{C}event/", event_views.EventLinkView.as_view(), name="competition-event"),
    path(
        f"{C}starters/from-event/",
        event_views.StartersFromEventView.as_view(),
        name="competition-starters-from-event",
    ),
    path(f"{C}starters/", views.StartersView.as_view(), name="competition-starters"),
    path(f"{C}starters/<int:pk>/", views.StarterView.as_view(), name="competition-starter"),
    path(f"{C}scores/", views.ScoreView.as_view(), name="competition-score"),
    path(f"{C}sync/", views.SyncView.as_view(), name="competition-sync"),
    path(f"{C}members/", views.MemberListView.as_view(), name="competition-members"),
    path(f"{C}candidates/", views.CandidatesView.as_view(), name="competition-candidates"),
    path(f"{C}unit-members/", views.UnitMembersView.as_view(), name="competition-unit-members"),
    path(f"{C}standings/", views.StandingsView.as_view(), name="competition-standings"),
    path(f"{C}version/", views.VersionView.as_view(), name="competition-version"),
    path(f"{C}status/", views.StatusView.as_view(), name="competition-status"),
    path(f"{C}reset/", views.ResetView.as_view(), name="competition-reset"),
    path(f"{C}copy/", views.CopyView.as_view(), name="competition-copy"),
    path(f"{C}export/", views.ExportView.as_view(), name="competition-export"),
    path(f"{C}shootoffs/", views.ShootOffsView.as_view(), name="competition-shootoffs"),
    path(f"{C}shootoffs/<int:pk>/", views.ShootOffView.as_view(), name="competition-shootoff"),
    path(
        f"{C}shootoff-entries/<int:pk>/",
        views.ShootOffEntryView.as_view(),
        name="competition-shootoff-entry",
    ),
    # Vogelschießen
    path(f"{C}bird/", bird_views.BirdStateView.as_view(), name="competition-bird"),
    path(f"{C}prizes/", bird_views.PrizesView.as_view(), name="competition-prizes"),
    path(f"{C}prizes/<int:pk>/", bird_views.PrizeView.as_view(), name="competition-prize"),
    path(f"{C}shots/", bird_views.ShotView.as_view(), name="competition-shots"),
    path(f"{C}undo/", bird_views.UndoView.as_view(), name="competition-undo"),
    path(f"{C}draw/", bird_views.DrawView.as_view(), name="competition-draw"),
    path(f"{C}draw-all/", bird_views.DrawAllView.as_view(), name="competition-draw-all"),
    # Fremde Wettbewerbe
    path(f"{C}teams/", foreign_views.TeamsView.as_view(), name="competition-teams"),
    path(f"{C}teams/<int:pk>/", foreign_views.TeamView.as_view(), name="competition-team"),
    path(f"{C}placings/", foreign_views.PlacingView.as_view(), name="competition-placings"),
    # Standzugang
    path(
        f"{C}stand-access/",
        stand_views.StandAccessListView.as_view(),
        name="competition-stand-accesses",
    ),
    path(
        f"{C}stand-access/<int:pk>/",
        stand_views.StandAccessView.as_view(),
        name="competition-stand-access",
    ),
    *router.urls,
]

# Standzugang ohne Anmeldung (Schlüssel im Link)
S = "public/stand/<str:token>/"
public_patterns = [
    path(S, stand_views.StandDetailView.as_view(), name="stand-detail"),
    path(f"{S}starters/", stand_views.StandStartersView.as_view(), name="stand-starters"),
    path(f"{S}members/", stand_views.StandMembersView.as_view(), name="stand-members"),
    path(f"{S}standings/", stand_views.StandStandingsView.as_view(), name="stand-standings"),
    path(f"{S}version/", stand_views.StandVersionView.as_view(), name="stand-version"),
    path(f"{S}sync/", stand_views.StandSyncView.as_view(), name="stand-sync"),
    path(f"{S}shootoffs/", stand_views.StandShootoffsView.as_view(), name="stand-shootoffs"),
    path(f"{S}shootoffs/<int:pk>/", stand_views.StandShootoffView.as_view(), name="stand-shootoff"),
    path(
        f"{S}shootoff-entries/<int:pk>/",
        stand_views.StandShootoffEntryView.as_view(),
        name="stand-shootoff-entry",
    ),
    path(
        f"{S}unit-members/", stand_views.StandUnitMembersView.as_view(), name="stand-unit-members"
    ),
]
