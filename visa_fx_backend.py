from flask import Flask, jsonify, request, render_template_string, send_file
import requests
import time
import csv
from datetime import datetime
from urllib.parse import quote
import os
from collections import defaultdict
from pathlib import Path

# Fix SSL certificate verification in Docker
os.environ['REQUESTS_CA_BUNDLE'] = '/etc/ssl/certs/ca-certificates.crt'

app = Flask(__name__)

cache = {}
last_fetched = 0
TTL = 3 * 60 * 60  # 3 hours
LOG_FILE = 'data/fx_log.csv'

if not Path(LOG_FILE).exists():
    Path(LOG_FILE).touch()

CURRENCIES = ['JPY', 'EUR', 'GBP', 'THB', 'CAD', 'AUD', 'INR', 'MXN', 'CHF', 'CNY', 'SEK', 'NZD']
FLAG_MAP = {
    'JPY': '🇯🇵', 'EUR': '🇪🇺', 'GBP': '🇬🇧', 'THB': '🇹🇭', 'CAD': '🇨🇦',
    'AUD': '🇦🇺', 'INR': '🇮🇳', 'MXN': '🇲🇽', 'CHF': '🇨🇭', 'CNY': '🇨🇳',
    'SEK': '🇸🇪', 'NZD': '🇳🇿'
}

HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US,en;q=0.9',
    'dnt': '1',
    'referer': 'https://usa.visa.com/support/consumer/travel-support/exchange-rate-calculator.html',
    'user-agent': 'Mozilla/5.0',
}

def fetch_visa_rate(to_currency):
    today = datetime.now().strftime('%m/%d/%Y')
    url = f"https://usa.visa.com/cmsapi/fx/rates?amount=10000&fee=0&utcConvertedDate={quote(today)}&exchangedate={quote(today)}&fromCurr=USD&toCurr={to_currency}"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()

def log_fx_rate(timestamp, currency, name, visa_rate, benchmark_rate, markup):
    with open(LOG_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, currency, name, visa_rate, benchmark_rate, markup])

def load_logs():
    history = defaultdict(list)
    if not os.path.exists(LOG_FILE):
        return history
    with open(LOG_FILE, 'r') as f:
        for row in csv.reader(f):
            if len(row) == 6:
                _, code, _, _, _, markup = row
                try:
                    history[code].append(float(markup))
                except:
                    continue
    return history

def generate_sparkline(data):
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
    global last_fetched
    now = int(time.time())
    last_updated_str = datetime.fromtimestamp(last_fetched).strftime('%Y-%m-%d %H:%M:%S') if last_fetched else 'Never'
    rows = []
    history = load_logs()

    for currency in CURRENCIES:
        should_refresh = currency not in cache or (now - last_fetched) > TTL
        if should_refresh:
            try:
                data = fetch_visa_rate(currency)
                cache[currency] = data
                last_fetched = now
                last_updated_str = datetime.fromtimestamp(last_fetched).strftime('%Y-%m-%d %H:%M:%S')

                # Log to CSV only when new data is fetched
                visa_rate = float(data['originalValues']['fxRateVisa'])
                currency_name = data['originalValues']['fromCurrencyName']
                benchmark = data['originalValues']['benchmarks'][0]
                benchmark_rate = float(benchmark['benchmarkFxRate'])
                markup = float(benchmark['markupWithoutAdditionalFee']) * 100
                log_fx_rate(last_updated_str, currency, currency_name, visa_rate, benchmark_rate, markup)
            except Exception as e:
                cache[currency] = {"error": str(e)}

        data = cache[currency]
        try:
            visa_rate = float(data['originalValues']['fxRateVisa'])
            currency_name = data['originalValues']['fromCurrencyName']
            benchmark = data['originalValues']['benchmarks'][0]
            benchmark_rate = float(benchmark['benchmarkFxRate'])
            markup = float(benchmark['markupWithoutAdditionalFee']) * 100
            trend = generate_sparkline(history[currency] + [markup])
            rows.append((
                f"{FLAG_MAP.get(currency, '')} {currency}",
                currency_name,
                f"{visa_rate:.6f}",
                f"{benchmark_rate:.6f}",
                f"{markup:.4f}%",
                trend
            ))
        except Exception:
            rows.append((currency, 'N/A', 'N/A', 'N/A', 'N/A', ''))

    html = '''
    <!doctype html>
    <html>
    <head>
        <title>Visa FX Tracker</title>
        <style>
            body { font-family: sans-serif; padding: 20px; }
            table { border-collapse: collapse; width: 100%; max-width: 1000px; margin: auto; }
            th, td { border: 1px solid #ccc; padding: 8px 12px; text-align: center; }
            th { background-color: #f4f4f4; }
            footer { text-align: center; margin-top: 20px; color: #666; font-size: 0.9em; }
        </style>
    </head>
    <body>
        <h1 style="text-align:center;">Visa FX Rate Tracker</h1>
        <table>
            <tr><th>Currency</th><th>Currency Name</th><th>Visa Rate</th><th>Benchmark Rate</th><th>Markup</th><th>Trend</th></tr>
            {% for row in rows %}
            <tr>
                <td>{{ row[0] }}</td>
                <td>{{ row[1] }}</td>
                <td>{{ row[2] }}</td>
                <td>{{ row[3] }}</td>
                <td>{{ row[4] }}</td>
                <td>{{ row[5] }}</td>
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
    return send_file(LOG_FILE, mimetype='text/csv', as_attachment=True)

@app.route('/export/json')
def export_json():
    return jsonify(cache)

@app.route('/log/view')
def view_log():
    if not os.path.exists(LOG_FILE):
        return "No log data yet."
    with open(LOG_FILE, 'r') as f:
        rows = list(csv.reader(f))
    html = '''
    <h2 style="text-align:center;">FX Log</h2>
    <table border=1 style="margin:auto; border-collapse:collapse;">
        <tr><th>Timestamp</th><th>Currency</th><th>Name</th><th>Visa</th><th>Benchmark</th><th>Markup %</th></tr>
        {% for row in rows %}
        <tr>{% for cell in row %}<td>{{ cell }}</td>{% endfor %}</tr>
        {% endfor %}
    </table>
    '''
    return render_template_string(html, rows=rows)

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=3000)
