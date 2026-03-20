from flask import Flask, jsonify, render_template, send_file, request, abort
from curl_cffi import requests as cffi_requests
import requests as http_requests
import threading
import time
import csv
import json
import logging
from datetime import datetime
from urllib.parse import quote
import os
from collections import defaultdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps

# Fix SSL certificate verification in Docker
os.environ['REQUESTS_CA_BUNDLE'] = '/etc/ssl/certs/ca-certificates.crt'

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Rate limiting ---

RATE_LIMIT = 30        # requests per window
RATE_WINDOW = 60       # window in seconds
_rate_buckets = {}     # ip -> (count, window_start)
_rate_lock = threading.Lock()


def rate_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr
        now = time.time()
        with _rate_lock:
            count, window_start = _rate_buckets.get(ip, (0, now))
            if now - window_start > RATE_WINDOW:
                count, window_start = 0, now
            count += 1
            _rate_buckets[ip] = (count, window_start)
        if count > RATE_LIMIT:
            abort(429)
        return f(*args, **kwargs)
    return decorated

REQUEST_TIMEOUT = 15  # seconds per HTTP request
FETCH_INTERVAL = 24 * 60 * 60  # 24 hours
DATA_DIR = Path(__file__).parent / 'data'
LOG_FILE = DATA_DIR / 'fx_log.csv'
CACHE_FILE = DATA_DIR / 'fx_cache.json'

DATA_DIR.mkdir(parents=True, exist_ok=True)
if not LOG_FILE.exists():
    LOG_FILE.touch()

CURRENCIES = ['JPY', 'EUR', 'GBP', 'THB', 'CAD', 'AUD', 'INR', 'MXN', 'CHF', 'CNY', 'SEK', 'NZD']
FLAG_MAP = {
    'JPY': '🇯🇵', 'EUR': '🇪🇺', 'GBP': '🇬🇧', 'THB': '🇹🇭', 'CAD': '🇨🇦',
    'AUD': '🇦🇺', 'INR': '🇮🇳', 'MXN': '🇲🇽', 'CHF': '🇨🇭', 'CNY': '🇨🇳',
    'SEK': '🇸🇪', 'NZD': '🇳🇿'
}

VISA_HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US,en;q=0.9',
    'dnt': '1',
    'referer': 'https://usa.visa.com/support/consumer/travel-support/exchange-rate-calculator.html',
    'sec-ch-ua': '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
}

REVOLUT_HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US,en;q=0.9',
    'dnt': '1',
    'referer': 'https://www.revolut.com/',
    'user-agent': 'Mozilla/5.0',
}

# In-memory cache: loaded from disk on startup, updated by background thread
cache = {
    'rates': {},       # {currency: {visa: {...}, revolut: {...}}}
    'last_updated': None,
}
cache_lock = threading.Lock()


# --- Disk persistence ---

def save_cache_to_disk():
    """Persist cache to disk so it survives restarts."""
    with cache_lock:
        snapshot = json.dumps(cache, default=str)
    CACHE_FILE.write_text(snapshot)


def load_cache_from_disk():
    """Load cache from disk on startup."""
    global cache
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            with cache_lock:
                cache.update(data)
            logger.info("Loaded cache from disk (last updated: %s)", cache.get('last_updated'))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load cache from disk: %s", e)


# --- API fetching ---

def fetch_visa_rate(to_currency):
    """Fetch exchange rate from Visa API using browser-like TLS fingerprint."""
    today = datetime.now().strftime('%m/%d/%Y')
    url = f"https://usa.visa.com/cmsapi/fx/rates?amount=10000&fee=0&utcConvertedDate={quote(today)}&exchangedate={quote(today)}&fromCurr=USD&toCurr={to_currency}"
    response = cffi_requests.get(
        url, headers=VISA_HEADERS, timeout=REQUEST_TIMEOUT, impersonate="chrome136"
    )
    response.raise_for_status()
    return response.json()


