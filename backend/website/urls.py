"""Adressen der Webseite (eingebunden in core/urls.py)."""

from django.urls import path

from . import content_views, public_views, social_views, views

org_patterns = [
    path("website/", views.WebsiteView.as_view(), name="website"),
    path(
        "website/privacy/generate/",
        views.PrivacyGenerateView.as_view(),
        name="website-privacy-generate",
    ),
    path(
        "website/privacy/publish/",
        views.PrivacyPublishView.as_view(),
        name="website-privacy-publish",
    ),
    path("website/domains/", views.DomainListView.as_view(), name="website-domains"),
    path("website/domains/<int:pk>/", views.DomainDetailView.as_view(), name="website-domain"),
    path(
        "website/preview-links/",
        views.PreviewLinkListView.as_view(),
        name="website-preview-links",
    ),
    path(
        "website/preview-links/<int:pk>/",
        views.PreviewLinkDetailView.as_view(),
        name="website-preview-link",
    ),
    path("website/preview/", views.PreviewOpenView.as_view(), name="website-preview"),
    path("website/held/", views.HeldListView.as_view(), name="website-held"),
    path("website/held/<int:pk>/", views.HeldDetailView.as_view(), name="website-held-message"),
    path("website/texts/", content_views.TextListView.as_view(), name="website-texts"),
    path(
        "website/texts/reorder/",
        content_views.PageOrderView.as_view(),
        name="website-texts-reorder",
    ),
    path("website/texts/<int:pk>/", content_views.TextDetailView.as_view(), name="website-text"),
    path(
        "website/texts/<int:pk>/publish/",
        content_views.TextPublishView.as_view(),
        name="website-text-publish",
    ),
    path(
        "website/texts/<int:pk>/revisions/<int:rev>/restore/",
        content_views.TextRestoreView.as_view(),
        name="website-text-restore",
    ),
    path("website/images/", content_views.ImageListView.as_view(), name="website-images"),
    path("website/images/<int:pk>/", content_views.ImageDetailView.as_view(), name="website-image"),
    path(
        "website/images/<int:pk>/crop/",
        content_views.ImageCropView.as_view(),
        name="website-image-crop",
    ),
    path(
        "website/images/<int:pk>/replace/",
        content_views.ImageReplaceView.as_view(),
        name="website-image-replace",
    ),
    path(
        "website/images/<int:pk>/copy/",
        content_views.ImageCopyView.as_view(),
        name="website-image-copy",
    ),
    path(
        "website/images/<int:pk>/file/",
        content_views.ImageFileView.as_view(),
        name="website-image-file",
    ),
    path("website/social/", social_views.FeedListView.as_view(), name="website-social"),
    path(
        "website/social/<int:pk>/",
        social_views.FeedDetailView.as_view(),
        name="website-social-feed",
    ),
    path(
        "website/social/<int:pk>/connect/",
        social_views.FeedConnectView.as_view(),
        name="website-social-connect",
    ),
    path(
        "website/social/<int:pk>/page/",
        social_views.FeedPageView.as_view(),
        name="website-social-page",
    ),
    path(
        "website/social/<int:pk>/publish-pending/",
        social_views.FeedPublishPendingView.as_view(),
        name="website-social-publish-pending",
    ),
    path(
        "website/social/<int:pk>/sync/",
        social_views.FeedSyncView.as_view(),
        name="website-social-sync",
    ),
    path("website/social/posts/", social_views.PostListView.as_view(), name="website-social-posts"),
    path(
        "website/social/posts/<int:pk>/",
        social_views.PostDetailView.as_view(),
        name="website-social-post",
    ),
    path(
        "website/social/images/<int:pk>/file/",
        social_views.PostImageFileView.as_view(),
        name="website-social-image",
    ),
    path(
        "members/<int:pk>/publication/",
        views.MemberPublicationView.as_view(),
        name="member-publication",
    ),
]

SITE = "public/site/v1/<str:key>/"
public_patterns = [
    path(
        "website/social/callback/",
        social_views.CallbackView.as_view(),
        name="website-social-callback",
    ),
    path("public/site/v1/resolve/", public_views.ResolveView.as_view(), name="site-resolve"),
    path(SITE, public_views.SiteInfoView.as_view(), name="site-info"),
    path(f"{SITE}preview/", public_views.PreviewView.as_view(), name="site-preview"),
    path(f"{SITE}board/", public_views.BoardView.as_view(), name="site-board"),
    path(f"{SITE}units/", public_views.UnitListView.as_view(), name="site-units"),
    path(f"{SITE}units/<str:slug>/", public_views.UnitDetailView.as_view(), name="site-unit"),
    path(f"{SITE}pages/<str:slug>/", public_views.PageView.as_view(), name="site-page"),
    path(f"{SITE}images/<str:image_key>/", public_views.ImageView.as_view(), name="site-image"),
    path(f"{SITE}photos/<str:token>/", public_views.PhotoView.as_view(), name="site-photo"),
    path(f"{SITE}honors/", public_views.HonorsView.as_view(), name="site-honors"),
    path(
        f"{SITE}honors/photos/<str:token>/",
        public_views.HonorsPhotoView.as_view(),
        name="site-honors-photo",
    ),
    path(f"{SITE}imprint/", public_views.ImprintView.as_view(), name="site-imprint"),
    path(
        f"{SITE}statute/preview/",
        public_views.StatutePreviewView.as_view(),
        name="site-statute-preview",
    ),
    path(
        f"{SITE}fee-rules/preview/",
        public_views.StatutePreviewView.as_view(kind="fee_rules"),
        name="site-fee-rules-preview",
    ),
    path(
        f"{SITE}founding-deed/preview/",
        public_views.StatutePreviewView.as_view(kind="founding_deed"),
        name="site-founding-deed-preview",
    ),
    path(f"{SITE}events/", public_views.EventsView.as_view(), name="site-events"),
    path(f"{SITE}events.ics", public_views.EventsIcsView.as_view(), name="site-events-ics"),
    path(f"{SITE}posts/", public_views.PostsView.as_view(), name="site-posts"),
    path(
        f"{SITE}posts/images/<str:image_key>/",
        public_views.PostImageView.as_view(),
        name="site-post-image",
    ),
    path(f"{SITE}contact/", public_views.ContactView.as_view(), name="site-contact"),
]
