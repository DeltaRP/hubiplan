"""Django-Einstellungen für hubiplan.

Alle umgebungsabhängigen Werte kommen aus Umgebungsvariablen (siehe .env.example).
"""

import base64
import hashlib
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY muss gesetzt sein.")
    SECRET_KEY = "unsicherer-entwicklungs-schluessel"  # nur mit DJANGO_DEBUG=true

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.headless",
    "accounts",
    "core",
    "organizations",
    "access",
    "audit",
    "members",
    "customfields",
    "exchange",
    "outbox",
    "portal",
    "finance",
    "datatransfer",
    "billing",
    "cards",
    "statutes",
    "documents",
    "events",
    "circulars",
    "changes",
    "letterhead",
    "website",
    "honors",
    "competitions",
    "peering",
    "devices",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "core.tenancy.TenantMiddleware",
    "changes.middleware.ChangeSetMiddleware",
    "core.filecheck.SafeFileMiddleware",
    "devices.middleware.SignatureFormatMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Datenbank: PostgreSQL über DATABASE_URL, z. B. postgres://user:pass@host:5432/db
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default="postgres://hubiplan:hubiplan@localhost:5432/hubiplan",
        conn_max_age=60,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Zur Laufzeit arbeitet die Anwendung in einer eingeschränkten Datenbankrolle,
# damit PostgreSQL Row-Level Security durchsetzt (siehe core/tenancy.py).
# Leer = kein Rollenwechsel (Migrationen, lokale Entwicklung mit SQLite).
DATABASE_APP_ROLE = os.environ.get("DATABASE_APP_ROLE", "")

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    # Audit 29.10. G08: naheliegende Wörter und geleakte Passwörter (ohne externen Dienst)
    {"NAME": "accounts.validators.ContextWordValidator"},
    {"NAME": "accounts.validators.LeakedPasswordValidator"},
]

# --- allauth: Anmeldung per E-Mail/Passwort, optionale 2FA per TOTP ---
ACCOUNT_ADAPTER = "accounts.adapter.AccountAdapter"  # keine Selbstregistrierung
HEADLESS_ADAPTER = "accounts.adapter.HeadlessAdapter"  # Startpasswort ersetzen (AT-S04)
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PASSWORD_RESET_TOKEN_GENERATOR = "accounts.tokens.InvitationTokenGenerator"
ACCOUNT_EMAIL_VERIFICATION = "none"  # Bestätigung folgt, sobald E-Mail-Versand steht
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
MFA_TOTP_ISSUER = os.environ.get("MFA_TOTP_ISSUER", "HUBIplan")
# 2FA-Geheimnisse verschlüsselt speichern (accounts/mfa.py); Schlüssel nur in der .env
MFA_ADAPTER = "accounts.mfa.MFAAdapter"
# Ein leerer Wert (z. B. aus docker-compose ${MFA_ENCRYPTION_KEYS:-}) gilt als nicht gesetzt
MFA_ENCRYPTION_KEYS = env_list("MFA_ENCRYPTION_KEYS") or env_list("MFA_ENCRYPTION_KEY")
if not MFA_ENCRYPTION_KEYS:
    if not DEBUG:
        raise ImproperlyConfigured("MFA_ENCRYPTION_KEY muss gesetzt sein.")
    # Nur mit DJANGO_DEBUG=true: aus dem SECRET_KEY abgeleitet
    _digest = hashlib.sha256(b"hubiplan-mfa:" + SECRET_KEY.encode()).digest()
    MFA_ENCRYPTION_KEYS = [base64.urlsafe_b64encode(_digest).decode()]
# Verschlüsselung gespeicherter Daten mit einem Schlüssel je Verein (core/crypto.py).
# Hauptschlüssel auf dem Server als eigene Datei (Docker-Secret), nicht in der .env;
# DATA_ENCRYPTION_KEY(S) nur für Entwicklung und Tests. Quelle austauschbar
# (DATA_KEY_PROVIDERS, Konzept „Externer Schlüsselspeicher“).
DATA_KEY_PROVIDERS = env_list("DATA_KEY_PROVIDERS") or ["file"]
DATA_ENCRYPTION_KEY_FILE = os.environ.get("DATA_ENCRYPTION_KEY_FILE", "")
DATA_ENCRYPTION_KEYS = env_list("DATA_ENCRYPTION_KEYS") or env_list("DATA_ENCRYPTION_KEY")
if not DATA_ENCRYPTION_KEYS and not DATA_ENCRYPTION_KEY_FILE:
    if not DEBUG:
        raise ImproperlyConfigured("DATA_ENCRYPTION_KEY_FILE muss gesetzt sein.")
    # Nur mit DJANGO_DEBUG=true: aus dem SECRET_KEY abgeleitet
    _digest = hashlib.sha256(b"hubiplan-daten:" + SECRET_KEY.encode()).digest()
    DATA_ENCRYPTION_KEYS = [base64.urlsafe_b64encode(_digest).decode()]
