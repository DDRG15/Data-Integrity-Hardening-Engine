FROM python:3.12-slim

# Non-root user — never run data processing as root
RUN useradd --create-home --shell /bin/bash dih

WORKDIR /app

# Install dependencies before copying source so this layer is cached on re-builds
COPY requirements.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source after deps so code changes don't bust the dependency cache
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Input and output data are mounted at runtime — never baked into the image
RUN mkdir /data && chown dih:dih /data
VOLUME ["/data"]

USER dih
WORKDIR /data

ENTRYPOINT ["dih-engine"]
CMD ["--help"]
