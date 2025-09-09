#!/usr/bin/env python3
"""
Live Candle-Based Trading Bot
Combines trading logic with real-time candle formation from ticks
"""

import argparse
import sys
import time
import logging
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from kiteconnect import KiteTicker, KiteConnect

# Setup main logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                   handlers=[logging.FileHandler('live_trader.log'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# Setup separate candle-only logger
candle_logger = logging.getLogger('candles')
candle_logger.setLevel(logging.INFO)
candle_handler = logging.FileHandler('trading_candles.log')
candle_formatter = logging.Formatter('%(message)s')
candle_handler.setFormatter(candle_formatter)
candle_logger.addHandler(candle_handler)
candle_logger.propagate = False

# Trading configuration
INITIAL_CAPITAL = 360000
TOTAL_RISK_PERCENTAGE = 0.02
MARKET_START = datetime.strptime("09:10:00", "%H:%M:%S").time()  # Start strategy from 9:10
MARKET_END = datetime.strptime("15:15:00", "%H:%M:%S").time()
STRATEGY_END = datetime.strptime("15:00:00", "%H:%M:%S").time()
TRADING_START = datetime.strptime("09:20:00", "%H:%M:%S").time()  # Start actual trading from 9:20
BREAKOUT_START_TIME = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0).time()
BREAKOUT_END_TIME = datetime.now().replace(hour=9, minute=19, second=0, microsecond=0).time()

