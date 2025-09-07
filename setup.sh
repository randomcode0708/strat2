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

#python3 get_access_token.py  --request_token oDaUbgxcnafWLgXTQH3t8OfPv6BeoY5c --api_key dsn6a9hdvuon0zve --api_secret 6iusnk6vx2ef5w3to3wppjxf53zufz6l
# Access Token: 37jDJmoqfPZAYLjf0PtZ5EvaFGykV69F

# source .venv/bin/activate && python kite_websocket.py --api_key dsn6a9hdvuon0zve --access_token 37jDJmoqfPZAYLjf0PtZ5EvaFGykV69F --symbols "NETWEB,FIRSTCRY,GMDCLTD,MOSCHIP,VIMTALABS,ATULAUTO,TEGA,RBLBANK,SWIGGY,KIOCL,NATIONALUM,M&M,COALINDIA,KOTAKBANK,INFY,HCLTECH,DIVISLAB,GODREJPROP,PRESTIGE,PERSISTENT,VBL" --mode ltp
