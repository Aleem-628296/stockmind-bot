import os
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import threading
import time

load_dotenv()
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_IDS = [int(id.strip()) for id in os.getenv("OWNER_ID", "").split(",") if id.strip()]
SECRETARY_IDS = [int(id.strip()) for id in os.getenv("SECRETARY_ID", "").split(",") if id.strip()]
ALLOWED_IDS = OWNER_IDS + SECRETARY_IDS
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

# --- DATABASE FUNCTIONS ---
def get_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        conn.autocommit = False
        return conn
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return None

def init_db():
    conn = get_db()
    if not conn:
        print("❌ Cannot initialize database")
        return
    try:
        c = conn.cursor()
        c.execute("DROP TABLE IF EXISTS user_state")
        c.execute('''CREATE TABLE IF NOT EXISTS stock
            (id SERIAL PRIMARY KEY, item_name TEXT, color TEXT, quantity INTEGER,
             cost_price REAL, selling_price REAL, category TEXT, UNIQUE(item_name, color))''')
        c.execute('''CREATE TABLE IF NOT EXISTS sales
            (id SERIAL PRIMARY KEY, item_name TEXT, color TEXT, quantity INTEGER,
             profit REAL, sold_by BIGINT, customer_info TEXT DEFAULT 'Walk-in',
             payment_status TEXT DEFAULT 'paid', reminder_count INTEGER DEFAULT 0,
             last_reminder_at TIMESTAMP,
             sold_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_state
            (chat_id BIGINT PRIMARY KEY, state TEXT, data TEXT)''')
        
        colors = ["White", "Black", "Yellow", "Green", "Red", "Purple", "Gold", "Silver", "Blue"]
        items = []
        for screen in ["iPhone Screen", "Samsung Screen", "Infinix Screen", "Tecno Screen", "iPad Touch Screen"]:
            items.append((screen, "", 1, 0.0, 0.0, "Screens & Displays"))
        for charger in ["Original Charger", "Multiple Purpose Charger", "Wireless Charging Flex"]:
            items.append((charger, "", 1, 0.0, 0.0, "Chargers & Power"))
        for part in ["Back Glass", "Housing"]:
            for color in colors:
                items.append((part, color, 1, 0.0, 0.0, "Housings & Back Covers"))
        for bat in ["iPhone Battery", "Battery Flex"]:
            items.append((bat, "", 1, 0.0, 0.0, "Batteries & Power"))
        for audio in ["Earpiece", "Ear Speaker", "Down Speaker"]:
            items.append((audio, "", 1, 0.0, 0.0, "Audio & Speakers"))
        for cam in ["Camera Lens", "Face ID Flex", "Mouthpiece (Mic)"]:
            items.append((cam, "", 1, 0.0, 0.0, "Cameras & Sensors"))
        items.append(("Down Screws", "", 1, 0.0, 0.0, "Small Parts"))

        for item in items:
            try:
                c.execute("""INSERT INTO stock (item_name, color, quantity, cost_price, selling_price, category)
                             VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (item_name, color) DO NOTHING""", item)
            except:
                pass
        conn.commit()
        print("✅ Database initialized!")
    except Exception as e:
        print(f"❌ Database init error: {e}")
        conn.rollback()
    finally:
        c.close()
        conn.close()

def save_state(chat_id, state, data_dict=None):
    conn = get_db()
    if not conn:
        return False
    try:
        data_json = json.dumps(data_dict) if data_dict else "{}"
        c = conn.cursor()
        c.execute("""INSERT INTO user_state (chat_id, state, data) VALUES (%s, %s, %s)
ON CONFLICT (chat_id) DO UPDATE SET state = EXCLUDED.state, data = EXCLUDED.data""",
                  (chat_id, state, data_json))
        conn.commit()
        c.close()
        return True
    except Exception as e:
        print(f"❌ Save state error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_state(chat_id):
    conn = get_db()
    if not conn:
        return None, {}
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT state, data FROM user_state WHERE chat_id=%s", (chat_id,))
        row = cursor.fetchone()
        cursor.close()
        if row:
            state = row['state'].strip() if row['state'] else None
            data = json.loads(row['data']) if row['data'] else {}
            return state, data
    except Exception as e:
        print(f"❌ Get state error: {e}")
    finally:
        conn.close()
    return None, {}

def clear_state(chat_id):
    conn = get_db()
    if not conn: return
    try:
        c = conn.cursor()
        c.execute("DELETE FROM user_state WHERE chat_id=%s", (chat_id,))
        conn.commit()
        c.close()
    except:
        conn.rollback()
    finally:
        conn.close()

# --- TELEGRAM API ---
def send_message(chat_id, text, reply_markup=None):
    url = f"{API_URL}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"❌ Send Error: {e}")

def send_force_reply(chat_id, text, placeholder="Type here...", reply_to_message_id=None):
    url = f"{API_URL}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {"force_reply": True, "input_field_placeholder": placeholder, "selective": True}
    }
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"❌ Force Reply Error: {e}")

