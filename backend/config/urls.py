from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


class SwaggerView(SpectacularSwaggerView):
    """Swagger-Oberfläche nur, wenn eingeschaltet (lädt Code von einem CDN)."""

    def get(self, request, *args, **kwargs):
        if not settings.API_DOCS_ENABLED:
            raise Http404
        return super().get(request, *args, **kwargs)


urlpatterns = [
    # Anmeldung, Abmeldung, 2FA (allauth headless, eigene OpenAPI-Doku unter
    # /_allauth/openapi.html)
    path("_allauth/", include("allauth.headless.urls")),
    path("api/", include("core.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SwaggerView.as_view(url_name="schema"), name="docs"),
]

if settings.ADMIN_ENABLED:
    urlpatterns += [
        # Der Admin hat eine eigene Passwort-Anmeldung ohne Zwei-Faktor-Abfrage.
        # Deshalb führt sie zur normalen Anmeldung; danach gilt die Sitzung auch hier.
        path("admin/login/", RedirectView.as_view(url="/anmelden", query_string=False)),
        path("admin/", admin.site.urls),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
