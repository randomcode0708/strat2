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

#source venv/bin/activate && python get_access_token.py  --request_token MY5o6a45WI2M36t7bk8Qgekg9qYrKV0z --api_key dsn6a9hdvuon0zve --api_secret 6iusnk6vx2ef5w3to3wppjxf53zufz6l
# Access Token: TtGjrZjo4W4E2jV6uuTgPUxjB9kQsE16

# source .venv/bin/activate && nohup python3 kite_websocket.py --api_key dsn6a9hdvuon0zve --access_token TtGjrZjo4W4E2jV6uuTgPUxjB9kQsE16 --symbols "MAMATA,AVANTIFEED,OFSS,WAAREEENER,TATAELXSI,MPHASIS,CGPOWER,KPITTECH,QPOWER,FLUOROCHEM,OLECTRA,TITAGARH,HDFCAMC,TIINDIA,BAJFINANCE,FORTIS,APOLLOHOSP,NESTLEIND,DRREDDY,GLENMARK,AMBER,DABUR" --mode ltp > /dev/null 2>&1 &

# source venv/bin/activate && python get_1min_data.py TCS

# source .venv/bin/activate && nohup python3 candle_builder.py --api_key dsn6a9hdvuon0zve --access_token WlobNvvYCVq6fxl6fgEBV2STVTZFK0YB --symbols "XXXXXXX" > /dev/null 2>&1 &

# source .venv/bin/activate && nohup python3 live_candle_trader.py --api_key dsn6a9hdvuon0zve --access_token WlobNvvYCVq6fxl6fgEBV2STVTZFK0YB --symbols "XXXXXXX" > /dev/null 2>&1 &