def answer_callback(query_id, text=""):
    url = f"{API_URL}/answerCallbackQuery"
    data = {"callback_query_id": query_id, "text": text}
    try:
        requests.post(url, json=data, timeout=5)
    except:
        pass

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"{API_URL}/editMessageText"
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"❌ Edit Message Error: {e}")

# --- UI BUILDERS ---
def build_main_menu(chat_id):
    is_owner = chat_id in OWNER_IDS
    if is_owner:
        buttons = [
            [{"text": "📋 View Stock", "callback_data": "main_view_stock"}, {"text": "💰 Record Sale", "callback_data": "main_record_sale"}],
            [{"text": "📜 Recent Sales", "callback_data": "main_recent_sales"}, {"text": "📊 Daily Summary", "callback_data": "main_summary"}],
            [{"text": "➕ Add Stock", "callback_data": "main_add_stock"}, {"text": "✏️ Edit/Remove", "callback_data": "main_edit_item"}],
            [{"text": "⚠️ Low Stock", "callback_data": "main_low_stock"}, {"text": "💳 Pending Payments", "callback_data": "main_pending_payments"}]
        ]
        text = "📊 *VICTORY VENTURE*\n\nHey Boss! What's on your mind?"
    else:
        buttons = [
            [{"text": "📋 View Stock", "callback_data": "main_view_stock"}, {"text": "💰 Record Sale", "callback_data": "main_record_sale"}],
            [{"text": "📜 Recent Sales", "callback_data": "main_recent_sales"}, {"text": "📊 Daily Summary", "callback_data": "main_summary"}]
        ]
        text = "📊 *VICTORY VENTURE*\n\nWelcome! What can I help you with?"
    return text, {"inline_keyboard": buttons}

def get_color_buttons():
    return [
        [{"text": "⚫ Black", "callback_data": "color_Black"}, {"text": "⚪ White", "callback_data": "color_White"}],
        [{"text": "🟡 Yellow", "callback_data": "color_Yellow"}, {"text": "🟢 Green", "callback_data": "color_Green"}],
        [{"text": "🔴 Red", "callback_data": "color_Red"}, {"text": "🟣 Purple", "callback_data": "color_Purple"}],
        [{"text": "🟨 Gold", "callback_data": "color_Gold"}, {"text": "⚪ Silver", "callback_data": "color_Silver"}],
        [{"text": "🔵 Blue", "callback_data": "color_Blue"}, {"text": "📝 Custom", "callback_data": "color_Custom"}]
    ]

