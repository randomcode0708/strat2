#!/usr/bin/env python3
import argparse
import sys
import time
import logging
import threading
from datetime import datetime
from kiteconnect import KiteTicker, KiteConnect

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                   handlers=[logging.FileHandler('kite_websocket.log'), logging.StreamHandler(sys.stdout)])
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
#FROM_TIME_BREAKOUT = datetime(2025, 9, 5, 9, 15, 0)
FROM_TIME_BREAKOUT = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)

TRADING_ACTIVE = True
kite = None

class KiteWebSocket:
    def __init__(self, api_key, access_token):
        self.api_key = api_key
        self.access_token = access_token
        self.kws = KiteTicker(api_key, access_token)
        self.tokens = []
        self.mode = None
        self.setup_callbacks()
    
    def setup_callbacks(self):
        self.kws.on_ticks = self.on_ticks
        self.kws.on_connect = self.on_connect
        self.kws.on_close = self.on_close
        self.kws.on_error = self.on_error
        self.kws.on_reconnect = self.on_reconnect
        self.kws.on_noreconnect = self.on_noreconnect
    
    def on_ticks(self, ws, ticks):
        global CANDLE_MAP, candles_initialized, TOKEN_TO_SYMBOL, QUANTITY_MAP, kite, TRADING_ACTIVE
        
        if not TRADING_ACTIVE:
            return
            
        current_time = datetime.now().time()
        if current_time < MARKET_START or current_time > MARKET_END :
            logger.info(f"Market not started yet or ended | Current Time: {current_time}")
            return

        if current_time >= STRATEGY_END:   
            logger.info(f"Strategy ended | Current Time: {current_time}")
            stop_trading_and_exit(ws)
            return

        if not candles_initialized:
            logger.info(f"Candles not initialized | Current Time: {current_time}")
            initialize_candle_data()

        for tick in ticks:
            token = tick['instrument_token']
            symbol = TOKEN_TO_SYMBOL[token]
            quantity = QUANTITY_MAP[symbol]
            lookfor_buy_sell(symbol, quantity, tick['last_price'])
    
    def on_connect(self, ws, response):
        logger.info("Connected")
        if self.tokens and self.mode is not None:
            ws.subscribe(self.tokens)
            ws.set_mode(self.mode, self.tokens)
            logger.info(f"Subscribed {len(self.tokens)} symbols")
    
    def on_close(self, ws, code, reason):
        pass
    
    def on_error(self, ws, code, reason):
        logger.error(f"WS Error: {reason}")
    
    def on_reconnect(self, ws, attempts_count):
        if self.tokens and self.mode is not None:
            ws.subscribe(self.tokens)
            ws.set_mode(self.mode, self.tokens)
    
    def on_noreconnect(self, ws):
        pass
    
    def subscribe_tokens(self, tokens, mode=None):
        if mode is None:
            mode = self.kws.MODE_LTP
        self.tokens = tokens
        self.mode = mode
    
    def connect(self):
        try:
            logger.info("Starting connection...")
            self.kws.connect()
        except Exception as e:
            logger.error(f"Connection error: {e}")

def initialize_candle_data():
    global CANDLE_MAP, candles_initialized, SYMBOLS, SYMBOL_TO_TOKEN, QUANTITY_MAP, kite
    global INITIAL_CAPITAL, TOTAL_RISK_PERCENTAGE, FROM_TIME_BREAKOUT, AVAILABLE_CAPITAL
    
    logger.info("Getting 5min candles...")
    
    for symbol in SYMBOLS:
        candles = kite.historical_data(SYMBOL_TO_TOKEN[symbol], FROM_TIME_BREAKOUT, datetime.now(), "5minute")
        logger.info(f"{symbol} | Full JSON Response: {candles}")
        first_candle = candles[0]
        CANDLE_MAP[symbol] = [first_candle]
        logger.info(f"{symbol} | O:{first_candle['open']:.2f} H:{first_candle['high']:.2f} "
                  f"L:{first_candle['low']:.2f} C:{first_candle['close']:.2f}")
    
    total_risk = INITIAL_CAPITAL * TOTAL_RISK_PERCENTAGE
    per_stock_risk = total_risk / len(SYMBOLS)
    
    for symbol in SYMBOLS:
        candle = CANDLE_MAP[symbol][0]
        breakout_range = abs(candle['high'] - candle['low'])
        quantity = int(per_stock_risk / breakout_range)
        QUANTITY_MAP[symbol] = quantity
        logger.info(f"{symbol} Range:{breakout_range:.2f} Qty:{quantity} perStockRisk:{per_stock_risk:.2f}")
    
    candles_initialized = True
    logger.info(f"Candles initialized | Available Capital: {AVAILABLE_CAPITAL:.0f}")

