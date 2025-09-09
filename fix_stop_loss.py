#!/usr/bin/env python3
"""
Adhoc script to check existing positions and place missing stop loss orders
"""

import argparse
import sys
from datetime import datetime
from kiteconnect import KiteConnect
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_breakout_candle_data(kite, symbols):
    """
    Get the first 5-minute candle data for today (9:15 AM candle)
    
    Args:
        kite: KiteConnect instance
        symbols: List of symbol names
    
    Returns:
        dict: Symbol to candle data mapping
    """
    logger.info("Fetching breakout candle data...")
    
    # Get instruments to map symbols to tokens
    instruments = kite.instruments("NSE")
    symbol_to_token = {}
    
    for symbol in symbols:
        for instrument in instruments:
            if (instrument['tradingsymbol'] == symbol and 
                instrument['segment'] == 'NSE' and 
                instrument['instrument_type'] == 'EQ'):
                symbol_to_token[symbol] = instrument['instrument_token']
                break
    
    # Get today's 9:15 AM candle (first 5-minute candle)
    from_time = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
    to_time = datetime.now()
    
    candle_data = {}
    
    for symbol in symbols:
        if symbol in symbol_to_token:
            try:
                candles = kite.historical_data(symbol_to_token[symbol], from_time, to_time, "5minute")
                if candles:
                    first_candle = candles[0]  # First 5-minute candle (9:15-9:20)
                    candle_data[symbol] = first_candle
                    logger.info(f"{symbol} Breakout Candle - O:{first_candle['open']:.2f} H:{first_candle['high']:.2f} L:{first_candle['low']:.2f} C:{first_candle['close']:.2f}")
                else:
                    logger.warning(f"{symbol} - No candle data found")
            except Exception as e:
                logger.error(f"{symbol} - Failed to get candle data: {e}")
        else:
            logger.warning(f"{symbol} - Token not found")
    
    return candle_data

def place_stop_loss_order(kite, symbol, quantity, direction, stop_loss_price):
    """
    Place stop loss order for a given position
    
    Args:
        kite: KiteConnect instance
        symbol: Trading symbol
        quantity: Quantity for stop loss
        direction: 'BUY' or 'SELL' - direction of the main position
        stop_loss_price: Price at which to trigger stop loss
    
    Returns:
        str: Stop loss order ID if successful, None if failed
    """
    try:
        # For LONG position (BUY), stop loss is a SELL order
        # For SHORT position (SELL), stop loss is a BUY order
        sl_transaction_type = kite.TRANSACTION_TYPE_SELL if direction == 'BUY' else kite.TRANSACTION_TYPE_BUY
        position_type = "LONG" if direction == 'BUY' else "SHORT"
        
        sl_order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            tradingsymbol=symbol,
            exchange=kite.EXCHANGE_NSE,
            transaction_type=sl_transaction_type,
            quantity=abs(quantity),  # Ensure positive quantity
            order_type=kite.ORDER_TYPE_SL,
            price=stop_loss_price,
            trigger_price=stop_loss_price,
            product=kite.PRODUCT_MIS,
            validity=kite.VALIDITY_DAY
        )
        
        logger.info(f"{symbol} STOP LOSS PLACED {sl_order_id} @ {stop_loss_price:.2f} for {position_type} position (Qty: {abs(quantity)})")
        return sl_order_id
        
    except Exception as e:
        logger.error(f"{symbol} STOP LOSS FAILED: {e}")
        return None

def check_and_fix_positions(kite, candle_data):
    """
    Check existing positions and place stop loss orders for positions without them
    
    Args:
        kite: KiteConnect instance
        candle_data: Dictionary of symbol to candle data
    """
    try:
        # Get current positions
        positions = kite.positions()['net']
        
        if not positions:
            logger.info("No positions found")
            return
        
        # Get current orders to check for existing stop loss orders
        orders = kite.orders()
        
        # Create a set of symbols that already have stop loss orders
        symbols_with_sl = set()
        for order in orders:
            if (order['order_type'] == 'SL' and 
                order['status'] in ['OPEN', 'TRIGGER_PENDING']):
                symbols_with_sl.add(order['tradingsymbol'])
        
        logger.info(f"Found {len(positions)} positions, {len(symbols_with_sl)} symbols already have stop loss orders")
        
        positions_needing_sl = []
        
        for position in positions:
            symbol = position['tradingsymbol']
            quantity = position['quantity']
            
            # Skip if no position or already has stop loss
            if quantity == 0 or symbol in symbols_with_sl:
                continue
            
            # Skip if we don't have candle data for this symbol
            if symbol not in candle_data:
                logger.warning(f"{symbol} - No breakout candle data available, skipping")
                continue
            
            positions_needing_sl.append(position)
        
        if not positions_needing_sl:
            logger.info("All positions already have stop loss orders or no positions need stop loss")
            return
        
        logger.info(f"Found {len(positions_needing_sl)} positions needing stop loss orders")
        
        # Place stop loss orders for positions that need them
        for position in positions_needing_sl:
            symbol = position['tradingsymbol']
            quantity = position['quantity']
            candle = candle_data[symbol]
            
            # Determine direction and stop loss price
            if quantity > 0:  # LONG position
                direction = 'BUY'
                stop_loss_price = candle['low']
                logger.info(f"{symbol} LONG position (Qty: {quantity}) - Setting SL at breakout low: {stop_loss_price:.2f}")
            else:  # SHORT position
                direction = 'SELL'
                stop_loss_price = candle['high']
                logger.info(f"{symbol} SHORT position (Qty: {quantity}) - Setting SL at breakout high: {stop_loss_price:.2f}")
            
            # Place the stop loss order
            sl_order_id = place_stop_loss_order(kite, symbol, quantity, direction, stop_loss_price)
            
            if sl_order_id:
                logger.info(f"{symbol} ✅ Stop loss order placed successfully")
            else:
                logger.error(f"{symbol} ❌ Failed to place stop loss order")
    
    except Exception as e:
        logger.error(f"Error checking positions: {e}")

def main():
    parser = argparse.ArgumentParser(description="Fix missing stop loss orders for existing positions")
    parser.add_argument('--api_key', required=True, help='Kite API key')
    parser.add_argument('--access_token', required=True, help='Kite access token')
    parser.add_argument('--symbols', help='Comma-separated list of symbols to check (optional - will check all positions if not provided)')
    
    args = parser.parse_args()
    
    try:
        # Initialize Kite Connect
        kite = KiteConnect(api_key=args.api_key)
        kite.set_access_token(args.access_token)
        
        logger.info("Connected to Kite Connect API")
        
        # Get current positions to determine which symbols to fetch candle data for
        positions = kite.positions()['net']
        position_symbols = [pos['tradingsymbol'] for pos in positions if pos['quantity'] != 0]
        
        if not position_symbols:
            logger.info("No open positions found")
            return
        
        # If symbols are provided via command line, use those; otherwise use position symbols
        if args.symbols:
            symbols = [s.strip().upper() for s in args.symbols.split(',')]
            logger.info(f"Using provided symbols: {symbols}")
        else:
            symbols = position_symbols
            logger.info(f"Using symbols from current positions: {symbols}")
        
        # Get breakout candle data
        candle_data = get_breakout_candle_data(kite, symbols)
        
        if not candle_data:
            logger.error("No candle data retrieved. Cannot proceed.")
            return
        
        # Check positions and place missing stop loss orders
        check_and_fix_positions(kite, candle_data)
        
        logger.info("Stop loss fix operation completed")
        
    except Exception as e:
        logger.error(f"Script failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