def fetch_revolut_rate(to_currency):
    """Fetch exchange rate from Revolut API."""
    url = f"https://www.revolut.com/api/exchange/quote?amount=100000&country=US&fromCurrency=USD&isRecipientAmount=false&toCurrency={to_currency}"
    response = http_requests.get(url, headers=REVOLUT_HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_currency_rates(currency):
    """Fetch both Visa and Revolut rates for a currency."""
    visa_data = None
    revolut_data = None

    try:
        visa_data = fetch_visa_rate(currency)
    except Exception as e:
        logger.warning("Failed to fetch Visa rate for %s: %s", currency, e)

    try:
        revolut_data = fetch_revolut_rate(currency)
    except Exception as e:
        logger.warning("Failed to fetch Revolut rate for %s: %s", currency, e)

    return currency, visa_data, revolut_data


def refresh_all_rates():
    """Fetch all currency rates in parallel and update the cache."""
    logger.info("Starting rate refresh for %d currencies...", len(CURRENCIES))
    now = datetime.now()
    ts = now.strftime('%Y-%m-%d %H:%M:%S')
    new_rates = {}

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_currency_rates, c): c for c in CURRENCIES}
        for future in as_completed(futures):
            currency, visa_data, revolut_data = future.result()
            new_rates[currency] = {
                'visa': visa_data,
                'revolut': revolut_data,
            }

            # Log to CSV when we have visa data
            if visa_data and 'originalValues' in visa_data:
                try:
                    vals = visa_data['originalValues']
                    visa_rate = float(vals['fxRateVisa'])
                    currency_name = vals['fromCurrencyName']
                    benchmark = vals['benchmarks'][0]
                    benchmark_rate = float(benchmark['benchmarkFxRate'])
                    markup = float(benchmark['markupWithoutAdditionalFee']) * 100
                    revolut_rate = None
                    if revolut_data and isinstance(revolut_data, dict) and 'rate' in revolut_data:
                        revolut_rate = float(revolut_data['rate']['rate'])
                    log_fx_rate(ts, currency, currency_name, visa_rate, benchmark_rate, markup, revolut_rate)
                except Exception as e:
                    logger.warning("Error logging data for %s: %s", currency, e)

    with cache_lock:
        cache['rates'] = new_rates
        cache['last_updated'] = ts

    save_cache_to_disk()

    success_visa = sum(1 for r in new_rates.values() if r['visa'] and 'originalValues' in r.get('visa', {}))
    success_revolut = sum(1 for r in new_rates.values() if r['revolut'] and 'rate' in r.get('revolut', {}))
    logger.info("Rate refresh complete: Visa %d/%d, Revolut %d/%d", success_visa, len(CURRENCIES), success_revolut, len(CURRENCIES))


def background_fetcher():
    """Background thread that refreshes rates once per day."""
    while True:
        try:
            refresh_all_rates()
        except Exception as e:
            logger.error("Background fetch failed: %s", e)
        time.sleep(FETCH_INTERVAL)


# --- CSV logging / history ---

def log_fx_rate(timestamp, currency, name, visa_rate, benchmark_rate, markup, revolut_rate=None):
    """Log exchange rate data to CSV file."""
    with open(LOG_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, currency, name, visa_rate, benchmark_rate, markup, revolut_rate or 'N/A'])


def load_logs():
    """Load historical markup data for trend analysis."""
    history = defaultdict(list)
    if not LOG_FILE.exists():
        return history
    with open(LOG_FILE, 'r') as f:
        for row in csv.reader(f):
            if len(row) >= 6:
                _, code, _, _, _, markup = row[:6]
                try:
                    history[code].append(float(markup))
                except (ValueError, IndexError):
                    continue
    return history


def generate_sparkline_points(data, width=80, height=20):
    """Generate SVG polyline points from data."""
    if not data:
        return ""
    pts = data[-20:]
    mi, ma = min(pts), max(pts)
    spread = ma - mi if ma != mi else 1
    n = len(pts)
    if n == 1:
        return f"{width/2},{height/2}"
    coords = []
    for i, val in enumerate(pts):
        x = (i / (n - 1)) * width
        y = height - ((val - mi) / spread) * height
        coords.append(f"{x:.1f},{y:.1f}")
    return " ".join(coords)


# --- Routes (all read-only from cache, never hit external APIs) ---

@app.route('/health')
def health():
    with cache_lock:
        has_data = bool(cache.get('rates'))
    return jsonify(status='ok', has_data=has_data)