def place_stop_loss_order(symbol, quantity, direction, stop_loss_price):

    global kite
    
    try:
        sl_transaction_type = kite.TRANSACTION_TYPE_SELL if direction == 'BUY' else kite.TRANSACTION_TYPE_BUY
        position_type = "LONG" if direction == 'BUY' else "SHORT"
        
        sl_order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            tradingsymbol=symbol,
            exchange=kite.EXCHANGE_NSE,
            transaction_type=sl_transaction_type,
            quantity=quantity,
            order_type=kite.ORDER_TYPE_SL,
            price=stop_loss_price,
            trigger_price=stop_loss_price,
            product=kite.PRODUCT_MIS,
            validity=kite.VALIDITY_DAY
        )
        
        logger.info(f"{symbol} STOP LOSS {sl_order_id} @ {stop_loss_price:.2f} for {position_type} position")
        return {'stop_loss_order_id': sl_order_id, 'stop_loss_price': stop_loss_price}
        
    except Exception as e:
        logger.error(f"{symbol} STOP LOSS FAILED: {e}")
        return None

def initialize_token_mappings():
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

def lookfor_buy_sell(symbol, quantity, ltp):
    global CANDLE_MAP, POSITIONS_TAKEN, AVAILABLE_CAPITAL, kite
    
    if symbol in POSITIONS_TAKEN:
        return
    
    candle = CANDLE_MAP[symbol][0]
    deployed_capital = quantity * ltp
    
    if deployed_capital > AVAILABLE_CAPITAL:
        logger.info(f"{symbol} SKIP - Need:{deployed_capital:.0f} Available:{AVAILABLE_CAPITAL:.0f}")
        return
    
    if ltp > candle['high']:
        try:
            order_id = kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=symbol, 
                                      exchange=kite.EXCHANGE_NSE, transaction_type=kite.TRANSACTION_TYPE_BUY,
                                      quantity=quantity, order_type=kite.ORDER_TYPE_MARKET,
                                      product=kite.PRODUCT_MIS, validity=kite.VALIDITY_DAY)
            AVAILABLE_CAPITAL -= deployed_capital
            logger.info(f"{symbol} BUY {order_id} @ {ltp:.2f} Qty:{quantity} Deployed:{deployed_capital:.0f} Remaining:{AVAILABLE_CAPITAL:.0f}")
            
            # Place stop loss at low of breakout candle for LONG position
            stop_loss_price = candle['low']
            sl_info = place_stop_loss_order(symbol, quantity, 'BUY', stop_loss_price)
            
            # Update position tracking
            position_data = {'direction': 'BUY', 'quantity': quantity, 'price': ltp}
            if sl_info:
                position_data.update(sl_info)
            POSITIONS_TAKEN[symbol] = position_data
                
        except Exception as e:
            logger.error(f"{symbol} BUY FAILED: {e}")
            
    elif ltp < candle['low']:
        try:
            order_id = kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=symbol,
                                      exchange=kite.EXCHANGE_NSE, transaction_type=kite.TRANSACTION_TYPE_SELL,
                                      quantity=quantity, order_type=kite.ORDER_TYPE_MARKET,
                                      product=kite.PRODUCT_MIS, validity=kite.VALIDITY_DAY)
            AVAILABLE_CAPITAL -= deployed_capital
            logger.info(f"{symbol} SELL {order_id} @ {ltp:.2f} Qty:{quantity} Deployed:{deployed_capital:.0f} Remaining:{AVAILABLE_CAPITAL:.0f}")
            
            # Place stop loss at high of breakout candle for SHORT position
            stop_loss_price = candle['high']
            sl_info = place_stop_loss_order(symbol, quantity, 'SELL', stop_loss_price)
            
            # Update position tracking
            position_data = {'direction': 'SELL', 'quantity': quantity, 'price': ltp}
            if sl_info:
                position_data.update(sl_info)
            POSITIONS_TAKEN[symbol] = position_data
                
        except Exception as e:
            logger.error(f"{symbol} SELL FAILED: {e}")

