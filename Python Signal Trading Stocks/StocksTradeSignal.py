import os
import time
import logging
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator
from datetime import datetime

load_dotenv()

# Email settings
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")
WATCHLIST = [s.strip().upper() for s in os.getenv("WATCHLIST", "AAPL").split(",")]
INTERVAL = os.getenv("INTERVAL", "5m")
FAST_SMA = int(os.getenv("FAST_SMA", 9))
SLOW_SMA = int(os.getenv("SLOW_SMA", 21))
RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
RSI_OVERSOLD = int(os.getenv("RSI_OVERSOLD", 30))
RSI_OVERBOUGHT = int(os.getenv("RSI_OVERBOUGHT", 70))
LOG_FILE = os.getenv("LOG_FILE", "signals_log.csv")
SLEEP_SECONDS = int(os.getenv("SLEEP_SECONDS", 60))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
def send_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_TO

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())
        logging.info("Email sent: %s", subject)
    except Exception as e:
        logging.exception("Failed to send email: %s", e)

def fetch_ohlcv(symbol, period="2d"):
    return yf.download(
        symbol,
        period=period,
        interval=INTERVAL,
        progress=False,
        auto_adjust=True  # or False if you want raw prices
    )


def compute_indicators(df):
    df['close'] = df['Close']
    df['sma_fast'] = df['close'].rolling(window=FAST_SMA).mean()
    df['sma_slow'] = df['close'].rolling(window=SLOW_SMA).mean()
    df['rsi'] = RSIIndicator(df['close'], window=RSI_PERIOD).rsi()
    return df

def detect_signals(df):
    if len(df) < max(FAST_SMA, SLOW_SMA) + 1:
        return None  # not enough data for SMAs

    last = df.iloc[[-1]]  # keep as dataframe for consistent indexing
    prev = df.iloc[[-2]]

    prev_fast = float(prev['sma_fast'].iloc[0])
    prev_slow = float(prev['sma_slow'].iloc[0])
    last_fast = float(last['sma_fast'].iloc[0])
    last_slow = float(last['sma_slow'].iloc[0])
    last_rsi = float(last['rsi'].iloc[0])

    cross_up = (prev_fast <= prev_slow) and (last_fast > last_slow)
    cross_down = (prev_fast >= prev_slow) and (last_fast < last_slow)

    if cross_up and last_rsi > RSI_OVERSOLD:
        return "buy"
    if cross_down and last_rsi < RSI_OVERBOUGHT:
        return "sell"
    return None

def log_signal(timestamp, symbol, signal, price, extra):
    row = {"timestamp": timestamp, "symbol": symbol, "signal": signal, "price": price, "extra": extra}
    df_row = pd.DataFrame([row])
    if not os.path.isfile(LOG_FILE):
        df_row.to_csv(LOG_FILE, index=False)
    else:
        df_row.to_csv(LOG_FILE, mode='a', header=False, index=False)

def main_loop():
    last_signals = {}
    while True:
        for symbol in WATCHLIST:
            try:
                df = fetch_ohlcv(symbol, period="7d")
                if df.empty:
                    continue
                df = compute_indicators(df)
                sig = detect_signals(df)
                price = float(df['close'].iloc[-1])
                ts = datetime.now().isoformat()

                logging.info(f"Checked {symbol} at {ts}, price={price:.2f}")

                if sig and last_signals.get(symbol) != sig:
                    subject = f"Stock Signal: {sig.upper()} {symbol}"
                    body = f"{sig.upper()} signal for {symbol}\nPrice: {price:.2f}\nTime (UTC): {ts}\nFast SMA={df['sma_fast'].iloc[-1]:.2f}, Slow SMA={df['sma_slow'].iloc[-1]:.2f}, RSI={df['rsi'].iloc[-1]:.1f}"
                    send_email(subject, body)
                    log_signal(ts, symbol, sig, price, body)
                    last_signals[symbol] = sig
            except Exception as e:
                logging.exception("Error processing %s", symbol, e)
        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main_loop()
