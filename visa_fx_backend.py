from flask import Flask, jsonify, render_template_string, send_file
import requests
import time
import csv
import logging
from datetime import datetime
from urllib.parse import quote
import os
from collections import defaultdict
from pathlib import Path

# Fix SSL certificate verification in Docker
os.environ['REQUESTS_CA_BUNDLE'] = '/etc/ssl/certs/ca-certificates.crt'

app = Flask(__name__)
logger = logging.getLogger(__name__)

cache = {}
cache_timestamps = {}  # per-currency cache timestamps
TTL = 3 * 60 * 60  # 3 hours
LOG_FILE = Path(__file__).parent / 'data' / 'fx_log.csv'

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
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
    'user-agent': 'Mozilla/5.0',
}

REVOLUT_HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US,en;q=0.9',
    'dnt': '1',
    'referer': 'https://www.revolut.com/',
    'user-agent': 'Mozilla/5.0',
}

def fetch_visa_rate(to_currency):
    """Fetch exchange rate from Visa API."""
    today = datetime.now().strftime('%m/%d/%Y')
    url = f"https://usa.visa.com/cmsapi/fx/rates?amount=10000&fee=0&utcConvertedDate={quote(today)}&exchangedate={quote(today)}&fromCurr=USD&toCurr={to_currency}"
    response = requests.get(url, headers=VISA_HEADERS)
    response.raise_for_status()
    return response.json()

def fetch_revolut_rate(to_currency):
    """Fetch exchange rate from Revolut API."""
    url = f"https://www.revolut.com/api/exchange/quote?amount=100000&country=US&fromCurrency=USD&isRecipientAmount=false&toCurrency={to_currency}"
    response = requests.get(url, headers=REVOLUT_HEADERS)
    response.raise_for_status()
    return response.json()

def log_fx_rate(timestamp, currency, name, visa_rate, benchmark_rate, markup, revolut_rate=None):
    """Log exchange rate data to CSV file."""
    with open(LOG_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, currency, name, visa_rate, benchmark_rate, markup, revolut_rate or 'N/A'])


def load_logs():
    """Load historical markup data for trend analysis."""
    history = defaultdict(list)
    if not os.path.exists(LOG_FILE):
        return history
    with open(LOG_FILE, 'r') as f:
        for row in csv.reader(f):
            if len(row) >= 6:  # Updated to handle old and new CSV format
                _, code, _, _, _, markup = row[:6]
                try:
                    history[code].append(float(markup))
                except (ValueError, IndexError):
                    continue
    return history

def generate_sparkline(data):
    """Generate ASCII sparkline from data points."""
    bars = "▁▂▃▄▅▆▇█"
    if not data:
        return ""
    mi, ma = min(data), max(data)
    if mi == ma:
        return bars[0] * len(data)
    step = (ma - mi) / (len(bars) - 1)
    return ''.join(bars[min(len(bars)-1, int((val - mi) / step))] for val in data[-20:])

