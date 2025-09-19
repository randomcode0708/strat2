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

# source venv/bin/activate && python get_access_token.py  --request_token UYStbSXu6O0sr3mSnzu30BKIvAQDJFyW --api_key dsn6a9hdvuon0zve --api_secret 6iusnk6vx2ef5w3to3wppjxf53zufz6l
# Access Token: 40qZJZeLNYuExaF2iGuQzP1ZBomNMdR1

# source .venv/bin/activate && nohup python3 kite_websocket.py --api_key dsn6a9hdvuon0zve --access_token 4FIY6PJkTG5QgnsZdyTBL3nj3cx9mrgY --symbols "XXXX" --mode ltp > /dev/null 2>&1 &

# source .venv/bin/activate && nohup python3 historical_breakout_trader.py --api_key dsn6a9hdvuon0zve --access_token 4FIY6PJkTG5QgnsZdyTBL3nj3cx9mrgY --symbols "INDUSINDBK,TRENT,GODFRYPHLP,IRMENERGY,POONAWALLA,DENTA,HITECH,HERITGFOOD,BANCOINDIA,TATAINVEST,ZENTEC,NETWEB,LICHSGFIN,LAURUSLABS,SAMMAANCAP,AUROPHARMA,ETERNAL,HYUNDAI,PNBHOUSING,COFORGE,CAMS,ASHOKLEY,NYKAA,TVSMOTOR,DIXON,POLYCAB,SILVERBEES,VOLTAS,ABB,DRREDDY,SWIGGY,HDFCAMC,FLUOROCHEM,AXISBANK,NIFTYBEES,KOTAKBANK" > /dev/null 2>&1 &

# source venv/bin/activate && python get_1min_data.py TCS 

# source .venv/bin/activate && nohup python3 candle_builder.py --api_key dsn6a9hdvuon0zve --access_token WlobNvvYCVq6fxl6fgEBV2STVTZFK0YB --symbols "XXXXXXX" > /dev/null 2>&1 &

# source .venv/bin/activate && nohup python3 live_candle_trader.py --api_key dsn6a9hdvuon0zve --access_token WlobNvvYCVq6fxl6fgEBV2STVTZFK0YB --symbols "XXXXXXX" > /dev/null 2>&1 &