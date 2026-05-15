"""
BTC Monitor — Sistema de alertas baseado no playbook Noobshark V1.1

Roda em loop, busca preço BTCUSDT da Binance API, avalia condições configuradas,
e dispara alertas via Telegram quando gatilhos forem acionados.

Requisitos:
    pip install requests python-dotenv

Setup:
    1. Criar bot Telegram via @BotFather → pegar TOKEN
    2. Mandar mensagem pro seu bot → pegar CHAT_ID via:
       https://api.telegram.org/bot<TOKEN>/getUpdates
    3. Criar arquivo .env (ver .env.example)
    4. python btc_monitor.py

Uso típico:
    Deixar rodando em terminal separado ou tmux/screen.
    Os alertas chegam direto no Telegram quando condições baterem.
    Cada alerta dispara uma vez por dia (cooldown configurável).
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable

import requests
from dotenv import load_dotenv

# ========================================================================
# CONFIGURAÇÃO
# ========================================================================

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SYMBOL = "BTCUSDT"
POLL_INTERVAL_SEC = 60  # checar a cada 1 min
STATE_FILE = Path(__file__).parent / "monitor_state.json"
LOG_FILE = Path(__file__).parent / "monitor.log"

# Cooldown por alerta (segundos) — evita spam quando preço fica oscilando no nível
ALERT_COOLDOWN_SEC = 4 * 60 * 60  # 4 horas

# ========================================================================
# LOGGING
# ========================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ========================================================================
# ALERTAS — definição declarativa
# ========================================================================
# Cada alerta tem:
#   - id: identificador único (usado pra cooldown)
#   - description: o que está acontecendo
#   - condition: função (price, candles) → bool
#   - action_text: o que fazer quando disparar
#   - priority: "critical" | "high" | "normal"


@dataclass
class Alert:
    id: str
    description: str
    condition: Callable[[float, list], bool]
    action_text: str
    priority: str = "normal"
    last_triggered: Optional[float] = None  # timestamp unix


# Os níveis abaixo refletem a análise Noobshark de 15/mai/26.
# AJUSTAR conforme o gráfico evolui. Cada alerta é editável.

ALERTS: list[Alert] = [
    Alert(
        id="break_mm200_up",
        description="🚀 BTC ROMPEU MM200D ($82.300) PRA CIMA",
        condition=lambda price, _: price > 82_300,
        action_text=(
            "Setup LONG potencial ativado.\n"
            "PRÓXIMOS PASSOS:\n"
            "1. Abrir gráfico 4h\n"
            "2. Esperar RETESTE do nível $82.000-$82.300\n"
            "3. Se formar rejeição válida (Bloco 3 Noobshark):\n"
            "   - Entrada: $82.300\n"
            "   - Stop: $81.500 (abaixo do reteste)\n"
            "   - TP1: $84.000 (zona heatmap)\n"
            "   - R:R ~2.1\n"
            "4. NÃO entrar no rompimento direto. Esperar reteste."
        ),
        priority="critical",
    ),
    Alert(
        id="break_range_down",
        description="🔻 BTC PERDEU $79.000 — RANGE QUEBRADO",
        condition=lambda price, _: price < 79_000,
        action_text=(
            "Continuação bearish ativada.\n"
            "PRÓXIMOS ALVOS:\n"
            "- $78.700 (Asia Low)\n"
            "- $78.000 (suporte psicológico)\n"
            "- $77.500 (gap CME)\n\n"
            "AÇÃO:\n"
            "1. NÃO comprar a faca\n"
            "2. Aguardar formação em $78k pra avaliar long\n"
            "3. Stack core: ZERO ação (você é holder)\n"
            "4. Cash USDT: manter parado"
        ),
        priority="critical",
    ),
    Alert(
        id="approach_resistance",
        description="⚠️ BTC APROXIMANDO MM200D ($82.000)",
        condition=lambda price, _: 81_800 <= price < 82_300,
        action_text=(
            "Zona de decisão. Próximos candles definem direção.\n"
            "ATENÇÃO:\n"
            "- MM200D foi rejeitada 5x no mês\n"
            "- Sem volume comprador forte, provavelmente rejeita de novo\n"
            "- Observar Coinbase delta no CoinGlass\n"
            "- Observar volume SPOT (não perp)\n\n"
            "NÃO ENTRAR ANTES DA DEFINIÇÃO."
        ),
        priority="high",
    ),
    Alert(
        id="approach_support",
        description="⚠️ BTC APROXIMANDO SUPORTE $79.000",
        condition=lambda price, _: 79_000 < price <= 79_300,
        action_text=(
            "Zona de defesa crítica.\n"
            "OBSERVAR:\n"
            "- Formação de candle de defesa (pin/engolfo)\n"
            "- Volume spot aumentando\n"
            "- 100eyes Abnormal Volatility ativa?\n\n"
            "POSSÍVEL SETUP LONG se defender com:\n"
            "- Score Noobshark >= 6\n"
            "- R:R >= 1.5"
        ),
        priority="high",
    ),
    Alert(
        id="volatility_spike",
        description="📊 VOLATILIDADE ANORMAL DETECTADA",
        condition=lambda price, candles: _is_volatility_spike(candles),
        action_text=(
            "Range dos últimos candles 15min > 2x média.\n"
            "Geralmente precede ou indica movimento direcional.\n"
            "ABRIR GRÁFICO E AVALIAR."
        ),
        priority="high",
    ),
    Alert(
        id="heartbeat_4h",
        description="💚 HEARTBEAT 4H — Status do mercado",
        condition=lambda _, __: _is_heartbeat_time(),
        action_text="Monitor ativo. Sem disparos críticos nas últimas 4h.",
        priority="normal",
    ),
]


# ========================================================================
# FUNÇÕES DE MERCADO
# ========================================================================


def fetch_price() -> Optional[float]:
    """Busca preço atual BTCUSDT da Binance."""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={SYMBOL}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as e:
        log.error(f"Falha ao buscar preço: {e}")
        return None


def fetch_candles(interval: str = "15m", limit: int = 20) -> Optional[list]:
    """
    Busca candles recentes da Binance.

    Retorna lista de dicts: [{open, high, low, close, volume, timestamp}, ...]
    """
    try:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={SYMBOL}&interval={interval}&limit={limit}"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        raw = r.json()
        return [
            {
                "timestamp": c[0],
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            }
            for c in raw
        ]
    except Exception as e:
        log.error(f"Falha ao buscar candles: {e}")
        return None


# ========================================================================
# CONDIÇÕES ESPECIAIS
# ========================================================================


def _is_volatility_spike(candles: list) -> bool:
    """Detecta range do último candle > 2x média dos 20 anteriores."""
    if not candles or len(candles) < 20:
        return False
    ranges = [c["high"] - c["low"] for c in candles[-20:]]
    last_range = ranges[-1]
    avg_range = sum(ranges[:-1]) / 19
    return last_range > 2.0 * avg_range


def _is_heartbeat_time() -> bool:
    """Dispara heartbeat a cada 4h em horários redondos."""
    now = datetime.now(timezone.utc)
    return now.hour % 4 == 0 and now.minute < 2


# ========================================================================
# TELEGRAM
# ========================================================================


def send_telegram(message: str, priority: str = "normal") -> bool:
    """Envia mensagem via Telegram. Retorna True se sucesso."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram não configurado. Mensagem não enviada.")
        log.warning(f"Mensagem que seria enviada:\n{message}")
        return False

    try:
        # disable_notification para heartbeats; som pra crítico
        silent = priority == "normal"
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_notification": silent,
        }
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Falha ao enviar Telegram: {e}")
        return False