@app.route('/')
def index():
    now = int(time.time())
    most_recent_fetch = max(cache_timestamps.values()) if cache_timestamps else 0
    last_updated_str = datetime.fromtimestamp(most_recent_fetch).strftime('%Y-%m-%d %H:%M:%S') if most_recent_fetch else 'Never'
    rows = []
    history = load_logs()

    for currency in CURRENCIES:
        currency_last_fetched = cache_timestamps.get(currency, 0)
        should_refresh = f"{currency}_visa" not in cache or (now - currency_last_fetched) > TTL
        if should_refresh:
            visa_data = None
            revolut_data = None

            # Fetch Visa rate
            try:
                visa_data = fetch_visa_rate(currency)
                cache[f"{currency}_visa"] = visa_data
            except Exception as e:
                logger.warning("Failed to fetch Visa rate for %s: %s", currency, e)
                cache[f"{currency}_visa"] = {"error": str(e)}

            # Fetch Revolut rate
            try:
                revolut_data = fetch_revolut_rate(currency)
                cache[f"{currency}_revolut"] = revolut_data
            except Exception as e:
                logger.warning("Failed to fetch Revolut rate for %s: %s", currency, e)
                cache[f"{currency}_revolut"] = {"error": str(e)}

            cache_timestamps[currency] = now
            last_updated_str = datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S')

            # Log to CSV only when new data is fetched
            if visa_data and 'error' not in visa_data:
                try:
                    visa_rate = float(visa_data['originalValues']['fxRateVisa'])
                    currency_name = visa_data['originalValues']['fromCurrencyName']
                    benchmark = visa_data['originalValues']['benchmarks'][0]
                    benchmark_rate = float(benchmark['benchmarkFxRate'])
                    markup = float(benchmark['markupWithoutAdditionalFee']) * 100

                    revolut_rate = None
                    if revolut_data and 'error' not in revolut_data:
                        revolut_rate = float(revolut_data['rate']['rate'])

                    log_fx_rate(last_updated_str, currency, currency_name, visa_rate, benchmark_rate, markup, revolut_rate)
                except Exception as e:
                    logger.warning("Error logging data for %s: %s", currency, e)

        # Display data
        visa_data = cache.get(f"{currency}_visa", {})
        revolut_data = cache.get(f"{currency}_revolut", {})

        try:
            visa_rate = float(visa_data['originalValues']['fxRateVisa'])
            currency_name = visa_data['originalValues']['fromCurrencyName']
            benchmark = visa_data['originalValues']['benchmarks'][0]
            benchmark_rate = float(benchmark['benchmarkFxRate'])
            markup = float(benchmark['markupWithoutAdditionalFee']) * 100
            trend = generate_sparkline(history[currency] + [markup])

            # Get Revolut rate
            revolut_rate_str = 'N/A'
            if revolut_data and 'error' not in revolut_data:
                try:
                    revolut_rate = float(revolut_data['rate']['rate'])
                    revolut_rate_str = f"{revolut_rate:.6f}"
                except (KeyError, ValueError, TypeError):
                    revolut_rate_str = 'Error'

            rows.append((
                f"{FLAG_MAP.get(currency, '')} {currency}",
                currency_name,
                f"{visa_rate:.6f}",
                revolut_rate_str,
                f"{benchmark_rate:.6f}",
                f"{markup:.4f}%",
                trend
            ))
        except Exception:
            rows.append((currency, 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', ''))

    html = '''
    <!doctype html>
    <html>
    <head>
        <title>FX Rate Comparison</title>
        <style>
            body { font-family: sans-serif; padding: 20px; }
            table { border-collapse: collapse; width: 100%; max-width: 1200px; margin: auto; }
            th, td { border: 1px solid #ccc; padding: 8px 12px; text-align: center; }
            th { background-color: #f4f4f4; }
            footer { text-align: center; margin-top: 20px; color: #666; font-size: 0.9em; }
            .provider { font-weight: bold; }
        </style>
    </head>
    <body>
        <h1 style="text-align:center;">FX Rate Comparison: Visa vs Revolut</h1>
        <table>
            <tr>
                <th>Currency</th>
                <th>Currency Name</th>
                <th class="provider">Visa Rate</th>
                <th class="provider">Revolut Rate</th>
                <th>Benchmark Rate</th>
                <th>Visa Markup</th>
                <th>Trend</th>
            </tr>
            {% for row in rows %}
            <tr>
                <td>{{ row[0] }}</td>
                <td>{{ row[1] }}</td>
                <td>{{ row[2] }}</td>
                <td>{{ row[3] }}</td>
                <td>{{ row[4] }}</td>
                <td>{{ row[5] }}</td>
                <td>{{ row[6] }}</td>
            </tr>
            {% endfor %}
        </table>
        <footer>
            <p>Last updated: {{ last_updated }}</p>
            <p>
                <a href="/export/csv">Download CSV</a> |
                <a href="/export/json">Download JSON</a> |
                <a href="/log/view">View Log</a>
            </p>
        </footer>
    </body>
    </html>
    '''
    return render_template_string(html, rows=rows, last_updated=last_updated_str)

@app.route('/export/csv')
def export_csv():
    return send_file(LOG_FILE, mimetype='text/csv', as_attachment=True, download_name='fx_log.csv')

@app.route('/export/json')
def export_json():
    """Export current rates as JSON (filtered to essential fields only)."""
    result = {}
    for currency in CURRENCIES:
        entry = {}
        visa_data = cache.get(f"{currency}_visa", {})
        revolut_data = cache.get(f"{currency}_revolut", {})
        if 'originalValues' in visa_data:
            vals = visa_data['originalValues']
            entry['visa_rate'] = vals.get('fxRateVisa')
            entry['currency_name'] = vals.get('fromCurrencyName')
            benchmarks = vals.get('benchmarks', [])
            if benchmarks:
                entry['benchmark_rate'] = benchmarks[0].get('benchmarkFxRate')
                entry['visa_markup'] = benchmarks[0].get('markupWithoutAdditionalFee')
        if revolut_data and 'error' not in revolut_data:
            try:
                entry['revolut_rate'] = revolut_data['rate']['rate']
            except (KeyError, TypeError):
                pass
        result[currency] = entry
    return jsonify(result)

@app.route('/log/view')
def view_log():
    """Display the exchange rate log data."""
    if not os.path.exists(LOG_FILE):
        return "No log data yet."
    with open(LOG_FILE, 'r') as f:
        rows = list(csv.reader(f))
    html = '''
    <h2 style="text-align:center;">FX Rate Log</h2>
    <table border=1 style="margin:auto; border-collapse:collapse;">
        <tr>
            <th>Timestamp</th>
            <th>Currency</th>
            <th>Name</th>
            <th>Visa Rate</th>
            <th>Benchmark Rate</th>
            <th>Visa Markup %</th>
            <th>Revolut Rate</th>
        </tr>
        {% for row in rows %}
        <tr>
            {% for cell in row %}
            <td>{{ cell }}</td>
            {% endfor %}
            {% if row|length < 7 %}
            <td>N/A</td>
            {% endif %}
        </tr>
        {% endfor %}
    </table>
    <p style="text-align:center; margin-top:20px;">
        <a href="/">← Back to Main Page</a>
    </p>
    '''
    return render_template_string(html, rows=rows)

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=3000)
