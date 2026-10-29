# GridSim v1: the battery-desk MCP server on port 18765, serving the ERCOT DAM v1 packs this training bundle plays.
# The build context is this folder: the plugin's own gridsim_core and agentenv_gridsim, and the v1 train and eval packs.
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/earakely-scale/agentenv-gridsim-plugin" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.description="GridSimEnv v1 as an AgentEnv environment. Prices derived from ERCOT Day-Ahead Market settlement point prices (NP4-180-ER); ERCOT does not endorse this product. Battery archetypes from EIA-860 (public domain)."
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app \
    GRIDSIM_TASKS_DIR=/app/packs/ercot-dam-v1-train:/app/packs/ercot-dam-v1-eval
RUN pip install "agentenv-framework-protocol==0.1.370" "fastmcp==3.4.8" "mcp==1.30.0" "pydantic==2.13.5" "numpy>=2,<3" \
    "highspy==1.15.1"
WORKDIR /app
COPY LICENSE NOTICE /app/
COPY gridsim_core /app/gridsim_core
COPY agentenv_gridsim /app/agentenv_gridsim
COPY packs /app/packs
RUN useradd --create-home --uid 1000 gridsim
USER gridsim
EXPOSE 18765
CMD ["python", "-m", "agentenv_gridsim.server"]
