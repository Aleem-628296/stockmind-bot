#!/bin/bash
# Start the reminder system in the background
python reminders.py &

# Start the main Telegram bot in the foreground (keeps Render alive)
python bot.py
