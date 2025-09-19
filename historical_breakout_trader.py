#!/usr/bin/env python3
import argparse
import sys
import time
import logging
import threading
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                   handlers=[logging.FileHandler('historical_breakout_trader.log'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

SYMBOLS = []
SYMBOL_TOKENS = []
TOKEN_TO_SYMBOL = {}
SYMBOL_TO_TOKEN = {}
CANDLE_MAP = {}
candles_initialized = False
INITIAL_CAPITAL = 360000
AVAILABLE_CAPITAL = INITIAL_CAPITAL
TOTAL_RISK_PERCENTAGE = 0.02
QUANTITY_MAP = {}
POSITIONS_TAKEN = {}

MARKET_START = datetime.strptime("09:21:00", "%H:%M:%S").time()
MARKET_END = datetime.strptime("15:15:00", "%H:%M:%S").time()
STRATEGY_END = datetime.strptime("15:00:00", "%H:%M:%S").time()
FROM_TIME_BREAKOUT = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)

TRADING_ACTIVE = True
POLLING_INTERVAL = 30  # 30 seconds
kite = None

class HistoricalBreakoutTrader:
    def __init__(self, api_key, access_token):
        self.api_key = api_key
        self.access_token = access_token
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self.last_checked_minute = None
        
    def start_trading(self):
        """Start the trading loop with 30-second polling"""
        global TRADING_ACTIVE, kite, candles_initialized
        kite = self.kite
        
        logger.info("Starting historical breakout trading...")
        
        # Initialize token mappings only (candle data will be initialized after market starts)
        initialize_token_mappings()
        
        while TRADING_ACTIVE:
            try:
                current_time = datetime.now()
                current_time_only = current_time.time()
                
                # Check if market is open
                if current_time_only < MARKET_START or current_time_only > MARKET_END:
                    logger.info(f"Market not open | Current Time: {current_time_only}")
                    self.sleep_until_next_minute(current_time)
                    continue
                
                # Initialize candle data only after market has started
                if not candles_initialized:
                    logger.info(f"Market started, initializing candle data | Current Time: {current_time_only}")
                    initialize_candle_data()
                
                # Check if strategy should end
                if current_time_only >= STRATEGY_END:
                    logger.info(f"Strategy ended | Current Time: {current_time_only}")
                    stop_trading_and_exit()
                    break
                
                # Check for breakouts using completed 1-minute candles
                self.check_breakouts_from_historical_data(current_time)
                
                # Sleep until next minute boundary (more efficient than fixed interval)
                self.sleep_until_next_minute(current_time)
                
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received, stopping...")
                stop_trading_and_exit()
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                # Sleep for 30 seconds on error to avoid rapid error loops
                time.sleep(30)
    
    def sleep_until_next_minute(self, current_time):
        """Sleep until the next minute boundary for efficient polling"""
        # Calculate seconds until next minute
        seconds_until_next_minute = 60 - current_time.second - (current_time.microsecond / 1000000.0)
        
        # Add a small buffer (1 second) to ensure the minute has fully passed
        sleep_duration = seconds_until_next_minute + 1
        
        # Minimum sleep of 5 seconds to avoid too frequent polling
        sleep_duration = max(5, sleep_duration)
        
        logger.debug(f"Sleeping {sleep_duration:.1f}s until next minute (current: {current_time.strftime('%H:%M:%S')})")
        time.sleep(sleep_duration)
    
    def check_breakouts_from_historical_data(self, current_time):
        """Check for breakouts using 1-minute historical data"""
        global CANDLE_MAP, QUANTITY_MAP, POSITIONS_TAKEN
        # Get the previous completed minute (not the current forming minute)
        previous_minute = current_time.replace(second=0, microsecond=0) - timedelta(minutes=1)
        
        # Skip if we already checked this minute
        if self.last_checked_minute == previous_minute:
            return
        self.last_checked_minute = previous_minute
        
        for symbol in SYMBOLS:
            if symbol in POSITIONS_TAKEN:
                continue
                
            try:
                to_time = current_time
                from_time = current_time - timedelta(minutes=5)  # Get last 5 minutes to be safe
                
                token = SYMBOL_TO_TOKEN[symbol]
                historical_data = kite.historical_data(
                    instrument_token=token,
                    from_date=from_time,
                    to_date=to_time,
                    interval="minute"
                )
                
                if not historical_data:
                    logger.error(f"{symbol} - No historical data found")
                    continue
                
                # Find the candle for the previous completed minute
                target_candle = None
                for candle in reversed(historical_data):  # Start from most recent
                    # Make both timestamps timezone-naive and compare only hour:minute
                    candle_time = candle['date'].replace(tzinfo=None)
                    candle_minute = candle_time.replace(second=0, microsecond=0)
                    if candle_minute == previous_minute:
                        target_candle = candle
                        logger.info(f"{symbol} - {candle_minute.strftime('%H:%M:%S')} close: {candle['close']:.2f}")
                        break
                
                if not target_candle:
                    logger.error(f"{symbol} - No candle found for {previous_minute.strftime('%H:%M')}")
                    logger.error(f"{symbol} - Available candle times: {[c['date'].replace(tzinfo=None).strftime('%H:%M') for c in historical_data]}")
                    continue
                
                # Check for breakout using the completed 1-minute candle
                quantity = QUANTITY_MAP[symbol]
                self.check_breakout_for_symbol(symbol, target_candle, quantity)
                
            except Exception as e:
                logger.error(f"Error checking {symbol}: {e}")
    
    def check_breakout_for_symbol(self, symbol, current_candle, quantity):
        """Check if current candle breaks out of the initial breakout range"""
        global CANDLE_MAP, POSITIONS_TAKEN, AVAILABLE_CAPITAL
        
        if symbol in POSITIONS_TAKEN:
            return
        
        breakout_candle = CANDLE_MAP[symbol][0]  # Initial 5-minute breakout candle
        current_price = current_candle['close']  # Use close price of completed 1-minute candle
        deployed_capital = quantity * current_price
        
        if deployed_capital > AVAILABLE_CAPITAL:
            logger.info(f"{symbol} SKIP - Need:{deployed_capital:.0f} Available:{AVAILABLE_CAPITAL:.0f}")
            return
        
        candle_time = current_candle['date'].strftime('%H:%M')
        
        # Check for upward breakout (price breaks above breakout candle high)
        if current_price > breakout_candle['high']:
            try:
                # order_id = kite.place_order(
                #     variety=kite.VARIETY_REGULAR,
                #     tradingsymbol=symbol,
                #     exchange=kite.EXCHANGE_NSE,
                #     transaction_type=kite.TRANSACTION_TYPE_BUY,
                #     quantity=quantity,
                #     order_type=kite.ORDER_TYPE_MARKET,
                #     product=kite.PRODUCT_MIS,
                #     validity=kite.VALIDITY_DAY
                # )
                order_id = 'N/A'
                AVAILABLE_CAPITAL -= deployed_capital
                logger.info(f"{symbol} BUY {order_id} @ {current_price:.2f} [{candle_time}] Qty:{quantity} "
                          f"Deployed:{deployed_capital:.0f} Remaining:{AVAILABLE_CAPITAL:.0f}")
                
                # Place stop loss at low of breakout candle for LONG position
                stop_loss_price = breakout_candle['low']
                sl_info = place_stop_loss_order(symbol, quantity, 'BUY', stop_loss_price)
                
                # Update position tracking
                position_data = {'direction': 'BUY', 'quantity': quantity, 'price': current_price}
                if sl_info:
                    position_data.update(sl_info)
                POSITIONS_TAKEN[symbol] = position_data
                
            except Exception as e:
                logger.error(f"{symbol} BUY FAILED: {e}")
        
        # Check for downward breakout (price breaks below breakout candle low)
        elif current_price < breakout_candle['low']:
            try:
                # order_id = kite.place_order(
                #     variety=kite.VARIETY_REGULAR,
                #     tradingsymbol=symbol,
                #     exchange=kite.EXCHANGE_NSE,
                #     transaction_type=kite.TRANSACTION_TYPE_SELL,
                #     quantity=quantity,
                #     order_type=kite.ORDER_TYPE_MARKET,
                #     product=kite.PRODUCT_MIS,
                #     validity=kite.VALIDITY_DAY
                # )
                order_id = 'N/A'
                
                AVAILABLE_CAPITAL -= deployed_capital
                logger.info(f"{symbol} SELL {order_id} @ {current_price:.2f} [{candle_time}] Qty:{quantity} "
                          f"Deployed:{deployed_capital:.0f} Remaining:{AVAILABLE_CAPITAL:.0f}")
                
                # Place stop loss at high of breakout candle for SHORT position
                stop_loss_price = breakout_candle['high']
                sl_info = place_stop_loss_order(symbol, quantity, 'SELL', stop_loss_price)
                
                # Update position tracking
                position_data = {'direction': 'SELL', 'quantity': quantity, 'price': current_price}
                if sl_info:
                    position_data.update(sl_info)
                POSITIONS_TAKEN[symbol] = position_data
                
            except Exception as e:
                logger.error(f"{symbol} SELL FAILED: {e}")

def initialize_candle_data():
    """Initialize the breakout candle data (5-minute candles from 9:15)"""
    global CANDLE_MAP, candles_initialized, SYMBOLS, SYMBOL_TO_TOKEN, QUANTITY_MAP, kite
    global INITIAL_CAPITAL, TOTAL_RISK_PERCENTAGE, FROM_TIME_BREAKOUT, AVAILABLE_CAPITAL
    
    logger.info("Initializing breakout candles...")
    
    for symbol in SYMBOLS:
        candles = kite.historical_data(SYMBOL_TO_TOKEN[symbol], FROM_TIME_BREAKOUT, datetime.now(), "5minute")
        first_candle = candles[0]
        CANDLE_MAP[symbol] = [first_candle]
        logger.info(f"{symbol} | O:{first_candle['open']:.2f} H:{first_candle['high']:.2f} "
                  f"L:{first_candle['low']:.2f} C:{first_candle['close']:.2f}")
    
    total_risk = INITIAL_CAPITAL * TOTAL_RISK_PERCENTAGE
    per_stock_risk = total_risk / len(SYMBOLS)
    
    for symbol in SYMBOLS:
        candle = CANDLE_MAP[symbol][0]
        breakout_range = abs(candle['high'] - candle['low'])
        quantity = max(1, int(per_stock_risk / breakout_range))
        QUANTITY_MAP[symbol] = quantity
        logger.info(f"{symbol} Range:{breakout_range:.2f} Qty:{quantity} perStockRisk:{per_stock_risk:.2f}")
    
    candles_initialized = True
    logger.info(f"Candles initialized | Available Capital: {AVAILABLE_CAPITAL:.0f}")

def place_stop_loss_order(symbol, quantity, direction, stop_loss_price):
    """Place stop loss order"""
    global kite
    
    try:
        sl_transaction_type = kite.TRANSACTION_TYPE_SELL if direction == 'BUY' else kite.TRANSACTION_TYPE_BUY
        position_type = "LONG" if direction == 'BUY' else "SHORT"
        
        # sl_order_id = kite.place_order(
        #     variety=kite.VARIETY_REGULAR,
        #     tradingsymbol=symbol,
        #     exchange=kite.EXCHANGE_NSE,
        #     transaction_type=sl_transaction_type,
        #     quantity=quantity,
        #     order_type=kite.ORDER_TYPE_SLM,
        #     trigger_price=stop_loss_price,
        #     product=kite.PRODUCT_MIS,
        #     validity=kite.VALIDITY_DAY
        # )
        sl_order_id = 'N/A'
        logger.info(f"{symbol} STOP LOSS {sl_order_id} @ {stop_loss_price:.2f} for {position_type} position")
        return {'stop_loss_order_id': sl_order_id, 'stop_loss_price': stop_loss_price}
        
    except Exception as e:
        logger.error(f"{symbol} STOP LOSS FAILED: {e}")
        return None

def initialize_token_mappings():
    """Initialize symbol to token mappings"""
    global SYMBOLS, SYMBOL_TOKENS, TOKEN_TO_SYMBOL, SYMBOL_TO_TOKEN, AVAILABLE_CAPITAL, INITIAL_CAPITAL, kite
    
    instruments = kite.instruments("NSE")
    SYMBOL_TOKENS.clear()
    TOKEN_TO_SYMBOL.clear()
    SYMBOL_TO_TOKEN.clear()
    POSITIONS_TAKEN.clear()
    
    for symbol in SYMBOLS:
        for instrument in instruments:
            if (instrument['tradingsymbol'] == symbol and 
                instrument['segment'] == 'NSE' and 
                instrument['instrument_type'] == 'EQ'):
                token = instrument['instrument_token']
                SYMBOL_TOKENS.append(token)
                TOKEN_TO_SYMBOL[token] = symbol
                SYMBOL_TO_TOKEN[symbol] = token
                break
    
    logger.info(f"Mapped {len(SYMBOL_TOKENS)} symbols")

def stop_trading_and_exit():
    """Stop trading and close all positions"""
    global TRADING_ACTIVE
    logger.info("Stopping trading...")
    TRADING_ACTIVE = False
    closeAllPositions()
    cancelAllOrders()
    
    def delayed_exit():
        time.sleep(2)
        sys.exit(0)
    
    threading.Thread(target=delayed_exit, daemon=True).start()

def closeAllPositions():
    """Close all open positions based on actual Kite API positions"""
    global kite
    
    try:
        # Get actual positions from Kite API
        positions = kite.positions()
        
        # Filter for MIS (intraday) positions that are not zero
        open_positions = []
        for position in positions['net']:
            if (position['product'] == 'MIS' and 
                position['quantity'] != 0 and 
                position['tradingsymbol'] in [s for s in SYMBOLS]):  # Only our trading symbols
                open_positions.append(position)
        
        if not open_positions:
            logger.info("No open positions to close")
            return
        
        logger.info(f"Closing {len(open_positions)} positions based on Kite API data...")
        
        for position in open_positions:
            try:
                symbol = position['tradingsymbol']
                quantity = abs(position['quantity'])  # Use absolute value
                
                # Determine transaction type to close the position
                if position['quantity'] > 0:  # Long position - need to sell
                    transaction_type = kite.TRANSACTION_TYPE_SELL
                    action = "SELL"
                else:  # Short position - need to buy
                    transaction_type = kite.TRANSACTION_TYPE_BUY
                    action = "BUY"
                
                # Place market order to close position
                # order_id = kite.place_order(
                #     variety=kite.VARIETY_REGULAR,
                #     tradingsymbol=symbol,
                #     exchange=kite.EXCHANGE_NSE,
                #     transaction_type=transaction_type,
                #     quantity=quantity,
                #     order_type=kite.ORDER_TYPE_MARKET,
                #     product=kite.PRODUCT_MIS,
                #     validity=kite.VALIDITY_DAY
                # )
                
                logger.info(f"{symbol} CLOSE {action} {order_id} Qty:{quantity} (API Position: {position['quantity']})")
                
            except Exception as e:
                logger.error(f"{symbol} CLOSE FAILED: {e}")
        
        # Clear our local tracking since we're closing everything
        POSITIONS_TAKEN.clear()
        
    except Exception as e:
        logger.error(f"Failed to fetch positions from API: {e}")

def cancelAllOrders():
    """Cancel all open orders based on actual Kite API orders"""
    global kite
    
    try:
        # Get actual orders from Kite API
        orders = kite.orders()
        
        # Filter for open orders (including our symbols and any other open orders)
        open_orders = []
        for order in orders:
            if order['status'] in ['OPEN', 'TRIGGER_PENDING', 'MODIFY_PENDING']:
                # Filter for MIS product and our trading symbols, or any stop loss orders
                if (order['product'] == 'MIS' and 
                    (order['tradingsymbol'] in SYMBOLS or 
                     order['order_type'] in ['SL', 'SLM'])):  # Include stop loss orders
                    open_orders.append(order)
        
        if not open_orders:
            logger.info("No open orders to cancel")
            return
        
        logger.info(f"Cancelling {len(open_orders)} open orders based on Kite API data...")
        
        for order in open_orders:
            try:
                # kite.cancel_order(order_id=order['order_id'], variety=order['variety'])
                order_type_desc = f"{order['order_type']}" + (f" (SL@{order['trigger_price']})" if order['order_type'] in ['SL', 'SLM'] else "")
                logger.info(f"Cancelled {order['tradingsymbol']} {order['order_id']} {order_type_desc}")
            except Exception as e:
                logger.error(f"Cancel failed {order['tradingsymbol']} {order['order_id']}: {e}")
                
    except Exception as e:
        logger.error(f"Failed to fetch orders from API: {e}")

def main():
    global SYMBOLS
    
    parser = argparse.ArgumentParser(description="Historical Breakout Trading Bot")
    parser.add_argument('--api_key', required=True, help='Kite API Key')
    parser.add_argument('--access_token', required=True, help='Kite Access Token')
    parser.add_argument('--symbols', required=True, help='Comma-separated list of symbols')
    parser.add_argument('--polling_interval', type=int, default=30, help='Polling interval in seconds (default: 30)')
    
    args = parser.parse_args()
    
    global POLLING_INTERVAL
    POLLING_INTERVAL = args.polling_interval
    
    SYMBOLS = [s.strip().upper() for s in args.symbols.split(',')]
    logger.info(f"Symbols: {SYMBOLS}")
    logger.info(f"Polling interval: {POLLING_INTERVAL} seconds")
    
    trader = HistoricalBreakoutTrader(args.api_key, args.access_token)
    
    try:
        trader.start_trading()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        stop_trading_and_exit()
    except Exception as e:
        logger.error(f"Error: {e}")
        stop_trading_and_exit()

if __name__ == "__main__":
    main()
