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
MARKET_START = datetime.strptime("09:20:00", "%H:%M:%S").time()
MARKET_END = datetime.strptime("15:15:00", "%H:%M:%S").time()
STRATEGY_END = datetime.strptime("15:00:00", "%H:%M:%S").time()
BREAKOUT_START_TIME = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0).time()

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
        self.current_5min_candles = {}  # symbol -> current 5-minute candle
        self.completed_1min_candles = defaultdict(list)  # symbol -> list of 1-min candles
        self.breakout_candles = {}  # symbol -> first 5-minute breakout candle
        
        # Symbol mappings
        self.symbol_tokens = {}
        self.token_symbols = {}
        
        # Timing
        self.current_1min = None
        self.current_5min = None
        self.breakout_candle_formed = False
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
        """Initialize symbol to token mapping and calculate quantities"""
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
            logger.info(f"{symbol} Range:{breakout_range:.2f} Qty:{quantity} Risk:{per_stock_risk:.2f}")
    
    def initialize_candle(self, symbol, price, timestamp, candle_type='1min'):
        """Initialize a new candle"""
        if candle_type == '1min':
            minute_timestamp = timestamp.replace(second=0, microsecond=0)
            candles_dict = self.current_1min_candles
        else:  # 5min
            # Round to 5-minute boundary
            minutes = (timestamp.minute // 5) * 5
            minute_timestamp = timestamp.replace(minute=minutes, second=0, microsecond=0)
            candles_dict = self.current_5min_candles
        
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
        
        candles_dict[symbol] = candle
        logger.info(f"{symbol} - New {candle_type} candle started at {minute_timestamp.strftime('%H:%M:%S')} | O:{price:.2f}")
        return candle
    
    def update_candle(self, symbol, price, volume, timestamp, candle_type='1min'):
        """Update existing candle with new tick data"""
        candles_dict = self.current_1min_candles if candle_type == '1min' else self.current_5min_candles
        
        if symbol not in candles_dict:
            return
        
        candle = candles_dict[symbol]
        
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
        
        # Add to completed candles
        self.completed_1min_candles[symbol].append(candle.copy())
        
        # Log completed candle
        logger.info(f"{symbol} - 1min Candle COMPLETED {candle['timestamp'].strftime('%H:%M')} | "
                   f"O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f} "
                   f"V:{candle['volume']} Ticks:{candle['tick_count']}")
        
        # Log to CSV
        candle_logger.info(f"{candle['timestamp'].strftime('%Y-%m-%d')},{candle['timestamp'].strftime('%H:%M')},"
                          f"{symbol},1min,{candle['open']:.2f},{candle['high']:.2f},{candle['low']:.2f},{candle['close']:.2f},"
                          f"{candle['volume']},{candle['tick_count']}")
        
        # Check for trading opportunity if breakout candle is available
        if self.breakout_candle_formed and symbol in self.breakout_candles and symbol in self.quantity_map:
            self.check_breakout_entry(symbol, candle)
        
        # Remove from current candles
        del self.current_1min_candles[symbol]
    
    def complete_5min_candle(self, symbol):
        """Complete 5-minute candle"""
        if symbol not in self.current_5min_candles:
            return
        
        candle = self.current_5min_candles[symbol]
        
        # Log completed 5-minute candle
        logger.info(f"{symbol} - 5min Candle COMPLETED {candle['timestamp'].strftime('%H:%M')} | "
                   f"O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f} "
                   f"V:{candle['volume']} Ticks:{candle['tick_count']}")
        
        # Log to CSV
        candle_logger.info(f"{candle['timestamp'].strftime('%Y-%m-%d')},{candle['timestamp'].strftime('%H:%M')},"
                          f"{symbol},5min,{candle['open']:.2f},{candle['high']:.2f},{candle['low']:.2f},{candle['close']:.2f},"
                          f"{candle['volume']},{candle['tick_count']}")
        
        # Check if this is the first 5-minute candle (9:15-9:20) for breakout reference
        if candle['timestamp'].time() == BREAKOUT_START_TIME:
            self.breakout_candles[symbol] = candle.copy()
            logger.info(f"{symbol} - BREAKOUT CANDLE SET | H:{candle['high']:.2f} L:{candle['low']:.2f}")
            
            # Calculate quantities once all breakout candles are formed
            if len(self.breakout_candles) == len(self.token_symbols):
                self.calculate_quantities_from_breakout()
                self.breakout_candle_formed = True
                logger.info("All breakout candles formed. Trading logic activated.")
        
        # Remove from current candles
        del self.current_5min_candles[symbol]
    
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
        
        # Check for LONG breakout (candle high > breakout high)
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
                logger.info(f"{symbol} BUY {order_id} @ {candle_close:.2f} Qty:{quantity} "
                           f"Deployed:{deployed_capital:.0f} Remaining:{self.available_capital:.0f}")
                
                # Place stop loss at breakout low
                stop_loss_price = breakout_candle['low']
                sl_info = self.place_stop_loss_order(symbol, quantity, 'BUY', stop_loss_price)
                
                # Update position tracking
                position_data = {'direction': 'BUY', 'quantity': quantity, 'price': candle_close}
                if sl_info:
                    position_data.update(sl_info)
                self.positions_taken[symbol] = position_data
                
            except Exception as e:
                logger.error(f"{symbol} BUY FAILED: {e}")
        
        # Check for SHORT breakout (candle low < breakout low)
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
                logger.info(f"{symbol} SELL {order_id} @ {candle_close:.2f} Qty:{quantity} "
                           f"Deployed:{deployed_capital:.0f} Remaining:{self.available_capital:.0f}")
                
                # Place stop loss at breakout high
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
            
            logger.info(f"{symbol} STOP LOSS {sl_order_id} @ {stop_loss_price:.2f} for {position_type} position")
            return {'stop_loss_order_id': sl_order_id, 'stop_loss_price': stop_loss_price}
            
        except Exception as e:
            logger.error(f"{symbol} STOP LOSS FAILED: {e}")
            return None
    
    def check_minute_changes(self, current_time):
        """Check for both 1-minute and 5-minute changes"""
        current_1min = current_time.replace(second=0, microsecond=0)
        current_5min = current_time.replace(minute=(current_time.minute // 5) * 5, second=0, microsecond=0)
        
        # Check 1-minute change
        if self.current_1min is None:
            self.current_1min = current_1min
        elif current_1min > self.current_1min:
            logger.info(f"1-minute changed: {self.current_1min.strftime('%H:%M')} -> {current_1min.strftime('%H:%M')}")
            
            # Complete all current 1-minute candles
            symbols_to_complete = list(self.current_1min_candles.keys())
            for symbol in symbols_to_complete:
                self.complete_1min_candle(symbol)
            
            self.current_1min = current_1min
        
        # Check 5-minute change
        if self.current_5min is None:
            self.current_5min = current_5min
        elif current_5min > self.current_5min:
            logger.info(f"5-minute changed: {self.current_5min.strftime('%H:%M')} -> {current_5min.strftime('%H:%M')}")
            
            # Complete all current 5-minute candles
            symbols_to_complete = list(self.current_5min_candles.keys())
            for symbol in symbols_to_complete:
                self.complete_5min_candle(symbol)
            
            self.current_5min = current_5min
    
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
                    self.initialize_candle(symbol, price, current_time, '1min')
                else:
                    self.update_candle(symbol, price, volume, current_time, '1min')
                
                # Update/initialize 5-minute candles (only if not formed breakout yet or still in first hour)
                if current_time.time() <= datetime.strptime("10:00:00", "%H:%M:%S").time():
                    if symbol not in self.current_5min_candles:
                        self.initialize_candle(symbol, price, current_time, '5min')
                    else:
                        self.update_candle(symbol, price, volume, current_time, '5min')
    
    def on_connect(self, ws, response):
        """Called when websocket connects"""
        logger.info("WebSocket Connected")
        if hasattr(self, 'tokens') and self.tokens:
            ws.subscribe(self.tokens)
            ws.set_mode(self.kws.MODE_FULL, self.tokens)
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
    
    def stop_trading_and_exit(self, ws=None):
        """Stop trading and close all positions"""
        logger.info("Market closed, stopping...")
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
        
        logger.info(f"Closing {len(self.positions_taken)} positions...")
        
        for symbol, position in self.positions_taken.items():
            try:
                # Cancel stop loss order if it exists
                if 'stop_loss_order_id' in position:
                    try:
                        self.kite.cancel_order(order_id=position['stop_loss_order_id'], variety=self.kite.VARIETY_REGULAR)
                        logger.info(f"{symbol} CANCELLED STOP LOSS {position['stop_loss_order_id']}")
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
                logger.info(f"{symbol} CLOSE {action} {order_id} Qty:{position['quantity']}")
                
            except Exception as e:
                logger.error(f"{symbol} CLOSE FAILED: {e}")
        
        self.positions_taken.clear()
    
    def cancel_all_orders(self):
        """Cancel all open orders"""
        try:
            orders = self.kite.orders()
            open_orders = [o for o in orders if o['status'] in ['OPEN', 'TRIGGER_PENDING']]
            
            if not open_orders:
                logger.info("No open orders to cancel")
                return
            
            logger.info(f"Cancelling {len(open_orders)} open orders...")
            
            for order in open_orders:
                try:
                    self.kite.cancel_order(order_id=order['order_id'], variety=order['variety'])
                    logger.info(f"Cancelled {order['tradingsymbol']} {order['order_id']}")
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
        
        logger.info(f"Starting live candle trader for {len(self.tokens)} symbols")
        logger.info(f"Auto-reconnect enabled: {self.kws.autoreconnect} (interval: {self.kws.reconnect_interval}s, tries: {self.kws.reconnect_tries})")
        logger.info(f"Initial Capital: {INITIAL_CAPITAL:,} | Risk: {TOTAL_RISK_PERCENTAGE*100}%")
        
        # Write header to candle log
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
            logger.info("Stopping live candle trader...")
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
