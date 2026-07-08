import os
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv

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
            [{"text": "➕ Add Stock", "callback_data": "main_add_stock"}, {"text": "✏️ Edit Item", "callback_data": "main_edit_item"}],
            [{"text": "🗑️ Remove Item", "callback_data": "main_remove_item"}, {"text": "⚠️ Low Stock", "callback_data": "main_low_stock"}]
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
            process_sale(chat_id, item_data, qty, "Walk-in Customer", message_id)
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
                    text += f"• {sale['item_name']}{color_str} x{sale['quantity']}\n  🕒 {dt_str} | 👤 {sale['customer_info']}\n  💰 GHS {sale['profit']:.2f}\n\n"
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_add_stock":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only you can add stock, Boss.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            save_state(chat_id, "add_new_name")
            send_force_reply(chat_id, "➕ *Add Stock*\n\nWhat's the item called?", "e.g. iPhone 15 Screen", reply_to_message_id=message_id)
            return

        elif callback_data.startswith("color_"):
            color = callback_data[6:]
            state, data_dict = get_state(chat_id)
            if color == "Custom":
                save_state(chat_id, "add_new_color_text", data_dict)
                send_force_reply(chat_id, "➕ *What color?*\n\nType it:", "e.g. Rose Gold", reply_to_message_id=message_id)
            else:
                data_dict['color'] = color
                # Check if item exists
                conn = get_db()
                if not conn:
                    edit_message(chat_id, message_id, "❌ Database error.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                    return
                c = conn.cursor(cursor_factory=RealDictCursor)
                c.execute("SELECT * FROM stock WHERE item_name=%s AND color=%s", (data_dict['name'], color))
                existing = c.fetchone()
                c.close(); conn.close()
                
                if existing:
                    data_dict['existing_id'] = existing['id']
                    data_dict['existing_qty'] = existing['quantity']
                    data_dict['existing_cost'] = existing['cost_price']
                    data_dict['existing_sell'] = existing['selling_price']
                    save_state(chat_id, "add_existing_choice", data_dict)
                    color_str = f" ({color})" if color else ""
                    text = f"Found: *{data_dict['name']}*{color_str}\n\nQty: {existing['quantity']}\nCost: GHS {existing['cost_price']:.2f}\nSell: GHS {existing['selling_price']:.2f}\n\nWhat do you want to do?"
                    markup = {"inline_keyboard": [
                        [{"text": "📦 Top Up Stock", "callback_data": "add_topup"}, {"text": "💰 Update Prices", "callback_data": "add_update"}],
                        [{"text": "❌ Cancel", "callback_data": "main_menu"}]
                    ]}
                    edit_message(chat_id, message_id, text, reply_markup=markup)
                else:
                    save_state(chat_id, "add_new_qty", data_dict)
                    text = f"✅ *{color}*\n\nHow many?"
                    markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
                    edit_message(chat_id, message_id, text, reply_markup=markup)
                    send_force_reply(chat_id, "👇 *Type the quantity:*", "e.g. 15", reply_to_message_id=message_id)
            return

        elif callback_data == "add_topup":
            state, data_dict = get_state(chat_id)
            if state != "add_existing_choice":
                edit_message(chat_id, message_id, "❌ Session expired.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            save_state(chat_id, "add_topup_qty", data_dict)
            send_force_reply(chat_id, "📦 *Top Up Stock*\n\nHow many are you adding?", "e.g. 20", reply_to_message_id=message_id)
            return

        elif callback_data == "add_update":
            state, data_dict = get_state(chat_id)
            if state != "add_existing_choice":
                edit_message(chat_id, message_id, "❌ Session expired.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            save_state(chat_id, "add_update_cost", data_dict)
            send_force_reply(chat_id, "💰 *Update Prices*\n\nNew cost price?", "e.g. 15.50", reply_to_message_id=message_id)
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
            color_str = f" ({data_dict['color']})" if data_dict.get('color') else ""
            text = f"➕ *Confirm*\n\n{data_dict['name']}{color_str}\nQty: {data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {category}\n\nAdd it?"
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
                color_str = f" ({data_dict['color']})" if data_dict['color'] else ""
                text = f"✅ *Added!*\n\n{data_dict['name']}{color_str} x{data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {data_dict['category']}" if c.fetchone() else "❌ Already exists."
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
                    [{"text": "💵 Sell", "callback_data": f"es_{item_id}"}, {"text": "🏷️ Category", "callback_data": f"ecat_{item_id}"}],
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

        elif callback_data.startswith("ecat_"):
            item_id = int(callback_data[5:])
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            buttons = [[{"text": cat['category'], "callback_data": f"ecatset_{item_id}_{cat['category']}"}] for cat in categories[:6]]
            buttons.append([{"text": "📝 Custom", "callback_data": f"ecatcustom_{item_id}"}])
            buttons.append([{"text": "⬅️ Back", "callback_data": f"e_{item_id}"}])
            edit_message(chat_id, message_id, "✏️ *New category?*", {"inline_keyboard": buttons})

        elif callback_data.startswith("ecatset_"):
            parts = callback_data.split("_", 2)
            item_id = int(parts[1])
            category = parts[2]
            conn = get_db()
            if not conn: return
            c = conn.cursor()
            c.execute("UPDATE stock SET category=%s WHERE id=%s", (category, item_id))
            conn.commit()
            c.close(); conn.close()
            edit_message(chat_id, message_id, f"✅ Category updated to *{category}*", {"inline_keyboard": [[{"text": "✏️ More", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})

        elif callback_data.startswith("ecatcustom_"):
            item_id = int(callback_data[11:])
            save_state(chat_id, "edit_category", {"item_id": item_id})
            send_force_reply(chat_id, "✏️ *Type new category:*", "e.g. Accessories", reply_to_message_id=message_id)

        elif callback_data == "main_remove_item":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only you can remove items.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            buttons = [[{"text": cat['category'], "callback_data": f"removecat_{cat['category']}"}] for cat in categories]
            buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
            text = "🗑️ *Remove Item*\n\nWhat are we removing?"
            edit_message(chat_id, message_id, text, {"inline_keyboard": buttons})
            return

        elif callback_data.startswith("removecat_"):
            category = callback_data[10:]
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE category=%s ORDER BY item_name", (category,))
            items = c.fetchall()
            c.close(); conn.close()
            if not items:
                text = f"Nothing in *{category}*."
                markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_remove_item"}]]}
            else:
                buttons = []
                for item in items:
                    color_str = f" ({item['color']})" if item['color'] else ""
                    title = f"{item['item_name']}{color_str} [{item['quantity']}]"
                    buttons.append([{"text": title, "callback_data": f"r_{item['id']}"}])
                buttons.append([{"text": "⬅️ Back", "callback_data": "main_remove_item"}])
                text = f"🗑️ *{category}*\n\nPick one to remove:"
                markup = {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("r_"):
            item_id = int(callback_data[2:])
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            if not item:
                text = "Can't find it."
                markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_remove_item"}]]}
            else:
                color_str = f" ({item['color']})" if item['color'] else ""
                text = f"🗑️ *{item['item_name']}*{color_str}\n\nQty: {item['quantity']}\n\nWhat do you want to do?"
                markup = {"inline_keyboard": [
                    [{"text": "🗑️ Remove All", "callback_data": f"rall_{item_id}"}, {"text": "📉 Reduce Qty", "callback_data": f"rred_{item_id}"}],
                    [{"text": "⬅️ Back", "callback_data": f"removecat_{item['category']}"}]
                ]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("rall_"):
            item_id = int(callback_data[5:])
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            if item:
                color_str = f" ({item['color']})" if item['color'] else ""
                text = f"⚠️ *Delete {item['item_name']}*{color_str}?\n\nThis can't be undone."
                markup = {"inline_keyboard": [[{"text": "✅ Yes", "callback_data": f"cdel_{item_id}"}, {"text": "❌ No", "callback_data": f"r_{item_id}"}]]}
                edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("rred_"):
            item_id = int(callback_data[5:])
            if save_state(chat_id, "remove_qty", {"item_id": item_id}):
                send_force_reply(chat_id, "📉 *How many to remove?*", "e.g. 5", reply_to_message_id=message_id)

        elif callback_data.startswith("cdel_"):
            item_id = int(callback_data[5:])
            conn = get_db()
            if not conn: return
            c = conn.cursor()
            c.execute("DELETE FROM stock WHERE id=%s", (item_id,))
            conn.commit()
            c.close(); conn.close()
            text = "🗑️ *Deleted!*"
            markup = {"inline_keyboard": [[{"text": "🗑️ More", "callback_data": "main_remove_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            clear_state(chat_id)
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_summary":
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT COUNT(*) as count, SUM(profit) as total FROM sales WHERE sold_at::date = CURRENT_DATE")
            result = c.fetchone()
            c.close(); conn.close()
            count = result['count'] or 0
            total = result['total'] or 0
            today = datetime.now().strftime("%d/%m/%Y")
            text = f"📊 *Today ({today})*\n\n🛒 Sales: {count}\n💰 Profit: GHS {total:.2f}"
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

        else:
            text, markup = build_main_menu(chat_id)
            clear_state(chat_id)
            edit_message(chat_id, message_id, text, reply_markup=markup)
    
    except Exception as e:
        print(f"❌ Button error: {e}")
        edit_message(chat_id, message_id, "❌ Oops, something went wrong.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})

def process_sale(chat_id, item_data, qty, customer_info, message_id):
    try:
        conn = get_db()
        if not conn:
            send_message(chat_id, "❌ Database error.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            return
        c = conn.cursor()
        new_qty = item_data['quantity'] - qty
        profit = (item_data['selling_price'] - item_data['cost_price']) * qty
        c.execute("UPDATE stock SET quantity=%s WHERE id=%s", (new_qty, item_data['item_id']))
        c.execute("INSERT INTO sales (item_name, color, quantity, profit, sold_by, customer_info) VALUES (%s, %s, %s, %s, %s, %s)",
                  (item_data['item_name'], item_data['color'], qty, profit, chat_id, customer_info))
        conn.commit()
        c.close(); conn.close()
        color_str = f" ({item_data['color']})" if item_data['color'] else ""
        now = datetime.now().strftime("%d/%m %I:%M%p")
        text = f"✅ *Done!*\n\n{qty}x {item_data['item_name']}{color_str} sold.\n{new_qty} left.\nMade GHS {profit:.2f}."
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
            send_message(chat_id, f"✅ *{qty}x {data['item_name']}*{cs}\n\nWho's buying?",
                        {"inline_keyboard": [
                            [{"text": "🚶 Walk-in", "callback_data": f"sw_{qty}"}],
                            [{"text": "✍️ Name & Number", "callback_data": f"st_{qty}"}],
                            [{"text": "❌ Cancel", "callback_data": "main_menu"}]
                        ]})

        elif state == "sell_customer":
            ci = text if text.lower() != "walk-in" else "Walk-in Customer"
            process_sale(chat_id, data, data['qty'], ci, None)

        elif state == "add_new_name":
            data['name'] = text
            save_state(chat_id, "add_new_color_btn", data)
            send_message(chat_id, f"✅ *{text}*\n\nWhat color? (or type 'none')", {"inline_keyboard": get_color_buttons() + [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})

        elif state == "add_new_color_text":
            color = text if text.lower() != "none" else ""
            data['color'] = color
            # Check if item exists
            conn = get_db()
            if not conn:
                send_message(chat_id, "❌ Database error.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE item_name=%s AND color=%s", (data['name'], color))
            existing = c.fetchone()
            c.close(); conn.close()
            
            if existing:
                data['existing_id'] = existing['id']
                data['existing_qty'] = existing['quantity']
                data['existing_cost'] = existing['cost_price']
                data['existing_sell'] = existing['selling_price']
                save_state(chat_id, "add_existing_choice", data)
                color_str = f" ({color})" if color else ""
                msg = f"Found: *{data['name']}*{color_str}\n\nQty: {existing['quantity']}\nCost: GHS {existing['cost_price']:.2f}\nSell: GHS {existing['selling_price']:.2f}\n\nWhat do you want to do?"
                markup = {"inline_keyboard": [
                    [{"text": "📦 Top Up Stock", "callback_data": "add_topup"}, {"text": "💰 Update Prices", "callback_data": "add_update"}],
                    [{"text": "❌ Cancel", "callback_data": "main_menu"}]
                ]}
                send_message(chat_id, msg, markup)
            else:
                save_state(chat_id, "add_new_qty", data)
                send_message(chat_id, f"✅ *{color if color else 'No color'}*\n\nHow many?", {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
                send_force_reply(chat_id, "👇 *Type quantity:*", "e.g. 15")

        elif state == "add_topup_qty":
            try:
                qty = int(text)
                if qty <= 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a positive number.")
                return
            new_qty = data['existing_qty'] + qty
            conn = get_db()
            if not conn:
                send_message(chat_id, "❌ Database error.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            c = conn.cursor()
            c.execute("UPDATE stock SET quantity=%s WHERE id=%s", (new_qty, data['existing_id']))
            conn.commit()
            c.close(); conn.close()
            color_str = f" ({data['color']})" if data['color'] else ""
            send_message(chat_id, f"✅ *Updated!*\n\n{data['name']}{color_str} now {new_qty} pcs.\nPrices unchanged.",
                        {"inline_keyboard": [[{"text": "➕ More", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            clear_state(chat_id)

        elif state == "add_update_cost":
            try:
                cost = float(text)
                if cost < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a number.")
                return
            data['new_cost'] = cost
            save_state(chat_id, "add_update_sell", data)
            send_message(chat_id, f"✅ Cost: GHS {cost:.2f}\n\nNew selling price?", {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})

        elif state == "add_update_sell":
            try:
                sell = float(text)
                if sell < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a number.")
                return
            data['new_sell'] = sell
            save_state(chat_id, "add_update_qty", data)
            send_message(chat_id, f"✅ Sell: GHS {sell:.2f}\n\nQuantity to add?", {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})

        elif state == "add_update_qty":
            try:
                qty = int(text)
                if qty <= 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a positive number.")
                return
            new_qty = data['existing_qty'] + qty
            conn = get_db()
            if not conn:
                send_message(chat_id, "❌ Database error.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            c = conn.cursor()
            c.execute("UPDATE stock SET quantity=%s, cost_price=%s, selling_price=%s WHERE id=%s",
                      (new_qty, data['new_cost'], data['new_sell'], data['existing_id']))
            conn.commit()
            c.close(); conn.close()
            color_str = f" ({data['color']})" if data['color'] else ""
            send_message(chat_id, f"✅ *Updated!*\n\n{data['name']}{color_str}\n{new_qty} pcs\nCost: GHS {data['new_cost']:.2f}\nSell: GHS {data['new_sell']:.2f}",
                        {"inline_keyboard": [[{"text": "➕ More", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            clear_state(chat_id)

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
            color_str = f" ({data['color']})" if data.get('color') else ""
            t = f"➕ *Confirm*\n\n{data['name']}{color_str}\nQty: {data['qty']}\nCost: GHS {data['cost']:.2f}\nSell: GHS {data['sell']:.2f}\nCategory: {text}\n\nAdd it?"
            send_message(chat_id, t, {"inline_keyboard": [[{"text": "✅ Yes", "callback_data": "addconfirm"}, {"text": "❌ No", "callback_data": "main_menu"}]]})

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
            c.execute("SELECT item_name, color FROM stock WHERE id=%s", (data['item_id'],))
            item = c.fetchone()
            c.close(); conn.close()
            color_str = f" ({item['color']})" if item['color'] else ""
            send_message(chat_id, f"✅ *{item['item_name']}*{color_str} = {qty}",
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
            c.execute("SELECT item_name, color FROM stock WHERE id=%s", (data['item_id'],))
            item = c.fetchone()
            c.close(); conn.close()
            color_str = f" ({item['color']})" if item['color'] else ""
            send_message(chat_id, f"✅ *{item['item_name']}*{color_str} cost = GHS {cost:.2f}",
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
            c.execute("SELECT item_name, color FROM stock WHERE id=%s", (data['item_id'],))
            item = c.fetchone()
            c.close(); conn.close()
            color_str = f" ({item['color']})" if item['color'] else ""
            send_message(chat_id, f"✅ *{item['item_name']}*{color_str} sell = GHS {sell:.2f}",
                        {"inline_keyboard": [[{"text": "✏️ More", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            clear_state(chat_id)

        elif state == "edit_category":
            conn = get_db()
            if not conn: return
            c = conn.cursor()
            c.execute("UPDATE stock SET category=%s WHERE id=%s", (text, data['item_id']))
            conn.commit()
            c.close(); conn.close()
            send_message(chat_id, f"✅ Category updated to *{text}*",
                        {"inline_keyboard": [[{"text": "✏️ More", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            clear_state(chat_id)

        elif state == "remove_qty":
            try:
                qty = int(text)
                if qty <= 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Enter a positive number.")
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (data['item_id'],))
            item = c.fetchone()
            if not item:
                send_message(chat_id, "❌ Item not found.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                clear_state(chat_id)
                return
            new_qty = item['quantity'] - qty
            if new_qty < 0:
                send_message(chat_id, f"❌ Can't remove {qty}. Only {item['quantity']} in stock.")
                clear_state(chat_id)
                return
            if new_qty == 0:
                c.execute("DELETE FROM stock WHERE id=%s", (data['item_id'],))
                conn.commit()
                c.close(); conn.close()
                color_str = f" ({item['color']})" if item['color'] else ""
                send_message(chat_id, f"🗑️ *{item['item_name']}*{color_str} removed completely.",
                            {"inline_keyboard": [[{"text": "🗑️ More", "callback_data": "main_remove_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            else:
                c.execute("UPDATE stock SET quantity=%s WHERE id=%s", (new_qty, data['item_id']))
                conn.commit()
                c.close(); conn.close()
                color_str = f" ({item['color']})" if item['color'] else ""
                send_message(chat_id, f"✅ *{item['item_name']}*{color_str}\n{item['quantity']} → {new_qty}",
                            {"inline_keyboard": [[{"text": "🗑️ More", "callback_data": "main_remove_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            clear_state(chat_id)

        else:
            if chat_id in ALLOWED_IDS:
                t, m = build_main_menu(chat_id)
                send_message(chat_id, "🤔 Type /start.", m)
    except Exception as e:
        print(f"❌ Text error: {e}")
        send_message(chat_id, "❌ Error. Type /start.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})

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
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