# Entpackte Datenschlüssel im Arbeitsspeicher halten (Sekunden, 0 = bis zum Neustart)
DATA_KEY_CACHE_SECONDS = int(os.environ.get("DATA_KEY_CACHE_SECONDS", "0"))
# Datei ohne zugeordneten Verein: Fehler statt Plattformschlüssel (Tests)
DATA_ENCRYPTION_STRICT = env_bool("DATA_ENCRYPTION_STRICT", False)
HEADLESS_ONLY = True
# „app“: Anmeldung der Android-App mit Passwort (X-Session-Token), danach Geräteschlüssel
HEADLESS_CLIENTS = ("browser", "app")
HEADLESS_FRONTEND_URLS = {
    "account_reset_password_from_key": f"{FRONTEND_URL}/passwort-zuruecksetzen/{{key}}",
    "account_signup": f"{FRONTEND_URL}/anmelden",
}

# --- Django REST Framework / OpenAPI ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        # App: Geräteschlüssel, nur für Mitgliederbereich und /api/app/v1/
        "devices.auth.DeviceTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    # Nur JSON: Die HTML-Ansicht von DRF (Browsable API) braucht niemand, und sie
    # liefert fremde Dateien (Bootstrap, jQuery, Font Awesome) an den Browser aus,
    # die eigene Lizenzhinweise verlangen (Lizenzaudit 31.10.2026, L06). Die Dateien
    # sammelt backend/Dockerfile deshalb auch nicht ein.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "core.schema.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "HUBIplan API",
    "DESCRIPTION": (
        "API der Vereinsverwaltung HUBIplan. Anmeldung und 2FA sind unter "
        "/_allauth/openapi.html dokumentiert."
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Schema und Swagger-Seite nur für Angemeldete, nicht öffentlich im Netz
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
    # Swagger-Oberfläche (nur wenn API_DOCS_ENABLED) in fester Version statt „latest“,
    # damit klar ist, welcher fremde Code mit welcher Lizenz geladen wird (Apache-2.0)
    "SWAGGER_UI_DIST": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.29.5",
    "SWAGGER_UI_FAVICON_HREF": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.29.5/favicon-32x32.png",
    # Eindeutige Namen für Auswahllisten, die mehrfach vorkommen
    "ENUM_NAME_OVERRIDES": {
        "InvoiceStatusEnum": "billing.models.Invoice.Status",
        "GenderEnum": [("f", "die (weiblich)"), ("m", "der (männlich)"), ("n", "das (sächlich)")],
    },
}

# --- Cache (Ratenbegrenzung, allauth); im Betrieb Redis, damit alle Prozesse ihn teilen ---
CACHE_URL = os.environ.get("CACHE_URL", "")
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": CACHE_URL}
        if CACHE_URL
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    )
}

