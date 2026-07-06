import os
import sqlite3
import requests
import time
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_IDS = [int(id.strip()) for id in os.getenv("OWNER_ID", "").split(",") if id.strip()]
SECRETARY_IDS = [int(id.strip()) for id in os.getenv("SECRETARY_ID", "").split(",") if id.strip()]
ALLOWED_IDS = OWNER_IDS + SECRETARY_IDS
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

processed_updates = set()
MAX_PROCESSED_CACHE = 1000

def init_db():
    conn = sqlite3.connect('stock.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL;')
    c.execute('''CREATE TABLE IF NOT EXISTS stock
        (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT, color TEXT, quantity INTEGER,
         cost_price REAL, selling_price REAL, category TEXT, UNIQUE(item_name, color))''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales
        (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT, color TEXT, quantity INTEGER,
         profit REAL, sold_by INTEGER, sold_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_state
        (chat_id INTEGER PRIMARY KEY, state TEXT, data TEXT)''')
    
    if c.execute("SELECT count(*) FROM stock").fetchone()[0] == 0:
        sample_items = [
            ("iPhone 15 Case", "Black", 20, 15, 25, "Phone Cases"),
            ("Samsung Charger", "", 50, 10, 20, "Chargers"),
            ("AirPods Pro", "White", 10, 80, 120, "Audio"),
            ("Screen Protector", "", 100, 2, 5, "Accessories")
        ]
        c.executemany("INSERT INTO stock (item_name, color, quantity, cost_price, selling_price, category) VALUES (?, ?, ?, ?, ?, ?)", sample_items)
        conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect('stock.db', timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def save_state(chat_id, state, data=""):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO user_state (chat_id, state, data) VALUES (?, ?, ?)", (chat_id, state, data))
    conn.commit()
    conn.close()

def get_state(chat_id):
    conn = get_db()
    row = conn.execute("SELECT state, data FROM user_state WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    return (row['state'], row['data']) if row else (None, None)

def clear_state(chat_id):
    conn = get_db()
    conn.execute("DELETE FROM user_state WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()

def send_message(chat_id, text, reply_markup=None):
    url = f"{API_URL}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = reply_markup
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

def build_main_menu(chat_id):
    is_owner = chat_id in OWNER_IDS
    if is_owner:
        buttons = [
            [{"text": "📋 View Stock", "callback_data": "main_view_stock"}],
            [{"text": "💰 Record Sale", "callback_data": "main_record_sale"}],
            [{"text": "📊 Daily Summary", "callback_data": "main_summary"}],
            [{"text": "➕ Add Stock", "callback_data": "main_add_stock"}],
            [{"text": "⚠️ Low Stock", "callback_data": "main_low_stock"}]
        ]
        text = "📊 *STOCKMIND — MAIN MENU*\n\nWelcome, Boss. What would you like to do?"
    else:
        buttons = [
            [{"text": "📋 View Stock", "callback_data": "main_view_stock"}],
            [{"text": "💰 Record Sale", "callback_data": "main_record_sale"}],
            [{"text": "📊 Daily Summary", "callback_data": "main_summary"}]
        ]
        text = "📊 *STOCKMIND — MAIN MENU*\n\nWelcome. What would you like to do?"
    return text, {"inline_keyboard": buttons}

def button_handler(query):
    chat_id = query['message']['chat']['id']
    message_id = query['message']['message_id']
    callback_data = query['data']
    
    answer_callback(query['id'])
    
    # MAIN MENU
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
            buttons = [[{"text": cat['category'] or "Uncategorized", "callback_data": f"viewcat_{cat['category']}"}] for cat in categories]
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
        
        markup = {"inline_keyboard": [
            [{"text": "📋 View Stock", "callback_data": "main_view_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]
        ]}
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
            buttons = [[{"text": cat['category'] or "Uncategorized", "callback_data": f"sellcat_{cat['category']}"}] for cat in categories]
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
            text = f"💰 *RECORD SALE*\n\nItem: *{item['item_name']}*{color_str}\nAvailable: {item['quantity']} pcs\n\nHow many are you selling?"
            buttons = []
            for qty in [1, 2, 3, 5, 10]:
                if qty <= item['quantity']:
                    buttons.append([{"text": str(qty), "callback_data": f"sellqty_{item_id}_{qty}"}])
            buttons.append([{"text": "❌ Cancel", "callback_data": "main_menu"}])
            markup = {"inline_keyboard": buttons}
        
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return
    
    elif callback_data.startswith("sellqty_"):
        parts = callback_data.split("_")
        item_id = int(parts[1])
        qty = int(parts[2])
        conn = get_db()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        conn.close()
        
        if not item:
            text = "Item not found."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            color_str = f" ({item['color']})" if item['color'] else ""
            profit = (item['selling_price'] - item['cost_price']) * qty
            text = f"💰 *CONFIRM SALE*\n\nItem: *{item['item_name']}*{color_str}\nQuantity: {qty}\nPrice: GHS {item['selling_price']:.2f} each\nTotal: GHS {item['selling_price'] * qty:.2f}\nProfit: GHS {profit:.2f}\n\nConfirm this sale?"
            markup = {"inline_keyboard": [
                [{"text": "✅ Confirm Sale", "callback_data": f"sellconfirm_{item_id}_{qty}"}, {"text": "❌ Cancel", "callback_data": "main_menu"}]
            ]}
        
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return
    
    elif callback_data.startswith("sellconfirm_"):
        parts = callback_data.split("_")
        item_id = int(parts[1])
        qty = int(parts[2])
        
        conn = get_db()
        item = conn.execute("SELECT * FROM stock WHERE id=?", (item_id,)).fetchone()
        
        if not item or item['quantity'] < qty:
            text = "❌ Not enough stock."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            new_qty = item['quantity'] - qty
            profit = (item['selling_price'] - item['cost_price']) * qty
            conn.execute("UPDATE stock SET quantity=? WHERE id=?", (new_qty, item_id))
            conn.execute("INSERT INTO sales (item_name, color, quantity, profit, sold_by) VALUES (?, ?, ?, ?, ?)",
                        (item['item_name'], item['color'], qty, profit, chat_id))
            conn.commit()
            conn.close()
            
            color_str = f" ({item['color']})" if item['color'] else ""
            text = f"✅ *Sale Recorded!*\n\nSold {qty}x *{item['item_name']}*{color_str}\nRemaining: {new_qty}\nProfit: GHS {profit:.2f}"
            markup = {"inline_keyboard": [[{"text": "💰 Record Another Sale", "callback_data": "main_record_sale"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            
            if chat_id in SECRETARY_IDS and OWNER_IDS:
                for owner in OWNER_IDS:
                    send_message(owner, f"📢 Staff sold {qty}x *{item['item_name']}*{color_str}.\nProfit: GHS {profit:.2f}")
        
        clear_state(chat_id)
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return
    
    # ADD STOCK
    elif callback_data == "main_add_stock":
        if chat_id not in OWNER_IDS:
            text = "❌ Only the owner can add stock."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        
        conn = get_db()
        items = conn.execute("SELECT DISTINCT item_name FROM stock ORDER BY item_name").fetchall()
        conn.close()
        
        buttons = []
        for item in items[:10]:
            buttons.append([{"text": item['item_name'], "callback_data": f"addstock_existing_{item['item_name']}"}])
        buttons.append([{"text": "➕ Add New Item", "callback_data": "addstock_new"}])
        buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])
        
        text = "➕ *ADD STOCK*\n\nSelect an existing item to restock, or add a new one:"
        markup = {"inline_keyboard": buttons}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return
    
    elif callback_data.startswith("addstock_existing_"):
        item_name = callback_data[20:]
        conn = get_db()
        items = conn.execute("SELECT * FROM stock WHERE item_name=?", (item_name,)).fetchall()
        conn.close()
        
        if not items:
            text = "Item not found."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            text = f"➕ *ADD STOCK: {item_name}*\n\nHow many units are you adding?"
            buttons = []
            for qty in [5, 10, 20, 50, 100]:
                buttons.append([{"text": str(qty), "callback_data": f"addqty_{item_name}_{qty}"}])
            buttons.append([{"text": "❌ Cancel", "callback_data": "main_menu"}])
            markup = {"inline_keyboard": buttons}
        
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return
    
    elif callback_data.startswith("addqty_"):
        parts = callback_data.split("_", 2)
        item_name = parts[1]
        qty = int(parts[2])
        
        conn = get_db()
        existing = conn.execute("SELECT id, quantity FROM stock WHERE item_name=? AND (color='' OR color IS NULL)", (item_name,)).fetchone()
        
        if existing:
            new_qty = existing['quantity'] + qty
            conn.execute("UPDATE stock SET quantity=? WHERE id=?", (new_qty, existing['id']))
            conn.commit()
            text = f"✅ *Stock Updated!*\n\n*{item_name}*: {existing['quantity']} → {new_qty}"
            markup = {"inline_keyboard": [[{"text": "➕ Add More Stock", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        else:
            text = "❌ Item not found."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        
        conn.close()
        clear_state(chat_id)
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return
    
    elif callback_data == "addstock_new":
        if chat_id not in OWNER_IDS:
            text = "❌ Only the owner can add stock."
            markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        
        text = "➕ *ADD NEW ITEM*\n\nStep 1/5: What is the item name?\n\n_Reply with the name (e.g., 'iPhone 15 Case')_"
        markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
        save_state(chat_id, "add_new_name")
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    elif callback_data.startswith("addcat_"):
        _, prev_data = get_state(chat_id)
        data_dict = eval(prev_data) if prev_data else {}
        if callback_data == "addcat_custom":
            text = f"✅ Sell: *GHS {data_dict.get('sell', 0):.2f}*\n\nPlease type the custom category name:"
            markup = {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
            save_state(chat_id, "add_new_category_text", str(data_dict))
            edit_message(chat_id, message_id, text, reply_markup=markup)
            return
        else:
            category = callback_data[8:]
            data_dict['category'] = category
            save_state(chat_id, "add_new_confirm", str(data_dict))
            text_msg = f"➕ *CONFIRM NEW ITEM*\n\nName: *{data_dict['name']}*\nColor: {data_dict['color'] or 'None'}\nQuantity: {data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {category}\n\nAdd this item?"
            markup = {"inline_keyboard": [
                [{"text": "✅ Confirm", "callback_data": "addconfirm"}, {"text": "❌ Cancel", "callback_data": "main_menu"}]
            ]}
            edit_message(chat_id, message_id, text_msg, reply_markup=markup)
            return

    elif callback_data == "addconfirm":
        _, prev_data = get_state(chat_id)
        data_dict = eval(prev_data) if prev_data else {}
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
            text = f"✅ *New Item Added!*\n\n{data_dict['name']} ({data_dict['color'] or 'None'}) added with {data_dict['qty']} units."
            markup = {"inline_keyboard": [[{"text": "➕ Add More Stock", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        except sqlite3.IntegrityError:
            text = "❌ Item with same name and color already exists."
            markup = {"inline_keyboard": [[{"text": "➕ Add More Stock", "callback_data": "main_add_stock"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        finally:
            conn.close()
        clear_state(chat_id)
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return

    # DAILY SUMMARY
    elif callback_data == "main_summary":
        conn = get_db()
        result = conn.execute("SELECT COUNT(*) as count, SUM(profit) as total FROM sales WHERE date(sold_at)=date('now')").fetchone()
        conn.close()
        
        count = result['count'] or 0
        total = result['total'] or 0
        
        text = f"📊 *DAILY SUMMARY*\n\n🛒 Sales Today: {count}\n💰 Total Profit: GHS {total:.2f}"
        markup = {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]}
        edit_message(chat_id, message_id, text, reply_markup=markup)
        return
    
    # LOW STOCK
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
    
    else:
        text, markup = build_main_menu(chat_id)
        clear_state(chat_id)
        edit_message(chat_id, message_id, text, reply_markup=markup)

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

    state, data = get_state(chat_id)
    
    if chat_id not in OWNER_IDS:
        # Only owners can send text commands beyond /start
        return
    
    if state == "add_new_name":
        data_dict = {"name": text}
        save_state(chat_id, "add_new_color", str(data_dict))
        send_message(chat_id, f"✅ Item: *{text}*\n\nWhat color? (or type 'none')", 
                    reply_markup={"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
    
    elif state == "add_new_color":
        color = "" if text.lower() == "none" else text
        _, prev_data = get_state(chat_id)
        data_dict = eval(prev_data) if prev_data else {}
        data_dict['color'] = color
        save_state(chat_id, "add_new_qty", str(data_dict))
        send_message(chat_id, f"✅ Color: *{color or 'None'}*\n\nHow many units?",
                    reply_markup={"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
    
    elif state == "add_new_qty":
        try:
            qty = int(text)
            if qty <= 0:
                send_message(chat_id, "❌ Please enter a positive number.")
                return
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
            return
        _, prev_data = get_state(chat_id)
        data_dict = eval(prev_data) if prev_data else {}
        data_dict['qty'] = qty
        save_state(chat_id, "add_new_cost", str(data_dict))
        send_message(chat_id, f"✅ Quantity: *{qty}*\n\nWhat is the cost price per unit?",
                    reply_markup={"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
    
    elif state == "add_new_cost":
        try:
            cost = float(text)
            if cost < 0:
                send_message(chat_id, "❌ Please enter a positive number.")
                return
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
            return
        _, prev_data = get_state(chat_id)
        data_dict = eval(prev_data) if prev_data else {}
        data_dict['cost'] = cost
        save_state(chat_id, "add_new_sell", str(data_dict))
        send_message(chat_id, f"✅ Cost: *GHS {cost:.2f}*\n\nWhat is the selling price per unit?",
                    reply_markup={"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]})
    
    elif state == "add_new_sell":
        try:
            sell = float(text)
            if sell < 0:
                send_message(chat_id, "❌ Please enter a positive number.")
                return
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number.")
            return
        _, prev_data = get_state(chat_id)
        data_dict = eval(prev_data) if prev_data else {}
        data_dict['sell'] = sell
        save_state(chat_id, "add_new_category_pending", str(data_dict))
        
        conn = get_db()
        categories = conn.execute("SELECT DISTINCT category FROM stock ORDER BY category").fetchall()
        conn.close()
        
        buttons = []
        for cat in categories[:5]:
            buttons.append([{"text": cat['category'], "callback_data": f"addcat_{cat['category']}"}])
        buttons.append([{"text": "📝 Type Custom Category", "callback_data": "addcat_custom"}])
        buttons.append([{"text": "❌ Cancel", "callback_data": "main_menu"}])
        
        send_message(chat_id, f"✅ Sell: *GHS {sell:.2f}*\n\nSelect a category:", reply_markup={"inline_keyboard": buttons})
    
    elif state == "add_new_category_text":
        _, prev_data = get_state(chat_id)
        data_dict = eval(prev_data) if prev_data else {}
        data_dict['category'] = text
        save_state(chat_id, "add_new_confirm", str(data_dict))
        
        text_msg = f"➕ *CONFIRM NEW ITEM*\n\nName: *{data_dict['name']}*\nColor: {data_dict['color'] or 'None'}\nQuantity: {data_dict['qty']}\nCost: GHS {data_dict['cost']:.2f}\nSell: GHS {data_dict['sell']:.2f}\nCategory: {text}\n\nAdd this item?"
        markup = {"inline_keyboard": [
            [{"text": "✅ Confirm", "callback_data": "addconfirm"}, {"text": "❌ Cancel", "callback_data": "main_menu"}]
        ]}
        send_message(chat_id, text_msg, reply_markup=markup)
    
    else:
        # Do not respond to unknown text to prevent stacking
        pass

def get_updates(offset=None):
    url = f"{API_URL}/getUpdates"
    params = {"timeout": 30, "offset": offset}
    try:
        response = requests.get(url, params=params, timeout=35).json()
        if response.get("ok"):
            return response.get("result", [])
    except Exception as e:
        print(f"Fetch Error: {e}")
        time.sleep(5)
    return []

def main():
    print("🚀 StockMind Engine Started (Telegram Mode)...")
    init_db()
    offset = None
    
    while True:
        updates = get_updates(offset)
        for update in updates:
            update_id = update['update_id']
            if update_id in processed_updates:
                continue
            processed_updates.add(update_id)
            if len(processed_updates) > MAX_PROCESSED_CACHE:
                processed_updates.pop()
            offset = update_id + 1
            
            try:
                if 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    if chat_id not in ALLOWED_IDS:
                        if 'text' in message and message['text'].strip() == "/start":
                            send_message(chat_id, "⛔ Access Denied.")
                        continue
                    if 'text' in message:
                        handle_text_message(chat_id, message['text'])
                elif 'callback_query' in update:
                    callback = update['callback_query']
                    chat_id = callback['message']['chat']['id']
                    if chat_id not in ALLOWED_IDS:
                        continue
                    button_handler(callback)
            except Exception as e:
                print(f"Processing Error: {e}")
                continue

if __name__ == "__main__":
    main()
