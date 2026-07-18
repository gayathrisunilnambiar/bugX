FROM python:3.11-slim

# git is required: Sentinel Bisect runs the reproduction command inside disposable
# git worktrees, and the fixture generator initializes its own throwaway repo.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# requirements.txt includes pytest, which the demo's reproduction command needs.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e .

# The reproduction command bisection searches against.
ENV DEMO_COMMAND="pytest -q tests/test_calculator.py"

EXPOSE 8787

# Default path needs no OPENAI_API_KEY: regenerate the fixture, then run the offline
# bisection demo (adaptive rerun schedule + flaky routing) with --serve so the HTML
# timeline stays reachable at the mapped port for the life of the container.
# --serve-host 0.0.0.0 is required for -p 8787:8787 on the host to reach it; the
# printed URL still says localhost, which is what a judge on the host actually opens.
CMD python fixtures/build_fixture.py && \
    sentinel-bisect \
      --repo fixtures/flaky-regression-demo \
      --command "$DEMO_COMMAND" \
      --report-file demo-report.md \
      --trace-file demo-trace.json \
      --serve --serve-host 0.0.0.0 --serve-port 8787
