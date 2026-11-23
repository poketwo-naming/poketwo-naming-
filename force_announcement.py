#!/usr/bin/env python3
"""Force the automatic update announcement to run on next startup."""
import json
import os
import sys

BOT_STATE_FILE = os.getenv("BOT_STATE_FILE", "bot_state.json")

if not os.path.exists(BOT_STATE_FILE):
    print(f"{BOT_STATE_FILE} does not exist yet; the bot will announce on startup.")
    sys.exit(0)

try:
    with open(BOT_STATE_FILE, "r", encoding="utf-8") as file:
        state = json.load(file)
    state.pop("automatic_update_announcement", None)
    state.pop("automatic_update_pending_message", None)
    state.pop("last_update_announcement", None)
    state.pop("pending_update_publication", None)
    with open(BOT_STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, ensure_ascii=False)
except (json.JSONDecodeError, OSError) as error:
    print(f"Could not clear the announcement state: {error}")
    sys.exit(1)

print("Cleared announcement state. Restart the bot to send and publish it.")
