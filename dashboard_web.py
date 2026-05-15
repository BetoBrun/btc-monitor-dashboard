"""
BTC Monitor Dashboard — Noobshark V1.2
Flask app with Binance data + crypto-signals API + RSI/MACD indicators.
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, render_template_string, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Config
SYMBOL = "BTCUSDT"
STATE_FILE = Path(__file__).parent / "monitor_state.json"
LOG_FILE = Path(__file__).parent / "monitor.log"
ALERT_COOLDOWN_SEC = 4 * 60 * 60

# Noobshark levels
LEVELS = {
    "MM200D": 82300,
    "Reteste Zone": 82000,
    "Support Zone": 79200,
    "Asia Low": 78700,
    "Gap CME": 77500,
}


def get_price():
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={SYMBOL}"
        r = requests.get(url, timeout=10)
        return float(r.json()["price"])
    except Exception as e:
        log.error(f"Price error: {e}")
        return None


def get_24h_stats():
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={SYMBOL}"
        r = requests.get(url, timeout=10)
        data = r.json()
        return {
            "change": float(data["priceChangePercent"]),
            "high": float(data["highPrice"]),
            "low": float(data["lowPrice"]),
            "volume": float(data["quoteVolume"]),
        }
    except Exception as e:
        log.error(f"24h stats error: {e}")
        return None


def get_signal():
    """Fetch BTC signal from crypto-signal-api (free, no API key)."""
    try:
        url = f"http://localhost:3100/api/v1/signal/{SYMBOL}?interval=1h"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass

    # Fallback: compute basic signal from Binance data
    try:
        # Get RSI from Binance klines
        klines_url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval=1h&limit=14"
        r = requests.get(klines_url, timeout=10)
        closes = [float(c[4]) for c in r.json()]

        # Simple RSI
        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))

        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))

        price = closes[-1]

        # Determine signal
        if rsi < 30:
            action = "BUY"
            strength = "strong"
            confidence = min(90, 100 - rsi)
        elif rsi > 70:
            action = "SELL"
            strength = "strong"
            confidence = min(90, rsi)
        else:
            action = "HOLD"
            strength = "moderate"
            confidence = 50

        return {
            "signal": {
                "action": action,
                "strength": strength,
                "confidence": round(confidence, 1),
                "score": 2 if action == "BUY" else -2 if action == "SELL" else 0,
            },
            "indicators": {
                "price": price,
                "rsi": round(rsi, 1),
            }
        }
    except Exception as e:
        log.error(f"Signal computation error: {e}")
        return None


def get_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_triggered": {}}


def get_cooldown_remaining(alert_id: str) -> int:
    state = get_state()
    last = state.get("last_triggered", {}).get(alert_id, 0)
    if last == 0:
        return 0
    remaining = ALERT_COOLDOWN_SEC - (datetime.now().timestamp() - last)
    return max(0, remaining)


def get_recent_logs(lines: int = 20) -> list:
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE) as f:
            return [l.strip() for l in f.readlines()[-lines:] if l.strip()]
    except Exception:
        return []


def price_status(price: float) -> str:
    if price >= LEVELS["MM200D"]:
        return "bullish"
    elif price <= LEVELS["Gap CME"]:
        return "bearish"
    elif price >= LEVELS["Reteste Zone"]:
        return "resistance"
    elif price <= LEVELS["Support Zone"]:
        return "support"
    return "neutral"


def signal_color(action: str) -> str:
    return {"BUY": "#00e676", "SELL": "#ff1744", "HOLD": "#ffd600"}.get(action, "#888")


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BTC Monitor — Noobshark V1.2</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0f;
            color: #e8e8f0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1100px; margin: 0 auto; }
        h1 { text-align: center; color: #ffd600; margin-bottom: 25px; font-size: 1.8em; }
        .price-card {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            border-radius: 16px;
            padding: 30px;
            text-align: center;
            margin-bottom: 20px;
            border: 1px solid #2a2a4a;
        }
        .price-label { color: #888; font-size: 0.9em; margin-bottom: 5px; }
        .price { font-size: 3em; font-weight: bold; color: {{ price_color }}; }
        .change { font-size: 1.1em; margin-top: 8px; color: {{ change_color }}; }
        .signal-badge {
            display: inline-block;
            padding: 10px 25px;
            border-radius: 25px;
            margin-top: 15px;
            font-weight: bold;
            font-size: 1.1em;
        }
        .signal-buy { background: #00e676; color: #000; }
        .signal-sell { background: #ff1744; color: #fff; }
        .signal-hold { background: #ffd600; color: #000; }
        .signal-confidence { font-size: 0.8em; margin-top: 5px; color: #aaa; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 15px; }
        .card {
            background: #12121c;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #2a2a4a;
        }
        .card h3 {
            color: #ffd600;
            margin-bottom: 15px;
            font-size: 0.95em;
            border-bottom: 1px solid #2a2a4a;
            padding-bottom: 10px;
        }
        .level-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #1a1a2e; }
        .level-name { color: #aaa; }
        .level-price { font-weight: bold; }
        .level-active { color: #00e676 !important; }
        .alert-item { padding: 10px; border-radius: 8px; margin-bottom: 8px; font-size: 0.85em; }
        .alert-critical { background: rgba(255, 23, 68, 0.2); border-left: 3px solid #ff1744; }
        .alert-high { background: rgba(255, 145, 0, 0.2); border-left: 3px solid #ff9100; }
        .alert-normal { background: rgba(41, 121, 255, 0.2); border-left: 3px solid #2979ff; }
        .alert-id { color: #ffd600; font-weight: bold; }
        .alert-cooldown { color: #888; font-size: 0.8em; }
        .indicator-row { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #1a1a2e; }
        .indicator-name { color: #aaa; }
        .indicator-value { font-weight: bold; color: #fff; }
        .indicator-rsi { color: {% if rsi_value < 30 %}#00e676{% elif rsi_value > 70 %}#ff1744{% else %}#ffd600{% endif %}; }
        .timestamp { text-align: center; color: #555; font-size: 0.75em; margin-top: 20px; }
        .refresh-btn {
            display: block;
            margin: 15px auto;
            padding: 12px 30px;
            background: #ffd600;
            color: #000;
            border: none;
            border-radius: 8px;
            font-weight: bold;
            cursor: pointer;
        }
        .refresh-btn:hover { background: #ffeb3b; }
        .log-entry { font-family: monospace; font-size: 0.75em; padding: 4px 0; color: #666; }
        .log-alert { color: #00e676; }
        .status-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 15px;
            font-size: 0.85em;
            font-weight: bold;
            margin-top: 8px;
        }
        .status-bullish { background: #00e676; color: #000; }
        .status-bearish { background: #ff1744; color: #fff; }
        .status-resistance { background: #ff9100; color: #000; }
        .status-support { background: #2979ff; color: #fff; }
        .status-neutral { background: #555; color: #fff; }
    </style>
    <meta http-equiv="refresh" content="60">
</head>
<body>
    <div class="container">
        <h1>BTC Monitor — Noobshark V1.2</h1>

        <div class="price-card">
            <div class="price-label">BTCUSDT</div>
            <div class="price">${{ "{:,.0f}".format(price) if price else "—" }}</div>
            {% if stats %}
            <div class="change">{{ "+" if stats.change >= 0 else "" }}{{ "%.2f"|format(stats.change) }}% (24h) | High: ${{ "{:,.0f}".format(stats.high) }} | Low: ${{ "{:,.0f}".format(stats.low) }}</div>
            {% endif %}
            <div class="status-badge status-{{ status }}">{{ status.upper() }}</div>
        </div>

        {% if signal_data and signal_data.signal %}
        <div class="price-card" style="padding: 20px;">
            <div style="font-size: 0.9em; color: #888;">SINAL RSI (1h)</div>
            <div class="signal-badge signal-{{ signal_data.signal.action.lower() }}">
                {{ signal_data.signal.action }} — {{ signal_data.signal.strength.upper() }}
            </div>
            <div class="signal-confidence">Confianca: {{ signal_data.signal.confidence }}%</div>
        </div>
        {% endif %}

        <div class="grid">
            <div class="card">
                <h3>📊 Niveis Noobshark</h3>
                {% for name, value in levels.items() %}
                <div class="level-row">
                    <span class="level-name">{{ name }}</span>
                    <span class="level-price {{ 'level-active' if is_near(price, value) else '' }}">${{ "{:,.0f}".format(value) }}</span>
                </div>
                {% endfor %}
            </div>

            <div class="card">
                <h3>📈 Indicadores</h3>
                {% if signal_data and signal_data.indicators %}
                <div class="indicator-row">
                    <span class="indicator-name">RSI 14</span>
                    <span class="indicator-value indicator-rsi" data-rsi="{{ signal_data.indicators.rsi }}">{{ signal_data.indicators.rsi }}</span>
                </div>
                {% endif %}
                <div class="indicator-row">
                    <span class="indicator-name">Preco Atual</span>
                    <span class="indicator-value">${{ "{:,.0f}".format(price) if price else "—" }}</span>
                </div>
                {% if stats %}
                <div class="indicator-row">
                    <span class="indicator-name">Volume 24h</span>
                    <span class="indicator-value">${{ "{:,.0f}".format(stats.volume / 1e9)[:4] }}B</span>
                </div>
                {% endif %}
            </div>

            <div class="card">
                <h3>🚨 Alertas Ativos</h3>
                {% for alert in alerts %}
                <div class="alert-item alert-{{ alert.priority }}">
                    <div><span class="alert-id">{{ alert.id }}</span> — {{ alert.description }}</div>
                    {% if alert.cooldown > 0 %}
                    <div class="alert-cooldown">Cooldown: {{ "%.0f"|format(alert.cooldown/60) }} min</div>
                    {% else %}
                    <div class="alert-cooldown" style="color:#00e676">ATIVO</div>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </div>

        <div class="card">
            <h3>📜 Log do Monitor</h3>
            {% for entry in logs %}
            <div class="log-entry {{ 'log-alert' if 'Alerta' in entry or 'disparado' in entry else '' }}">{{ entry }}</div>
            {% endfor %}
        </div>

        <button class="refresh-btn" onclick="location.reload()">🔄 Atualizar</button>

        <div class="timestamp">
            Atualizado: {{ timestamp }} | BTC Monitor V1.2 — Noobshark | Proxima atualizacao em 60s
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def index():
    price = get_price()
    stats = get_24h_stats()
    signal_data = get_signal()
    status = price_status(price) if price else "neutral"

    price_color = "#00e676" if status == "bullish" else "#ff1744" if status == "bearish" else "#ffd600"
    change_color = "#00e676" if stats and stats["change"] >= 0 else "#ff1744" if stats else "#888"

    alerts = [
        {"id": "break_mm200_up", "description": "BTC ROMPEU MM200D ($82.300)", "priority": "critical", "cooldown": get_cooldown_remaining("break_mm200_up")},
        {"id": "break_range_down", "description": "BTC PERDEU $79.000", "priority": "critical", "cooldown": get_cooldown_remaining("break_range_down")},
        {"id": "approach_resistance", "description": "BTC em $81.800-$82.300", "priority": "high", "cooldown": get_cooldown_remaining("approach_resistance")},
        {"id": "approach_support", "description": "BTC em $79.000-$79.300", "priority": "high", "cooldown": get_cooldown_remaining("approach_support")},
        {"id": "volatility_spike", "description": "Volatilidade anormal", "priority": "high", "cooldown": get_cooldown_remaining("volatility_spike")},
    ]

    logs = get_recent_logs(20)
    rsi_value = signal_data.get("indicators", {}).get("rsi", 50) if signal_data else 50

    def is_near(price, level, tolerance=500):
        return price and abs(price - level) < tolerance

    return render_template_string(
        HTML_TEMPLATE,
        price=price,
        stats=stats,
        signal_data=signal_data,
        status=status,
        price_color=price_color,
        change_color=change_color,
        levels=LEVELS,
        alerts=alerts,
        logs=logs,
        is_near=is_near,
        rsi_value=rsi_value,
        timestamp=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    )


@app.route("/api/status")
def api_status():
    price = get_price()
    stats = get_24h_stats()
    signal_data = get_signal()
    state = get_state()
    return jsonify({
        "price": price,
        "status": price_status(price) if price else None,
        "24h_change": stats["change"] if stats else None,
        "24h_high": stats["high"] if stats else None,
        "24h_low": stats["low"] if stats else None,
        "signal": signal_data.get("signal") if signal_data else None,
        "rsi": signal_data.get("indicators", {}).get("rsi") if signal_data else None,
        "last_alerts": state.get("last_triggered", {}),
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "btc-monitor-v1.2"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)