# calma — multi-stage, NON-ROOT container (roadmap WS-B distribution).
#   build:  docker build -t calma:0.12.0 .
#   run:    docker run --rm --network=none -v "$PWD:/work" -w /work calma:0.12.0 verify . "Sharpe 1.8"
# The core is pure-stdlib (dependencies = []), so the runtime carries no third-party line unless you build
# the parquet variant (--build-arg EXTRAS=parquet). In a release pipeline: pin the base image by DIGEST,
# install from a hashed lock (--require-hashes), and add cosign-keyless signing + a CycloneDX/SPDX SBOM +
# SLSA provenance (verifiable with `gh attestation verify`). See docs/install.md.

# ---- builder: build the wheel and install it into an isolated venv ----
FROM python:3.12-slim AS builder
ARG EXTRAS=""
WORKDIR /build
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --upgrade pip build
COPY . .
RUN /opt/venv/bin/python -m build --wheel --outdir /tmp/dist \
 && WHL="$(ls /tmp/dist/calma-*.whl)" \
 && /opt/venv/bin/pip install --no-cache-dir "${WHL}${EXTRAS:+[$EXTRAS]}"

# ---- runtime: a slim, NON-ROOT image carrying only the venv ----
FROM python:3.12-slim
# a non-root, no-login user; the verifier never needs root (it re-executes UNTRUSTED code)
RUN useradd --create-home --shell /usr/sbin/nologin calma
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    CALMA_INVOKED_AS="calma" \
    PYTHONDONTWRITEBYTECODE=1
USER calma
WORKDIR /work
ENTRYPOINT ["calma"]
CMD ["--help"]
