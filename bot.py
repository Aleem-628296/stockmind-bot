import os
import sqlite3
import json
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_IDS = [int(id.strip()) for id in os.getenv("OWNER_ID", "").split(",") if id.strip()]
SECRETARY_IDS = [int(id.strip()) for id in os.getenv("SECRETARY_ID", "").split(",") if id.strip()]
NOTIFICATION_IDS = [int(id.strip()) for id in os.getenv("NOTIFICATION_IDS", "").split(",") if id.strip()]
ALLOWED_IDS = OWNER_IDS + SECRETARY_IDS
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# --- DATABASE FUNCTIONS ---
def init_db():
    conn = sqlite3.connect('stock.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL;')
    c.execute('''CREATE TABLE IF NOT EXISTS stock
    (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT, color TEXT, quantity INTEGER,
    cost_price REAL, selling_price REAL, category TEXT, UNIQUE(item_name, color))''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales
    (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT, color TEXT, quantity INTEGER,
    profit REAL, sold_by INTEGER, customer_info TEXT, sold_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_state
    (chat_id INTEGER PRIMARY KEY, state TEXT, data TEXT)''')
    
    try:
        c.execute("ALTER TABLE sales ADD COLUMN customer_info TEXT DEFAULT 'Walk-in'")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE sales ADD COLUMN payment_status TEXT DEFAULT 'paid'")
    except sqlite3.OperationalError:
        pass

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
    
    c.executemany("INSERT OR IGNORE INTO stock (item_name, color, quantity, cost_price, selling_price, category) VALUES (?, ?, ?, ?, ?, ?)", items)
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect('stock.db', timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def save_state(chat_id, state, data_dict=None):
    conn = get_db()
    data_json = json.dumps(data_dict) if data_dict else "{}"
    conn.execute("INSERT OR REPLACE INTO user_state (chat_id, state, data) VALUES (?, ?, ?)", (chat_id, state, data_json))
    conn.commit()
    conn.close()

def get_state(chat_id):
    conn = get_db()
    row = conn.execute("SELECT state, data FROM user_state WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    if row:
        try:
            return row['state'], json.loads(row['data'])
        except json.JSONDecodeError:
            return row['state'], {}
    return None, {}

def clear_state(chat_id):
    conn = get_db()
    conn.execute("DELETE FROM user_state WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()

# --- TELEGRAM API FUNCTIONS ---
def send_message(chat_id, text, reply_markup=None):
    url = f"{API_URL}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Send Error: {e}")

def send_force_reply(chat_id, text, placeholder="Type here..."):
    url = f"{API_URL}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {"force_reply": True, "input_field_placeholder": placeholder}
    }
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Send Error: {e}")

def answer_callback(query_id, text=""):
    url = f"{API_URL}/answerCallbackQuery"
    data = {"callback_query_id": query_id, "text": text}
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Answer Callback Error: {e}")

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"{API_URL}/editMessageText"
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Edit Message Error: {e}")

# --- UI BUILDERS ---
def build_main_menu(chat_id):
    is_owner = chat_id in OWNER_IDS
    if is_owner:
        buttons = [
            [{"text": "📋 View Stock", "callback_data": "main_view_stock"}, {"text": "💰 Record Sale", "callback_data": "main_record_sale"}],
            [{"text": "📜 Recent Sales", "callback_data": "main_recent_sales"}, {"text": "📊 Daily Summary", "callback_data": "main_summary"}],
            [{"text": "➕ Add Stock", "callback_data": "main_add_stock"}, {"text": "✏️ Edit Item", "callback_data": "main_edit_item"}],
            [{"text": "🗑️ Remove Item", "callback_data": "main_remove_item"}, {"text": "⚠️ Low Stock", "callback_data": "main_low_stock"}],
            [{"text": "⏳ Pending Payments", "callback_data": "main_pending"}]
        ]
        text = "📊 *VICTORY VENTURE — MAIN MENU*\n\nWelcome, Boss. What would you like to do?"
    else:
        buttons = [
            [{"text": "📋 View Stock", "callback_data": "main_view_stock"}, {"text": "💰 Record Sale", "callback_data": "main_record_sale"}],
            [{"text": "📜 Recent Sales", "callback_data": "main_recent_sales"}, {"text": "📊 Daily Summary", "callback_data": "main_summary"}]
        ]
        text = "📊 *VICTORY VENTURE — MAIN MENU*\n\nWelcome. What would you like to do?"
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

    if callback_data == "main_menu":
        text, markup = build_main_menu(chat_id)
        clear_state(chat_id)
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    # VIEW STOCK
    elif callback_data == "main_view_stock":
        conn = get_db()
        categories = conn.execute("SELECT DISTINCT category FROM stock ORDER BY category").fetchall()
        conn.close()
        if not categories:
            text = "📋 No items in stock yet."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            buttons = [[{"text": cat['category'], "callback_data": f"viewcat_{cat['category']}"}] for cat in categories]
            buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
            text = "📋 *VIEW STOCK*\n\nSelect a category:"
            markup = {"inline_keyboard": buttons}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("viewcat_"):
        category = callback_data[8:]
        conn = get_db()
        items = conn.execute("SELECT * FROM stock WHERE category=? ORDER BY item_name", (category,)).fetchall()
        conn.close()
        if not items:
            text = f"📋 No items in *{category}*."
        else:
            text = f"📋 *{category}*\n\n"
            for item in items:
                color_str = f" ({item['color']})" if item['color'] else ""
                text += f"• *{item['item_name']}*{color_str}\n  Qty: {item['quantity']} | Price: GHS {item['selling_price']:.0f}\n\n"
        markup = {"inline_keyboard": [[{"text": "📋 View Stock", "callback_data": "main_view_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    # RECORD SALE
    elif callback_data == "main_record_sale":
        conn = get_db()
        categories = conn.execute("SELECT DISTINCT category FROM stock WHERE quantity > 0 ORDER BY category").fetchall()
        conn.close()
        if not categories:
            text = "📋 No items in stock to sell."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            buttons = [[{"text": cat['category'], "callback_data": f"sellcat_{cat['category']}"}] for cat in categories]
            buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
            text = "💰 *RECORD SALE*\n\nSelect the item category:"
            markup = {"inline_keyboard": buttons}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("sellcat_"):
        category = callback_data[8:]
        conn = get_db()
        items = conn.execute("SELECT * FROM stock WHERE category=? AND quantity > 0 ORDER BY item_name", (category,)).fetchall()
        conn.close()
        if not items:
            text = f"No items in stock for *{category}*."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            buttons = []
            for item in items:
                color_str = f" ({item['color']})" if item['color'] else ""
                title = f"{item['item_name']}{color_str} ({item['quantity']})"
                buttons.append([{"text": title, "callback_data": f"sellitem_{item['id']}"}])
            buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
            text = "💰 *RECORD SALE*\n\nSelect the item sold:"
            markup = {"inline_keyboard": buttons}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("sellitem_"):
        item_id = int(callback_data[9:])
        conn = get_db()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        conn.close()
        if not item:
            text = "Item not found."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            color_str = f" ({item['color']})" if item['color'] else ""
            text = f"💰 *RECORD SALE*\n\nItem: *{item['item_name']}*{color_str}\nAvailable: {item['quantity']} pcs\n\n*How many are you selling?*\n\n_Tap below to type the amount._"
            save_state(chat_id, f"sell_enter_qty_{item_id}")
            markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            send_force_reply(chat_id, "👇 *Type the quantity now:*", "e.g. 5")
        return

    elif callback_data.startswith("sell_walkin_"):
        parts = callback_data.split("_")
        item_id = int(parts[2])
        qty = int(parts[3])
        process_sale_confirmation(chat_id, item_id, qty, "Walk-in Customer", payment_status='paid', message_id=message_id)
        return

    elif callback_data.startswith("sell_paid_") or callback_data.startswith("sell_credit_"):
        parts = callback_data.split("_")
        payment_status = 'paid' if parts[1] == 'paid' else 'pending'
        item_id = int(parts[2])
        qty = int(parts[3])
        
        state, data_dict = get_state(chat_id)
        customer_info = data_dict.get('customer_info', 'Walk-in Customer')
        
        process_sale_confirmation(chat_id, item_id, qty, customer_info, payment_status=payment_status, message_id=message_id)
        clear_state(chat_id)
        return

    elif callback_data.startswith("sell_type_"):
        parts = callback_data.split("_")
        item_id = int(parts[2])
        qty = int(parts[3])
        save_state(chat_id, f"sell_type_{item_id}_{qty}")
        send_force_reply(chat_id, "💰 *RECORD SALE*\n\nPlease type the Customer's Name & Phone Number:\n\n_The keyboard is open. Type and send._", "e.g. John 0241234567")
        return

    elif callback_data == "main_recent_sales":
        conn = get_db()
        sales = conn.execute("SELECT * FROM sales ORDER BY sold_at DESC LIMIT 10").fetchall()
        conn.close()
        if not sales:
            text = "📜 No recent sales recorded."
        else:
            text = "📜 *RECENT SALES (Last 10)*\n\n"
            for sale in sales:
                color_str = f" ({sale['color']})" if sale['color'] else ""
                dt = sale['sold_at']
                if dt:
                    try:
                        dt_obj = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
                        dt_str = dt_obj.strftime("%d/%m/%Y %I:%M %p")
                    except:
                        dt_str = dt
                else:
                    dt_str = "Unknown"
                text += f"• {sale['item_name']}{color_str} x{sale['quantity']}\n  🕒 {dt_str}\n  👤 {sale['customer_info']}\n  💰 Profit: GHS {sale['profit']:.2f}\n\n"
        markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    # ADD STOCK - NEW FLOW
    elif callback_data == "main_add_stock":
        if chat_id not in OWNER_IDS:
            text = "❌ Only the owner can add stock."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        save_state(chat_id, "add_new_name")
        send_force_reply(chat_id, "➕ *ADD STOCK*\n\nStep 1/5: What is the item name?\n\n_The keyboard is open. Type the name and send._", "e.g. iPhone 15 Screen")
        return

    elif callback_data.startswith("color_"):
        color = callback_data[6:]
        state, data_dict = get_state(chat_id)
        if color == "Custom":
            save_state(chat_id, "add_new_color_text", data_dict)
            send_force_reply(chat_id, "➕ *ADD STOCK*\n\nPlease type the custom color name:", "e.g. Rose Gold")
            return
        else:
            data_dict['color'] = color if color != "none" else ""
            conn = get_db()
            item = conn.execute("SELECT * FROM stock WHERE item_name=? AND color=?", 
                              (data_dict['name'], data_dict['color'])).fetchone()
            conn.close()
            if item:
                data_dict['existing_id'] = item['id']
                data_dict['existing_qty'] = item['quantity']
                data_dict['existing_cost'] = item['cost_price']
                data_dict['existing_sell'] = item['selling_price']
                save_state(chat_id, "add_existing_choice", data_dict)
                color_str = f" ({color})" if color != "none" else ""
                text = f"Found: *{data_dict['name']}*{color_str}\n\nQty: {item['quantity']}\nCost: GHS {item['cost_price']:.2f}\nSell: GHS {item['selling_price']:.2f}\n\nAre you topping up stock or changing prices?"
                markup = {"inline_keyboard": [
                    [{"text": "📦 Top Up Stock", "callback_data": "add_topup"}, {"text": "💰 Update Prices", "callback_data": "add_update"}],
                    [{"text": "❌ Cancel", "callback_data": "main_menu"}]
                ]}
                edit_message(chat_id, message_id, text, reply_markup=markup)
            else:
                save_state(chat_id, "add_new_qty", data_dict)
                text = f"✅ Color: *{color}*\n\nHow many units are you adding?\n\n_Tap below to type the amount._"
                markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
                edit_message(chat_id, message_id, text, reply_markup=markup)
                send_force_reply(chat_id, "👇 *Type the quantity now:*", "e.g. 15")
        return

    elif callback_data == "add_topup":
        state, data_dict = get_state(chat_id)
        if state != "add_existing_choice":
            edit_message(chat_id, message_id, "❌ Session expired. Please start over.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            return
        save_state(chat_id, "add_topup_qty", data_dict)
        send_force_reply(chat_id, "📦 *TOP UP STOCK*\n\nHow many are you adding?\n\n_The keyboard is open. Type the number and send._", "e.g. 20")
        return

    elif callback_data == "add_update":
        state, data_dict = get_state(chat_id)
        if state != "add_existing_choice":
            edit_message(chat_id, message_id, "❌ Session expired. Please start over.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
            return
        save_state(chat_id, "add_update_cost", data_dict)
        send_force_reply(chat_id, "💰 *UPDATE PRICES*\n\nNew cost price per unit?\n\n_The keyboard is open. Type and send._", "e.g. 15.50")
        return

    elif callback_data.startswith("addcat_"):
        state, data_dict = get_state(chat_id)
        if callback_data == "addcat_custom":
            text = f"✅ Sell: *GHS {data_dict.get('sell', 0):.2f}*\n\nPlease type the custom category name:"
            markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
            save_state(chat_id, "add_new_category_text", data_dict)
            send_force_reply(chat_id, text, "e.g. Tools")
            return
        else:
            category = callback_data[8:]
            data_dict['category'] = category
            save_state(chat_id, "add_new_confirm", data_dict)
            color_str = f" ({data_dict['color']})" if data_dict['color'] else ""
            text_msg = f"➕ *CONFIRM NEW ITEM*\n\nName: *{data_dict['name']}*{color_str}\nQuantity: {data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {category}\n\nAdd this item?"
            markup = {"inline_keyboard": [[{"text": "✅ Confirm", "callback_data": "addconfirm"}, {"text": "❌ Cancel", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text_msg, reply_markup=markup)
            return

    elif callback_data == "addconfirm":
        state, data_dict = get_state(chat_id)
        required_keys = ['name', 'color', 'qty', 'cost', 'sell', 'category']
        if not all(k in data_dict for k in required_keys):
            text = "❌ Incomplete data."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            clear_state(chat_id)
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        conn = get_db()
        try:
            conn.execute("""INSERT INTO stock (item_name, color, quantity, cost_price, selling_price, category)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                         (data_dict['name'], data_dict['color'], data_dict['qty'],
                          data_dict['cost'], data_dict['sell'], data_dict['category']))
            conn.commit()
            color_str = f" ({data_dict['color']})" if data_dict['color'] else ""
            text = f"✅ *Added!*\n\n{data_dict['name']}{color_str} x{data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {data_dict['category']}\n\n*What next?*"
            markup = {"inline_keyboard": [[{"text": "➕ Add More Stock", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        except sqlite3.IntegrityError:
            text = "❌ Item with same name and color already exists."
            markup = {"inline_keyboard": [[{"text": "➕ Add More Stock", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        finally:
            conn.close()
        clear_state(chat_id)
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    # EDIT ITEM
    elif callback_data == "main_edit_item":
        if chat_id not in OWNER_IDS:
            text = "❌ Only the owner can edit items."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        conn = get_db()
        categories = conn.execute("SELECT DISTINCT category FROM stock ORDER BY category").fetchall()
        conn.close()
        buttons = [[{"text": cat['category'], "callback_data": f"editcat_{cat['category']}"}] for cat in categories]
        buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
        text = "✏️ *EDIT ITEM*\n\nSelect a category:"
        markup = {"inline_keyboard": buttons}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("editcat_"):
        category = callback_data[8:]
        conn = get_db()
        items = conn.execute("SELECT * FROM stock WHERE category=? ORDER BY item_name", (category,)).fetchall()
        conn.close()
        if not items:
            text = f"No items in *{category}*."
            markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_edit_item"}]]}
        else:
            buttons = []
            for item in items:
                color_str = f" ({item['color']})" if item['color'] else ""
                title = f"{item['item_name']}{color_str} [Qty: {item['quantity']}]"
                buttons.append([{"text": title, "callback_data": f"edititem_{item['id']}"}])
            buttons.append([{"text": "⬅️ Back to Categories", "callback_data": "main_edit_item"}])
            text = f"✏️ *EDIT: {category}*\n\nSelect the item to edit:"
            markup = {"inline_keyboard": buttons}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("edititem_"):
        item_id = int(callback_data[9:])
        conn = get_db()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        conn.close()
        if not item:
            text = "Item not found."
            markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_edit_item"}]]}
        else:
            color_str = f" ({item['color']})" if item['color'] else ""
            text = f"✏️ *EDIT ITEM*\n\n*{item['item_name']}*{color_str}\nCategory: {item['category']}\nQty: {item['quantity']}\nCost: GHS {item['cost_price']:.2f}\nSell: GHS {item['selling_price']:.2f}\n\n*What would you like to change?*"
            markup = {"inline_keyboard": [
                [{"text": "📦 Update Qty", "callback_data": f"editqty_{item_id}"}, {"text": "💰 Update Cost", "callback_data": f"editcost_{item_id}"}],
                [{"text": "💵 Update Sell Price", "callback_data": f"editsell_{item_id}"}, {"text": "🏷️ Update Category", "callback_data": f"editcat_field_{item_id}"}],
                [{"text": "⬅️ Back", "callback_data": f"editcat_{item['category']}"}]
            ]}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("editqty_"):
        item_id = int(callback_data[8:])
        save_state(chat_id, f"edit_qty_{item_id}")
        send_force_reply(chat_id, "✏️ *UPDATE QUANTITY*\n\nType the NEW total quantity for this item:", "e.g. 50")
        return

    elif callback_data.startswith("editcost_"):
        item_id = int(callback_data[9:])
        save_state(chat_id, f"edit_cost_{item_id}")
        send_force_reply(chat_id, "✏️ *UPDATE COST PRICE*\n\nType the NEW cost price per unit:", "e.g. 15.50")
        return

    elif callback_data.startswith("editsell_"):
        item_id = int(callback_data[9:])
        save_state(chat_id, f"edit_sell_{item_id}")
        send_force_reply(chat_id, "✏️ *UPDATE SELLING PRICE*\n\nType the NEW selling price per unit:", "e.g. 25.00")
        return

    elif callback_data.startswith("editcat_field_"):
        item_id = int(callback_data[14:])
        conn = get_db()
        categories = conn.execute("SELECT DISTINCT category FROM stock ORDER BY category").fetchall()
        conn.close()
        buttons = [[{"text": cat['category'], "callback_data": f"editcatset_{item_id}_{cat['category']}"}] for cat in categories[:6]]
        buttons.append([{"text": "📝 Type Custom", "callback_data": f"editcatcustom_{item_id}"}])
        buttons.append([{"text": "⬅️ Back", "callback_data": f"edititem_{item_id}"}])
        text = "✏️ *UPDATE CATEGORY*\n\nSelect a category:"
        edit_message(chat_id, message_id, text, {"inline_keyboard": buttons})
        return

    elif callback_data.startswith("editcatset_"):
        parts = callback_data.split("_", 2)
        item_id = int(parts[1])
        category = parts[2]
        conn = get_db()
        conn.execute("UPDATE stock SET category=? WHERE id=?", (category, item_id))
        conn.commit()
        conn.close()
        text = f"✅ *Category Updated!*\n\nNow in: *{category}*"
        markup = {"inline_keyboard": [[{"text": "✏️ Edit Another", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("editcatcustom_"):
        item_id = int(callback_data[16:])
        save_state(chat_id, f"edit_category_{item_id}")
        send_force_reply(chat_id, "✏️ *UPDATE CATEGORY*\n\nType the new category name:", "e.g. Accessories")
        return

    # REMOVE ITEM
    elif callback_data == "main_remove_item":
        if chat_id not in OWNER_IDS:
            text = "❌ Only the owner can remove items."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        conn = get_db()
        categories = conn.execute("SELECT DISTINCT category FROM stock ORDER BY category").fetchall()
        conn.close()
        buttons = [[{"text": cat['category'], "callback_data": f"removecat_{cat['category']}"}] for cat in categories]
        buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
        text = "🗑️ *REMOVE ITEM*\n\nSelect a category:"
        markup = {"inline_keyboard": buttons}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("removecat_"):
        category = callback_data[10:]
        conn = get_db()
        items = conn.execute("SELECT * FROM stock WHERE category=? ORDER BY item_name", (category,)).fetchall()
        conn.close()
        if not items:
            text = f"No items in *{category}*."
            markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_remove_item"}]]}
        else:
            buttons = []
            for item in items:
                color_str = f" ({item['color']})" if item['color'] else ""
                title = f"{item['item_name']}{color_str} [Qty: {item['quantity']}]"
                buttons.append([{"text": title, "callback_data": f"removeitem_{item['id']}"}])
            buttons.append([{"text": "⬅️ Back to Categories", "callback_data": "main_remove_item"}])
            text = f"🗑️ *REMOVE: {category}*\n\nSelect the item to remove:"
            markup = {"inline_keyboard": buttons}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("removeitem_"):
        item_id = int(callback_data[11:])
        conn = get_db()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        conn.close()
        if not item:
            text = "Item not found."
            markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_remove_item"}]]}
        else:
            color_str = f" ({item['color']})" if item['color'] else ""
            text = f"🗑️ *{item['item_name']}*{color_str}\n\nQty: {item['quantity']}\n\nRemove entire item or reduce quantity?"
            markup = {"inline_keyboard": [
                [{"text": "🗑️ Remove All", "callback_data": f"removeall_{item_id}"}, {"text": "📉 Reduce Quantity", "callback_data": f"reducereduce_{item_id}"}],
                [{"text": "⬅️ Back", "callback_data": f"removecat_{item['category']}"}]
            ]}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("removeall_"):
        item_id = int(callback_data[10:])
        conn = get_db()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        conn.close()
        if item:
            color_str = f" ({item['color']})" if item['color'] else ""
            text = f"⚠️ *CONFIRM DELETION*\n\nAre you sure you want to permanently delete:\n*{item['item_name']}*{color_str}?\n\n_This cannot be undone._"
            markup = {"inline_keyboard": [
                [{"text": "✅ Yes, Delete", "callback_data": f"confirmdelete_{item_id}"}, {"text": "❌ No, Cancel", "callback_data": f"removeitem_{item_id}"}]
            ]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("reducereduce_"):
        item_id = int(callback_data[13:])
        save_state(chat_id, f"reduce_qty_{item_id}")
        send_force_reply(chat_id, "📉 *REDUCE QUANTITY*\n\nHow many units to remove?", "e.g. 5")
        return

    elif callback_data.startswith("confirmdelete_"):
        item_id = int(callback_data[14:])
        conn = get_db()
        conn.execute("DELETE FROM stock WHERE id=?", (item_id,))
        conn.commit()
        conn.close()
        text = "🗑️ *Item Deleted Successfully!*\n\n*What next?*"
        markup = {"inline_keyboard": [[{"text": "🗑️ Remove Another", "callback_data": "main_remove_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        clear_state(chat_id)
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data == "main_summary":
        conn = get_db()
        result = conn.execute("SELECT COUNT(*) as count, SUM(profit) as total FROM sales WHERE date(sold_at)=date('now')").fetchone()
        pending_result = conn.execute("SELECT COUNT(*) as count, SUM(profit) as total FROM sales WHERE date(sold_at)=date('now') AND payment_status='pending'").fetchone()
        conn.close()
        
        count = result['count'] or 0
        total = result['total'] or 0
        pend_count = pending_result['count'] or 0
        pend_total = pending_result['total'] or 0
        
        today = datetime.now().strftime("%d/%m/%Y")
        text = f"📊 *DAILY SUMMARY ({today})*\n\n🛒 Sales Today: {count}\n💰 Total Profit: GHS {total:.2f}\n⏳ Pending: GHS {pend_total:.2f} ({pend_count} customers)\n\n*What next?*"
        markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data == "main_low_stock":
        if chat_id not in OWNER_IDS:
            text = "❌ Only the owner can view low stock."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        conn = get_db()
        items = conn.execute("SELECT * FROM stock WHERE quantity <= 5 ORDER BY quantity ASC").fetchall()
        conn.close()
        if items:
            text = "⚠️ *LOW STOCK ALERT*\n\n"
            for item in items:
                color_str = f" ({item['color']})" if item['color'] else ""
                text += f"• *{item['item_name']}*{color_str} — {item['quantity']} left\n"
        else:
            text = "✅ All items have more than 5 in stock."
        markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data == "main_pending":
        if chat_id not in OWNER_IDS:
            text = "❌ Only the owner can view pending payments."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        
        conn = get_db()
        sales = conn.execute("SELECT * FROM sales WHERE payment_status='pending' ORDER BY sold_at ASC").fetchall()
        conn.close()
        
        if not sales:
            text = "✅ No pending payments."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            text = "⏳ *PENDING PAYMENTS*\n\n"
            buttons = []
            for sale in sales:
                color_str = f" ({sale['color']})" if sale['color'] else ""
                dt = sale['sold_at']
                hours = 0
                if dt:
                    try:
                        dt_obj = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
                        diff = datetime.now() - dt_obj
                        hours = int(diff.total_seconds() // 3600)
                    except:
                        pass
                
                text += f"• *{sale['item_name']}*{color_str} x{sale['quantity']}\n  👤 {sale['customer_info']}\n  💰 GHS {sale['profit']:.2f} | 🕒 {hours}h ago\n"
                buttons.append([{"text": f"✅ Mark Paid: {sale['customer_info']}", "callback_data": f"markpaid_{sale['id']}"}])
            markup = {"inline_keyboard": buttons + [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("markpaid_"):
        sale_id = int(callback_data[9:])
        conn = get_db()
        conn.execute("UPDATE sales SET payment_status='paid' WHERE id=?", (sale_id,))
        conn.commit()
        
        sales = conn.execute("SELECT * FROM sales WHERE payment_status='pending' ORDER BY sold_at ASC").fetchall()
        conn.close()
        
        if not sales:
            text = "✅ *Marked as Paid!*\n\nNo more pending payments."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            text = "✅ *Marked as Paid!*\n\n⏳ *PENDING PAYMENTS*\n\n"
            buttons = []
            for sale in sales:
                color_str = f" ({sale['color']})" if sale['color'] else ""
                dt = sale['sold_at']
                hours = 0
                if dt:
                    try:
                        dt_obj = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
                        diff = datetime.now() - dt_obj
                        hours = int(diff.total_seconds() // 3600)
                    except:
                        pass
                
                text += f"• *{sale['item_name']}*{color_str} x{sale['quantity']}\n  👤 {sale['customer_info']}\n  💰 GHS {sale['profit']:.2f} | 🕒 {hours}h ago\n"
                buttons.append([{"text": f"✅ Mark Paid: {sale['customer_info']}", "callback_data": f"markpaid_{sale['id']}"}])
            markup = {"inline_keyboard": buttons + [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    else:
        text, markup = build_main_menu(chat_id)
        clear_state(chat_id)
        edit_message(chat_id, message_id, text, reply_markup=markup)

def process_sale_confirmation(chat_id, item_id, qty, customer_info, payment_status='paid', message_id=None):
    conn = get_db()
    item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
    if not item or item['quantity'] < qty:
        text = "❌ Not enough stock."
        markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        if message_id:
            edit_message(chat_id, message_id, text, reply_markup=markup)
        else:
            send_message(chat_id, text, reply_markup=markup)
        clear_state(chat_id)
        return

    new_qty = item['quantity'] - qty
    profit = (item['selling_price'] - item['cost_price']) * qty
    
    conn.execute("UPDATE stock SET quantity=? WHERE id=?", (new_qty, item_id))
    conn.execute("INSERT INTO sales (item_name, color, quantity, profit, sold_by, customer_info, payment_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (item['item_name'], item['color'], qty, profit, chat_id, customer_info, payment_status))
    conn.commit()
    conn.close()

    color_str = f" ({item['color']})" if item['color'] else ""
    now = datetime.now().strftime("%d/%m/%Y %I:%M %p")
    
    status_str = "(Paid)" if payment_status == 'paid' else "(Credit — Pending)"
    text = f"✅ *Sale Recorded! {status_str}*\n\n🕒 {now}\n📦 Sold {qty}x *{item['item_name']}*{color_str}\n👤 Customer: *{customer_info}*\n📉 Remaining: {new_qty}\n💰 Profit: GHS {profit:.2f}\n\n*What next?*"
    
    markup = {"inline_keyboard": [[{"text": "💰 Record Another Sale", "callback_data": "main_record_sale"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
    
    if message_id:
        edit_message(chat_id, message_id, text, reply_markup=markup)
    else:
        send_message(chat_id, text, reply_markup=markup)

    # Notification to dedicated notification chat (falls back to owners if empty)
    status_text = "Paid" if payment_status == 'paid' else "Credit"
    notify_targets = NOTIFICATION_IDS if NOTIFICATION_IDS else OWNER_IDS
    for target_id in notify_targets:
        send_message(target_id, f"🔔 Sale: {item['item_name']}{color_str} x{qty} — GHS {profit:.2f} ({status_text} — {customer_info})")

    clear_state(chat_id)

# --- TEXT MESSAGE HANDLER ---
def handle_text_message(chat_id, text):
    text = text.strip()
    if text == "/start":
        if chat_id not in ALLOWED_IDS:
            send_message(chat_id, "⛔ Access Denied.")
            return
        text_msg, markup = build_main_menu(chat_id)
        send_message(chat_id, text_msg, reply_markup=markup)
        clear_state(chat_id)
        return

    state, data_dict = get_state(chat_id)
    if chat_id not in OWNER_IDS and not state:
        return

    # 1. Handle Sale Quantity Input
    if state and state.startswith("sell_enter_qty_"):
        item_id = int(state.split("_")[3])
        try:
            qty = int(text)
            if qty <= 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid positive number.")
            return
        conn = get_db()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        conn.close()
        if item and qty > item['quantity']:
            send_message(chat_id, f"❌ Not enough stock! Only {item['quantity']} available.")
            return
        markup = {"inline_keyboard": [
            [{"text": "🚶 Walk-in Customer", "callback_data": f"sell_walkin_{item_id}_{qty}"}],
            [{"text": "✍️ Enter Name & Number", "callback_data": f"sell_type_{item_id}_{qty}"}],
            [{"text": "❌ Cancel", "callback_data": "main_menu"}]
        ]}
        send_message(chat_id, f"✅ Quantity: *{qty}*\n\nWho is buying this?\n\n_Tap an option below._", reply_markup=markup)
        return

    # 2. Handle Customer Info Input & Payment Choice
    elif state and state.startswith("sell_type_"):
        parts = state.split("_")
        item_id = int(parts[2])
        qty = int(parts[3])
        customer_info = text if text.lower() != "walk-in" else "Walk-in Customer"
        
        data_dict = {'customer_info': customer_info}
        save_state(chat_id, f"sell_payment_choice_{item_id}_{qty}", data_dict)
        
        markup = {"inline_keyboard": [
            [{"text": "💵 Paid Now", "callback_data": f"sell_paid_{item_id}_{qty}"}],
            [{"text": "⏳ Pay Later", "callback_data": f"sell_credit_{item_id}_{qty}"}],
            [{"text": "❌ Cancel", "callback_data": "main_menu"}]
        ]}
        send_message(chat_id, f"✅ Customer: *{customer_info}*\n\nHow will they pay?", reply_markup=markup)
        return

    # 3. Handle Add Stock - Top Up
    elif state == "add_topup_qty":
        try:
            qty = int(text)
            if qty <= 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid positive number.")
            return
        new_qty = data_dict['existing_qty'] + qty
        conn = get_db()
        conn.execute("UPDATE stock SET quantity=? WHERE id=?", (new_qty, data_dict['existing_id']))
        conn.commit()
        conn.close()
        color_str = f" ({data_dict['color']})" if data_dict['color'] else ""
        text_msg = f"✅ *Updated!*\n\n{data_dict['name']}{color_str} now {new_qty} pcs.\nPrices unchanged.\n\n*What next?*"
        markup = {"inline_keyboard": [[{"text": "➕ Add More Stock", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        clear_state(chat_id)
        send_message(chat_id, text_msg, reply_markup=markup)
        return

    # 4. Handle Add Stock - Update Prices
    elif state == "add_update_cost":
        try:
            cost = float(text)
            if cost < 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
            return
        data_dict['new_cost'] = cost
        save_state(chat_id, "add_update_sell", data_dict)
        send_message(chat_id, f"✅ Cost: *GHS {cost:.2f}*\n\nNew selling price per unit?",
                    reply_markup={"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
        return

    elif state == "add_update_sell":
        try:
            sell = float(text)
            if sell < 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
            return
        data_dict['new_sell'] = sell
        save_state(chat_id, "add_update_qty", data_dict)
        send_message(chat_id, f"✅ Sell: *GHS {sell:.2f}*\n\nQuantity to add?",
                    reply_markup={"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
        return

    elif state == "add_update_qty":
        try:
            qty = int(text)
            if qty <= 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid positive number.")
            return
        new_qty = data_dict['existing_qty'] + qty
        conn = get_db()
        conn.execute("UPDATE stock SET quantity=?, cost_price=?, selling_price=? WHERE id=?",
                    (new_qty, data_dict['new_cost'], data_dict['new_sell'], data_dict['existing_id']))
        conn.commit()
        conn.close()
        color_str = f" ({data_dict['color']})" if data_dict['color'] else ""
        text_msg = f"✅ *Updated!*\n\n{data_dict['name']}{color_str}\n{new_qty} pcs\nCost: GHS {data_dict['new_cost']:.2f}\nSell: GHS {data_dict['new_sell']:.2f}\n\n*What next?*"
        markup = {"inline_keyboard": [[{"text": "➕ Add More Stock", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        clear_state(chat_id)
        send_message(chat_id, text_msg, reply_markup=markup)
        return

    # 5. Handle Add New Item Flow
    elif state == "add_new_name":
        data_dict['name'] = text
        save_state(chat_id, "add_new_color_btn", data_dict)
        markup = {"inline_keyboard": get_color_buttons() + [[{"text": "⚪ None", "callback_data": "color_none"}, {"text": "❌ Cancel", "callback_data": "main_menu"}]]}
        send_message(chat_id, f"✅ Item: *{text}*\n\nSelect color (or tap 'None' if no color):", reply_markup=markup)
        return

    elif state == "add_new_color_text":
        data_dict['color'] = text
        save_state(chat_id, "add_new_qty", data_dict)
        text = f"✅ Color: *{text}*\n\nHow many units are you adding?\n\n_Tap below to type the amount._"
        markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
        send_message(chat_id, text, reply_markup=markup)
        send_force_reply(chat_id, "👇 *Type the quantity now:*", "e.g. 15")
        return

    elif state == "add_new_qty":
        try:
            qty = int(text)
            if qty <= 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a positive number.")
            return
        data_dict['qty'] = qty
        save_state(chat_id, "add_new_cost", data_dict)
        send_message(chat_id, f"✅ Quantity: *{qty}*\n\nWhat is the cost price per unit?",
                    reply_markup={"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
        return

    elif state == "add_new_cost":
        try:
            cost = float(text)
            if cost < 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
            return
        data_dict['cost'] = cost
        save_state(chat_id, "add_new_sell", data_dict)
        send_message(chat_id, f"✅ Cost: *GHS {cost:.2f}*\n\nWhat is the selling price per unit?",
                    reply_markup={"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
        return

    elif state == "add_new_sell":
        try:
            sell = float(text)
            if sell < 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
            return
        data_dict['sell'] = sell
        save_state(chat_id, "add_new_category_pending", data_dict)
        conn = get_db()
        categories = conn.execute("SELECT DISTINCT category FROM stock ORDER BY category").fetchall()
        conn.close()
        buttons = []
        for cat in categories[:5]:
            buttons.append([{"text": cat['category'], "callback_data": f"addcat_{cat['category']}"}])
        buttons.append([{"text": "📝 Type Custom Category", "callback_data": "addcat_custom"}])
        buttons.append([{"text": "❌ Cancel", "callback_data": "main_menu"}])
        send_message(chat_id, f"✅ Sell: *GHS {sell:.2f}*\n\nSelect a category:", reply_markup={"inline_keyboard": buttons})
        return

    elif state == "add_new_category_text":
        data_dict['category'] = text
        save_state(chat_id, "add_new_confirm", data_dict)
        color_str = f" ({data_dict['color']})" if data_dict['color'] else ""
        text_msg = f"➕ *CONFIRM NEW ITEM*\n\nName: *{data_dict['name']}*{color_str}\nQuantity: {data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {text}\n\nAdd this item?"
        markup = {"inline_keyboard": [[{"text": "✅ Confirm", "callback_data": "addconfirm"}, {"text": "❌ Cancel", "callback_data": "main_menu"}]]}
        send_message(chat_id, text_msg, reply_markup=markup)
        return

    # 6. Handle Edit Item Inputs
    elif state and state.startswith("edit_qty_"):
        item_id = int(state.split("_")[2])
        try:
            qty = int(text)
            if qty < 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid positive number.")
            return
        conn = get_db()
        conn.execute("UPDATE stock SET quantity=? WHERE id=?", (qty, item_id))
        conn.commit()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        conn.close()
        color_str = f" ({item['color']})" if item['color'] else ""
        text_msg = f"✅ *Quantity Updated!*\n\n*{item['item_name']}*{color_str} is now {qty}.\n\n*What next?*"
        markup = {"inline_keyboard": [[{"text": "✏️ Edit Another", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        clear_state(chat_id)
        send_message(chat_id, text_msg, reply_markup=markup)
        return

    elif state and state.startswith("edit_cost_"):
        item_id = int(state.split("_")[2])
        try:
            cost = float(text)
            if cost < 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
            return
        conn = get_db()
        conn.execute("UPDATE stock SET cost_price=? WHERE id=?", (cost, item_id))
        conn.commit()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        conn.close()
        color_str = f" ({item['color']})" if item['color'] else ""
        text_msg = f"✅ *Cost Price Updated!*\n\n*{item['item_name']}*{color_str} cost is now GHS {cost:.2f}.\n\n*What next?*"
        markup = {"inline_keyboard": [[{"text": "✏️ Edit Another", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        clear_state(chat_id)
        send_message(chat_id, text_msg, reply_markup=markup)
        return

    elif state and state.startswith("edit_sell_"):
        item_id = int(state.split("_")[2])
        try:
            sell = float(text)
            if sell < 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
            return
        conn = get_db()
        conn.execute("UPDATE stock SET selling_price=? WHERE id=?", (sell, item_id))
        conn.commit()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        conn.close()
        color_str = f" ({item['color']})" if item['color'] else ""
        text_msg = f"✅ *Selling Price Updated!*\n\n*{item['item_name']}*{color_str} sell price is now GHS {sell:.2f}.\n\n*What next?*"
        markup = {"inline_keyboard": [[{"text": "✏️ Edit Another", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        clear_state(chat_id)
        send_message(chat_id, text_msg, reply_markup=markup)
        return

    elif state and state.startswith("edit_category_"):
        item_id = int(state.split("_")[2])
        conn = get_db()
        conn.execute("UPDATE stock SET category=? WHERE id=?", (text, item_id))
        conn.commit()
        conn.close()
        text_msg = f"✅ *Category Updated!*\n\nNow in: *{text}*\n\n*What next?*"
        markup = {"inline_keyboard": [[{"text": "✏️ Edit Another", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        clear_state(chat_id)
        send_message(chat_id, text_msg, reply_markup=markup)
        return

    # 7. Handle Remove Item - Reduce Quantity
    elif state and state.startswith("reduce_qty_"):
        item_id = int(state.split("_")[2])
        try:
            qty = int(text)
            if qty <= 0: raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid positive number.")
            return
        conn = get_db()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        if item:
            new_qty = item['quantity'] - qty
            if new_qty < 0:
                send_message(chat_id, f"❌ Cannot remove {qty}. Only {item['quantity']} in stock.")
                clear_state(chat_id)
                return
            if new_qty == 0:
                conn.execute("DELETE FROM stock WHERE id=?", (item_id,))
                conn.commit()
                conn.close()
                color_str = f" ({item['color']})" if item['color'] else ""
                text_msg = f"🗑️ *Removed!*\n\n*{item['item_name']}*{color_str} deleted completely.\n\n*What next?*"
            else:
                conn.execute("UPDATE stock SET quantity=? WHERE id=?", (new_qty, item_id))
                conn.commit()
                conn.close()
                color_str = f" ({item['color']})" if item['color'] else ""
                text_msg = f"✅ *Quantity Reduced!*\n\n*{item['item_name']}*{color_str}: {item['quantity']} → {new_qty}\n\n*What next?*"
        else:
            text_msg = "❌ Item not found."
            conn.close()
        markup = {"inline_keyboard": [[{"text": "🗑️ Remove Another", "callback_data": "main_remove_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        clear_state(chat_id)
        send_message(chat_id, text_msg, reply_markup=markup)
        return

    # FALLBACK
    if chat_id in ALLOWED_IDS:
        text_msg, markup = build_main_menu(chat_id)
        send_message(chat_id, "🤔 I didn't catch that. Here is the main menu:", reply_markup=markup)
        clear_state(chat_id)
    else:
        send_message(chat_id, "⛔ Access Denied.")

# --- WEBHOOK ROUTES ---
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    update = request.get_json()
    try:
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            if chat_id not in ALLOWED_IDS:
                if 'text' in message and message['text'].strip() == "/start":
                    send_message(chat_id, "⛔ Access Denied.")
                    return jsonify({"ok": True})
            if 'text' in message:
                handle_text_message(chat_id, message['text'])
        elif 'callback_query' in update:
            callback = update['callback_query']
            chat_id = callback['message']['chat']['id']
            if chat_id not in ALLOWED_IDS:
                return jsonify({"ok": True})
            button_handler(callback)
    except Exception as e:
        print(f"Processing Error: {e}")
    return jsonify({"ok": True})

@app.route('/setup', methods=['GET'])
def setup_webhook():
    if not WEBHOOK_URL:
        return "Error: WEBHOOK_URL environment variable not set."
    url = f"{API_URL}/setWebhook"
    data = {"url": WEBHOOK_URL}
    response = requests.post(url, json=data)
    return response.text

@app.route('/', methods=['GET'])
def index():
    return "Victory Venture StockMind Bot is running!"

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