# --- BUTTON HANDLER ---
def button_handler(query):
    chat_id = query['message']['chat']['id']
    message_id = query['message']['message_id']
    callback_data = query['data']
    answer_callback(query['id'])
    
    try:
        if callback_data == "main_menu":
            text, markup = build_main_menu(chat_id)
            clear_state(chat_id)
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_view_stock":
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            if not categories:
                text = "Nothing here yet. Tap Add Stock and let's get your inventory set up."
                markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                buttons = [[{"text": cat['category'], "callback_data": f"viewcat_{cat['category']}"}] for cat in categories]
                buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
                text = "📋 *What are you looking for?*\n\nPick a category:"
                markup = {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("viewcat_"):
            category = callback_data[8:]
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE category=%s ORDER BY item_name", (category,))
            items = c.fetchall()
            c.close(); conn.close()
            if not items:
                text = f"Nothing in *{category}* right now."
            else:
                text = f"📋 *{category}*\n\n"
                for item in items:
                    color_str = f" ({item['color']})" if item['color'] else ""
                    text += f"• *{item['item_name']}*{color_str}\n  {item['quantity']} left | GHS {item['selling_price']:.0f}\n\n"
            markup = {"inline_keyboard": [[{"text": "📋 View Stock", "callback_data": "main_view_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_record_sale":
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock WHERE quantity > 0 ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            if not categories:
                text = "No items to sell yet. Add some stock first!"
                markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                buttons = [[{"text": cat['category'], "callback_data": f"sellcat_{cat['category']}"}] for cat in categories]
                buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
                text = "💰 *What did you sell?*\n\nPick the category:"
                markup = {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("sellcat_"):
            category = callback_data[8:]
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE category=%s AND quantity > 0 ORDER BY item_name", (category,))
            items = c.fetchall()
            c.close(); conn.close()
            if not items:
                text = f"No items in *{category}* right now."
                markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                buttons = []
                for item in items:
                    color_str = f" ({item['color']})" if item['color'] else ""
                    title = f"{item['item_name']}{color_str} ({item['quantity']})"
                    buttons.append([{"text": title, "callback_data": f"s_{item['id']}"}])
                buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
                text = "💰 *Which item?*\n\nTap to select:"
                markup = {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("s_"):
            item_id = int(callback_data[2:])
            conn = get_db()
            if not conn:
                edit_message(chat_id, message_id, "❌ Database error.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            if not item:
                text = "Hmm, can't find that item."
                markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                color_str = f" ({item['color']})" if item['color'] else ""
                if item['quantity'] <= 5:
                    text = f"💰 *{item['item_name']}*{color_str}\n\nHeads up: Only {item['quantity']} left. How many selling?"
                else:
                    text = f"💰 *{item['item_name']}*{color_str}\n\nWe've got {item['quantity']} in stock. How many selling?"
                item_data = {
                    "item_id": item['id'],
                    "item_name": item['item_name'],
                    "color": item['color'],
                    "quantity": item['quantity'],
                    "cost_price": item['cost_price'],
                    "selling_price": item['selling_price']
                }
                if save_state(chat_id, "sell_qty", item_data):
                    markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
                    edit_message(chat_id, message_id, text, reply_markup=markup)
                    send_force_reply(chat_id, "👇 *Type the quantity:*", "e.g. 5", reply_to_message_id=message_id)
                else:
                    edit_message(chat_id, message_id, "❌ Error. Please try again.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            return

        elif callback_data.startswith("sw_"):
            qty = int(callback_data[3:])
            state, item_data = get_state(chat_id)
            if state != "sell_confirm" or not item_data:
                edit_message(chat_id, message_id, "❌ Session expired. Start over.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            item_data['qty'] = qty
            item_data['payment'] = 'paid'
            save_state(chat_id, "sell_customer", item_data)
            process_sale(chat_id, item_data, qty, "Walk-in Customer", 'paid', message_id)
            return

        elif callback_data.startswith("st_"):
            qty = int(callback_data[3:])
            state, item_data = get_state(chat_id)
            if state != "sell_confirm" or not item_data:
                edit_message(chat_id, message_id, "❌ Session expired. Start over.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            item_data['qty'] = qty
            save_state(chat_id, "sell_customer", item_data)
            send_force_reply(chat_id, "💰 *Who's buying?*\n\nType their name and number:", "e.g. John 0241234567", reply_to_message_id=message_id)
            return

        elif callback_data.startswith("sp_"):
            qty = int(callback_data[3:])
            state, item_data = get_state(chat_id)
            if state != "sell_confirm" or not item_data:
                edit_message(chat_id, message_id, "❌ Session expired. Start over.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            item_data['qty'] = qty
            item_data['payment'] = 'credit'
            save_state(chat_id, "sell_credit_customer", item_data)
            send_force_reply(chat_id, "💳 *Credit sale*\n\nWho's taking this on credit?\n\nType their name and number:", "e.g. Kwame 0241234567", reply_to_message_id=message_id)
            return

        elif callback_data == "main_recent_sales":
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM sales ORDER BY sold_at DESC LIMIT 10")
            sales = c.fetchall()
            c.close(); conn.close()
            if not sales:
                text = "No sales yet today."
            else:
                text = "📜 *Recent Sales*\n\n"
                for sale in sales:
                    color_str = f" ({sale['color']})" if sale['color'] else ""
                    dt_str = sale['sold_at'].strftime("%d/%m %I:%M%p") if sale['sold_at'] else "?"
                    status = "💳" if sale['payment_status'] == 'credit' else "✅"
                    text += f"{status} {sale['item_name']}{color_str} x{sale['quantity']}\n  🕒 {dt_str} | 👤 {sale['customer_info']}\n  💰 GHS {sale['profit']:.2f}\n\n"
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_add_stock":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only you can add stock, Boss.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            buttons = [[{"text": cat['category'], "callback_data": f"addcat_{cat['category']}"}] for cat in categories]
            buttons.append([{"text": "➕ Add New Item", "callback_data": "addstock_new"}])
            buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
            text = "➕ *Add Stock*\n\nWhat are we restocking?"
            edit_message(chat_id, message_id, text, {"inline_keyboard": buttons})
            return

        elif callback_data.startswith("addcat_"):
            category = callback_data[7:]
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE category=%s ORDER BY item_name", (category,))
            items = c.fetchall()
            c.close(); conn.close()
            if not items:
                text = f"Nothing in *{category}*."
                markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_add_stock"}]]}
            else:
                buttons = []
                for item in items:
                    color_str = f" ({item['color']})" if item['color'] else ""
                    title = f"{item['item_name']}{color_str} [{item['quantity']}]"
                    buttons.append([{"text": title, "callback_data": f"a_{item['id']}"}])
                buttons.append([{"text": "⬅️ Back", "callback_data": "main_add_stock"}])
                text = f"➕ *{category}*\n\nWhat are you restocking?"
                markup = {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("a_"):
            item_id = int(callback_data[2:])
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            if not item:
                text = "Can't find that item."
                markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_add_stock"}]]}
            else:
                color_str = f" ({item['color']})" if item['color'] else ""
                text = f"➕ *{item['item_name']}*{color_str}\n\nCurrently: {item['quantity']}\n\nHow many adding?"
                item_data = {"item_id": item['id'], "item_name": item['item_name'], "color": item['color'], "current_qty": item['quantity']}
                if save_state(chat_id, "add_qty", item_data):
                    markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
                    edit_message(chat_id, message_id, text, reply_markup=markup)
                    send_force_reply(chat_id, "👇 *Type the quantity:*", "e.g. 20", reply_to_message_id=message_id)
                else:
                    edit_message(chat_id, message_id, "❌ Error. Try again.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            return

        elif callback_data == "addstock_new":
            if chat_id not in OWNER_IDS: return
            save_state(chat_id, "add_new_name")
            send_force_reply(chat_id, "➕ *New Item*\n\nWhat's the item called?", "e.g. iPhone 15 Screen", reply_to_message_id=message_id)
            return

        elif callback_data.startswith("color_"):
            color = callback_data[6:]
            state, data_dict = get_state(chat_id)
            if color == "Custom":
                save_state(chat_id, "add_new_color_text", data_dict)
                send_force_reply(chat_id, "➕ *What color?*\n\nType it:", "e.g. Rose Gold", reply_to_message_id=message_id)
            else:
                data_dict['color'] = color
                save_state(chat_id, "add_new_qty", data_dict)
                text = f"✅ *{color}*\n\nHow many?"
                markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
                edit_message(chat_id, message_id, text, reply_markup=markup)
                send_force_reply(chat_id, "👇 *Type the quantity:*", "e.g. 15", reply_to_message_id=message_id)
            return

        elif callback_data == "addcat_custom":
            state, data_dict = get_state(chat_id)
            save_state(chat_id, "add_new_category_text", data_dict)
            send_force_reply(chat_id, f"✅ Sell: GHS {data_dict.get('sell', 0):.2f}\n\nWhat category?", "e.g. Tools", reply_to_message_id=message_id)
            return

        elif callback_data.startswith("selcat_"):
            category = callback_data[7:]
            state, data_dict = get_state(chat_id)
            data_dict['category'] = category
            save_state(chat_id, "add_new_confirm", data_dict)
            text = f"➕ *Confirm*\n\n{data_dict['name']}\nColor: {data_dict.get('color', 'None')}\nQty: {data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {category}\n\nAdd it?"
            markup = {"inline_keyboard": [[{"text": "✅ Yes", "callback_data": "addconfirm"}, {"text": "❌ No", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "addconfirm":
            state, data_dict = get_state(chat_id)
            if not all(k in data_dict for k in ['name', 'color', 'qty', 'cost', 'sell', 'category']):
                edit_message(chat_id, message_id, "❌ Missing info.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                clear_state(chat_id)
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor()
            try:
                c.execute("""INSERT INTO stock (item_name, color, quantity, cost_price, selling_price, category)
                             VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (item_name, color) DO NOTHING RETURNING id""",
                          (data_dict['name'], data_dict['color'], data_dict['qty'], data_dict['cost'], data_dict['sell'], data_dict['category']))
                conn.commit()
                text = f"✅ *Added!*\n\n{data_dict['name']} ({data_dict['color']}) x{data_dict['qty']}" if c.fetchone() else "❌ Already exists."
            except Exception as e:
                text = f"❌ Error: {e}"
            finally:
                c.close(); conn.close()
            markup = {"inline_keyboard": [[{"text": "➕ More", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            clear_state(chat_id)
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_edit_item":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only you can edit items.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            buttons = [[{"text": cat['category'], "callback_data": f"editcat_{cat['category']}"}] for cat in categories]
            buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
            text = "✏️ *Edit Item*\n\nWhat are we changing?"
            edit_message(chat_id, message_id, text, {"inline_keyboard": buttons})
            return

        elif callback_data.startswith("editcat_"):
            category = callback_data[8:]
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE category=%s ORDER BY item_name", (category,))
            items = c.fetchall()
            c.close(); conn.close()
            if not items:
                text = f"Nothing in *{category}*."
                markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_edit_item"}]]}
            else:
                buttons = []
                for item in items:
                    color_str = f" ({item['color']})" if item['color'] else ""
                    title = f"{item['item_name']}{color_str} [{item['quantity']}]"
                    buttons.append([{"text": title, "callback_data": f"e_{item['id']}"}])
                buttons.append([{"text": "⬅️ Back", "callback_data": "main_edit_item"}])
                text = f"✏️ *{category}*\n\nPick one:"
                markup = {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("e_"):
            item_id = int(callback_data[2:])
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            if not item:
                text = "Can't find it."
                markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_edit_item"}]]}
            else:
                color_str = f" ({item['color']})" if item['color'] else ""
                text = f"✏️ *{item['item_name']}*{color_str}\n\nQty: {item['quantity']}\nCost: GHS {item['cost_price']:.2f}\nSell: GHS {item['selling_price']:.2f}\n\nWhat to change?"
                markup = {"inline_keyboard": [
                    [{"text": "📦 Qty", "callback_data": f"eq_{item_id}"}, {"text": "💰 Cost", "callback_data": f"ec_{item_id}"}],
                    [{"text": "💵 Sell", "callback_data": f"es_{item_id}"}, {"text": "🗑️ Delete", "callback_data": f"del_{item_id}"}],
                    [{"text": "⬅️ Back", "callback_data": f"editcat_{item['category']}"}]
                ]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("eq_"):
            item_id = int(callback_data[3:])
            if save_state(chat_id, "edit_qty", {"item_id": item_id}):
                send_force_reply(chat_id, "✏️ *New quantity?*", "e.g. 50", reply_to_message_id=message_id)

        elif callback_data.startswith("ec_"):
            item_id = int(callback_data[3:])
            if save_state(chat_id, "edit_cost", {"item_id": item_id}):
                send_force_reply(chat_id, "✏️ *New cost price?*", "e.g. 15.50", reply_to_message_id=message_id)

        elif callback_data.startswith("es_"):
            item_id = int(callback_data[3:])
            if save_state(chat_id, "edit_sell", {"item_id": item_id}):
                send_force_reply(chat_id, "✏️ *New selling price?*", "e.g. 25.00", reply_to_message_id=message_id)

        elif callback_data.startswith("del_"):
            item_id = int(callback_data[4:])
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            if item:
                color_str = f" ({item['color']})" if item['color'] else ""
                text = f"⚠️ *Delete {item['item_name']}*{color_str}?\n\nThis can't be undone."
                markup = {"inline_keyboard": [[{"text": "✅ Yes", "callback_data": f"cdel_{item_id}"}, {"text": "❌ No", "callback_data": f"e_{item_id}"}]]}
                edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("cdel_"):
            item_id = int(callback_data[5:])
            conn = get_db()
            if not conn: return
            c = conn.cursor()
            c.execute("DELETE FROM stock WHERE id=%s", (item_id,))
            conn.commit()
            c.close(); conn.close()
            text = "🗑️ *Deleted!*"
            markup = {"inline_keyboard": [[{"text": "✏️ More", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            clear_state(chat_id)
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_summary":
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("""SELECT
                COUNT(*) as total_sales,
                COALESCE(SUM(profit), 0) as total_profit,
                COALESCE(SUM(CASE WHEN payment_status='paid' THEN profit ELSE 0 END), 0) as paid_amount,
                COALESCE(SUM(CASE WHEN payment_status='credit' THEN profit ELSE 0 END), 0) as pending_amount,
                COUNT(CASE WHEN payment_status='credit' THEN 1 END) as pending_count
                FROM sales WHERE sold_at::date = CURRENT_DATE""")
            result = c.fetchone()
            c.close(); conn.close()
            today = datetime.now().strftime("%d/%m/%Y")
            text = f"📊 *Today ({today})*\n\n"
            text += f"🛒 Sales: {result['total_sales']}\n"
            text += f"💰 Total: GHS {result['total_profit']:.2f}\n"
            text += f"✅ Collected: GHS {result['paid_amount']:.2f}\n"
            if result['pending_count'] > 0:
                text += f"💳 Pending: GHS {result['pending_amount']:.2f} ({result['pending_count']})"
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_low_stock":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only you can see this.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE quantity <= 5 ORDER BY quantity ASC")
            items = c.fetchall()
            c.close(); conn.close()
            if not items:
                text = "✅ All stocked up!"
            else:
                text = "⚠️ *Running Low*\n\n"
                for item in items:
                    color_str = f" ({item['color']})" if item['color'] else ""
                    text += f"• *{item['item_name']}*{color_str} — {item['quantity']} left\n"
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_pending_payments":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only you can see this.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM sales WHERE payment_status='credit' ORDER BY sold_at ASC")
            pending = c.fetchall()
            c.close(); conn.close()
            if not pending:
                text = "✅ No pending payments!"
                markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                text = f"💳 *Pending Payments ({len(pending)})*\n\n"
                buttons = []
                for sale in pending[:6]:
                    color_str = f" ({sale['color']})" if sale['color'] else ""
                    text += f"• {sale['item_name']}{color_str} x{sale['quantity']}\n  👤 {sale['customer_info']} | GHS {sale['profit']:.2f}\n\n"
                    buttons.append([{"text": f"✅ {sale['customer_info']}", "callback_data": f"markpaid_{sale['id']}"}])
                buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
                markup = {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("markpaid_"):
            sale_id = int(callback_data[9:])
            conn = get_db()
            if not conn: return
            c = conn.cursor()
            c.execute("UPDATE sales SET payment_status='paid' WHERE id=%s", (sale_id,))
            conn.commit()
            c.close(); conn.close()
            text = "✅ *Sorted!*\n\nPayment marked as received."
            markup = {"inline_keyboard": [[{"text": "💳 More Pending", "callback_data": "main_pending_payments"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        else:
            text, markup = build_main_menu(chat_id)
            clear_state(chat_id)
            edit_message(chat_id, message_id, text, reply_markup=markup)
    
    except Exception as e:
        print(f"❌ Button error: {e}")
        edit_message(chat_id, message_id, "❌ Oops, something went wrong.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})

def process_sale(chat_id, item_data, qty, customer_info, payment_status, message_id):
    try:
        conn = get_db()
        if not conn:
            send_message(chat_id, "❌ Database error.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            return
        c = conn.cursor()
        new_qty = item_data['quantity'] - qty
        profit = (item_data['selling_price'] - item_data['cost_price']) * qty
        c.execute("UPDATE stock SET quantity=%s WHERE id=%s", (new_qty, item_data['item_id']))
        c.execute("""INSERT INTO sales (item_name, color, quantity, profit, sold_by, customer_info, payment_status)
                     VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                  (item_data['item_name'], item_data['color'], qty, profit, chat_id, customer_info, payment_status))
        conn.commit()
        c.close(); conn.close()
        color_str = f" ({item_data['color']})" if item_data['color'] else ""
        now = datetime.now().strftime("%d/%m %I:%M%p")
        if payment_status == 'paid':
            text = f"✅ *Done!*\n\n{qty}x {item_data['item_name']}{color_str} sold.\n{new_qty} left.\nMade GHS {profit:.2f}."
        else:
            text = f"💳 *Credit Sale*\n\n{qty}x {item_data['item_name']}{color_str} to {customer_info}.\n{new_qty} left.\nPending: GHS {profit:.2f}"
        markup = {"inline_keyboard": [[{"text": "💰 Another", "callback_data": "main_record_sale"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        if chat_id in SECRETARY_IDS and OWNER_IDS:
            for owner in OWNER_IDS:
                send_message(owner, f"📢 {customer_info} bought {qty}x {item_data['item_name']}{color_str}.\nProfit: GHS {profit:.2f}")
        clear_state(chat_id)
    except Exception as e:
        print(f"❌ Sale error: {e}")
        send_message(chat_id, "❌ Error recording sale.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
        clear_state(chat_id)

# --- TEXT HANDLER ---
def handle_text_message(chat_id, text):
    text = text.strip()
    if text in ("/start", "/reset"):
        if chat_id not in ALLOWED_IDS:
            send_message(chat_id, "⛔ Access Denied.")
            return
        t, m = build_main_menu(chat_id)
        send_message(chat_id, t, m)
        clear_state(chat_id)
        return

    state, data = get_state(chat_id)
    if not state:
        if chat_id in ALLOWED_IDS:
            t, m = build_main_menu(chat_id)
            send_message(chat_id, "🤔 Type /start to begin.", m)
        return

    try:
        if state == "sell_qty":
            try:
                qty = int(text)
                if qty <= 0 or qty > data.get('quantity', 0):
                    send_message(chat_id, f"❌ Enter 1-{data.get('quantity', 0)}.")
                    return
            except ValueError:
                send_message(chat_id, "❌ Enter a number.")
                return
            data['qty'] = qty
            save_state(chat_id, "sell_confirm", data)
            cs = f" ({data['color']})" if data.get('color') else ""
            send_message(chat_id, f"✅ *{qty}x {data['item_name']}*{cs}\n\nHow's payment?",
                        {"inline_keyboard": [
                            [{"text": "💵 Paid Now", "callback_data": f"sw_{qty}"}],
                            [{"text": "💳 Pay Later", "callback_data": f"sp_{qty}"}],
                            [{"text": "❌ Cancel", "callback_data": "main_menu"}]
                        ]})

        elif state == "sell_customer":
            ci = text if text.lower() != "walk-in" else "Walk-in Customer"
            process_sale(chat_id, data, data['qty'], ci, 'paid', None)

        elif state == "sell_credit_customer":
            ci = text if text.lower() != "walk-in" else "Unknown"
            process_sale(chat_id, data, data['qty'], ci, 'credit', None)

        elif state == "add_qty":
            try:
                qty = int(text)
                if qty <= 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a positive number.")
                return
            new_qty = data['current_qty'] + qty
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("UPDATE stock SET quantity=%s WHERE id=%s", (new_qty, data['item_id']))
            conn.commit()
            c.close(); conn.close()
            send_message(chat_id, f"✅ *{data['item_name']}*\n{data['current_qty']} → {new_qty}",
                        {"inline_keyboard": [[{"text": "➕ More", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            clear_state(chat_id)

        elif state == "edit_qty":
            try:
                qty = int(text)
                if qty < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a number.")
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("UPDATE stock SET quantity=%s WHERE id=%s", (qty, data['item_id']))
            conn.commit()
            c.execute("SELECT item_name FROM stock WHERE id=%s", (data['item_id'],))
            item = c.fetchone()
            c.close(); conn.close()
            send_message(chat_id, f"✅ *{item['item_name']}* = {qty}" if item else "✅ Updated.",
                        {"inline_keyboard": [[{"text": "✏️ More", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            clear_state(chat_id)

        elif state == "edit_cost":
            try:
                cost = float(text)
                if cost < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a number.")
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("UPDATE stock SET cost_price=%s WHERE id=%s", (cost, data['item_id']))
            conn.commit()
            c.execute("SELECT item_name FROM stock WHERE id=%s", (data['item_id'],))
            item = c.fetchone()
            c.close(); conn.close()
            send_message(chat_id, f"✅ *{item['item_name']}* cost = GHS {cost:.2f}" if item else "✅ Updated.",
                        {"inline_keyboard": [[{"text": "✏️ More", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            clear_state(chat_id)

        elif state == "edit_sell":
            try:
                sell = float(text)
                if sell < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a number.")
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("UPDATE stock SET selling_price=%s WHERE id=%s", (sell, data['item_id']))
            conn.commit()
            c.execute("SELECT item_name FROM stock WHERE id=%s", (data['item_id'],))
            item = c.fetchone()
            c.close(); conn.close()
            send_message(chat_id, f"✅ *{item['item_name']}* sell = GHS {sell:.2f}" if item else "✅ Updated.",
                        {"inline_keyboard": [[{"text": "✏️ More", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            clear_state(chat_id)

        elif state == "add_new_name":
            data['name'] = text
            save_state(chat_id, "add_new_color_btn", data)
            send_message(chat_id, f"✅ *{text}*\n\nWhat color?", {"inline_keyboard": get_color_buttons() + [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})

        elif state == "add_new_color_text":
            data['color'] = text
            save_state(chat_id, "add_new_qty", data)
            send_message(chat_id, f"✅ *{text}*\n\nHow many?", {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
            send_force_reply(chat_id, "👇 *Type quantity:*", "e.g. 15")

        elif state == "add_new_qty":
            try:
                qty = int(text)
                if qty <= 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a positive number.")
                return
            data['qty'] = qty
            save_state(chat_id, "add_new_cost", data)
            send_message(chat_id, f"✅ *{qty}*\n\nCost price?", {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})

        elif state == "add_new_cost":
            try:
                cost = float(text)
                if cost < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a number.")
                return
            data['cost'] = cost
            save_state(chat_id, "add_new_sell", data)
            send_message(chat_id, f"✅ Cost: GHS {cost:.2f}\n\nSelling price?", {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})

        elif state == "add_new_sell":
            try:
                sell = float(text)
                if sell < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a number.")
                return
            data['sell'] = sell
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            btns = [[{"text": c['category'], "callback_data": f"selcat_{c['category']}"}] for c in (categories or [])[:5]]
            btns.append([{"text": "📝 Custom", "callback_data": "addcat_custom"}])
            btns.append([{"text": "❌ Cancel", "callback_data": "main_menu"}])
            send_message(chat_id, f"✅ Sell: GHS {sell:.2f}\n\nCategory?", {"inline_keyboard": btns})

        elif state == "add_new_category_text":
            data['category'] = text
            save_state(chat_id, "add_new_confirm", data)
            t = f"➕ *Confirm*\n\n{data['name']}\nColor: {data.get('color', 'None')}\nQty: {data['qty']}\nCost: GHS {data['cost']:.2f}\nSell: GHS {data['sell']:.2f}\nCategory: {text}\n\nAdd it?"
            send_message(chat_id, t, {"inline_keyboard": [[{"text": "✅ Yes", "callback_data": "addconfirm"}, {"text": "❌ No", "callback_data": "main_menu"}]]})

        else:
            if chat_id in ALLOWED_IDS:
                t, m = build_main_menu(chat_id)
                send_message(chat_id, "🤔 Type /start.", m)
    except Exception as e:
        print(f"❌ Text error: {e}")
        send_message(chat_id, "❌ Error. Type /start.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})

# --- BACKGROUND REMINDER TASK ---
def send_payment_reminders():
    while True:
        try:
            time.sleep(1800)
            now = datetime.now()
            hour = now.hour
            if hour < 8 or hour >= 20:
                continue
            conn = get_db()
            if not conn:
                continue
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("""SELECT * FROM sales
                         WHERE payment_status='credit'
                         AND reminder_count < 6
                         AND (last_reminder_at IS NULL OR last_reminder_at < %s)""",
                      (now - timedelta(hours=2),))
            pending = c.fetchall()
            for sale in pending:
                for owner in OWNER_IDS:
                    color_str = f" ({sale['color']})" if sale['color'] else ""
                    msg = f"💳 *Payment Reminder*\n\n{sale['customer_info']} owes GHS {sale['profit']:.2f}\nFor {sale['item_name']}{color_str}\n\nTap to mark as paid:"
                    markup = {"inline_keyboard": [[{"text": "✅ Mark Paid", "callback_data": f"markpaid_{sale['id']}"}]]}
                    send_message(owner, msg, markup)
                c.execute("""UPDATE sales SET reminder_count=reminder_count+1, last_reminder_at=%s WHERE id=%s""",
                          (now, sale['id']))
            conn.commit()
            c.close(); conn.close()
        except Exception as e:
            print(f"❌ Reminder error: {e}")

# --- WEBHOOK ---
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    update = request.get_json()
    try:
        if 'message' in update:
            msg = update['message']
            cid = msg['chat']['id']
            if cid not in ALLOWED_IDS:
                if 'text' in msg and msg['text'].strip() == "/start":
                    send_message(cid, "⛔ Access Denied.")
                return jsonify({"ok": True})
            if 'text' in msg:
                handle_text_message(cid, msg['text'])
        elif 'callback_query' in update:
            cb = update['callback_query']
            cid = cb['message']['chat']['id']
            if cid not in ALLOWED_IDS:
                return jsonify({"ok": True})
            button_handler(cb)
    except Exception as e:
        print(f"❌ Error: {e}")
    return jsonify({"ok": True})

@app.route('/setup', methods=['GET'])
def setup_webhook():
    if not WEBHOOK_URL: return "WEBHOOK_URL not set."
    return requests.post(f"{API_URL}/setWebhook", json={"url": WEBHOOK_URL}).text

@app.route('/', methods=['GET'])
def index():
    return "Victory Venture Bot is running!"

if __name__ == '__main__':
    init_db()
    reminder_thread = threading.Thread(target=send_payment_reminders, daemon=True)
    reminder_thread.start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
