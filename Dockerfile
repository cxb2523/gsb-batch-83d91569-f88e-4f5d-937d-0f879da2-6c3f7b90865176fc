# The Playwright engine (the one the README recommends) with its own
# Chromium, for a scheduled job or a CI canary. Not required for local
# development — `pip install` directly is simpler there.
#
#   docker build -t flippa-scraper .
#   docker run --rm -v "$PWD/out:/out" flippa-scraper \
#     --url "https://flippa.com/search?filter%5Bproperty_type%5D=saas" \
#     --pages 3 --out /out/saas
#
# Pass --twocaptcha-key/--proxy the same way as locally, or mount a .env at
# /app/.env. Nothing here bakes in a credential, and CI asserts that: a .env
# baked into an image is a credential published to everyone who can pull it.
FROM python:3.12-slim

WORKDIR /app

# From the lock, hash-checked: the image carries exactly the versions CI
# tested, and a tampered download fails the build instead of shipping.
COPY requirements-playwright.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements-playwright.lock \
    # Playwright's own apt-get for Chromium's shared libraries — not pip
    # packages, so this has to be its own explicit step.
    && playwright install --with-deps chromium

# The entrypoint's transitive local imports, and nothing else. smoke_test.py's
# own check compares this list against the real import graph: every repo in
# this family once shipped an image that died with ModuleNotFoundError on
# every invocation, --help included, because one module was missing here.
COPY captcha_solver.py cli_types.py env_config.py fingerprint_client.py \
     output_writer.py page_flow.py playwright_scraper.py product_parser.py \
     proxy_pool.py diff_runs.py ./

ENTRYPOINT ["python3", "playwright_scraper.py"]
CMD ["--help"]