@app.route('/')
@rate_limit
def index():
    with cache_lock:
        rates = cache.get('rates', {})
        last_updated_str = cache.get('last_updated') or 'Fetching...'

    history = load_logs()
    rows = []

    for currency in CURRENCIES:
        currency_data = rates.get(currency, {})
        visa_data = currency_data.get('visa') or {}
        revolut_data = currency_data.get('revolut') or {}

        try:
            # Visa rate is foreign→USD, invert to get USD→foreign
            visa_raw = float(visa_data['originalValues']['fxRateVisa'])
            visa_rate = 1.0 / visa_raw
            currency_name = visa_data['originalValues']['fromCurrencyName']
            benchmark = visa_data['originalValues']['benchmarks'][0]
            benchmark_raw = float(benchmark['benchmarkFxRate'])
            benchmark_rate = 1.0 / benchmark_raw
            visa_markup = float(benchmark['markupWithoutAdditionalFee']) * 100

            # Revolut rate is already USD→foreign
            revolut_rate = None
            revolut_markup = None
            if revolut_data and isinstance(revolut_data, dict) and 'rate' in revolut_data:
                try:
                    revolut_rate = float(revolut_data['rate']['rate'])
                    revolut_markup = ((benchmark_rate - revolut_rate) / benchmark_rate) * 100
                except (KeyError, ValueError, TypeError):
                    pass

            # Determine decimal places based on rate magnitude
            decimals = 2 if visa_rate > 100 else (4 if visa_rate > 1 else 6)

            trend_data = history.get(currency, []) + [visa_markup]
            sparkline_points = generate_sparkline_points(trend_data)

            rows.append({
                'currency': f"{FLAG_MAP.get(currency, '')} {currency}",
                'name': currency_name,
                'visa_rate': f"{visa_rate:.{decimals}f}",
                'visa_markup': f"{visa_markup:.3f}%",
                'visa_markup_val': visa_markup,
                'revolut_rate': f"{revolut_rate:.{decimals}f}" if revolut_rate else 'N/A',
                'revolut_markup': f"{revolut_markup:.3f}%" if revolut_markup is not None else 'N/A',
                'revolut_markup_val': revolut_markup,
                'sparkline': sparkline_points,
            })
        except Exception:
            rows.append({
                'currency': f"{FLAG_MAP.get(currency, '')} {currency}",
                'name': 'N/A', 'visa_rate': 'N/A', 'visa_markup': 'N/A',
                'visa_markup_val': None, 'revolut_rate': 'N/A',
                'revolut_markup': 'N/A', 'revolut_markup_val': None,
                'sparkline': '',
            })

    return render_template('index.html', rows=rows, last_updated=last_updated_str)


@app.route('/export/csv')
@rate_limit
def export_csv():
    return send_file(LOG_FILE, mimetype='text/csv', as_attachment=True, download_name='fx_log.csv')


@app.route('/export/json')
@rate_limit
def export_json():
    """Export current rates as JSON."""
    with cache_lock:
        rates = cache.get('rates', {})

    result = {}
    for currency in CURRENCIES:
        entry = {}
        currency_data = rates.get(currency, {})
        visa_data = currency_data.get('visa') or {}
        revolut_data = currency_data.get('revolut') or {}
        if 'originalValues' in visa_data:
            vals = visa_data['originalValues']
            entry['visa_rate'] = vals.get('fxRateVisa')
            entry['currency_name'] = vals.get('fromCurrencyName')
            benchmarks = vals.get('benchmarks', [])
            if benchmarks:
                entry['benchmark_rate'] = benchmarks[0].get('benchmarkFxRate')
                entry['visa_markup'] = benchmarks[0].get('markupWithoutAdditionalFee')
        if revolut_data and isinstance(revolut_data, dict) and 'rate' in revolut_data:
            try:
                entry['revolut_rate'] = revolut_data['rate']['rate']
            except (KeyError, TypeError):
                pass
        result[currency] = entry
    return jsonify(result)


@app.route('/log/view')
@rate_limit
def view_log():
    """Display the exchange rate log data."""
    if not LOG_FILE.exists():
        return "No log data yet."
    with open(LOG_FILE, 'r') as f:
        rows = list(csv.reader(f))
    return render_template('log.html', rows=rows)


# --- Startup ---

load_cache_from_disk()

# Start background fetcher thread (daemon so it dies with the main process)
_fetcher = threading.Thread(target=background_fetcher, daemon=True)
_fetcher.start()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=3000)
