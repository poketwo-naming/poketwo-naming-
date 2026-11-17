# Pokétwo Naming Bot 🎀

A Discord bot designed to help Pokétwo players manage and name their Pokémon collection!

## Features

- **Suggest Names** - Get creative name suggestions for any Pokémon
- **Save Names** - Store nicknames for your Pokémon with IDs
- **View Saved Names** - Display all your saved Pokémon nicknames
- **Delete Names** - Remove nicknames from your collection
- **Bot Status** - Check if the bot is online

## Commands

| Command | Usage | Description |
|---------|-------|-------------|
| `!suggestname <pokemon>` | `!suggestname pikachu` | Get name suggestions for a Pokémon |
| `!savename <id> <nickname>` | `!savename 12345 Sparky` | Save a nickname for your Pokémon |
| `!mynames` | `!mynames` | View all your saved Pokémon names |
| `!deletename <id>` | `!deletename 12345` | Delete a saved Pokémon name |
| `!ping` | `!ping` | Check bot status and latency |
| `!help_naming` | `!help_naming` | Display this help message |

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd poketwo-naming-
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create `.env` file**
   ```
   DISCORD_TOKEN=your_discord_bot_token_here
   ```

4. **Run the bot**
   ```bash
   python main.py
   ```

## Setup

### Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application"
3. Go to "Bot" tab and click "Add Bot"
4. Copy your token and add it to `.env` as `DISCORD_TOKEN`

### Invite Bot to Server

1. Go to OAuth2 → URL Generator
2. Select `bot` scope
3. Select permissions: `Send Messages`, `Read Messages`, `Embed Links`
4. Copy and open the generated URL

## Bot Hosting

Deploy this bot to hosting platforms:

- **Railway** - https://railway.app
- **Render** - https://render.com
- **Replit** - https://replit.com
- **Heroku** - https://heroku.com

## Project Structure

```
poketwo-naming-/
├── main.py                  # Bot entry point
├── bot.py                   # Bot commands and logic
├── pokemon_suggestions.json # Name suggestion database
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables (not committed)
├── .gitignore              # Git ignore rules
└── pokemon_names.json      # User saved names (generated at runtime)
```

## Example Usage

```
User: !suggestname charizard
Bot: 
🎀 Name Suggestions for charizard
• Blaze
• Inferno
• Dragon
• Flame
• Char

User: !savename 54321 Inferno
Bot: ✅ Name Saved!
Pokémon 54321 is now named Inferno

User: !mynames
Bot:
👤 YourName's Pokémon Names
ID: 54321
Inferno
```

## Contributing

Feel free to add more Pokémon and name suggestions to `pokemon_suggestions.json`!

## License

This project is open source and available under the MIT License.

---

**Made with ❤️ for Pokétwo players**
