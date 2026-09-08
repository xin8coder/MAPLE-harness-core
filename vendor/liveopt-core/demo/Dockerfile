# LiveOpt web demo image. Build from the REPO ROOT, not from demo/:
#   docker build -f demo/Dockerfile -t liveopt-demo .
#   docker run --rm -p 8000:8000 liveopt-demo
# The demo executes LLM-generated Workbench code; run it only with trusted
# users (or keep it on loopback) and pass API keys through the UI at runtime.
FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -e ".[demo]"

EXPOSE 8000
CMD ["liveopt-demo", "--host", "0.0.0.0", "--port", "8000"]
