FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Im Betrieb nur die Laufzeit-Abhängigkeiten; scripts/test.sh baut mit
# --build-arg REQUIREMENTS=requirements-dev.txt (pytest, ruff)
ARG REQUIREMENTS=requirements.txt
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r "$REQUIREMENTS"

COPY . .

# Statische Dateien schon beim Bauen einsammeln: Im Betrieb ist das Dateisystem
# schreibgeschützt (read_only in docker-compose.server.yml). Ohne die Dateien von
# DRF (Bootstrap, jQuery, Font Awesome): Die HTML-Ansicht der API ist aus, und so
# gehen keine fremden Dateien ohne Lizenzhinweis an den Browser (Lizenzaudit 31.10., L06).
RUN DJANGO_DEBUG=true DJANGO_SECRET_KEY=nur-zum-bauen python manage.py collectstatic --noinput -v0 --ignore rest_framework
RUN useradd --create-home --uid 1000 app && mkdir -p /app/media /app/private /app/loeschliste && chown -R app /app
USER app

EXPOSE 8000
ENTRYPOINT ["sh", "./docker-entrypoint.sh"]
# Ohne Steuer-Socket: braucht kein beschreibbares Home-Verzeichnis und ist eine Angriffsfläche weniger
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--no-control-socket"]
