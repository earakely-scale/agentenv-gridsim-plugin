# The GridSim envs on port 18765: the battery-desk MCP server with the ERCOT DAM task packs, or, behind the gateway,
# gridsim-live (the live packs) or gridsim-hybrid (the hybrid packs) when ENVIRONMENT_NAME names one.
#   Build: agent-env gridsim setup   (docker build -t agentenv-gridsim-env .)
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/earakely-scale/agentenv-gridsim-plugin" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.description="GridSimEnv as an AgentEnv environment. Prices derived from ERCOT Day-Ahead and Real-Time Market settlement point prices (NP4-180-ER, NP6-785-ER); ERCOT does not endorse this product. Battery archetypes from EIA-860 (public domain)."
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app
RUN pip install "agentenv-framework-protocol==0.1.370" "fastmcp==3.4.8" "mcp==1.30.0" "pydantic==2.13.5" "numpy>=2,<3"
WORKDIR /app
COPY LICENSE NOTICE /app/
COPY data /app/gridsim_core/data
COPY src/gridsim_core /app/gridsim_core
COPY src/agentenv_gridsim /app/agentenv_gridsim
RUN useradd --create-home --uid 1000 gridsim
USER gridsim
EXPOSE 18765
CMD ["python", "-m", "agentenv_gridsim.server"]
