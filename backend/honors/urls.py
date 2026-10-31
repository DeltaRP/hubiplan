"""Adressen von Würden und Chronik (eingebunden in core/urls.py)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("honors/dignities", views.DignityViewSet, basename="honors-dignity")
router.register("honors/reigns", views.ReignViewSet, basename="honors-reign")

org_patterns = [
    path(
        "honors/reigns/<int:pk>/photo/",
        views.ReignPhotoView.as_view(),
        name="honors-reign-photo",
    ),
    path(
        "honors/import/preview/",
        views.ImportPreviewView.as_view(),
        name="honors-import-preview",
    ),
    path("honors/origins/", views.OriginsView.as_view(), name="honors-origins"),
    path("honors/shared/", views.SharedView.as_view(), name="honors-shared"),
    path("honors/people/", views.PeopleView.as_view(), name="honors-people"),
    path("honors/import/", views.ImportView.as_view(), name="honors-import"),
    *router.urls,
]
