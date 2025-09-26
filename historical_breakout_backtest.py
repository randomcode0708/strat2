#!/usr/bin/env python3
import argparse
import sys
import time
import logging
import threading
import json
import csv
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
HISTORICAL_DATA_CACHE = {}  # Cache all historical data per symbol
candles_initialized = False
INITIAL_CAPITAL = 360000
AVAILABLE_CAPITAL = INITIAL_CAPITAL
TOTAL_RISK_PERCENTAGE = 0.02
QUANTITY_MAP = {}
POSITIONS_TAKEN = {}
TRADES_TAKEN = []  # Store all trades for final output

MARKET_START = datetime.strptime("09:21:00", "%H:%M:%S").time()
MARKET_END = datetime.strptime("15:15:00", "%H:%M:%S").time()
STRATEGY_END = datetime.strptime("15:00:00", "%H:%M:%S").time()
FROM_TIME_BREAKOUT = None  # Will be set based on command line date parameter

TRADING_ACTIVE = True
POLLING_INTERVAL = 30  # 30 seconds
kite = None

class HistoricalBreakoutTrader:
    def __init__(self, api_key, access_token, trading_date=None):
        self.api_key = api_key
        self.access_token = access_token
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self.last_checked_minute = None
        self.trading_date = trading_date or datetime.now().date()
        self.simulated_time = None  # For backtesting time simulation
        
    def start_trading(self):
        """Start the trading loop with 30-second polling"""
        global TRADING_ACTIVE, kite, candles_initialized, FROM_TIME_BREAKOUT
        kite = self.kite
        
        # Set the FROM_TIME_BREAKOUT based on trading date
        FROM_TIME_BREAKOUT = datetime.combine(self.trading_date, datetime.strptime("09:15:00", "%H:%M:%S").time())
        
        logger.info(f"Starting historical breakout trading for date: {self.trading_date}")
        logger.info(f"Breakout time set to: {FROM_TIME_BREAKOUT}")
        
        # Initialize token mappings only (candle data will be initialized after market starts)
        initialize_token_mappings()
        
        # Fetch all historical data once (backtesting mode only)
        logger.info("Fetching all historical data once...")
        self.fetch_all_historical_data()
        
        # Initialize simulated time (always backtesting mode)
        self.simulated_time = datetime.combine(self.trading_date, datetime.strptime("09:21:00", "%H:%M:%S").time())
        logger.info(f"Backtesting mode: Starting simulation at {self.simulated_time}")
        
        while TRADING_ACTIVE:
            try:
                # Always use simulated time (backtesting mode only)
                if self.simulated_time is None:
                    logger.error("Simulated time is None! This should not happen.")
                    break
                current_time = self.simulated_time
                current_time_only = current_time.time()
                logger.debug(f"Backtesting: Using simulated time {current_time}")
                
                # Initialize candle data only after market has started
                if not candles_initialized:
                    logger.info(f"Market started, initializing candle data | Current Time: {current_time_only}")
                    initialize_candle_data(self.trading_date)
                
                # Check if strategy should end when we reach 3:01 PM candle (use simulated time for backtest)
                end_time = datetime.strptime("15:01:00", "%H:%M:%S").time()
                logger.debug(f"Checking exit condition: {current_time_only} >= {end_time} = {current_time_only >= end_time}")
                if current_time_only >= end_time:
                    logger.info(f"Strategy ended - reached 3:01 PM candle | Simulated Time: {current_time_only}")
                    stop_trading_and_exit()
                    break
                
                # Check if all cached data has been processed
                if self.is_cached_data_exhausted(current_time):
                    logger.info("All cached candle data has been processed. Ending trading session.")
                    stop_trading_and_exit()
                    break
                
                # Check for breakouts using cached data
                self.check_breakouts_from_cached_data(current_time, self.trading_date)
                
                # Advance simulated time by 1 minute (backtesting mode only)
                old_time = self.simulated_time
                self.simulated_time += timedelta(minutes=1)
                logger.info(f"Backtesting: Advanced time from {old_time.strftime('%H:%M:%S')} to {self.simulated_time.strftime('%H:%M:%S')}")
                # Add a small delay to make the progression visible
                time.sleep(0.1)
                
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received, stopping...")
                stop_trading_and_exit()
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                # Sleep for 30 seconds on error to avoid rapid error loops
                time.sleep(30)
    
    
    def fetch_all_historical_data(self):
        """Fetch all historical data for the trading day once and cache it"""
        global HISTORICAL_DATA_CACHE, SYMBOL_TO_TOKEN
        
        # Define the time range (always backtesting mode)
        start_time = datetime.combine(self.trading_date, datetime.strptime("09:00:00", "%H:%M:%S").time())
        end_time = datetime.combine(self.trading_date, datetime.strptime("15:30:00", "%H:%M:%S").time())
        
        logger.info(f"Backtesting mode: Fetching historical data from {start_time} to {end_time}")
        
        for symbol in SYMBOLS:
            try:
                token = SYMBOL_TO_TOKEN[symbol]
                historical_data = self.kite.historical_data(
                    instrument_token=token,
                    from_date=start_time,
                    to_date=end_time,
                    interval="minute"
                )
                
                if historical_data:
                    HISTORICAL_DATA_CACHE[symbol] = historical_data
                    logger.info(f"{symbol}: Cached {len(historical_data)} minute candles")
                    #logger.info(f"{symbol}: Historical data: {historical_data}")
                else:
                    logger.warning(f"{symbol}: No historical data found for {self.trading_date}")
                    HISTORICAL_DATA_CACHE[symbol] = []
                    
            except Exception as e:
                logger.error(f"Error fetching historical data for {symbol}: {e}")
                HISTORICAL_DATA_CACHE[symbol] = []
        
        logger.info(f"Historical data caching completed for {len(HISTORICAL_DATA_CACHE)} symbols")
    
    def is_cached_data_exhausted(self, current_time):
        """Check if all cached candles have been processed"""
        global HISTORICAL_DATA_CACHE
        
        if not HISTORICAL_DATA_CACHE:
            logger.debug("No cached data available - exhausted")
            return True
        
        # Get the previous completed minute (same logic as in check_breakouts_from_cached_data)
        previous_minute = current_time.replace(second=0, microsecond=0) - timedelta(minutes=1)
        logger.debug(f"Checking if data exhausted for previous_minute: {previous_minute}")
        
        # Check if any symbol has data beyond the previous minute
        for symbol in SYMBOLS:
            cached_data = HISTORICAL_DATA_CACHE.get(symbol, [])
            if not cached_data:
                continue
                
            # Find if there's any candle at or after the previous minute
            for candle in cached_data:
                candle_time = candle['date'].replace(tzinfo=None)
                candle_minute = candle_time.replace(second=0, microsecond=0)
                if candle_minute >= previous_minute:
                    logger.debug(f"Found data for {symbol} at {candle_minute} >= {previous_minute} - not exhausted")
                    return False  # Still have data to process
        
        logger.debug("All cached data has been processed - exhausted")
        return True  # No more data available
    
    def check_breakouts_from_cached_data(self, current_time, trading_date):
        """Check for breakouts using cached historical data"""
        global CANDLE_MAP, QUANTITY_MAP, POSITIONS_TAKEN, HISTORICAL_DATA_CACHE
        
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
                # Get cached historical data for this symbol
                cached_data = HISTORICAL_DATA_CACHE.get(symbol, [])
                if not cached_data:
                    logger.error(f"{symbol} - No cached historical data found")
                    continue
                
                # Find the candle for the previous completed minute
                target_candle = None
                for candle in cached_data:
                    # Make both timestamps timezone-naive and compare only hour:minute
                    candle_time = candle['date'].replace(tzinfo=None)
                    candle_minute = candle_time.replace(second=0, microsecond=0)
                    if candle_minute == previous_minute:
                        target_candle = candle
                        logger.info(f"{symbol} - {candle_minute.strftime('%H:%M:%S')} close: {candle['close']:.2f}")
                        break
                
                if not target_candle:
                    logger.debug(f"{symbol} - No candle found for {previous_minute.strftime('%H:%M')} in cached data")
                    continue
                
                # Check for breakout using the completed 1-minute candle
                quantity = QUANTITY_MAP[symbol]
                self.check_breakout_for_symbol(symbol, target_candle, quantity, current_time)
                
            except Exception as e:
                logger.error(f"Error checking {symbol} from cached data: {e}")
    
    def check_breakout_for_symbol(self, symbol, current_candle, quantity, trading_time):
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
                
                # Record the trade using the candle timestamp (when breakout actually occurred)
                candle_timestamp = current_candle['date'].replace(tzinfo=None)
                trade_record = {
                    'timestamp': candle_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'symbol': symbol,
                    'action': 'BUY',
                    'quantity': quantity,
                    'price': current_price,
                    'deployed_capital': deployed_capital,
                    'order_id': order_id,
                    'stop_loss_price': stop_loss_price,
                    'breakout_high': breakout_candle['high'],
                    'breakout_low': breakout_candle['low'],
                    'trade_type': 'ENTRY'
                }
                TRADES_TAKEN.append(trade_record)
                
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
                
                # Record the trade using the candle timestamp (when breakout actually occurred)
                candle_timestamp = current_candle['date'].replace(tzinfo=None)
                trade_record = {
                    'timestamp': candle_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'symbol': symbol,
                    'action': 'SELL',
                    'quantity': quantity,
                    'price': current_price,
                    'deployed_capital': deployed_capital,
                    'order_id': order_id,
                    'stop_loss_price': stop_loss_price,
                    'breakout_high': breakout_candle['high'],
                    'breakout_low': breakout_candle['low'],
                    'trade_type': 'ENTRY'
                }
                TRADES_TAKEN.append(trade_record)
                
                # Update position tracking
                position_data = {'direction': 'SELL', 'quantity': quantity, 'price': current_price}
                if sl_info:
                    position_data.update(sl_info)
                POSITIONS_TAKEN[symbol] = position_data
                
            except Exception as e:
                logger.error(f"{symbol} SELL FAILED: {e}")

