#!/bin/bash
# Setup virtual environment and install dependencies

echo "Setting up Kite Connect Access Token Generator..."

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# source venv/bin/activate && python get_access_token.py  --request_token BRTcVVKXP9pdtcOqvii8qW0lfmVlJ75A --api_key dsn6a9hdvuon0zve --api_secret 6iusnk6vx2ef5w3to3wppjxf53zufz6l
# Access Token: 40qZJZeLNYuExaF2iGuQzP1ZBomNMdR1

# source .venv/bin/activate && nohup python3 kite_websocket.py --api_key dsn6a9hdvuon0zve --access_token PMOh6hPqIiyjLR2rT6l5ikRvY8CbErfb --symbols "XXXX" --mode ltp > /dev/null 2>&1 &

# source .venv/bin/activate && nohup python3 historical_breakout_trader.py --api_key dsn6a9hdvuon0zve --access_token PMOh6hPqIiyjLR2rT6l5ikRvY8CbErfb --symbols "PAGEIND,BSE,INDUSINDBK,TRENT,VBL,ATGL,SHREEPUSHK,ADANIGREEN,BORORENEW,NETWEB,ADANIENSOL,ANANTRAJ,HUDCO,ADANIENT,MUTHOOTFIN,NBCC,SILVERBEES,AVANTEL,ENRIN,FLUOROCHEM,MRF,ETERNAL,BAJFINANCE,AXISBANK" > /dev/null 2>&1 &

#/home/masoodfortrade/strat2/historical_breakout_trader.log
#/home/masoodfortrade/strat2/trades_20250923_150005.csv

# source venv/bin/activate && python get_1min_data.py NBCC 2

# source venv/bin/activate && python historical_breakout_backtest.py --api_key dsn6a9hdvuon0zve --access_token PMOh6hPqIiyjLR2rT6l5ikRvY8CbErfb --date 2025-09-23 --symbols "PAGEIND,BSE,INDUSINDBK,TRENT,VBL,ATGL,SHREEPUSHK,ADANIGREEN,BORORENEW,NETWEB,ADANIENSOL,ANANTRAJ,HUDCO,ADANIENT,MUTHOOTFIN,NBCC,SILVERBEES,AVANTEL,ENRIN,FLUOROCHEM,MRF,ETERNAL,BAJFINANCE,AXISBANK"