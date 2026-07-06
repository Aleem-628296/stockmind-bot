import sqlite3

def populate_victory_venture():
    conn = sqlite3.connect('stock.db')
    c = conn.cursor()

    colors = ["White", "Black", "Yellow", "Green", "Red", "Purple", "Gold", "Silver", "Blue"]
    items = []

    # Screens & Displays
    for screen in ["iPhone Screen", "Samsung Screen", "Infinix Screen", "Tecno Screen", "iPad Touch Screen"]:
        items.append((screen, "", 1, 0.0, 0.0, "Screens & Displays"))
    
    # Chargers & Power
    for charger in ["Original Charger", "Multiple Purpose Charger", "Wireless Charging Flex"]:
        items.append((charger, "", 1, 0.0, 0.0, "Chargers & Power"))
    
    # Housings & Back Covers (ALL 9 COLORS)
    for part in ["Back Glass", "Housing"]:
        for color in colors:
            items.append((part, color, 1, 0.0, 0.0, "Housings & Back Covers"))
    
    # Batteries
    for bat in ["iPhone Battery", "Battery Flex"]:
        items.append((bat, "", 1, 0.0, 0.0, "Batteries & Power"))
    
    # Audio & Speakers
    for audio in ["Earpiece", "Ear Speaker", "Down Speaker"]:
        items.append((audio, "", 1, 0.0, 0.0, "Audio & Speakers"))
    
    # Cameras & Sensors
    for cam in ["Camera Lens", "Face ID Flex", "Mouthpiece (Mic)"]:
        items.append((cam, "", 1, 0.0, 0.0, "Cameras & Sensors"))
    
    # Small Parts
    items.append(("Down Screws", "", 1, 0.0, 0.0, "Small Parts"))

    added_count = 0
    for item in items:
        try:
            c.execute("INSERT INTO stock (item_name, color, quantity, cost_price, selling_price, category) VALUES (?, ?, ?, ?, ?, ?)", item)
            added_count += 1
        except sqlite3.IntegrityError:
            pass # Skip duplicates
        except Exception as e:
            print(f"Error adding {item[0]}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ SUCCESS! Added {added_count} items to Victory Venture inventory!")

if __name__ == "__main__":
    populate_victory_venture()
