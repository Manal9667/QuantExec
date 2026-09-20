# Deployment Guide

How to run QuantExec beyond a bare `python`/`npm` dev loop. It covers the
one-command Docker stack, configuration, and what to change before exposing
it beyond localhost.

> **Reminder (spec §48):** QuantExec is a research/backtesting system, not a
> live trading platform or broker. "Deploying" it means hosting the
> simulator + dashboard for analysis, not connecting to any exchange.

---

## 1. Local stack with Docker Compose (recommended)

Prerequisites: Docker with the Compose plugin.

```bash
# From the repo root:
docker compose up --build
```

This builds and runs two services:

| Service | URL | What it is |
|---|---|---|
| `backend` | http://localhost:8000 | FastAPI over the compiled C++ engine. API docs at `/docs`, `/redoc`. |
| `frontend` | http://localhost:5173 | Static React dashboard (built with Vite, served by `serve`). |

The backend image is a **multi-stage build**: stage 1 compiles the C++
engine + pybind11 module with CMake; stage 2 is a slim runtime image that
copies only the built `executor*.so` and the Python backend. The frontend
image builds the Vite bundle and serves the static files.

The SQLite database is persisted on the host via the `./experiments`
volume, so experiments survive `docker compose down` / `up`.

Stop with `Ctrl-C`, or `docker compose down` (add `-v` to also drop
anonymous volumes).

---

## 2. Configuration

All backend runtime configuration is environment-driven (see
[`backend/config.py`](../backend/config.py) and
[`.env.example`](../.env.example)). Compose wires these through with
sensible defaults, so `docker compose up` works with no `.env`. To
override, either export the variable or create a `.env` at the repo root
(Compose reads it automatically):

```bash
# .env  (repo root)
QUANTEXEC_CORS_ORIGINS=https://dashboard.example.com
QUANTEXEC_LOG_LEVEL=WARNING
QUANTEXEC_COMMISSION_BPS=0.5
QUANTEXEC_EXCHANGE_FEE_BPS=0.1
```

| Variable | Default | Notes |
|---|---|---|
| `QUANTEXEC_DB_PATH` | `/app/experiments/experiments.db` (in container) | Points at the mounted volume |
| `QUANTEXEC_CORS_ORIGINS` | `*` | **Tighten to your dashboard origin(s) before exposing the API** |
| `QUANTEXEC_LOG_LEVEL` | `INFO` | `DEBUG`…`CRITICAL` |
| `QUANTEXEC_COMMISSION_BPS` / `_EXCHANGE_FEE_BPS` / `_FIXED_FEE_PER_FILL` | `0.0` | Default cost assumptions when a request omits `costs` |

**Frontend → backend URL.** A production build has no dev-server `/api`
proxy, so the backend origin is baked in at build time via the
`VITE_API_BASE_URL` build arg. For a non-localhost backend:

```bash
VITE_API_BASE_URL=https://api.example.com docker compose build frontend
docker compose up
```

---

## 3. Running without Docker

### Backend

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install pybind11 -r backend/requirements.txt
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
      -Dpybind11_DIR="$(python3 -c 'import pybind11; print(pybind11.get_cmake_dir())')"
cmake --build build --config Release --target executor -j"$(nproc)"

# Serve (production-style: multiple workers, bound to all interfaces)
PYTHONPATH=build:backend uvicorn main:app --app-dir backend \
    --host 0.0.0.0 --port 8000 --workers 4
```

> **SQLite + workers caveat:** each worker process opens its own SQLite
> connection (see `backend/db.py`). SQLite handles concurrent reads fine and
> serializes writes; for this synchronous, low-write workload that is
> adequate. If you expect real write concurrency, move to PostgreSQL
> (§5).

### Frontend

```bash
cd frontend
npm ci
VITE_API_BASE_URL=https://api.example.com npm run build   # outputs dist/
# Serve dist/ with any static host (nginx, serve, S3+CloudFront, ...)
npx serve -s dist -l 5173
```

---

## 4. Putting it behind a reverse proxy

For a single public origin, terminate TLS at a reverse proxy and route
`/api/*` to the backend and everything else to the static frontend. Example
nginx sketch:

```nginx
server {
    listen 443 ssl;
    server_name quantexec.example.com;
    # ssl_certificate ... ; ssl_certificate_key ... ;

    location /api/ {
        proxy_pass http://backend:8000/;   # strip /api prefix
    }
    location / {
        root /usr/share/nginx/html;         # the built frontend dist/
        try_files $uri /index.html;
    }
}
```

If you serve the dashboard and API from the same origin this way, build the
frontend with `VITE_API_BASE_URL=/api` and set
`QUANTEXEC_CORS_ORIGINS` to that origin (or leave CORS unused, since
same-origin requests don't need it).

---

## 5. Scaling notes and the SQLite → PostgreSQL path

The persistence layer is intentionally plain `sqlite3` with no ORM
(spec §33/§40). It is the right default for a single-node research tool.
Reasons you might outgrow it, and the honest current state:

- **Write concurrency / multi-node.** SQLite is single-writer. Moving to
  PostgreSQL would require replacing the connection/SQL in `backend/db.py`
  (the SQL is standard enough that the queries port directly, but there is
  **no ORM or migration framework** to do this automatically — see
  `LIMITATIONS.md`).
- **Synchronous execution.** `POST /experiments` runs the engine inline and
  blocks until done (`LIMITATIONS.md` §5). For long runs or high
  concurrency you would introduce a task queue (e.g. RQ/Celery) and make the
  endpoint return `queued` immediately — the `queued`/`cancelled` states and
  the `DELETE /experiments/{id}` endpoint already exist for exactly that
  future mode.

---

## 6. Security checklist before exposing beyond localhost

The defaults are tuned for local development. Before putting this on a
network:

- [ ] **Set `QUANTEXEC_CORS_ORIGINS`** to your dashboard origin(s) — the
      default `*` is permissive.
- [ ] **Add authentication.** There is **no auth/authorization** in the API
      today (`LIMITATIONS.md` §5) — anyone who can reach the port can create
      and read experiments. Put it behind an authenticating proxy or add
      auth middleware.
- [ ] **Terminate TLS** at a proxy (§4); the app speaks plain HTTP.
- [ ] **Bound resource use.** `quantity`, `slices`, and dataset size are
      validated, but there is no per-client rate limiting; add it at the
      proxy if the endpoint is public.
- [ ] **Datasets are read from within the repo root only** (path-traversal
      is rejected in `experiment_service.resolve_dataset_path`), but treat
      any uploaded dataset as untrusted input and validate it with
      `scripts/build_dataset_manifest.py` first.

---

## 7. Health checks and observability

- **Liveness/readiness:** `GET /health` returns `{"status": "ok"}`. The
  Compose backend service already uses it as its healthcheck, and the
  frontend waits for it via `depends_on: condition: service_healthy`.
- **Logs:** the backend emits one structured JSON object per line
  (`backend/logging_utils.py`); set `QUANTEXEC_LOG_LEVEL` to control
  verbosity. Ship stdout to your log aggregator.
- **Performance:** CI runs `scripts/check_perf_regression.py` against a
  committed baseline (`docs/BENCHMARKING.md` §7); run it in your own
  pipeline if you want a perf gate on your hardware.
