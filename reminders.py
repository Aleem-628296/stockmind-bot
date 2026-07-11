import os
import time
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from datetime import datetime
from dotenv import load_dotenv
import urllib.parse

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SECRETARY_IDS = [int(id.strip()) for id in os.getenv("SECRETARY_ID", "").split(",") if id.strip()]
NOTIFICATION_IDS = [int(id.strip()) for id in os.getenv("NOTIFICATION_IDS", "").split(",") if id.strip()]
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
DATABASE_URL = os.getenv("DATABASE_URL")

LOG_FILE = "reminders_log.json"

def load_log():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_log(log_data):
    with open(LOG_FILE, 'w') as f:
        json.dump(log_data, f)

def send_message(chat_id, text):
    url = f"{API_URL}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Reminder Send Error: {e}")

def get_db_connection():
    """Parse DATABASE_URL and connect with IPv4 forced"""
    parsed = urllib.parse.urlparse(DATABASE_URL)
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path[1:],
        connect_timeout=10
    )
    return conn

def get_pending_sales():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM sales WHERE payment_status='pending'")
    sales = cur.fetchall()
    cur.close()
    conn.close()
    return sales

def run_reminders():
    log_data = load_log()
    sales = get_pending_sales()
    now = datetime.now()
    current_hour = now.hour
    current_date = now.strftime("%Y-%m-%d")
    
    notify_targets = NOTIFICATION_IDS if NOTIFICATION_IDS else SECRETARY_IDS
    
    for sale in sales:
        sale_id = str(sale['id'])
        dt = sale['sold_at']
        if not dt:
            continue
            
        try:
            if isinstance(dt, str):
                dt_obj = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
            else:
                dt_obj = dt
        except Exception:
            continue
            
        diff = now - dt_obj
        hours_passed = int(diff.total_seconds() // 3600)
        
        color_str = f" ({sale['color']})" if sale['color'] else ""
        item_name = f"{sale['item_name']}{color_str}"
        customer = sale['customer_info']
        amount = sale['profit']
        
        # Hourly reminders (1h to 6h)
        if 1 <= hours_passed <= 6:
            log_key = f"{sale_id}_h{hours_passed}"
            if log_key not in log_data:
                msg = f"⏳ *REMINDER ({hours_passed}h)*\n\n{customer} owes GHS {amount:.2f} for {item_name}."
                for target_id in notify_targets:
                    send_message(target_id, msg)
                log_data[log_key] = True
                
        # End of day reminder at 19:00
        if current_hour == 19:
            eod_key = f"{sale_id}_eod_{current_date}"
            if eod_key not in log_data:
                msg = f"🔔 *END OF DAY*\n\n{customer} owes GHS {amount:.2f} for {item_name}. Collect before closing."
                for target_id in notify_targets:
                    send_message(target_id, msg)
                log_data[eod_key] = True
            
    save_log(log_data)

if __name__ == "__main__":
    print("Reminder system started... Running every 15 minutes.")
    while True:
        try:
            run_reminders()
        except Exception as e:
            print(f"Error in reminder loop: {e}")
        time.sleep(900)
