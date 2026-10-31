# Backup-Dienst: tägliches verschlüsseltes Backup mit Rücksicherungstest.
# Gleiche PostgreSQL-Version wie die Datenbank, damit pg_dump passt.
FROM postgres:18-alpine@sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5
RUN apk add --no-cache openssl rsync openssh-client age
COPY run.sh backup.sh restore-test.sh verify.sh hmac.sh /usr/local/bin/
COPY dateifelder.txt /usr/local/share/hubiplan/
RUN chmod 755 /usr/local/bin/run.sh /usr/local/bin/backup.sh /usr/local/bin/restore-test.sh \
    /usr/local/bin/verify.sh /usr/local/bin/hmac.sh
# Statusordner (Volume backup-status): gehört dem Backup-Dienst, der Worker liest nur
RUN mkdir -p /status && chown postgres:postgres /status && chmod 755 /status
USER postgres
ENTRYPOINT ["/usr/local/bin/run.sh"]