# --- Celery (Hintergrund-Jobs) ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TIMEZONE = "Europe/Berlin"
# Regelmäßige Jobs (laufen im Dienst "beat")
CELERY_BEAT_SCHEDULE = {
    "datenuebernahme-aufraeumen": {
        "task": "datatransfer.tasks.purge_expired",
        "schedule": 24 * 60 * 60,  # täglich
    },
    "listen-import-export-aufraeumen": {
        "task": "exchange.tasks.purge_expired",
        "schedule": 24 * 60 * 60,  # täglich
    },
    "loeschfrist": {
        "task": "members.tasks.purge_expired_members",
        "schedule": 24 * 60 * 60,  # täglich
    },
    "termin-erinnerungen": {
        "task": "events.tasks.send_event_reminders",
        "schedule": 60 * 60,  # stündlich
    },
    "rueckgaengig-aufraeumen": {
        "task": "changes.tasks.purge_old_changes",
        "schedule": 24 * 60 * 60,  # täglich
    },
    "dokumente-aufraeumen": {
        "task": "documents.tasks.purge_documents",
        "schedule": 24 * 60 * 60,  # täglich
    },
    # Rundschreiben, deren Versandauftrag verloren ging, weiterversenden
    "rundschreiben-wiederanlauf": {"task": "circulars.tasks.resume_stalled", "schedule": 15 * 60},
    "rechnungen-ablegen": {"task": "billing.tasks.archive_invoices", "schedule": 15 * 60},
    "postausgang-aufraeumen": {
        "task": "outbox.tasks.purge_sent_mails",
        "schedule": 24 * 60 * 60,  # täglich
    },
    # Social-Media-Beiträge der Webseite (ohne verbundene Kanäle: nichts zu tun)
    "webseite-beitraege-abrufen": {"task": "website.tasks.sync_social_feeds", "schedule": 30 * 60},
    "webseite-beitraege-zugang": {
        "task": "website.tasks.maintain_social_feeds",
        "schedule": 24 * 60 * 60,
    },
    "webseite-nachrichten-aufraeumen": {
        "task": "website.tasks.purge_held_messages",
        "schedule": 24 * 60 * 60,  # täglich
    },
    # Verbund: Stände prüfen und fällige Pakete zustellen (ohne Kopplung: nichts zu tun)
    "verbund-staende": {"task": "peering.tasks.sync_all", "schedule": 5 * 60},
    "verbund-zustellen": {"task": "peering.tasks.deliver_due", "schedule": 60},
    "verbund-abgleich": {"task": "peering.tasks.reconcile_all", "schedule": 24 * 60 * 60},
    "verbund-schluessel": {"task": "peering.tasks.keys_daily", "schedule": 24 * 60 * 60},
    "startpasswoerter-ablaufen": {
        "task": "accounts.tasks.expire_initial_passwords",
        "schedule": 60 * 60,  # stündlich
    },
    # Mailverteiler: Sammelpostfach abholen (ohne IMAP-Zugang: nichts zu tun)
    "verteiler-abholen": {"task": "circulars.tasks.fetch_inbound", "schedule": 60},
    # Backup-Stand prüfen, Alarm-Mail bei Fehler oder Lücke (ohne Statusordner: nichts)
    # Änderungsprotokoll versiegeln und Kette prüfen (Finanzamt-Prüfung C3)
    "protokoll-pruefen": {"task": "audit.tasks.check_chains", "schedule": 24 * 60 * 60},
    "backup-pruefen": {"task": "core.backup_status.check_backup", "schedule": 60 * 60},
}
# Statusdatei des Backup-Dienstes (docker-compose.server.yml) und ab wann ein fehlendes
# vollständiges Backup gemeldet wird
BACKUP_STATUS_DIR = os.environ.get("BACKUP_STATUS_DIR", "")
BACKUP_MAX_AGE_HOURS = int(os.environ.get("BACKUP_MAX_AGE_HOURS", "26"))
# Zugestellte Mails: Text und Anhänge nach so vielen Tagen leeren (Nachweis bleibt)
OUTBOX_RETENTION_DAYS = int(os.environ.get("OUTBOX_RETENTION_DAYS", "30"))

# --- Sicherheit ---
# Django-Admin unter /admin/: im Server-Betrieb standardmäßig aus (weniger
# Angriffsfläche); bei Bedarf mit DJANGO_ADMIN_ENABLED=true in der .env einschalten
ADMIN_ENABLED = env_bool("DJANGO_ADMIN_ENABLED", True)
# Swagger-Oberfläche unter /api/docs/ lädt Code von einem fremden Server (CDN);
# im Server-Betrieb aus (docker-compose.server.yml), Schema unter /api/schema/ bleibt
API_DOCS_ENABLED = env_bool("DJANGO_API_DOCS_ENABLED", True)
# Alarm-Mails (core/alarm.py): Empfänger (leer = alle Superuser) und ab wie vielen
# exportierten Zeilen ein Export gemeldet wird
SECURITY_ALERTS = env_bool("SECURITY_ALERTS", True)
SECURITY_ALERT_EMAIL = os.environ.get("SECURITY_ALERT_EMAIL", "")
ALERT_EXPORT_ROWS = int(os.environ.get("ALERT_EXPORT_ROWS", "200"))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 12 * 60 * 60  # 12 Stunden
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", not DEBUG)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- E-Mail ---
# Jede Mail landet im Postausgang (outbox). Mit EMAIL_HOST wird sie zusätzlich per
# SMTP versendet; ohne (Testserver) ist der Postausgang das Test-Postfach, das
# Plattform-Admins in der Oberfläche ansehen.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = 15
EMAIL_BACKEND = os.environ.get("DJANGO_EMAIL_BACKEND", "outbox.backend.OutboxBackend")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "HUBIplan <noreply@localhost>")
# Höchstens so viele Rundschreiben-Mails je Stunde (Limit des Mailpostfachs, z. B. Hestia
# 100/h); 0 = ohne Grenze. Ein Zehntel bleibt frei für Anmelde- und Systemmails.
MAIL_RATE_PER_HOUR = int(os.environ.get("MAIL_RATE_PER_HOUR", "0"))

