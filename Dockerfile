# syntax=docker/dockerfile:1

############################
# Builder stage
############################
FROM python:3.10-alpine AS builder

LABEL MAINTAINER="Daniel Pryor <daniel@pryorda.net>"
LABEL NAME=vmware_exporter

# Build toolchain needed to compile native deps (cryptography/cffi via rust/cargo)
RUN apk add --no-cache --update \
    gcc python3-dev musl-dev libffi-dev openssl-dev rust cargo

# Isolate everything in a venv so it can be copied wholesale into the runtime image
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /opt/vmware_exporter

# Install dependencies first; this layer is cached unless requirements.txt changes,
# so editing source code no longer triggers a full (slow) dependency rebuild.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Now copy the source and install just the package itself (fast, no deps rebuild)
COPY . ./
RUN pip install --no-cache-dir --no-deps .

############################
# Runtime stage
############################
FROM python:3.10-alpine

LABEL MAINTAINER="Daniel Pryor <daniel@pryorda.net>"
LABEL NAME=vmware_exporter

# Only the shared libraries required at runtime (no compilers)
RUN apk add --no-cache --update libffi openssl libgcc

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv

EXPOSE 9272

ENTRYPOINT ["vmware_exporter"]
