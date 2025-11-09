ARG BUILD_FROM=ghcr.io/hassio-addons/base:17.1.4
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 py3-pip
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt
COPY run.sh /run.sh
RUN chmod a+x /run.sh
COPY app.py /app/app.py
CMD [ "/run.sh" ]
