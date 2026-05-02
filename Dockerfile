FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd -g 10001 app \
  && useradd -u 10001 -g 10001 -m -s /usr/sbin/nologin app \
  && mkdir -p /config \
  && chown -R app:app /config

COPY requirements.txt /app/requirements.txt
RUN python -m pip install -r /app/requirements.txt

COPY solis_inverter_exporter.py /app/solis_inverter_exporter.py

EXPOSE 9121

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9121/-/healthy', timeout=3).read()"

USER app

ENTRYPOINT ["python", "/app/solis_inverter_exporter.py"]
CMD ["--config-file", "/config/config.yaml"]
