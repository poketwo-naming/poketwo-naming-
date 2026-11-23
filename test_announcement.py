#!/usr/bin/env python3
"""Test if bot can post to announcement channel."""
import os
import asyncio
import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1574489953444827146
ROLE_ID = 1574502724370825286

if not TOKEN:
    print("❌ DISCORD_TOKEN not set")
    exit(1)

async def test_announcement():
    intents = discord.Intents.default()
    intents.message_content = True
    
    async with discord.Client(intents=intents) as client:
        await client.login(TOKEN)
        
        try:
            channel = await client.fetch_channel(CHANNEL_ID)
            print(f"✅ Found channel: {channel}")
            print(f"   Channel name: {channel.name}")
            print(f"   Channel type: {type(channel)}")
            
            # Check if it's a news channel (announcement channel)
            if isinstance(channel, discord.TextChannel):
                perms = channel.permissions_for(client.user)
                print(f"\n📋 Bot Permissions:")
                print(f"   Send Messages: {perms.send_messages}")
                print(f"   Manage Messages: {perms.manage_messages}")
                print(f"   Mention @everyone: {perms.mention_everyone}")
                
                if not perms.send_messages:
                    print("\n❌ Bot cannot send messages to this channel!")
                else:
                    print("\n✅ Bot can send messages")
                    
            elif isinstance(channel, discord.ForumChannel):
                print(f"⚠️  Channel is a Forum, not a text channel")
            else:
                print(f"⚠️  Channel type: {type(channel).__name__}")
                
        except Exception as e:
            print(f"❌ Error: {e}")

try:
    asyncio.run(test_announcement())
except KeyboardInterrupt:
    print("\nCancelled")
except Exception as e:
    print(f"❌ Fatal error: {e}")
    import traceback
    traceback.print_exc()
