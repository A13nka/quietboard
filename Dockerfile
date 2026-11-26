# Basis auf Patch-Stand und Digest festgelegt; Dependabot schlägt Aktualisierungen vor (.github/dependabot.yml)
FROM python:3.13.18-slim@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50
ARG VERSION=dev
ENV APP_VERSION=$VERSION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 status && mkdir /data && chown status /data
WORKDIR /srv
# Nur die festgelegten Pakete mit Prüfsummen (requirements.lock, erzeugt mit `make lock`)
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock
COPY app ./app
COPY tools ./tools
COPY hosts ./hosts
COPY LICENSE THIRD_PARTY_NOTICES.md ./
USER status
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status==200 else 1)" || exit 1
# Weitergeleitete Header wertet die App selbst aus – nur von vertrauten Proxys (TRUSTED_PROXIES, app/security.py)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
