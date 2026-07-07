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
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return None

def init_db():
    conn = get_db()
    if not conn:
        print(" Cannot initialize database - connection failed")
        return
    
    conn.autocommit = True
    c = conn.cursor()
    
    try:
        # Create Tables (Using BIGINT for chat_id to prevent overflow errors)
        c.execute('''CREATE TABLE IF NOT EXISTS stock
            (id SERIAL PRIMARY KEY, item_name TEXT, color TEXT, quantity INTEGER,
             cost_price REAL, selling_price REAL, category TEXT, UNIQUE(item_name, color))''')
        c.execute('''CREATE TABLE IF NOT EXISTS sales
            (id SERIAL PRIMARY KEY, item_name TEXT, color TEXT, quantity INTEGER,
             profit REAL, sold_by BIGINT, customer_info TEXT DEFAULT 'Walk-in', 
             sold_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_state
            (chat_id BIGINT PRIMARY KEY, state TEXT, data TEXT)''')
        
        # Add customer_info column if it doesn't exist
        c.execute("""SELECT column_name FROM information_schema.columns 
                     WHERE table_name='sales' AND column_name='customer_info'""")
        if not c.fetchone():
            c.execute("ALTER TABLE sales ADD COLUMN customer_info TEXT DEFAULT 'Walk-in'")

        # Auto-populate
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
                             VALUES (%s, %s, %s, %s, %s, %s) 
                             ON CONFLICT (item_name, color) DO NOTHING""", item)
            except Exception as e:
                print(f"Error inserting {item[0]}: {e}")
        
        print("✅ Cloud Database initialized and populated!")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
    finally:
        c.close()
        conn.close()

def save_state(chat_id, state, data_dict=None):
    conn = get_db()
    if not conn:
        print(f"❌ Cannot save state - no database connection")
        return False
    try:
        data_json = json.dumps(data_dict) if data_dict else "{}"
        c = conn.cursor()
        c.execute("""INSERT INTO user_state (chat_id, state, data) VALUES (%s, %s, %s) 
                     ON CONFLICT (chat_id) DO UPDATE SET state = EXCLUDED.state, data = EXCLUDED.data""", 
                  (chat_id, state, data_json))
        conn.commit()
        c.close()
        print(f"✅ State saved: chat_id={chat_id}, state={state}")
        return True
    except Exception as e:
        print(f" Save state error: {e}")
        return False
    finally:
        conn.close()

def get_state(chat_id):
    conn = get_db()
    if not conn:
        print(f"❌ Cannot get state - no database connection")
        return None, {}
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT state, data FROM user_state WHERE chat_id=%s", (chat_id,))
        row = cursor.fetchone()
        cursor.close()
        if row:
            try:
                state = row['state'].strip() if row['state'] else None
                data = json.loads(row['data']) if row['data'] else {}
                print(f"✅ State retrieved: chat_id={chat_id}, state={state}")
                return state, data
            except Exception as e:
                print(f"❌ Error parsing state data: {e}")
                return row['state'], {}
        else:
            print(f"️ No state found for chat_id={chat_id}")
    except Exception as e:
        print(f"❌ Get state error: {e}")
    finally:
        conn.close()
    return None, {}

def clear_state(chat_id):
    conn = get_db()
    if not conn:
        return
    try:
        c = conn.cursor()
        c.execute("DELETE FROM user_state WHERE chat_id=%s", (chat_id,))
        conn.commit()
        c.close()
    except Exception as e:
        print(f"❌ Clear state error: {e}")
    finally:
        conn.close()

# --- TELEGRAM API FUNCTIONS ---
def send_message(chat_id, text, reply_markup=None):
    url = f"{API_URL}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=data, timeout=10)
        if not response.ok:
            print(f"❌ Send message error: {response.text}")
    except Exception as e:
        print(f"❌ Send Error: {e}")

def send_force_reply(chat_id, text, placeholder="Type here..."):
    url = f"{API_URL}/sendMessage"
    data = {
        "chat_id": chat_id, 
        "text": text, 
        "parse_mode": "Markdown",
        "reply_markup": {"force_reply": True, "input_field_placeholder": placeholder}
    }
    try:
        response = requests.post(url, json=data, timeout=10)
        if not response.ok:
            print(f"❌ Force reply error: {response.text}")
    except Exception as e:
        print(f"❌ Force Reply Error: {e}")

def answer_callback(query_id, text=""):
    url = f"{API_URL}/answerCallbackQuery"
    data = {"callback_query_id": query_id, "text": text}
    try:
        requests.post(url, json=data, timeout=5)
    except Exception as e:
        print(f"❌ Answer Callback Error: {e}")

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"{API_URL}/editMessageText"
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=data, timeout=10)
        if not response.ok:
            print(f"❌ Edit message error: {response.text}")
    except Exception as e:
        print(f"❌ Edit Message Error: {e}")

# --- UI BUILDERS ---
def build_main_menu(chat_id):
    is_owner = chat_id in OWNER_IDS
    if is_owner:
        buttons = [
            [{"text": "📋 View Stock", "callback_data": "main_view_stock"}, {"text": "💰 Record Sale", "callback_data": "main_record_sale"}],
            [{"text": " Recent Sales", "callback_data": "main_recent_sales"}, {"text": "📊 Daily Summary", "callback_data": "main_summary"}],
            [{"text": "➕ Add Stock", "callback_data": "main_add_stock"}, {"text": "✏️ Edit/Remove", "callback_data": "main_edit_item"}],
            [{"text": "⚠️ Low Stock", "callback_data": "main_low_stock"}]
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
        [{"text": "⚫ Black", "callback_data": "color_Black"}, {"text": " White", "callback_data": "color_White"}],
        [{"text": "🟡 Yellow", "callback_data": "color_Yellow"}, {"text": "🟢 Green", "callback_data": "color_Green"}],
        [{"text": " Red", "callback_data": "color_Red"}, {"text": "🟣 Purple", "callback_data": "color_Purple"}],
        [{"text": "🟨 Gold", "callback_data": "color_Gold"}, {"text": "⚪ Silver", "callback_data": "color_Silver"}],
        [{"text": "🔵 Blue", "callback_data": "color_Blue"}, {"text": "📝 Custom", "callback_data": "color_Custom"}]
    ]

# --- BUTTON HANDLER ---
def button_handler(query):
    chat_id = query['message']['chat']['id']
    message_id = query['message']['message_id']
    callback_data = query['data']
    
    print(f"🔘 Button clicked: {callback_data}")
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
                text, markup = "📋 No items in stock yet.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                buttons = [[{"text": cat['category'], "callback_data": f"viewcat_{cat['category']}"}] for cat in categories]
                buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
                text, markup = "📋 *VIEW STOCK*\n\nSelect a category:", {"inline_keyboard": buttons}
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
            
            text = f"📋 *{category}*\n\n" if items else f"📋 No items in *{category}*."
            for item in items:
                color_str = f" ({item['color']})" if item['color'] else ""
                text += f"• *{item['item_name']}*{color_str}\n  Qty: {item['quantity']} | Price: GHS {item['selling_price']:.0f}\n\n"
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
                text, markup = "📋 No items in stock to sell.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                buttons = [[{"text": cat['category'], "callback_data": f"sellcat_{cat['category']}"}] for cat in categories]
                buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
                text, markup = "💰 *RECORD SALE*\n\nSelect the item category:", {"inline_keyboard": buttons}
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
                text, markup = f"No items in stock for *{category}*.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                buttons = []
                for item in items:
                    color_str = f" ({item['color']})" if item['color'] else ""
                    title = f"{item['item_name']}{color_str} ({item['quantity']})"
                    buttons.append([{"text": title, "callback_data": f"s_{item['id']}"}])
                buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
                text, markup = "💰 *RECORD SALE*\n\nSelect the item sold:", {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("s_"):
            item_id = int(callback_data[2:])
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            
            if not item:
                text, markup = "Item not found.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                color_str = f" ({item['color']})" if item['color'] else ""
                text = f"💰 *RECORD SALE*\n\nItem: *{item['item_name']}*{color_str}\nAvailable: {item['quantity']} pcs\n\n*How many are you selling?*\n\n_Tap below to type the amount._"
                save_state(chat_id, f"sell_qty_{item_id}")
                markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
                edit_message(chat_id, message_id, text, reply_markup=markup)
                send_force_reply(chat_id, "👇 *Type the quantity now:*", "e.g. 5")
            return

        elif callback_data.startswith("sw_"):
            parts = callback_data.split("_")
            item_id, qty = int(parts[1]), int(parts[2])
            process_sale_confirmation(chat_id, item_id, qty, "Walk-in Customer", message_id=message_id)
            return

        elif callback_data.startswith("st_"):
            parts = callback_data.split("_")
            item_id, qty = int(parts[1]), int(parts[2])
            save_state(chat_id, f"sell_type_{item_id}_{qty}")
            send_force_reply(chat_id, "💰 *RECORD SALE*\n\nPlease type the Customer's Name & Phone Number:", "e.g. John 0241234567")
            return

        elif callback_data == "main_recent_sales":
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM sales ORDER BY sold_at DESC LIMIT 10")
            sales = c.fetchall()
            c.close(); conn.close()
            
            text = " *RECENT SALES (Last 10)*\n\n" if sales else "📜 No recent sales recorded."
            for sale in sales:
                color_str = f" ({sale['color']})" if sale['color'] else ""
                dt_str = sale['sold_at'].strftime("%d/%m/%Y %I:%M %p") if sale['sold_at'] else "Unknown"
                text += f"• {sale['item_name']}{color_str} x{sale['quantity']}\n  🕒 {dt_str}\n  👤 {sale['customer_info']}\n  💰 Profit: GHS {sale['profit']:.2f}\n\n"
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_add_stock":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only the owner can add stock.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            
            buttons = [[{"text": cat['category'], "callback_data": f"addcat_{cat['category']}"}] for cat in categories]
            buttons.append([{"text": "➕ Add Brand New Item", "callback_data": "addstock_new"}])
            buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
            text = "➕ *ADD STOCK*\n\nSelect a category to restock, or add a new item:"
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
                text, markup = f"No items in *{category}*.", {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_add_stock"}]]}
            else:
                buttons = []
                for item in items:
                    color_str = f" ({item['color']})" if item['color'] else ""
                    title = f"{item['item_name']}{color_str} [Qty: {item['quantity']}]"
                    buttons.append([{"text": title, "callback_data": f"a_{item['id']}"}])
                buttons.append([{"text": "⬅️ Back to Categories", "callback_data": "main_add_stock"}])
                text = f"➕ *ADD STOCK: {category}*\n\nSelect the exact item to restock:"
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
                text, markup = "Item not found.", {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_add_stock"}]]}
            else:
                color_str = f" ({item['color']})" if item['color'] else ""
                text = f"➕ *RESTOCK: {item['item_name']}*{color_str}\n\nCurrent Stock: {item['quantity']}\n\n*How many units are you adding?*\n\n_Tap below to type the amount._"
                save_state(chat_id, f"add_qty_{item_id}")
                markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
                edit_message(chat_id, message_id, text, reply_markup=markup)
                send_force_reply(chat_id, " *Type the quantity now:*", "e.g. 20")
            return

        elif callback_data == "addstock_new":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only the owner can add stock.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            save_state(chat_id, "add_new_name")
            send_force_reply(chat_id, "➕ *ADD NEW ITEM*\n\nStep 1/5: What is the item name?", "e.g. iPhone 15 Screen")
            return

        elif callback_data.startswith("color_"):
            color = callback_data[6:]
            state, data_dict = get_state(chat_id)
            if color == "Custom":
                save_state(chat_id, "add_new_color_text", data_dict)
                send_force_reply(chat_id, "➕ *ADD NEW ITEM*\n\nPlease type the custom color name:", "e.g. Rose Gold")
            else:
                data_dict['color'] = color
                save_state(chat_id, "add_new_qty", data_dict)
                text = f"✅ Color: *{color}*\n\n*How many units are you adding?*\n\n_Tap below to type the amount._"
                markup = {"inline_keyboard": [[{"text": " Cancel", "callback_data": "main_menu"}]]}
                edit_message(chat_id, message_id, text, reply_markup=markup)
                send_force_reply(chat_id, "👇 *Type the quantity now:*", "e.g. 15")
            return

        elif callback_data == "addcat_custom":
            state, data_dict = get_state(chat_id)
            text = f"✅ Sell: *GHS {data_dict.get('sell', 0):.2f}*\n\nPlease type the custom category name:"
            save_state(chat_id, "add_new_category_text", data_dict)
            send_force_reply(chat_id, text, "e.g. Tools")
            return

        elif callback_data.startswith("selcat_"):
            category = callback_data[7:]
            state, data_dict = get_state(chat_id)
            data_dict['category'] = category
            save_state(chat_id, "add_new_confirm", data_dict)
            text_msg = f"➕ *CONFIRM NEW ITEM*\n\nName: *{data_dict['name']}*\nColor: {data_dict['color'] or 'None'}\nQuantity: {data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {category}\n\nAdd this item?"
            markup = {"inline_keyboard": [[{"text": "✅ Confirm", "callback_data": "addconfirm"}, {"text": "❌ Cancel", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text_msg, reply_markup=markup)
            return

        elif callback_data == "addconfirm":
            state, data_dict = get_state(chat_id)
            required_keys = ['name', 'color', 'qty', 'cost', 'sell', 'category']
            if not all(k in data_dict for k in required_keys):
                edit_message(chat_id, message_id, "❌ Incomplete data.", {"inline_keyboard": [[{"text": " Main Menu", "callback_data": "main_menu"}]]})
                clear_state(chat_id)
                return
            
            conn = get_db()
            if not conn: return
            c = conn.cursor()
            try:
                c.execute("""INSERT INTO stock (item_name, color, quantity, cost_price, selling_price, category)
                             VALUES (%s, %s, %s, %s, %s, %s)
                             ON CONFLICT (item_name, color) DO NOTHING RETURNING id""",
                             (data_dict['name'], data_dict['color'], data_dict['qty'],
                              data_dict['cost'], data_dict['sell'], data_dict['category']))
                conn.commit()
                text = f"✅ *New Item Added!*\n\n{data_dict['name']} ({data_dict['color'] or 'None'}) added with {data_dict['qty']} units." if c.fetchone() else "❌ Item with same name and color already exists."
            except Exception as e:
                text = f"❌ Error: {e}"
            finally:
                c.close(); conn.close()
            markup = {"inline_keyboard": [[{"text": "➕ Add More Stock", "callback_data": "main_add_stock"}, {"text": " Main Menu", "callback_data": "main_menu"}]]}
            clear_state(chat_id)
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_edit_item":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only the owner can edit items.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            
            buttons = [[{"text": cat['category'], "callback_data": f"editcat_{cat['category']}"}] for cat in categories]
            buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
            text = "✏️ *EDIT/REMOVE ITEM*\n\nSelect a category:"
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
                text, markup = f"No items in *{category}*.", {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_edit_item"}]]}
            else:
                buttons = []
                for item in items:
                    color_str = f" ({item['color']})" if item['color'] else ""
                    title = f"{item['item_name']}{color_str} [Qty: {item['quantity']}]"
                    buttons.append([{"text": title, "callback_data": f"e_{item['id']}"}])
                buttons.append([{"text": "⬅️ Back to Categories", "callback_data": "main_edit_item"}])
                text = f"✏️ *EDIT: {category}*\n\nSelect the item to edit or remove:"
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
                text, markup = "Item not found.", {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "main_edit_item"}]]}
            else:
                color_str = f" ({item['color']})" if item['color'] else ""
                text = f"✏️ *EDIT ITEM*\n\n*{item['item_name']}*{color_str}\nCategory: {item['category']}\nQty: {item['quantity']}\nCost: GHS {item['cost_price']:.2f}\nSell: GHS {item['selling_price']:.2f}\n\n*What would you like to change?*"
                markup = {"inline_keyboard": [
                    [{"text": "📦 Update Qty", "callback_data": f"eq_{item_id}"}, {"text": "💰 Update Cost", "callback_data": f"ec_{item_id}"}],
                    [{"text": "💵 Update Sell Price", "callback_data": f"es_{item_id}"}],
                    [{"text": "🗑️ Delete Item", "callback_data": f"del_{item_id}"}],
                    [{"text": "⬅️ Back", "callback_data": f"editcat_{item['category']}"}]
                ]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data.startswith("eq_"):
            item_id = int(callback_data[3:])
            if save_state(chat_id, f"edit_qty_{item_id}"):
                send_force_reply(chat_id, "✏️ *UPDATE QUANTITY*\n\nType the NEW total quantity for this item:", "e.g. 50")
            return

        elif callback_data.startswith("ec_"):
            item_id = int(callback_data[3:])
            if save_state(chat_id, f"edit_cost_{item_id}"):
                send_force_reply(chat_id, "✏️ *UPDATE COST PRICE*\n\nType the NEW cost price per unit:", "e.g. 15.50")
            return

        elif callback_data.startswith("es_"):
            item_id = int(callback_data[3:])
            if save_state(chat_id, f"edit_sell_{item_id}"):
                send_force_reply(chat_id, "✏️ *UPDATE SELLING PRICE*\n\nType the NEW selling price per unit:", "e.g. 25.00")
            return

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
                text = f"️ *CONFIRM DELETION*\n\nAre you sure you want to permanently delete:\n*{item['item_name']}*{color_str}?\n\n_This cannot be undone._"
                markup = {"inline_keyboard": [
                    [{"text": "✅ Yes, Delete", "callback_data": f"cdel_{item_id}"}, {"text": "❌ No, Cancel", "callback_data": f"e_{item_id}"}]
                ]}
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
            
            text = "🗑️ *Item Deleted Successfully!*\n\n*What next?*"
            markup = {"inline_keyboard": [[{"text": "✏️ Edit Another Item", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
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
            text = f"📊 *DAILY SUMMARY ({today})*\n\n🛒 Sales Today: {count}\n💰 Total Profit: GHS {total:.2f}"
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return

        elif callback_data == "main_low_stock":
            if chat_id not in OWNER_IDS:
                edit_message(chat_id, message_id, "❌ Only the owner can view low stock.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
                return
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE quantity <= 5 ORDER BY quantity ASC")
            items = c.fetchall()
            c.close(); conn.close()
            
            text = "⚠️ *LOW STOCK ALERT*\n\n" if items else "✅ All items have more than 5 in stock."
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
        print(f"❌ Button handler error: {e}")
        edit_message(chat_id, message_id, "❌ An error occurred. Please try again.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})

def process_sale_confirmation(chat_id, item_id, qty, customer_info, message_id=None):
    conn = get_db()
    if not conn:
        send_message(chat_id, "❌ Database error.", {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})
        return
    
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
        item = c.fetchone()
        
        if not item or item['quantity'] < qty:
            text = "❌ Not enough stock."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            if message_id: edit_message(chat_id, message_id, text, reply_markup=markup)
            else: send_message(chat_id, text, reply_markup=markup)
            c.close(); conn.close(); clear_state(chat_id)
            return

        new_qty = item['quantity'] - qty
        profit = (item['selling_price'] - item['cost_price']) * qty
        
        c.execute("UPDATE stock SET quantity=%s WHERE id=%s", (new_qty, item_id))
        c.execute("INSERT INTO sales (item_name, color, quantity, profit, sold_by, customer_info) VALUES (%s, %s, %s, %s, %s, %s)",
                    (item['item_name'], item['color'], qty, profit, chat_id, customer_info))
        conn.commit()
        c.close()
    except Exception as e:
        print(f"❌ Sale confirmation error: {e}")
        send_message(chat_id, "❌ Error recording sale.", {"inline_keyboard": [[{"text": " Main Menu", "callback_data": "main_menu"}]]})
        conn.close(); clear_state(chat_id)
        return
    
    conn.close()
    
    color_str = f" ({item['color']})" if item['color'] else ""
    now = datetime.now().strftime("%d/%m/%Y %I:%M %p")
    
    text = f"✅ *Sale Recorded!*\n\n🕒 {now}\n📦 Sold {qty}x *{item['item_name']}*{color_str}\n Customer: *{customer_info}*\n Remaining: {new_qty}\n💰 Profit: GHS {profit:.2f}"
    markup = {"inline_keyboard": [[{"text": "💰 Record Another Sale", "callback_data": "main_record_sale"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
    
    if message_id: edit_message(chat_id, message_id, text, reply_markup=markup)
    else: send_message(chat_id, text, reply_markup=markup)
        
    if chat_id in SECRETARY_IDS and OWNER_IDS:
        for owner in OWNER_IDS:
            send_message(owner, f"📢 Staff sold {qty}x *{item['item_name']}*{color_str} to {customer_info}.\nProfit: GHS {profit:.2f}")
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
    print(f" Text received: '{text}' | State: {state} | Data: {data_dict}")
    
    if state is None:
        if chat_id in ALLOWED_IDS:
            text_msg, markup = build_main_menu(chat_id)
            send_message(chat_id, " I didn't catch that. Here is the main menu:", reply_markup=markup)
            clear_state(chat_id)
        else:
            send_message(chat_id, "⛔ Access Denied.")
        return

    try:
        if state.startswith("sell_qty_"):
            item_id = int(state.split("_")[2])
            try:
                qty = int(text)
                if qty <= 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Please enter a valid positive number.")
                return
            
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            
            if item and qty > item['quantity']:
                send_message(chat_id, f"❌ Not enough stock! Only {item['quantity']} available.")
                return

            markup = {"inline_keyboard": [
                [{"text": "🚶 Walk-in Customer", "callback_data": f"sw_{item_id}_{qty}"}],
                [{"text": "✍️ Enter Name & Number", "callback_data": f"st_{item_id}_{qty}"}],
                [{"text": "❌ Cancel", "callback_data": "main_menu"}]
            ]}
            send_message(chat_id, f"✅ Quantity: *{qty}*\n\nWho is buying this?", reply_markup=markup)
            return

        elif state.startswith("sell_type_"):
            parts = state.split("_")
            item_id, qty = int(parts[2]), int(parts[3])
            customer_info = text if text.lower() != "walk-in" else "Walk-in Customer"
            process_sale_confirmation(chat_id, item_id, qty, customer_info)
            return

        elif state.startswith("add_qty_"):
            item_id = int(state.split("_")[2])
            try:
                qty = int(text)
                if qty <= 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Please enter a valid positive number.")
                return
            
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            if item:
                new_qty = item['quantity'] + qty
                c.execute("UPDATE stock SET quantity=%s WHERE id=%s", (new_qty, item_id))
                conn.commit()
                text_msg = f"✅ *Stock Updated!*\n\n*{item['item_name']}*: {item['quantity']} → {new_qty}"
                markup = {"inline_keyboard": [[{"text": "➕ Add More Stock", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            else:
                text_msg = "❌ Item not found."
                markup = {"inline_keyboard": [[{"text": " Main Menu", "callback_data": "main_menu"}]]}
            c.close(); conn.close(); clear_state(chat_id)
            send_message(chat_id, text_msg, reply_markup=markup)
            return

        elif state.startswith("edit_qty_"):
            item_id = int(state.split("_")[2])
            try:
                qty = int(text)
                if qty < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Please enter a valid positive number.")
                return
            
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("UPDATE stock SET quantity=%s WHERE id=%s", (qty, item_id))
            conn.commit()
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            
            text_msg = f"✅ *Quantity Updated!*\n\n*{item['item_name']}* is now {qty}."
            markup = {"inline_keyboard": [[{"text": "✏️ Edit Another", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            clear_state(chat_id)
            send_message(chat_id, text_msg, reply_markup=markup)
            return

        elif state.startswith("edit_cost_"):
            item_id = int(state.split("_")[2])
            try:
                cost = float(text)
                if cost < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Please enter a valid number.")
                return
            
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("UPDATE stock SET cost_price=%s WHERE id=%s", (cost, item_id))
            conn.commit()
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            
            text_msg = f"✅ *Cost Price Updated!*\n\n*{item['item_name']}* cost is now GHS {cost:.2f}."
            markup = {"inline_keyboard": [[{"text": "✏️ Edit Another", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            clear_state(chat_id)
            send_message(chat_id, text_msg, reply_markup=markup)
            return

        elif state.startswith("edit_sell_"):
            item_id = int(state.split("_")[2])
            try:
                sell = float(text)
                if sell < 0: raise ValueError
            except ValueError:
                send_message(chat_id, "❌ Please enter a valid number.")
                return
            
            conn = get_db()
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("UPDATE stock SET selling_price=%s WHERE id=%s", (sell, item_id))
            conn.commit()
            c.execute("SELECT * FROM stock WHERE id=%s", (item_id,))
            item = c.fetchone()
            c.close(); conn.close()
            
            text_msg = f"✅ *Selling Price Updated!*\n\n*{item['item_name']}* sell price is now GHS {sell:.2f}."
            markup = {"inline_keyboard": [[{"text": "✏️ Edit Another", "callback_data": "main_edit_item"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            clear_state(chat_id)
            send_message(chat_id, text_msg, reply_markup=markup)
            return

        elif state == "add_new_name":
            data_dict['name'] = text
            save_state(chat_id, "add_new_color_btn", data_dict)
            markup = {"inline_keyboard": get_color_buttons() + [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
            send_message(chat_id, f"✅ Item: *{text}*\n\nSelect color:", reply_markup=markup)
            return

        elif state == "add_new_color_text":
            data_dict['color'] = text
            save_state(chat_id, "add_new_qty", data_dict)
            text = f"✅ Color: *{text}*\n\n*How many units are you adding?*"
            markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
            send_message(chat_id, text, reply_markup=markup)
            send_force_reply(chat_id, "👇 *Type the quantity now:*", "e.g. 15")
            return

        elif state == "add_new_qty":
            try:
                qty = int(text)
                if qty <= 0: raise ValueError
            except ValueError:
                send_message(chat_id, " Please enter a positive number.")
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
            if not conn: return
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT DISTINCT category FROM stock ORDER BY category")
            categories = c.fetchall()
            c.close(); conn.close()
            
            buttons = []
            for cat in categories[:5]:
                buttons.append([{"text": cat['category'], "callback_data": f"selcat_{cat['category']}"}])
            buttons.append([{"text": "📝 Type Custom Category", "callback_data": "addcat_custom"}])
            buttons.append([{"text": "❌ Cancel", "callback_data": "main_menu"}])
            send_message(chat_id, f"✅ Sell: *GHS {sell:.2f}*\n\nSelect a category:", reply_markup={"inline_keyboard": buttons})
            return
        
        elif state == "add_new_category_text":
            data_dict['category'] = text
            save_state(chat_id, "add_new_confirm", data_dict)
            text_msg = f"➕ *CONFIRM NEW ITEM*\n\nName: *{data_dict['name']}*\nColor: {data_dict['color'] or 'None'}\nQuantity: {data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {text}\n\nAdd this item?"
            markup = {"inline_keyboard": [[{"text": "✅ Confirm", "callback_data": "addconfirm"}, {"text": "❌ Cancel", "callback_data": "main_menu"}]]}
            send_message(chat_id, text_msg, reply_markup=markup)
            return

        # FALLBACK
        if chat_id in ALLOWED_IDS:
            text_msg, markup = build_main_menu(chat_id)
            send_message(chat_id, "🤔 I didn't catch that. Here is the main menu:", reply_markup=markup)
            clear_state(chat_id)
        else:
            send_message(chat_id, "⛔ Access Denied.")
    
    except Exception as e:
        print(f"❌ Text handler error: {e}")
        send_message(chat_id, "❌ An error occurred. Type /start to restart.", reply_markup={"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]})

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
        print(f"❌ Processing Error: {e}")
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
