# BTC Monitor — Noobshark V1.2

Monitor de BTC com alertas Telegram + Dashboard web online.

## Funcionalidades

- **Preço BTCUSDT** em tempo real (Binance API)
- **RSI 14** calculado automaticamente (1h)
- **Níveis Noobshark:** MM200D, Reteste Zone, Support, Asia Low, Gap CME
- **Alertas Telegram:** rompimento, suporte, resistência, volatilidade
- **Dashboard web:** accessible de qualquer lugar

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
# Editar .env com TELEGRAM_TOKEN e TELEGRAM_CHAT_ID

# Rodar monitor (alertas Telegram)
python btc_monitor.py

# Rodar dashboard web
python dashboard_web.py
```

## Deploy Online

### Railway (recomendado)

1. Fork/copy este repo
2. Conecte no [Railway](https://railway.app)
3. Deploy automático via GitHub
4. Adicione secrets: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`

### Render

1. Fork/copy este repo
2. Conecte no [Render](https://render.com)
3. Upload `render.yaml`
4. Adicione environment variables

## Endpoints

- `/` — Dashboard web
- `/api/status` — JSON status
- `/health` — Health check

## Níveis Noobshark (15/mai/26)

| Nível | Preço |
|-------|-------|
| MM200D | $82,300 |
| Reteste Zone | $82,000 |
| Support Zone | $79,200 |
| Asia Low | $78,700 |
| Gap CME | $77,500 |

## Estrutura

```
btc_monitor_package/
├── btc_monitor.py        # Monitor + alertas Telegram
├── dashboard_web.py     # Dashboard Flask
├── requirements.txt     # Dependências
├── .env.example          # Template
├── Dockerfile            # Para deploy
├── railway.json          # Config Railway
├── render.yaml           # Config Render
└── .github/workflows/    # GitHub Actions
```