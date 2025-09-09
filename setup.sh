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

#source venv/bin/activate && python get_access_token.py  --request_token s7rMa2STvDAaitj23cbZfsc2cqzjtdMK --api_key dsn6a9hdvuon0zve --api_secret 6iusnk6vx2ef5w3to3wppjxf53zufz6l
# Access Token: MmlxhvDEtlgxobu4z2c1HXHBk9vwFMKn

# source .venv/bin/activate && nohup python3 kite_websocket.py --api_key dsn6a9hdvuon0zve --access_token MmlxhvDEtlgxobu4z2c1HXHBk9vwFMKn --symbols "IOLCP,MOBIKWIK,COHANCE,MOSCHIP,GMDCLTD,ASHOKLEY,JMFINANCIL,TATAMOTORS,M&M,BAJAJ-AUTO,EICHERMOT,EXIDEIND,TVSMOTOR,KAYNES,ABCAPITAL,MANAPPURAM,MARUTI,ESCORTS,ENRIN,NYKAA,POLYCAB,DIXON,BAJFINANCE,ONGC,INFY,TCS,TECHM,SBILIFE,GRSE,MAXHEALTH,PERSISTENT,FORCEMOT,PARADEEP" --mode ltp > /dev/null 2>&1 &

# source .venv/bin/activate && nohup python3 candle_builder.py --api_key dsn6a9hdvuon0zve --access_token MmlxhvDEtlgxobu4z2c1HXHBk9vwFMKn --symbols "IOLCP,MOBIKWIK,COHANCE,MOSCHIP,GMDCLTD,ASHOKLEY,JMFINANCIL,TATAMOTORS,M&M,BAJAJ-AUTO,EICHERMOT,EXIDEIND,TVSMOTOR,KAYNES,ABCAPITAL,MANAPPURAM,MARUTI,ESCORTS,ENRIN,NYKAA,POLYCAB,DIXON,BAJFINANCE,ONGC,INFY,TCS,TECHM,SBILIFE,GRSE,MAXHEALTH,PERSISTENT,FORCEMOT,PARADEEP" > /dev/null 2>&1 &