def initialize_candle_data(trading_date=None):
    """Initialize the breakout candle data (5-minute candles from 9:15)"""
    global CANDLE_MAP, candles_initialized, SYMBOLS, SYMBOL_TO_TOKEN, QUANTITY_MAP, kite
    global INITIAL_CAPITAL, TOTAL_RISK_PERCENTAGE, FROM_TIME_BREAKOUT, AVAILABLE_CAPITAL
    
    logger.info(f"Initializing breakout candles for date: {trading_date or 'today'}...")
    
    # For consistency with real-time, always use the exact same time range
    # Use 9:15 to 9:20 for the 5-minute breakout candle (same as real-time)
    from_time_exact = datetime.combine(trading_date or datetime.now().date(), 
                                      datetime.strptime("09:15:00", "%H:%M:%S").time())
    to_time_exact = datetime.combine(trading_date or datetime.now().date(), 
                                    datetime.strptime("09:20:00", "%H:%M:%S").time())
    
    for symbol in SYMBOLS:
        candles = kite.historical_data(SYMBOL_TO_TOKEN[symbol], from_time_exact, to_time_exact, "5minute")
        if not candles:
            logger.error(f"No candle data found for {symbol} on {trading_date or 'today'}")
            continue
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
    global HISTORICAL_DATA_CACHE
    
    instruments = kite.instruments("NSE")
    SYMBOL_TOKENS.clear()
    TOKEN_TO_SYMBOL.clear()
    SYMBOL_TO_TOKEN.clear()
    POSITIONS_TAKEN.clear()
    HISTORICAL_DATA_CACHE.clear()
    
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
    
    # Save all trades to file before exiting
    save_trades_to_file()
    
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
                order_id = 'N/A'
                
                # Record the closing trade (use current time for exit trades)
                close_trade_record = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'symbol': symbol,
                    'action': action,
                    'quantity': quantity,
                    'price': 'MARKET',  # Market order, actual price will be determined at execution
                    'deployed_capital': 0,  # Closing position, not deploying capital
                    'order_id': order_id,
                    'stop_loss_price': None,
                    'breakout_high': None,
                    'breakout_low': None,
                    'trade_type': 'EXIT'
                }
                TRADES_TAKEN.append(close_trade_record)
                
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

