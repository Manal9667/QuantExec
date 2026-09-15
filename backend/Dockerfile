# Builds the C++ execution engine (incl. Phase 2: POV, latency, impact),
# then runs the FastAPI backend against the compiled `executor` module.
#
# Build/run from the repo root:
#   docker compose up backend

FROM python:3.11-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY CMakeLists.txt ./
COPY include ./include
COPY src ./src
COPY tests ./tests
COPY benchmarks ./benchmarks
COPY example ./example
COPY backend/requirements.txt ./backend/requirements.txt

RUN pip install --no-cache-dir pybind11 -r backend/requirements.txt

RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
      -Dpybind11_DIR=$(python3 -c "import pybind11; print(pybind11.get_cmake_dir())") \
    && cmake --build build --config Release --target executor -j "$(nproc)"

# ---------------------------------------------------------------------------

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /app/build/executor*.so ./build/
COPY backend ./backend
COPY datasets ./datasets
COPY configs ./configs

RUN pip install --no-cache-dir -r backend/requirements.txt

ENV PYTHONPATH=/app/build:/app/backend
WORKDIR /app/backend

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]