FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1
ENV SOLIS_INVERTER_EXPORTER_CONFIG=/config/config.yaml

WORKDIR /app

RUN groupadd -g 10001 app && useradd -u 10001 -g 10001 -m -s /usr/sbin/nologin app
RUN mkdir -p /config && chown -R app:app /config

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY solis_inverter_exporter.py /app/solis_inverter_exporter.py

EXPOSE 8686

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8686/-/healthy',timeout=3).read()"

USER app

ENTRYPOINT ["python", "/app/solis_inverter_exporter.py"]
CMD ["--config-file", "/config/config.yaml"]