# --- Mailverteiler (circulars/inbound.py) ---
# Domains der Verteiler-Adressen, z. B. verein.example.org; die erste wird angezeigt
INBOUND_DOMAINS = [d.lower() for d in env_list("INBOUND_DOMAINS")]
# Sammelpostfach, in dem alle Mails an die Verteiler landen (IMAP über TLS)
INBOUND_IMAP_HOST = os.environ.get("INBOUND_IMAP_HOST", "")
# Speicherbudget der Dokumentablage je Verein (GB), ändern je Verein im Plattform-Admin
DOCUMENT_BUDGET_GB = int(os.environ.get("DOCUMENT_BUDGET_GB", "5"))
# Kennung des eigenen Mailservers in Authentication-Results (leer: oberster Eintrag zählt)
MAIL_AUTHSERV_ID = os.environ.get("MAIL_AUTHSERV_ID", "")
INBOUND_IMAP_PORT = int(os.environ.get("INBOUND_IMAP_PORT", "993"))
INBOUND_IMAP_USER = os.environ.get("INBOUND_IMAP_USER", "")
INBOUND_IMAP_PASSWORD = os.environ.get("INBOUND_IMAP_PASSWORD", "")
INBOUND_IMAP_FOLDER = os.environ.get("INBOUND_IMAP_FOLDER", "INBOX")
# Ohne Sammelpostfach (Testserver): Probe-Eingang aus der Oberfläche erlaubt
INBOUND_SIMULATION = env_bool("INBOUND_SIMULATION", not INBOUND_IMAP_HOST)

LANGUAGE_CODE = "de-de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Hochgeladene Dateien (Logos)
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
# Private Dateien (Importe, Exporte) – nur über die API mit Rechteprüfung
PRIVATE_ROOT = Path(os.environ.get("PRIVATE_ROOT", BASE_DIR / "private"))
# Löschliste außerhalb der Datenbank (Fachfrage 7, 31.10.b): eigenes Volume, nicht im Backup
# der Datenbank, damit sie nach dem Einspielen eines älteren Backups erneut greift. Leer: aus
LOESCHLISTE_PATH = os.environ.get("LOESCHLISTE_PATH", "")
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
# Virenprüfung mit dem clamd des Servers (Fachfrage 4, 31.10.b); leer: keine Prüfung
CLAMD_SOCKET = os.environ.get("CLAMD_SOCKET", "")
CLAMD_MAX_BYTES = int(os.environ.get("CLAMD_MAX_BYTES", str(25 * 1024 * 1024 - 64 * 1024)))
CLAMD_TIMEOUT = int(os.environ.get("CLAMD_TIMEOUT", "60"))
FILE_UPLOAD_HANDLERS = [
    "core.virenscan.ClamavUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# Webseite: auf dem Testserver alle Webseiten nur in der Vorschau zeigen
# (erfundene Testdaten sollen nie öffentlich wirken)
WEBSITE_PREVIEW_ONLY = env_bool("WEBSITE_PREVIEW_ONLY", False)
# Testserver: feste Adresse der Vereinsseite (z. B. https://…/webseite/) statt der Domain
WEBSITE_PUBLIC_URL = os.environ.get("WEBSITE_PUBLIC_URL", "")
# Social-Media-Beiträge: Version der Meta-Schnittstelle und (optional) eigene Adresse für
# die Rückleitung von Meta (Standard: FRONTEND_URL)
META_GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v26.0")
SOCIAL_CALLBACK_BASE = os.environ.get("SOCIAL_CALLBACK_BASE", "")

# Verbund: Kopplung von Einheiten über mehrere HUBIplan-Instanzen (App peering).
# Eingeschaltet wird er je Instanz von der Plattform (Einstellung in der Datenbank).
# Öffentliche Adresse dieser Instanz für andere Instanzen (Standard: FRONTEND_URL)
PEERING_BASE_URL = os.environ.get("PEERING_BASE_URL", "")
# Datei mit Instanz-ID und privatem Schlüssel (Standard: PRIVATE_ROOT/peering/instance.json)
PEERING_KEY_FILE = os.environ.get("PEERING_KEY_FILE", "")
# Land des Serverstandorts (Selbstauskunft, ISO-Kürzel)
PEERING_COUNTRY = os.environ.get("PEERING_COUNTRY", "DE")
# Push an die App (Web-Push mit VAPID). Schlüsseldatei Standard: PRIVATE_ROOT/push/vapid.json
PUSH_VAPID_KEY_FILE = os.environ.get("PUSH_VAPID_KEY_FILE", "")
# Absender-Angabe für Push-Dienste (https-Adresse oder mailto:), Standard FRONTEND_URL
PUSH_VAPID_SUBJECT = os.environ.get("PUSH_VAPID_SUBJECT", "")
# Push-Gateway der Play-Variante (Schritt A6); leer: nur UnifiedPush und Abruf
PUSH_GATEWAY_URL = os.environ.get("PUSH_GATEWAY_URL", "")
# Nur für Tests: Push auch an interne Adressen
PUSH_ALLOW_INTERNAL = env_bool("PUSH_ALLOW_INTERNAL", False)
# Nur für Testaufbauten: Partner auch über http und interne Adressen erreichen
PEERING_ALLOW_INSECURE = env_bool("PEERING_ALLOW_INSECURE", False)
