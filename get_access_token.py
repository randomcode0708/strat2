#!/usr/bin/env python3
"""Kite Connect Access Token Generator"""

import argparse
import sys
from kiteconnect import KiteConnect

def get_access_token(api_key, request_token, api_secret):
    """Generate access token using Kite Connect API"""
    kite = KiteConnect(api_key=api_key)
    return kite.generate_session(request_token, api_secret=api_secret)

def interactive_mode():
    """Get credentials from user input"""
    print("=== Kite Connect Access Token Generator ===\n")
    
    api_key = input("API Key: ").strip()
    if not api_key:
        print("Error: API Key required")
        return None
        
    request_token = input("Request Token: ").strip()
    if not request_token:
        print("Error: Request Token required")
        return None
        
    api_secret = input("API Secret: ").strip()
    if not api_secret:
        print("Error: API Secret required")
        return None
        
    return api_key, request_token, api_secret

def main():
    parser = argparse.ArgumentParser(description="Generate Kite Connect access token")
    parser.add_argument('--api_key', help='API key')
    parser.add_argument('--request_token', help='Request token') 
    parser.add_argument('--api_secret', help='API secret')
    parser.add_argument('--json', action='store_true', help='JSON output')
    
    args = parser.parse_args()
    
    if not all([args.api_key, args.request_token, args.api_secret]):
        if any([args.api_key, args.request_token, args.api_secret]):
            print("Error: All three arguments required")
            sys.exit(1)
        
        result = interactive_mode()
        if result is None:
            sys.exit(1)
        api_key, request_token, api_secret = result
    else:
        api_key, request_token, api_secret = args.api_key, args.request_token, args.api_secret
    
    try:
        session_data = get_access_token(api_key, request_token, api_secret)
        
        if args.json:
            import json
            print(json.dumps(session_data, indent=2))
        else:
            print(f"\nAccess Token: {session_data['access_token']}")
            print(f"User ID: {session_data['user_id']}")
            print(f"User: {session_data['user_name']} ({session_data['email']})")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
