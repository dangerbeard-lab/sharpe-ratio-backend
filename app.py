from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
from datetime import datetime, timedelta
import logging
import json

app = Flask(__name__)
CORS(app, origins="*")  # Enable CORS for all origins

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Keys - These will be set as environment variables in Render
ALPHA_VANTAGE_KEY = os.environ.get('ALPHA_VANTAGE_KEY', 'WNADQXZP5A8MN1WP')
COINDESK_API_KEY = os.environ.get('COINDESK_API_KEY', 'b4d0bccb7c6ee3d278430470f5a1a7052ae1a398283a9fc882fdad3426e2705b')

# Enhanced cache with TTL
cache = {}
cache_ttl = {
    'bitcoin': 60,  # 1 minute for crypto
    'stock': 300,    # 5 minutes for stocks
    'fx': 3600       # 1 hour for FX rates
}

def get_cached_value(key, category='stock'):
    """Get cached value if still valid"""
    if key in cache:
        cached_time, cached_data = cache[key]
        ttl = cache_ttl.get(category, 300)
        if (datetime.now() - cached_time).seconds < ttl:
            return cached_data
    return None

def set_cache(key, value):
    """Set cache value with timestamp"""
    cache[key] = (datetime.now(), value)

@app.route('/')
def home():
    return jsonify({
        "status": "ok",
        "message": "Sharpe Ratio Tracker API is running",
        "version": "1.1.0",
        "endpoints": {
            "/api/bitcoin": "Get Bitcoin price in AUD",
            "/api/stock/<symbol>": "Get stock price",
            "/api/fx/<from_currency>/<to_currency>": "Get exchange rate",
            "/api/portfolio": "Get all portfolio prices (POST)",
            "/api/health": "Health check"
        }
    })

