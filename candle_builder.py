#!/usr/bin/env python3
"""
Real-time 1-minute OHLC Candle Builder from Kite WebSocket Ticks
"""

import argparse
import sys
import time
import logging
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from kiteconnect import KiteTicker, KiteConnect
import json

# Setup main logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                   handlers=[logging.FileHandler('candle_builder.log'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# Setup separate candle-only logger (no timestamp formatting)
candle_logger = logging.getLogger('candles')
candle_logger.setLevel(logging.INFO)
candle_handler = logging.FileHandler('completed_candles.log')
candle_formatter = logging.Formatter('%(message)s')  # Only message, no timestamp
candle_handler.setFormatter(candle_formatter)
candle_logger.addHandler(candle_handler)
candle_logger.propagate = False

class CandleBuilder:
    def __init__(self, api_key, access_token):
        self.api_key = api_key
        self.access_token = access_token
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self.kws = KiteTicker(api_key, access_token)
        
        # Auto-reconnect settings
        self.kws.autoreconnect = True
        self.kws.reconnect_interval = 5
        self.kws.reconnect_tries = 50
        
        # Data structures for candle building
        self.current_candles = {}  # symbol -> current minute candle data
        self.completed_candles = defaultdict(list)  # symbol -> list of completed candles
        self.symbol_tokens = {}  # symbol -> token mapping
        self.token_symbols = {}  # token -> symbol mapping
        
        # Candle timing
        self.current_minute = None
        self.candle_lock = threading.Lock()
        
        self.setup_callbacks()
    
    def setup_callbacks(self):
        """Setup websocket callbacks"""
        self.kws.on_ticks = self.on_ticks
        self.kws.on_connect = self.on_connect
        self.kws.on_close = self.on_close
        self.kws.on_error = self.on_error
        self.kws.on_reconnect = self.on_reconnect
        self.kws.on_noreconnect = self.on_noreconnect
    
    def initialize_symbols(self, symbols):
        """Initialize symbol to token mapping"""
        logger.info(f"Initializing {len(symbols)} symbols...")
        
        instruments = self.kite.instruments("NSE")
        tokens = []
        
        for symbol in symbols:
            for instrument in instruments:
                if (instrument['tradingsymbol'] == symbol and 
                    instrument['segment'] == 'NSE' and 
                    instrument['instrument_type'] == 'EQ'):
                    token = instrument['instrument_token']
                    tokens.append(token)
                    self.symbol_tokens[symbol] = token
                    self.token_symbols[token] = symbol
                    logger.info(f"Mapped {symbol} -> {token}")
                    break
            else:
                logger.warning(f"Token not found for symbol: {symbol}")
        
        return tokens
    
    def get_current_minute(self):
        """Get current minute timestamp (truncated to minute)"""
        now = datetime.now()
        return now.replace(second=0, microsecond=0)
    
    def initialize_candle(self, symbol, price, timestamp):
        """Initialize a new candle for the current minute"""
        minute_timestamp = timestamp.replace(second=0, microsecond=0)
        
        candle = {
            'symbol': symbol,
            'timestamp': minute_timestamp,
            'open': price,
            'high': price,
            'low': price,
            'close': price,
            'volume': 0,
            'tick_count': 0,
            'first_tick_time': timestamp,
            'last_tick_time': timestamp
        }
        
        self.current_candles[symbol] = candle
        logger.info(f"{symbol} - New 1min candle started at {minute_timestamp.strftime('%H:%M:%S')} | O:{price:.2f}")
        return candle
    
    def update_candle(self, symbol, price, volume, timestamp):
        """Update existing candle with new tick data"""
        candle = self.current_candles[symbol]
        
        # Update OHLC
        if price > candle['high']:
            candle['high'] = price
        if price < candle['low']:
            candle['low'] = price
        candle['close'] = price
        
        # Update volume and metadata
        candle['volume'] += volume
        candle['tick_count'] += 1
        candle['last_tick_time'] = timestamp
    
    def complete_candle(self, symbol):
        """Complete current candle and move to completed list"""
        if symbol not in self.current_candles:
            return
        
        candle = self.current_candles[symbol]
        
        # Add to completed candles
        self.completed_candles[symbol].append(candle.copy())
        
        # Log to main log
        logger.info(f"{symbol} - Candle COMPLETED {candle['timestamp'].strftime('%H:%M')} | "
                   f"O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f} "
                   f"V:{candle['volume']} Ticks:{candle['tick_count']}")
        
        # Log to candle-only log in CSV format
        candle_logger.info(f"{candle['timestamp'].strftime('%Y-%m-%d')},{candle['timestamp'].strftime('%H:%M')},"
                          f"{symbol},{candle['open']:.2f},{candle['high']:.2f},{candle['low']:.2f},{candle['close']:.2f},"
                          f"{candle['volume']},{candle['tick_count']}")
        
        # Remove from current candles
        del self.current_candles[symbol]
    
    def check_minute_change(self, current_time):
        """Check if we've moved to a new minute and complete candles if needed"""
        current_minute = current_time.replace(second=0, microsecond=0)
        
        if self.current_minute is None:
            self.current_minute = current_minute
            return
        
        if current_minute > self.current_minute:
            logger.info(f"Minute changed: {self.current_minute.strftime('%H:%M')} -> {current_minute.strftime('%H:%M')}")
            
            # Complete all current candles
            symbols_to_complete = list(self.current_candles.keys())
            for symbol in symbols_to_complete:
                self.complete_candle(symbol)
            
            self.current_minute = current_minute
    
    def on_ticks(self, ws, ticks):
        """Process incoming ticks and build candles"""
        current_time = datetime.now()
        
        with self.candle_lock:
            # Check if minute has changed
            self.check_minute_change(current_time)
            
            for tick in ticks:
                token = tick['instrument_token']
                if token not in self.token_symbols:
                    continue
                
                symbol = self.token_symbols[token]
                price = tick['last_price']
                volume = tick.get('volume_traded', 0) if 'volume_traded' in tick else 0
                
                # Initialize or update candle
                if symbol not in self.current_candles:
                    self.initialize_candle(symbol, price, current_time)
                else:
                    self.update_candle(symbol, price, volume, current_time)
    
    def on_connect(self, ws, response):
        """Called when websocket connects"""
        logger.info("WebSocket Connected")
        if hasattr(self, 'tokens') and self.tokens:
            ws.subscribe(self.tokens)
            ws.set_mode(self.kws.MODE_FULL, self.tokens)  # Use FULL mode to get volume data
            logger.info(f"Subscribed to {len(self.tokens)} tokens in FULL mode")
    
    def on_close(self, ws, code, reason):
        """Called when websocket closes"""
        logger.info(f"WebSocket Closed: {code} - {reason}")
    
    def on_error(self, ws, code, reason):
        """Called when websocket encounters error"""
        logger.error(f"WebSocket Error: {code} - {reason}")
    
    def on_reconnect(self, ws, attempts_count):
        """Called when websocket reconnects"""
        logger.info(f"WebSocket Reconnected successfully (attempt {attempts_count})")
        if hasattr(self, 'tokens') and self.tokens:
            ws.subscribe(self.tokens)
            ws.set_mode(self.kws.MODE_FULL, self.tokens)
            logger.info(f"Re-subscribed to {len(self.tokens)} tokens after reconnection")
    
    def on_noreconnect(self, ws):
        """Called when websocket fails to reconnect"""
        logger.error("WebSocket failed to reconnect")
    
    def start(self, symbols):
        """Start the candle builder"""
        # Initialize symbol mappings
        self.tokens = self.initialize_symbols(symbols)
        
        if not self.tokens:
            logger.error("No valid tokens found. Exiting.")
            return
        
        logger.info(f"Starting candle builder for {len(self.tokens)} symbols")
        logger.info(f"Auto-reconnect enabled: {self.kws.autoreconnect} (interval: {self.kws.reconnect_interval}s, tries: {self.kws.reconnect_tries})")
        
        # Write header to candle log (only if file is empty/new)
        try:
            with open('completed_candles.log', 'r') as f:
                if not f.read().strip():  # File is empty
                    candle_logger.info("Date,Time,Symbol,Open,High,Low,Close,Volume,Ticks")
        except FileNotFoundError:
            # File doesn't exist, write header
            candle_logger.info("Date,Time,Symbol,Open,High,Low,Close,Volume,Ticks")
        
        try:
            # Connect to websocket
            self.kws.connect()
        except KeyboardInterrupt:
            logger.info("Stopping candle builder...")
            self.print_final_summary()
        except Exception as e:
            logger.error(f"Error in candle builder: {e}")
        finally:
            self.kws.close()
    
    
    def print_final_summary(self):
        """Print final summary of all completed candles"""
        logger.info("=" * 80)
        logger.info("FINAL CANDLE SUMMARY")
        logger.info("=" * 80)
        
        for symbol in sorted(self.completed_candles.keys()):
            candles = self.completed_candles[symbol]
            logger.info(f"\n{symbol} - {len(candles)} completed candles:")
            logger.info(f"{'Time':<8} {'Open':<8} {'High':<8} {'Low':<8} {'Close':<8} {'Volume':<10} {'Ticks':<6}")
            logger.info("-" * 60)
            
            for candle in candles:
                time_str = candle['timestamp'].strftime('%H:%M')
                logger.info(f"{time_str:<8} {candle['open']:<8.2f} {candle['high']:<8.2f} {candle['low']:<8.2f} "
                           f"{candle['close']:<8.2f} {candle['volume']:<10} {candle['tick_count']:<6}")
    
    def export_candles_to_json(self, filename=None):
        """Export all completed candles to JSON file"""
        if filename is None:
            filename = f"candles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        export_data = {}
        for symbol, candles in self.completed_candles.items():
            export_data[symbol] = []
            for candle in candles:
                candle_data = candle.copy()
                candle_data['timestamp'] = candle_data['timestamp'].isoformat()
                candle_data['first_tick_time'] = candle_data['first_tick_time'].isoformat()
                candle_data['last_tick_time'] = candle_data['last_tick_time'].isoformat()
                export_data[symbol].append(candle_data)
        
        with open(filename, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"Candles exported to {filename}")

def main():
    parser = argparse.ArgumentParser(description="Real-time 1-minute OHLC Candle Builder")
    parser.add_argument('--api_key', required=True, help='Kite API key')
    parser.add_argument('--access_token', required=True, help='Kite access token')
    parser.add_argument('--symbols', required=True, help='Comma-separated list of symbols')
    parser.add_argument('--export', action='store_true', help='Export candles to JSON on exit')
    
    args = parser.parse_args()
    
    # Parse symbols
    symbols = [s.strip().upper() for s in args.symbols.split(',')]
    logger.info(f"Building 1-minute candles for: {symbols}")
    
    # Create and start candle builder
    builder = CandleBuilder(args.api_key, args.access_token)
    
    try:
        builder.start(symbols)
    finally:
        if args.export:
            builder.export_candles_to_json()

if __name__ == "__main__":
    main()
