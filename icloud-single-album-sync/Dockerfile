ARG BUILD_FROM
FROM $BUILD_FROM

# Install dependencies including Selenium and Chromium
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-requests \
    py3-beautifulsoup4 \
    py3-yaml \
    chromium \
    chromium-chromedriver

# Install Selenium
RUN pip3 install selenium

# Copy add-on files
COPY run.sh /app/
COPY sync.py /app/
RUN chmod +x /app/run.sh /app/sync.py

# Set working directory
WORKDIR /app

# Start the add-on
CMD ["/app/run.sh"]