class LiveCandleTrader:
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
        
        # Trading state
        self.trading_active = True
        self.available_capital = INITIAL_CAPITAL
        self.positions_taken = {}
        self.quantity_map = {}
        
        # Candle data structures
        self.current_1min_candles = {}  # symbol -> current 1-minute candle
        self.completed_1min_candles = defaultdict(list)  # symbol -> list of 1-min candles
        self.breakout_1min_candles = defaultdict(list)  # symbol -> list of 1-min candles for breakout (9:15-9:19)
        self.breakout_candles = {}  # symbol -> consolidated breakout candle from 5 candles
        
        # Symbol mappings
        self.symbol_tokens = {}
        self.token_symbols = {}
        
        # Timing
        self.current_1min = None
        self.breakout_candle_formed = False
        self.candle_lock = threading.Lock()
        
        # Pre-calculate expected breakout times
        self.expected_breakout_times = [
            datetime.now().replace(hour=9, minute=15, second=0, microsecond=0).time(),
            datetime.now().replace(hour=9, minute=16, second=0, microsecond=0).time(),
            datetime.now().replace(hour=9, minute=17, second=0, microsecond=0).time(),
            datetime.now().replace(hour=9, minute=18, second=0, microsecond=0).time(),
            datetime.now().replace(hour=9, minute=19, second=0, microsecond=0).time()
        ]
        
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
                    break
            else:
                logger.warning(f"Token not found for symbol: {symbol}")
        
        return tokens
    
    def calculate_quantities_from_breakout(self):
        """Calculate quantities based on breakout candle ranges"""
        if not self.breakout_candles:
            return
        
        total_risk = INITIAL_CAPITAL * TOTAL_RISK_PERCENTAGE
        per_stock_risk = total_risk / len(self.breakout_candles)
        
        for symbol, candle in self.breakout_candles.items():
            breakout_range = abs(candle['high'] - candle['low'])
            quantity = int(per_stock_risk / breakout_range) if breakout_range > 0 else 1
            self.quantity_map[symbol] = quantity
    
    def initialize_candle(self, symbol, price, timestamp):
        """Initialize a new 1-minute candle"""
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
        
        self.current_1min_candles[symbol] = candle
        return candle
    
    def update_candle(self, symbol, price, volume, timestamp):
        """Update existing 1-minute candle with new tick data"""
        if symbol not in self.current_1min_candles:
            return
        
        candle = self.current_1min_candles[symbol]
        
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
    
    def complete_1min_candle(self, symbol):
        """Complete 1-minute candle and check for trading opportunities"""
        if symbol not in self.current_1min_candles:
            return
        
        candle = self.current_1min_candles[symbol]
        candle_time = candle['timestamp'].time()
        
        # Add to completed candles
        self.completed_1min_candles[symbol].append(candle.copy())
        
        # Log to CSV
        candle_logger.info(f"{candle['timestamp'].strftime('%Y-%m-%d')},{candle['timestamp'].strftime('%H:%M')},"
                          f"{symbol},1min,{candle['open']:.2f},{candle['high']:.2f},{candle['low']:.2f},{candle['close']:.2f},"
                          f"{candle['volume']},{candle['tick_count']}")
        
        # Check if this is exactly one of the 5 breakout candles (9:15, 9:16, 9:17, 9:18, 9:19)
        if candle_time in self.expected_breakout_times:
            # Ensure we don't add duplicate candles for the same minute
            existing_times = [c['timestamp'].time() for c in self.breakout_1min_candles[symbol]]
            if candle_time not in existing_times:
                self.breakout_1min_candles[symbol].append(candle.copy())
                
                # Log first breakout candle
                if len(self.breakout_1min_candles[symbol]) == 1:
                    logger.info(f"{symbol} - Breakout period started (9:15-9:19)")
                
                # If we have all 5 candles (9:15, 9:16, 9:17, 9:18, 9:19), form breakout candle
                if len(self.breakout_1min_candles[symbol]) == 5:
                    self.form_breakout_candle(symbol)
        
        # Check for trading opportunity if breakout candle is available and after trading start time
        elif (self.breakout_candle_formed and symbol in self.breakout_candles and 
              symbol in self.quantity_map and candle_time >= TRADING_START):
            self.check_breakout_entry(symbol, candle)
        
        # Remove from current candles
        del self.current_1min_candles[symbol]
    
    def form_breakout_candle(self, symbol):
        """Form breakout candle from 5 one-minute candles (9:15-9:19)"""
        candles = self.breakout_1min_candles[symbol]
        
        if len(candles) != 5:
            return
        
        # Validate that we have exactly the right 5 candles (9:15, 9:16, 9:17, 9:18, 9:19)
        expected_minutes = [15, 16, 17, 18, 19]
        actual_minutes = sorted([c['timestamp'].minute for c in candles])
        
        if actual_minutes != expected_minutes:
            logger.error(f"{symbol} - Invalid breakout candles. Expected: {expected_minutes}, Got: {actual_minutes}")
            return
        
        # Create consolidated breakout candle from 5 candles
        breakout_candle = {
            'symbol': symbol,
            'timestamp': candles[0]['timestamp'],  # Start time (9:15)
            'open': candles[0]['open'],  # Open of first candle
            'high': max(c['high'] for c in candles),  # Highest high
            'low': min(c['low'] for c in candles),   # Lowest low
            'close': candles[-1]['close'],  # Close of last candle
            'volume': sum(c['volume'] for c in candles),  # Total volume
            'tick_count': sum(c['tick_count'] for c in candles)  # Total ticks
        }
        
        self.breakout_candles[symbol] = breakout_candle
        logger.info(f"{symbol} - BREAKOUT CANDLE SET | H:{breakout_candle['high']:.2f} L:{breakout_candle['low']:.2f}")
        
        # Log consolidated breakout candle to CSV
        candle_logger.info(f"{breakout_candle['timestamp'].strftime('%Y-%m-%d')},{breakout_candle['timestamp'].strftime('%H:%M')},"
                          f"{symbol},breakout,{breakout_candle['open']:.2f},{breakout_candle['high']:.2f},"
                          f"{breakout_candle['low']:.2f},{breakout_candle['close']:.2f},"
                          f"{breakout_candle['volume']},{breakout_candle['tick_count']}")
        
        # Calculate quantities when all breakout candles ready
        if len(self.breakout_candles) == len(self.token_symbols):
            self.calculate_quantities_from_breakout()
            self.breakout_candle_formed = True
            logger.info("Breakout candles formed. Trading active.")
    
    def check_breakout_entry(self, symbol, completed_1min_candle):
        """Check if 1-minute candle shows breakout and take entry"""
        if symbol in self.positions_taken:
            return
        
        breakout_candle = self.breakout_candles[symbol]
        quantity = self.quantity_map[symbol]
        candle_close = completed_1min_candle['close']
        candle_high = completed_1min_candle['high']
        candle_low = completed_1min_candle['low']
        
        deployed_capital = quantity * candle_close
        
        if deployed_capital > self.available_capital:
            logger.info(f"{symbol} SKIP - Need:{deployed_capital:.0f} Available:{self.available_capital:.0f}")
            return
        
        # LONG breakout
        if candle_high > breakout_candle['high']:
            try:
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    tradingsymbol=symbol,
                    exchange=self.kite.EXCHANGE_NSE,
                    transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                    quantity=quantity,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_MIS,
                    validity=self.kite.VALIDITY_DAY
                )
                
                self.available_capital -= deployed_capital
                logger.info(f"{symbol} BUY {order_id} @ {candle_close:.2f} Qty:{quantity}")
                
                # Place SL at breakout low
                stop_loss_price = breakout_candle['low']
                sl_info = self.place_stop_loss_order(symbol, quantity, 'BUY', stop_loss_price)
                
                # Update position tracking
                position_data = {'direction': 'BUY', 'quantity': quantity, 'price': candle_close}
                if sl_info:
                    position_data.update(sl_info)
                self.positions_taken[symbol] = position_data
                
            except Exception as e:
                logger.error(f"{symbol} BUY FAILED: {e}")
        
        # SHORT breakout
        elif candle_low < breakout_candle['low']:
            try:
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    tradingsymbol=symbol,
                    exchange=self.kite.EXCHANGE_NSE,
                    transaction_type=self.kite.TRANSACTION_TYPE_SELL,
                    quantity=quantity,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_MIS,
                    validity=self.kite.VALIDITY_DAY
                )
                
                self.available_capital -= deployed_capital
                logger.info(f"{symbol} SELL {order_id} @ {candle_close:.2f} Qty:{quantity}")
                
                # Place SL at breakout high
                stop_loss_price = breakout_candle['high']
                sl_info = self.place_stop_loss_order(symbol, quantity, 'SELL', stop_loss_price)
                
                # Update position tracking
                position_data = {'direction': 'SELL', 'quantity': quantity, 'price': candle_close}
                if sl_info:
                    position_data.update(sl_info)
                self.positions_taken[symbol] = position_data
                
            except Exception as e:
                logger.error(f"{symbol} SELL FAILED: {e}")
    
    def place_stop_loss_order(self, symbol, quantity, direction, stop_loss_price):
        """Place stop loss order for a given position"""
        try:
            sl_transaction_type = self.kite.TRANSACTION_TYPE_SELL if direction == 'BUY' else self.kite.TRANSACTION_TYPE_BUY
            position_type = "LONG" if direction == 'BUY' else "SHORT"
            
            sl_order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                tradingsymbol=symbol,
                exchange=self.kite.EXCHANGE_NSE,
                transaction_type=sl_transaction_type,
                quantity=quantity,
                order_type=self.kite.ORDER_TYPE_SL,
                price=stop_loss_price,
                trigger_price=stop_loss_price,
                product=self.kite.PRODUCT_MIS,
                validity=self.kite.VALIDITY_DAY
            )
            
            logger.info(f"{symbol} SL {sl_order_id} @ {stop_loss_price:.2f}")
            return {'stop_loss_order_id': sl_order_id, 'stop_loss_price': stop_loss_price}
            
        except Exception as e:
            logger.error(f"{symbol} STOP LOSS FAILED: {e}")
            return None
    
    def check_minute_changes(self, current_time):
        """Check for 1-minute changes"""
        current_1min = current_time.replace(second=0, microsecond=0)
        
        # Check 1-minute change
        if self.current_1min is None:
            self.current_1min = current_1min
        elif current_1min > self.current_1min:
            # Complete all current 1-minute candles
            symbols_to_complete = list(self.current_1min_candles.keys())
            for symbol in symbols_to_complete:
                self.complete_1min_candle(symbol)
            
            self.current_1min = current_1min
    
    def on_ticks(self, ws, ticks):
        """Process incoming ticks"""
        if not self.trading_active:
            return
        
        current_time = datetime.now()
        
        # Check market hours
        if current_time.time() < MARKET_START or current_time.time() > MARKET_END:
            return
        
        # Check strategy end
        if current_time.time() >= STRATEGY_END:
            logger.info(f"Strategy ended | Current Time: {current_time.time()}")
            self.stop_trading_and_exit(ws)
            return
        
        with self.candle_lock:
            # Check for minute changes
            self.check_minute_changes(current_time)
            
            for tick in ticks:
                token = tick['instrument_token']
                if token not in self.token_symbols:
                    continue
                
                symbol = self.token_symbols[token]
                price = tick['last_price']
                volume = tick.get('volume_traded', 0) if 'volume_traded' in tick else 0
                
                # Update/initialize 1-minute candles
                if symbol not in self.current_1min_candles:
                    self.initialize_candle(symbol, price, current_time)
                else:
                    self.update_candle(symbol, price, volume, current_time)
    
    def on_connect(self, ws, response):
        """Called when websocket connects"""
        if hasattr(self, 'tokens') and self.tokens:
            ws.subscribe(self.tokens)
            ws.set_mode(self.kws.MODE_FULL, self.tokens)
    
    def on_close(self, ws, code, reason):
        """Called when websocket closes"""
    
    def on_error(self, ws, code, reason):
        """Called when websocket encounters error"""
        logger.error(f"WebSocket Error: {code} - {reason}")
    
    def on_reconnect(self, ws, attempts_count):
        """Called when websocket reconnects"""
        if hasattr(self, 'tokens') and self.tokens:
            ws.subscribe(self.tokens)
            ws.set_mode(self.kws.MODE_FULL, self.tokens)
    
    def on_noreconnect(self, ws):
        """Called when websocket fails to reconnect"""
        logger.error("WebSocket failed to reconnect")
    
    def stop_trading_and_exit(self, ws=None):
        """Stop trading and close all positions"""
        logger.info("Market closed, stopping.")
        self.trading_active = False
        self.close_all_positions()
        self.cancel_all_orders()
        if ws:
            ws.close()
        
        def delayed_exit():
            time.sleep(2)
            sys.exit(0)
        
        threading.Thread(target=delayed_exit, daemon=True).start()
    
    def close_all_positions(self):
        """Close all open positions"""
        if not self.positions_taken:
            return
        
        
        for symbol, position in self.positions_taken.items():
            try:
                # Cancel stop loss order if it exists
                if 'stop_loss_order_id' in position:
                    try:
                        self.kite.cancel_order(order_id=position['stop_loss_order_id'], variety=self.kite.VARIETY_REGULAR)
                    except Exception as e:
                        logger.error(f"{symbol} CANCEL STOP LOSS FAILED: {e}")
                
                # Close the position
                opposite_direction = self.kite.TRANSACTION_TYPE_SELL if position['direction'] == 'BUY' else self.kite.TRANSACTION_TYPE_BUY
                
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    tradingsymbol=symbol,
                    exchange=self.kite.EXCHANGE_NSE,
                    transaction_type=opposite_direction,
                    quantity=position['quantity'],
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=self.kite.PRODUCT_MIS,
                    validity=self.kite.VALIDITY_DAY
                )
                
                action = "SELL" if position['direction'] == 'BUY' else "BUY"
                logger.info(f"{symbol} CLOSE {action} {order_id}")
                
            except Exception as e:
                logger.error(f"{symbol} CLOSE FAILED: {e}")
        
        self.positions_taken.clear()
    
    def cancel_all_orders(self):
        """Cancel all open orders"""
        try:
            orders = self.kite.orders()
            open_orders = [o for o in orders if o['status'] in ['OPEN', 'TRIGGER_PENDING']]
            
            if not open_orders:
                return
            
            
            for order in open_orders:
                try:
                    self.kite.cancel_order(order_id=order['order_id'], variety=order['variety'])
                except Exception as e:
                    logger.error(f"Cancel failed {order['order_id']}: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to fetch orders: {e}")
    
    def start(self, symbols):
        """Start the live candle trader"""
        # Initialize symbol mappings
        self.tokens = self.initialize_symbols(symbols)
        
        if not self.tokens:
            logger.error("No valid tokens found. Exiting.")
            return
        
        logger.info(f"Starting trader: {len(self.tokens)} symbols | Capital: {INITIAL_CAPITAL:,} | Risk: {TOTAL_RISK_PERCENTAGE*100}%")
        logger.info(f"Strategy: 9:10+ | Breakout: 9:15-9:19 | Trading: 9:20+")
        
        # Initialize candle log
        try:
            with open('trading_candles.log', 'r') as f:
                if not f.read().strip():
                    candle_logger.info("Date,Time,Symbol,Type,Open,High,Low,Close,Volume,Ticks")
        except FileNotFoundError:
            candle_logger.info("Date,Time,Symbol,Type,Open,High,Low,Close,Volume,Ticks")
        
        try:
            # Connect to websocket
            self.kws.connect()
        except KeyboardInterrupt:
            logger.info("Stopping trader...")
        except Exception as e:
            logger.error(f"Error in live candle trader: {e}")
        finally:
            self.kws.close()

def main():
    parser = argparse.ArgumentParser(description="Live Candle-Based Trading Bot")
    parser.add_argument('--api_key', required=True, help='Kite API key')
    parser.add_argument('--access_token', required=True, help='Kite access token')
    parser.add_argument('--symbols', required=True, help='Comma-separated list of symbols')
    
    args = parser.parse_args()
    
    # Parse symbols
    symbols = [s.strip().upper() for s in args.symbols.split(',')]
    logger.info(f"Live trading with candle-based entries for: {symbols}")
    
    # Create and start trader
    trader = LiveCandleTrader(args.api_key, args.access_token)
    trader.start(symbols)

if __name__ == "__main__":
    main()