@app.route('/api/bitcoin')
def get_bitcoin_price():
    """Fetch Bitcoin price in AUD from multiple sources"""
    
    # Check cache first
    cached_price = get_cached_value('bitcoin_aud', 'bitcoin')
    if cached_price:
        logger.info(f"Returning cached Bitcoin price: {cached_price}")
        return jsonify(cached_price)
    
    # Try CoinGecko first (most reliable, no API key needed)
    try:
        response = requests.get(
            'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=aud',
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            price = data['bitcoin']['aud']
            result = {"price": price, "source": "CoinGecko"}
            set_cache('bitcoin_aud', result)
            logger.info(f"Bitcoin price from CoinGecko: {price} AUD")
            return jsonify(result)
    except Exception as e:
        logger.error(f"CoinGecko API error: {e}")
    
    # Try CoinDesk API
    try:
        headers = {'X-API-KEY': COINDESK_API_KEY}
        response = requests.get(
            'https://api.coindesk.com/v2/tb/price/ticker?assets=BTC&currency=AUD',
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'BTC' in data['data']:
                price = float(data['data']['BTC']['price'])
                result = {"price": price, "source": "CoinDesk"}
                set_cache('bitcoin_aud', result)
                logger.info(f"Bitcoin price from CoinDesk: {price} AUD")
                return jsonify(result)
    except Exception as e:
        logger.error(f"CoinDesk API error: {e}")
    
    # Fallback to Alpha Vantage
    try:
        response = requests.get(
            f'https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency=BTC&to_currency=AUD&apikey={ALPHA_VANTAGE_KEY}',
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            if 'Realtime Currency Exchange Rate' in data:
                price = float(data['Realtime Currency Exchange Rate']['5. Exchange Rate'])
                result = {"price": price, "source": "Alpha Vantage"}
                set_cache('bitcoin_aud', result)
                logger.info(f"Bitcoin price from Alpha Vantage: {price} AUD")
                return jsonify(result)
    except Exception as e:
        logger.error(f"Alpha Vantage crypto error: {e}")
    
    # Ultimate fallback
    result = {"price": 170000, "source": "fallback"}
    set_cache('bitcoin_aud', result)
    return jsonify(result)

@app.route('/api/stock/<symbol>')
def get_stock_price(symbol):
    """Fetch stock price and convert to AUD if needed"""
    
    # Check cache first
    cache_key = f"stock_{symbol}"
    cached_data = get_cached_value(cache_key, 'stock')
    if cached_data:
        logger.info(f"Returning cached price for {symbol}")
        return jsonify(cached_data)
    
    # Clean symbol for API
    clean_symbol = symbol.replace('.AX', '').replace('.PA', '').replace('.V', '')
    
    try:
        # Use Alpha Vantage for stock prices
        response = requests.get(
            f'https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={clean_symbol}&apikey={ALPHA_VANTAGE_KEY}',
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'Global Quote' in data and '05. price' in data['Global Quote']:
                price = float(data['Global Quote']['05. price'])
                
                # Convert to AUD if needed
                if '.PA' in symbol:  # European stock
                    fx_rate = get_fx_rate_internal('EUR', 'AUD')
                    price = price * fx_rate
                elif not '.AX' in symbol and not '.V' in symbol:  # US stock
                    fx_rate = get_fx_rate_internal('USD', 'AUD')
                    price = price * fx_rate
                
                result = {"symbol": symbol, "price": price, "source": "Alpha Vantage"}
                set_cache(cache_key, result)
                logger.info(f"{symbol} price: {price} AUD")
                return jsonify(result)
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
    
    # Fallback prices (updated August 2025 estimates)
    fallback_prices = {
        'VBTC': 35.65,
        'VTS': 476.55,
        'VEU': 103.02,
        'ZETA': 44.50,
        'NUGG.AX': 50.83,
        'ASML': 1570.00,
        'MC.PA': 1335.00,
        'TTD': 124.00,
        'MSTY': 41.45,
        'SOS.V': 12.00,
        'SPY': 860.00  # S&P 500 ETF in AUD
    }
    
    price = fallback_prices.get(symbol, 100)
    result = {"symbol": symbol, "price": price, "source": "fallback"}
    set_cache(cache_key, result)
    return jsonify(result)

@app.route('/api/fx/<from_currency>/<to_currency>')
def get_fx_rate(from_currency, to_currency):
    """Get exchange rate between two currencies"""
    rate = get_fx_rate_internal(from_currency, to_currency)
    return jsonify({
        "from": from_currency,
        "to": to_currency,
        "rate": rate
    })

def get_fx_rate_internal(from_currency, to_currency):
    """Internal function to get FX rates with caching"""
    
    # Check cache
    cache_key = f"fx_{from_currency}_{to_currency}"
    cached_rate = get_cached_value(cache_key, 'fx')
    if cached_rate:
        return cached_rate
    
    try:
        # Try exchangerate-api first (no key needed, more reliable)
        response = requests.get(
            f'https://api.exchangerate-api.com/v4/latest/{from_currency}',
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            if 'rates' in data and to_currency in data['rates']:
                rate = data['rates'][to_currency]
                set_cache(cache_key, rate)
                logger.info(f"FX rate {from_currency}/{to_currency}: {rate}")
                return rate
    except Exception as e:
        logger.error(f"Exchange rate API error: {e}")
    
    # Try Alpha Vantage as backup
    try:
        response = requests.get(
            f'https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={from_currency}&to_currency={to_currency}&apikey={ALPHA_VANTAGE_KEY}',
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            if 'Realtime Currency Exchange Rate' in data:
                rate = float(data['Realtime Currency Exchange Rate']['5. Exchange Rate'])
                set_cache(cache_key, rate)
                return rate
    except Exception as e:
        logger.error(f"Alpha Vantage FX error: {e}")
    
    # Fallback rates
    default_rates = {
        'USD_AUD': 1.48,
        'EUR_AUD': 1.63,
        'AUD_USD': 0.68,
        'AUD_EUR': 0.61
    }
    
    key = f"{from_currency}_{to_currency}"
    rate = default_rates.get(key, 1.5)
    set_cache(cache_key, rate)
    return rate

@app.route('/api/portfolio', methods=['POST'])
def get_portfolio_prices():
    """Get all portfolio prices in one optimized call"""
    
    holdings = request.json.get('holdings', [])
    results = {}
    
    # Get Bitcoin price
    btc_response = get_bitcoin_price()
    btc_data = btc_response.get_json()
    results['BTC'] = btc_data['price']
    
    # Get FX rates (cached for efficiency)
    fx_rates = {
        'USD': get_fx_rate_internal('USD', 'AUD'),
        'EUR': get_fx_rate_internal('EUR', 'AUD')
    }
    results['fx_rates'] = fx_rates
    
    # Get stock prices (with caching)
    for holding in holdings:
        if holding['type'] != 'crypto':
            symbol = holding['symbol']
            stock_response = get_stock_price(symbol)
            stock_data = stock_response.get_json()
            results[symbol] = stock_data['price']
    
    # Get S&P 500 (SPY as proxy)
    spy_response = get_stock_price('SPY')
    spy_data = spy_response.get_json()
    results['SPY'] = spy_data['price']
    
    # Log summary
    logger.info(f"Portfolio update: {len(results)} prices fetched")
    
    return jsonify({
        "prices": results,
        "timestamp": datetime.now().isoformat(),
        "cache_info": {
            "items_cached": len(cache),
            "bitcoin_source": btc_data.get('source', 'unknown')
        }
    })

@app.route('/api/health')
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache_size": len(cache)
    })

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
