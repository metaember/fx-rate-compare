# FX Rate Comparison

A Flask dashboard that compares foreign exchange rates from **Visa** and **Revolut** against ECB benchmark rates. Useful for seeing real-world currency markups when using cards abroad.

## Features

- Live Visa and Revolut FX rates vs ECB mid-market benchmarks
- Markup % calculation for transparency
- Sparkline trend charts showing how markups evolve
- CSV logging for long-term analysis
- Background rate fetching (once daily) — page loads never hit external APIs
- Disk-persisted cache survives restarts
- Docker support with optional Traefik integration

## Getting Started

### Run locally

```bash
uv venv && source .venv/bin/activate
uv pip install -r pyproject.toml
python visa_fx_backend.py
```

Then visit http://localhost:3000

### Docker

```bash
docker compose up -d
```

For local development with port mapping:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

For production with Traefik:

```bash
export DOMAIN_NAME=yourdomain.com
docker compose up -d
```

## Routes

| Route          | Description                          |
|----------------|--------------------------------------|
| `/`            | Main dashboard                       |
| `/health`      | Health check endpoint                |
| `/export/json` | Current rates as JSON                |
| `/export/csv`  | Historical rates as downloadable CSV |
| `/log/view`    | Full log table in browser            |

## Project Structure

```
fx-rate-compare/
├── visa_fx_backend.py          # Flask app + background fetcher
├── templates/
│   ├── base.html               # Shared layout and styles
│   ├── index.html              # Main dashboard
│   └── log.html                # Log viewer
├── data/
│   ├── fx_log.csv              # Historical rates (auto-generated)
│   └── fx_cache.json           # Persisted rate cache
├── pyproject.toml              # Dependencies
├── Dockerfile
├── docker-compose.yml
├── docker-compose.override.yml # Traefik labels (production)
└── docker-compose.local.yml    # Port mapping (development)
```

## How It Works

A background thread fetches rates from Visa and Revolut APIs once every 24 hours. Results are cached in memory and persisted to `data/fx_cache.json`. All HTTP endpoints serve from cache — no user request ever triggers an external API call.

Visa's API is behind Cloudflare, so requests use `curl_cffi` with browser TLS fingerprint impersonation.

## License

MIT
