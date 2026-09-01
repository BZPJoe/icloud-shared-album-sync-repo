ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache \
    python3 \
    py3-requests \
    py3-yaml

COPY run.sh sync.py /app/
RUN chmod +x /app/run.sh /app/sync.py

WORKDIR /app
CMD ["/app/run.sh"]

