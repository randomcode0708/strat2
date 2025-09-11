#!/usr/bin/env python3
"""
Simple script to get 1-minute historical data for NSE stocks
Usage: python get_1min_data.py TCS
"""

import sys
import json
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

# Your credentials
API_KEY = "dsn6a9hdvuon0zve"
ACCESS_TOKEN = "TtGjrZjo4W4E2jV6uuTgPUxjB9kQsE16"

def get_1min_data(symbol, days_back=1):
    """Get 1-minute historical data for a given symbol"""
    
    # Initialize Kite Connect
    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(ACCESS_TOKEN)
    
    # Clean symbol (remove NSE: prefix if present)
    if symbol.startswith("NSE:"):
        symbol = symbol[4:]
    symbol = symbol.upper()
    
    # Get instruments to find token
    print(f"Getting 1-minute data for {symbol}...")
    instruments = kite.instruments("NSE")
    
    token = None
    for instrument in instruments:
        if (instrument['tradingsymbol'] == symbol and 
            instrument['segment'] == 'NSE' and 
            instrument['instrument_type'] == 'EQ'):
            token = instrument['instrument_token']
            break
    
    if not token:
        print(f"Error: Symbol {symbol} not found")
        return None
    
    # Calculate date range
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days_back)
    
    try:
        # Fetch 1-minute historical data
        data = kite.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval="minute"
        )
        
        print(f"\nFetched {len(data)} 1-minute candles for {symbol}")
        print(f"From: {from_date.strftime('%Y-%m-%d %H:%M')} To: {to_date.strftime('%Y-%m-%d %H:%M')}")
        
        # Show first 5 and last 5 candles
        if data:
            print(f"\nFirst 5 candles:")
            print(f"{'Time':<17} {'Open':<8} {'High':<8} {'Low':<8} {'Close':<8} {'Volume':<10}")
            print("-" * 70)
            
            for candle in data[:5]:
                time_str = candle['date'].strftime('%H:%M')
                print(f"{time_str:<17} {candle['open']:<8.2f} {candle['high']:<8.2f} {candle['low']:<8.2f} {candle['close']:<8.2f} {candle['volume']:<10}")
            
            if len(data) > 10:
                print("...")
                print(f"\nLast 5 candles:")
                print(f"{'Time':<17} {'Open':<8} {'High':<8} {'Low':<8} {'Close':<8} {'Volume':<10}")
                print("-" * 70)
                
                for candle in data[-5:]:
                    time_str = candle['date'].strftime('%H:%M')
                    print(f"{time_str:<17} {candle['open']:<8.2f} {candle['high']:<8.2f} {candle['low']:<8.2f} {candle['close']:<8.2f} {candle['volume']:<10}")
        
        return data
        
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python get_1min_data.py <SYMBOL> [days_back]")
        print("Example: python get_1min_data.py TCS")
        print("Example: python get_1min_data.py NSE:TCS 2")
        sys.exit(1)
    
    symbol = sys.argv[1]
    days_back = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    
    data = get_1min_data(symbol, days_back)
    
    if data:
        # Optionally save to JSON
        filename = f"{symbol.replace('NSE:', '')}_1min_data.json"
        json_data = []
        for candle in data:
            candle_copy = candle.copy()
            candle_copy['date'] = candle_copy['date'].isoformat()
            json_data.append(candle_copy)
        
        with open(filename, 'w') as f:
            json.dump(json_data, f, indent=2)
        
        print(f"\nData saved to {filename}")

if __name__ == "__main__":
    main()
