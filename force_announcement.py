#!/usr/bin/env python3
"""Force the update announcement to post on next bot startup."""
import json
import os
import sys

BOT_STATE_FILE = os.getenv("BOT_STATE_FILE", "bot_state.json")

if not os.path.exists(BOT_STATE_FILE):
    print(f"⚠️  {BOT_STATE_FILE} not found. Bot state hasn't been created yet.")
    print("The announcement will post on first bot startup.")
    sys.exit(0)

try:
    with open(BOT_STATE_FILE, "r") as f:
        bot_state = json.load(f)
except Exception as e:
    print(f"❌ Error reading {BOT_STATE_FILE}: {e}")
    sys.exit(1)

# Clear the announcement digest to force a re-post
old_digest = bot_state.pop("last_update_announcement", None)
old_pending = bot_state.pop("pending_update_publication", None)

# Save the modified state
try:
    with open(BOT_STATE_FILE, "w") as f:
        json.dump(bot_state, f, indent=2, ensure_ascii=False)
    print(f"✅ Cleared announcement cache in {BOT_STATE_FILE}")
    if old_digest:
        print(f"   Old digest: {old_digest[:16]}...")
    print("   Bot will post the update announcement on next restart.")
except Exception as e:
    print(f"❌ Error writing {BOT_STATE_FILE}: {e}")
    sys.exit(1)

