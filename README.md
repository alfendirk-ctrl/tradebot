# ₿ TradeBot — OKX Price Action Bot

Een live Bitcoin trading bot voor OKX met een React dashboard.

---

## 🏗 Structuur

```
bot/
├── bot.py           # Price action strategie + trade logica
├── api.py           # FastAPI server (REST endpoints)
├── requirements.txt
├── Procfile         # Railway start commando
├── .env.example     # API keys template
└── dashboard/       # React monitoring dashboard
    └── src/App.jsx
```

---

## 🚀 Setup

### 1. OKX API keys aanmaken
1. Ga naar OKX → Account → API Management
2. Maak een nieuwe API key aan met **Trade** permissies
3. Noteer: API Key, Secret, Passphrase

### 2. Python bot (lokaal testen)
```bash
pip install -r requirements.txt
cp .env.example .env
# Vul .env in met je OKX keys
# Zet OKX_SANDBOX=true voor demo trading eerst!

uvicorn api:app --reload
```
Bot API draait op http://localhost:8000

### 3. Railway deployment
1. Push naar GitHub
2. Nieuw Railway project → "Deploy from GitHub repo"
3. Voeg environment variables toe in Railway dashboard:
   - `OKX_API_KEY`
   - `OKX_SECRET`
   - `OKX_PASSPHRASE`
   - `OKX_SANDBOX=false` (voor live)

### 4. Dashboard
```bash
cd dashboard
npm install
VITE_API_URL=https://jouw-railway-url.railway.app npm run dev
```

---

## 📊 Strategie — Price Action

De bot detecteert setups op basis van:

| Signaal | Conditie |
|---|---|
| **Bullish Pin Bar** | Lange lower wick (≥2× body), bij swing low |
| **Bearish Pin Bar** | Lange upper wick (≥2× body), bij swing high |
| **Bullish Engulfing** | Bearish candle volledig omsloten door bullish candle |
| **Bearish Engulfing** | Bullish candle volledig omsloten door bearish candle |
| **Volume filter** | Huidige volume ≥ 1.5× 20-periode gemiddelde |

**Risk Management:**
- Stop Loss: 1.5× ATR(14) van entry
- Take Profit: 3.0× ATR(14) van entry → Risk:Reward = 1:2
- Position size: automatisch op basis van % risico per trade

---

## ⚠️ Disclaimer

Dit is educatieve software. Gebruik eerst **sandbox mode** (OKX_SANDBOX=true).
Live trading brengt financieel risico met zich mee.
