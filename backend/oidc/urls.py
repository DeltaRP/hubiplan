from django.urls import path

from . import views

urlpatterns = [
    path(
        "oidc/.well-known/openid-configuration",
        views.DiscoveryView.as_view(),
        name="oidc-discovery",
    ),
    path("oidc/jwks", views.JwksView.as_view(), name="oidc-jwks"),
    path("oidc/token", views.TokenView.as_view(), name="oidc-token"),
    path("oidc/userinfo", views.UserinfoView.as_view(), name="oidc-userinfo"),
    path("oidc/authorize/", views.AuthorizeView.as_view(), name="oidc-authorize"),
]
