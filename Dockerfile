FROM ghcr.io/anomalyco/opencode

RUN apk add --no-cache python3 py3-pip curl

RUN pip3 install --no-cache-dir --break-system-packages "discord.py>=2.3,<3" "aiohttp>=3.9,<4" "pyyaml>=6.0"

RUN mkdir -p /app/opencode

WORKDIR /app

COPY config.yaml .
COPY src/ ./src/
COPY main.py .
COPY start.sh .

RUN chmod +x start.sh

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["./start.sh"]
