import sqlite3

def populate_victory_venture():
    conn = sqlite3.connect('stock.db')
    c = conn.cursor()

    # Format: (item_name, color, quantity, cost_price, selling_price, category)
    items = [
        # Screens & Displays
        ("iPhone Screen", "", 1, 0.0, 0.0, "Screens & Displays"),
        ("Samsung Screen", "", 1, 0.0, 0.0, "Screens & Displays"),
        ("Infinix Screen", "", 1, 0.0, 0.0, "Screens & Displays"),
        ("Tecno Screen", "", 1, 0.0, 0.0, "Screens & Displays"),
        ("iPad Touch Screen", "", 1, 0.0, 0.0, "Screens & Displays"),
        
        # Chargers & Power
        ("Original Charger", "", 1, 0.0, 0.0, "Chargers & Power"),
        ("Multiple Purpose Charger", "", 1, 0.0, 0.0, "Chargers & Power"),
        ("Wireless Charging Flex", "", 1, 0.0, 0.0, "Chargers & Power"),
        
        # Housings & Back Covers (With Colors)
        ("Back Glass", "Black", 1, 0.0, 0.0, "Housings & Back Covers"),
        ("Back Glass", "White", 1, 0.0, 0.0, "Housings & Back Covers"),
        ("Back Glass", "Blue", 1, 0.0, 0.0, "Housings & Back Covers"),
        ("Housing", "Black", 1, 0.0, 0.0, "Housings & Back Covers"),
        ("Housing", "White", 1, 0.0, 0.0, "Housings & Back Covers"),
        
        # Batteries
        ("iPhone Battery", "", 1, 0.0, 0.0, "Batteries & Power"),
        ("Battery Flex", "", 1, 0.0, 0.0, "Batteries & Power"),
        
        # Audio & Speakers
        ("Earpiece", "", 1, 0.0, 0.0, "Audio & Speakers"),
        ("Ear Speaker", "", 1, 0.0, 0.0, "Audio & Speakers"),
        ("Down Speaker", "", 1, 0.0, 0.0, "Audio & Speakers"),
        
        # Cameras & Sensors
        ("Camera Lens", "", 1, 0.0, 0.0, "Cameras & Sensors"),
        ("Face ID Flex", "", 1, 0.0, 0.0, "Cameras & Sensors"),
        ("Mouthpiece (Mic)", "", 1, 0.0, 0.0, "Cameras & Sensors"),
        
        # Small Parts
        ("Down Screws", "", 1, 0.0, 0.0, "Small Parts"),
    ]

    added_count = 0
    for item in items:
        try:
            c.execute("INSERT INTO stock (item_name, color, quantity, cost_price, selling_price, category) VALUES (?, ?, ?, ?, ?, ?)", item)
            added_count += 1
        except sqlite3.IntegrityError:
            print(f"⚠️ Skipped duplicate: {item[0]} {item[1]}")
        except Exception as e:
            print(f"❌ Error adding {item[0]}: {e}")

    conn.commit()
    conn.close()
    print(f"\n✅ SUCCESS! Added {added_count} items to Victory Venture inventory!")

if __name__ == "__main__":
    populate_victory_venture()

