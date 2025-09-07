#!/usr/bin/env python3

import os
import sys
import time
import signal
import psutil
import logging
import argparse
import subprocess
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class TradingBotManager:
    def __init__(self):
        self.process = None
        self.shutdown_requested = False
        
    def find_existing_processes(self):
        """Find existing kite_websocket.py processes"""
        existing_pids = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                if 'kite_websocket.py' in cmdline and proc.info['pid'] != os.getpid():
                    existing_pids.append(proc.info['pid'])
                    logger.info(f"Found existing process: PID {proc.info['pid']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return existing_pids
    
    def kill_existing_processes(self):
        """Kill all existing kite_websocket.py processes"""
        pids = self.find_existing_processes()
        if not pids:
            logger.info("No existing processes found")
            return
            
        logger.info(f"Killing {len(pids)} existing processes...")
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                proc.wait(timeout=10)
                logger.info(f"Terminated process PID {pid}")
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                try:
                    proc.kill()
                    logger.info(f"Force killed process PID {pid}")
                except psutil.NoSuchProcess:
                    pass
            except Exception as e:
                logger.error(f"Failed to kill process PID {pid}: {e}")
        
        time.sleep(2)  # Wait for cleanup
    
    def start_trading_bot(self, api_key, access_token, symbols, mode='ltp'):
        """Start the kite_websocket.py process"""
        cmd = [
            sys.executable, 'kite_websocket.py',
            '--api_key', api_key,
            '--access_token', access_token,
            '--symbols', symbols,
            '--mode', mode
        ]
        
        logger.info(f"Starting trading bot with command: {' '.join(cmd)}")
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            logger.info(f"Trading bot started with PID {self.process.pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to start trading bot: {e}")
            return False
    
    def monitor_process(self):
        """Monitor the trading bot process"""
        if not self.process:
            return False
            
        # Log output in real-time
        try:
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    logger.info(f"BOT: {line.strip()}")
                if self.shutdown_requested:
                    break
                    
            return_code = self.process.poll()
            if return_code is not None:
                logger.info(f"Trading bot exited with code {return_code}")
                return False
        except Exception as e:
            logger.error(f"Error monitoring process: {e}")
            return False
            
        return True
    
    def stop_trading_bot(self):
        """Stop the trading bot gracefully"""
        if not self.process:
            return
            
        logger.info("Stopping trading bot...")
        self.shutdown_requested = True
        
        try:
            self.process.terminate()
            self.process.wait(timeout=15)
            logger.info("Trading bot stopped gracefully")
        except subprocess.TimeoutExpired:
            logger.warning("Force killing trading bot")
            self.process.kill()
            self.process.wait()
        except Exception as e:
            logger.error(f"Error stopping trading bot: {e}")
        
        self.process = None
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop_trading_bot()
        sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description='Trading Bot Manager for GCP')
    parser.add_argument('--api_key', required=True, help='Kite API Key')
    parser.add_argument('--access_token', required=True, help='Kite Access Token')
    parser.add_argument('--symbols', required=True, help='Comma-separated symbols')
    parser.add_argument('--mode', choices=['ltp', 'quote', 'full'], default='ltp', help='Streaming mode')
    parser.add_argument('--restart-on-failure', action='store_true', help='Auto-restart on failure')
    
    args = parser.parse_args()
    
    # Validate environment
    if not os.path.exists('kite_websocket.py'):
        logger.error("kite_websocket.py not found in current directory")
        sys.exit(1)
    
    manager = TradingBotManager()
    
    # Setup signal handlers
    signal.signal(signal.SIGTERM, manager.signal_handler)
    signal.signal(signal.SIGINT, manager.signal_handler)
    
    logger.info("Trading Bot Manager starting...")
    logger.info(f"Symbols: {args.symbols}")
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Auto-restart: {args.restart_on_failure}")
    
    try:
        while True:
            # Kill existing processes
            manager.kill_existing_processes()
            
            # Start trading bot
            if not manager.start_trading_bot(args.api_key, args.access_token, args.symbols, args.mode):
                logger.error("Failed to start trading bot")
                if not args.restart_on_failure:
                    sys.exit(1)
                time.sleep(30)
                continue
            
            # Monitor process
            success = manager.monitor_process()
            
            if not success and args.restart_on_failure:
                logger.warning("Trading bot failed, restarting in 30 seconds...")
                manager.stop_trading_bot()
                time.sleep(30)
                continue
            else:
                break
                
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        manager.stop_trading_bot()
        logger.info("Trading Bot Manager stopped")

if __name__ == "__main__":
    main()
