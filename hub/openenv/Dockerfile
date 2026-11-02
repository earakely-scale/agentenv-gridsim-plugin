# GridSimEnv Desk on OpenEnv: the server, its Try Environment page and the MCP playground, on port 8000. No model is
# called and nothing secret is read: every session plays gridsim_core's desk on the packed ERCOT data.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 HOME=/home/user PORT=8000 PYTHONPATH=/app \
    ENABLE_WEB_INTERFACE=true MAX_CONCURRENT_ENVS=32 SESSION_IDLE_S=1200 PLAYGROUND_SESSIONS=48
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY . /app
RUN useradd --create-home --uid 1000 user && chown -R user:user /app
USER user
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000} --ws-ping-interval 60 --ws-ping-timeout 600"]