def stop_trading_and_exit(ws=None):
    global TRADING_ACTIVE
    logger.info("Market closed, stopping...")
    TRADING_ACTIVE = False
    closeAllPositions()
    cancelAllOrders()
    if ws:
        ws.close()
    
    def delayed_exit():
        time.sleep(2)
        sys.exit(0)
    
    threading.Thread(target=delayed_exit, daemon=True).start()

def closeAllPositions():
    global POSITIONS_TAKEN, kite
    
    if not POSITIONS_TAKEN:
        return
    
    logger.info(f"Closing {len(POSITIONS_TAKEN)} positions...")
    
    for symbol, position in POSITIONS_TAKEN.items():
        try:
            # Cancel stop loss order if it exists
            if 'stop_loss_order_id' in position:
                try:
                    kite.cancel_order(order_id=position['stop_loss_order_id'], variety=kite.VARIETY_REGULAR)
                    logger.info(f"{symbol} CANCELLED STOP LOSS {position['stop_loss_order_id']}")
                except Exception as e:
                    logger.error(f"{symbol} CANCEL STOP LOSS FAILED: {e}")
            
            # Close the position
            opposite_direction = kite.TRANSACTION_TYPE_SELL if position['direction'] == 'BUY' else kite.TRANSACTION_TYPE_BUY
            
            order_id = kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=symbol,
                                      exchange=kite.EXCHANGE_NSE, transaction_type=opposite_direction,
                                      quantity=position['quantity'], order_type=kite.ORDER_TYPE_MARKET,
                                      product=kite.PRODUCT_MIS, validity=kite.VALIDITY_DAY)
            
            action = "SELL" if position['direction'] == 'BUY' else "BUY"
            logger.info(f"{symbol} CLOSE {action} {order_id} Qty:{position['quantity']}")
            
        except Exception as e:
            logger.error(f"{symbol} CLOSE FAILED: {e}")
    
    POSITIONS_TAKEN.clear()

def cancelAllOrders():
    global kite
    
    try:
        orders = kite.orders()
        open_orders = [o for o in orders if o['status'] in ['OPEN', 'TRIGGER_PENDING']]
        
        if not open_orders:
            logger.info("No open orders to cancel")
            return
        
        logger.info(f"Cancelling {len(open_orders)} open orders...")
        
        for order in open_orders:
            try:
                kite.cancel_order(order_id=order['order_id'], variety=order['variety'])
                logger.info(f"Cancelled {order['tradingsymbol']} {order['order_id']}")
            except Exception as e:
                logger.error(f"Cancel failed {order['order_id']}: {e}")
                
    except Exception as e:
        logger.error(f"Failed to fetch orders: {e}")

def main():
    global SYMBOLS, kite
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--api_key', required=True)
    parser.add_argument('--access_token', required=True)
    parser.add_argument('--symbols', required=True)
    parser.add_argument('--tokens')
    parser.add_argument('--mode', choices=['ltp', 'quote', 'full'], default='ltp')
    
    args = parser.parse_args()
    
    kite = KiteConnect(api_key=args.api_key)
    kite.set_access_token(args.access_token)
    
    SYMBOLS = [s.strip().upper() for s in args.symbols.split(',')]
    logger.info(f"Symbols: {SYMBOLS}")
    
    initialize_token_mappings()
    
    if args.tokens:
        tokens = [int(t.strip()) for t in args.tokens.split(',')]
    else:
        tokens = [SYMBOL_TO_TOKEN[symbol] for symbol in SYMBOLS]
    
    mode_map = {'ltp': KiteTicker("", "").MODE_LTP, 'quote': KiteTicker("", "").MODE_QUOTE, 'full': KiteTicker("", "").MODE_FULL}
    mode = mode_map[args.mode]
    
    logger.info(f"Starting {len(tokens)} symbols in {args.mode} mode")
    kws_client = KiteWebSocket(args.api_key, args.access_token)
    kws_client.subscribe_tokens(tokens, mode)
    
    try:
        kws_client.connect()
    except KeyboardInterrupt:
        kws_client.kws.close()
    except SystemExit:
        kws_client.kws.close()
    except Exception as e:
        logger.error(f"Error: {e}")
        kws_client.kws.close()

if __name__ == "__main__":
    main()
