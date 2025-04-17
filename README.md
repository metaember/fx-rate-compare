# 💱 Visa FX Rate Tracker

A Flask-based dashboard that tracks foreign exchange rates from Visa's public FX API and compares them against ECB benchmark rates. Great for figuring out **real-world currency markups** when using cards like the Chase Sapphire Reserve abroad.

---

## 🌍 Features

- 📈 **Live Visa FX Rates** vs. **ECB Mid-Market Benchmarks**
- 📊 **Markup %** calculation for transparency
- 🔥 **Sparkline trend charts** to show how markups evolve over time
- 📁 **CSV logging** for long-term analysis
- 🌐 Clean HTML dashboard at `/` with flag emojis 🇯🇵🇬🇧🇲🇽
- 📤 `/export/csv` and `/export/json` endpoints
- 📜 `/log/view` to see all historical data in browser

---

## 🧪 Example Use Cases

- See if you're getting overcharged on foreign transactions
- Compare Visa's rate to the true interbank rate
- Monitor currency trends if you're a frequent traveler

---

## 🚀 Getting Started

### ▶️ Run with Python (`uv` or pip)

```bash
# Using uv (fast dependency manager)
uv venv && source .venv/bin/activate
uv pip install flask requests
python visa_fx_backend.py
```
Or with pip:

```bash
python -m venv venv
source venv/bin/activate
pip install flask requests
python visa_fx_backend.py
```

Then visit:
📍 http://localhost:3000


## 🐳 Docker Usage

```bash
docker build -t visa-fx-tracker .
docker run -d -p 3000:3000 visa-fx-tracker
```

Or with docker compose:

```bash
docker compose up -d
```

### Docker Deployment

1. Local development (with port mapping):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
   ```
   Access at: http://localhost:3000

2. Production deployment with Traefik:
   ```bash
   # Set your domain variables
   export SUBDOMAIN=visa-fx
   export DOMAIN_NAME=yourdomain.com

   # Start the application
   docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
   ```
   Access at: https://visa-fx.yourdomain.com

## 🧾 Routes

| Route          | Description                                           |
|----------------|-------------------------------------------------------|
| `/`            | Main dashboard (Visa vs. ECB with sparkline trends)   |
| `/export/json` | Latest FX data in JSON                                |
| `/export/csv`  | All logged rates as downloadable CSV                  |
| `/log/view`    | Full log table in browser                             |

## 🔒 Privacy / Safety Notes
No authentication, credentials, or tokens are used

All headers mimic a standard browser (no API keys)

Logs are local only — no data is sent to third parties

## 📂 Project Structure

```
visa-fx-tracker/
├── visa_fx_backend.py     # Main Flask app
├── requirements.txt       # Pip dependencies
├── pyproject.toml         # uv-compatible dependencies (optional)
├── fx_log.csv             # Logged historical rates (auto-generated)
├── Dockerfile             # Container build
└── README.md              # You're here!
```

## 📖 License
MIT — use, modify, and share freely.
Attribution appreciated but not required. ✌️

## ✨ Credits
Built by me — inspired by real travel, real markups, and real curiosity.
Feel free to fork, improve, or open issues!