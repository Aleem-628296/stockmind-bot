#!/bin/bash
# Start the reminder system in the background
python3 reminders.py &

# Start the main Telegram bot in the foreground (keeps Render alive)
python3 bot.py
