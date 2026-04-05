FROM docker:dind

RUN apk add --no-cache \
    bash \
    curl \
    python3 \
    py3-pip \
    openjdk17-jre \
    git

RUN curl -fsSL https://get.nextflow.io | bash && \
    mv nextflow /usr/local/bin/ && \
    chmod +x /usr/local/bin/nextflow

RUN pip install --break-system-packages \
    streamflow \
    fastapi \
    uvicorn \
    python-multipart

COPY app/ /app/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8082
ENTRYPOINT ["/entrypoint.sh"]