def save_trades_to_file():
    """Save all trades to CSV and JSON files"""
    global TRADES_TAKEN
    
    if not TRADES_TAKEN:
        logger.info("No trades to save")
        return
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save as CSV
    csv_filename = f"trades_{timestamp}.csv"
    try:
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            if TRADES_TAKEN:
                fieldnames = TRADES_TAKEN[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(TRADES_TAKEN)
        logger.info(f"Trades saved to CSV: {csv_filename}")
    except Exception as e:
        logger.error(f"Failed to save trades to CSV: {e}")
    
    # Save as JSON for more detailed format
    json_filename = f"trades_{timestamp}.json"
    try:
        with open(json_filename, 'w', encoding='utf-8') as jsonfile:
            json.dump({
                'trading_session': {
                    'start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'symbols': SYMBOLS,
                    'initial_capital': INITIAL_CAPITAL,
                    'total_trades': len(TRADES_TAKEN)
                },
                'trades': TRADES_TAKEN
            }, jsonfile, indent=2)
        logger.info(f"Trades saved to JSON: {json_filename}")
    except Exception as e:
        logger.error(f"Failed to save trades to JSON: {e}")
    
    # Print summary to console
    print_trade_summary()

def print_trade_summary():
    """Print a summary of all trades to console"""
    global TRADES_TAKEN
    
    if not TRADES_TAKEN:
        logger.info("No trades executed during this session")
        return
    
    entry_trades = [t for t in TRADES_TAKEN if t['trade_type'] == 'ENTRY']
    exit_trades = [t for t in TRADES_TAKEN if t['trade_type'] == 'EXIT']
    
    print("\n" + "="*60)
    print("TRADING SESSION SUMMARY")
    print("="*60)
    print(f"Total Trades: {len(TRADES_TAKEN)}")
    print(f"Entry Trades: {len(entry_trades)}")
    print(f"Exit Trades: {len(exit_trades)}")
    print(f"Initial Capital: ₹{INITIAL_CAPITAL:,.2f}")
    print(f"Remaining Capital: ₹{AVAILABLE_CAPITAL:,.2f}")
    
    if entry_trades:
        print("\nENTRY TRADES:")
        print("-" * 60)
        for trade in entry_trades:
            print(f"{trade['timestamp']} | {trade['symbol']} {trade['action']} "
                  f"{trade['quantity']} @ ₹{trade['price']:.2f} | "
                  f"Capital: ₹{trade['deployed_capital']:,.0f}")
    
    if exit_trades:
        print("\nEXIT TRADES:")
        print("-" * 60)
        for trade in exit_trades:
            print(f"{trade['timestamp']} | {trade['symbol']} {trade['action']} "
                  f"{trade['quantity']} @ {trade['price']}")
    
    print("="*60)

def main():
    global SYMBOLS
    
    parser = argparse.ArgumentParser(description="Historical Breakout Trading Bot")
    parser.add_argument('--api_key', required=True, help='Kite API Key')
    parser.add_argument('--access_token', required=True, help='Kite Access Token')
    parser.add_argument('--symbols', required=True, help='Comma-separated list of symbols')
    parser.add_argument('--polling_interval', type=int, default=30, help='Polling interval in seconds (default: 30)')
    parser.add_argument('--date', type=str, help='Trading date in YYYY-MM-DD format (default: today)')
    
    args = parser.parse_args()
    
    global POLLING_INTERVAL
    POLLING_INTERVAL = args.polling_interval
    
    SYMBOLS = [s.strip().upper() for s in args.symbols.split(',')]
    
    # Parse the trading date
    trading_date = None
    if args.date:
        try:
            trading_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Please use YYYY-MM-DD format.")
            sys.exit(1)
    
    logger.info(f"Symbols: {SYMBOLS}")
    logger.info(f"Polling interval: {POLLING_INTERVAL} seconds")
    logger.info(f"Trading date: {trading_date or 'today (live trading)'}")
    
    trader = HistoricalBreakoutTrader(args.api_key, args.access_token, trading_date)
    
    try:
        trader.start_trading()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        stop_trading_and_exit()
    except Exception as e:
        logger.error(f"Error: {e}")
        # Save trades even if there's an unexpected error
        save_trades_to_file()
        stop_trading_and_exit()

if __name__ == "__main__":
    main()
