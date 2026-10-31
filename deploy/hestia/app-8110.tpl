#=========================================================================#
# HUBIplan hinter HestiaCP (nginx-Proxy-Vorlage, HTTP)                    #
# Kopieren nach /usr/local/hestia/data/templates/web/nginx/app-8110.tpl   #
# Leitet nur auf HTTPS um; Let's-Encrypt-Prüfung läuft über nginx.conf_*. #
#                                                                         #
# Aufgebaut nach den Standardvorlagen von HestiaCP 1.9.4                  #
# (nginx-Vorlagen für Weiterleitungen, github.com/hestiacp/hestiacp),     #
# GPL-3.0; geändert für HUBIplan seit 2026-10. Diese Datei steht daher    #
# unter der GPL-3.0; Volltext in LICENSE-GPL-3.0.txt daneben,             #
# Einordnung in docs/lizenzen.md.                                         #
#=========================================================================#

server {
	listen      %ip%:%proxy_port%;
	server_name %domain_idn% %alias_idn%;
	error_log   /var/log/%web_system%/domains/%domain%.error.log error;

	include %home%/%user%/conf/web/%domain%/nginx.forcessl.conf*;

	location ~ /\.(?!well-known\/|file) {
		deny all;
		return 404;
	}

	location / {
		return 301 https://$host$request_uri;
	}

	include %home%/%user%/conf/web/%domain%/nginx.conf_*;
}
