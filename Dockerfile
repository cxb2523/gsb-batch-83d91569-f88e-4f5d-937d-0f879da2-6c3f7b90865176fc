# MeshAtlas in a container. It talks to the host's tailscaled through its socket (mounted read-only below),
# so it needs the tailscale CLI but not its own Tailscale login.
FROM python:3.12-slim

ARG TAILSCALE_VERSION=1.104.5
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl openssh-client iputils-ping \
 && arch="$(dpkg --print-architecture)" \
 && curl -fsSL "https://pkgs.tailscale.com/stable/tailscale_${TAILSCALE_VERSION}_${arch}.tgz" \
    | tar -xz --strip-components=1 -C /usr/local/bin "tailscale_${TAILSCALE_VERSION}_${arch}/tailscale" \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 meshatlas \
 && mkdir -p /data && chown meshatlas /data

USER meshatlas
ENV MESHATLAS_DATA=/data \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=60s --timeout=5s CMD python3 -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('MESHATLAS_PORT','8765'))" || exit 1
ENTRYPOINT ["meshatlas"]
CMD ["run", "--host", "0.0.0.0"]