def format_alert_message(alert: Alert, price: float) -> str:
    """Formata mensagem pro Telegram com HTML."""
    timestamp = datetime.now().strftime("%d/%m %H:%M")
    priority_emoji = {
        "critical": "🚨",
        "high": "⚠️",
        "normal": "ℹ️",
    }.get(alert.priority, "")

    return (
        f"{priority_emoji} <b>{alert.description}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 BTC: <b>${price:,.0f}</b>\n"
        f"🕐 {timestamp}\n\n"
        f"<b>AÇÃO:</b>\n{alert.action_text}\n\n"
        f"<i>Alerta ID: {alert.id}</i>"
    )


# ========================================================================
# ESTADO PERSISTENTE
# ========================================================================


def load_state() -> dict:
    """Carrega estado salvo (cooldowns dos alertas)."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Falha ao carregar estado: {e}")
    return {"last_triggered": {}}


def save_state(state: dict) -> None:
    """Salva estado em disco."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error(f"Falha ao salvar estado: {e}")


# ========================================================================
# LOOP PRINCIPAL
# ========================================================================


def evaluate_alerts(price: float, candles: list, state: dict) -> None:
    """Avalia todos os alertas, dispara os que bateram (respeitando cooldown)."""
    now = time.time()
    last = state.setdefault("last_triggered", {})

    for alert in ALERTS:
        try:
            triggered = alert.condition(price, candles)
        except Exception as e:
            log.error(f"Erro avaliando alerta {alert.id}: {e}")
            continue

        if not triggered:
            continue

        # Cooldown check
        last_time = last.get(alert.id, 0)
        elapsed = now - last_time
        if elapsed < ALERT_COOLDOWN_SEC:
            log.debug(
                f"Alerta {alert.id} em cooldown "
                f"(faltam {(ALERT_COOLDOWN_SEC - elapsed) / 60:.0f} min)"
            )
            continue

        # DISPARA
        msg = format_alert_message(alert, price)
        success = send_telegram(msg, priority=alert.priority)
        if success:
            last[alert.id] = now
            log.info(f"[OK] Alerta disparado: {alert.id} (price={price})")
        else:
            log.warning(f"[X] Alerta {alert.id} bateu mas envio falhou")

    save_state(state)


def main() -> None:
    log.info("=" * 50)
    log.info("BTC Monitor — Noobshark V1.1 — iniciado")
    log.info(f"Símbolo: {SYMBOL}")
    log.info(f"Poll: {POLL_INTERVAL_SEC}s")
    log.info(f"Cooldown: {ALERT_COOLDOWN_SEC / 3600:.1f}h")
    log.info(f"Alertas ativos: {len(ALERTS)}")
    log.info("=" * 50)

    # Validar config
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("⚠️ Telegram não configurado. Rodando em modo log-only.")
        log.warning("Configure TELEGRAM_TOKEN e TELEGRAM_CHAT_ID no .env")

    # Ping inicial
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        send_telegram(
            "🟢 <b>BTC Monitor iniciado</b>\n"
            f"Vigiando {len(ALERTS)} condições.\n"
            "Você receberá alertas quando gatilhos baterem.",
            priority="normal",
        )

    state = load_state()

    while True:
        try:
            price = fetch_price()
            if price is None:
                time.sleep(POLL_INTERVAL_SEC)
                continue

            candles = fetch_candles("15m", 20)
            if candles is None:
                candles = []

            log.info(f"BTC: ${price:,.2f}")
            evaluate_alerts(price, candles, state)

            time.sleep(POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            log.info("Monitor encerrado pelo usuário.")
            if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
                send_telegram("🔴 <b>BTC Monitor encerrado</b>", priority="normal")
            break
        except Exception as e:
            log.error(f"Erro no loop principal: {e}", exc_info=True)
            time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
