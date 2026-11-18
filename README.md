# Pokétwo Naming Bot 🎀

A Discord bot designed to help Pokétwo players manage and name their Pokémon collection!

## Features

- **Suggest Names** - Get creative name suggestions for any Pokémon
- **Save Names** - Store nicknames for your Pokémon with IDs
- **View Saved Names** - Display all your saved Pokémon nicknames
- **Delete Names** - Remove nicknames from your collection
- **Recognize Spawns** - Identify every Pokétwo spawn from its image and display confidence
- **Type Icons** - Prefix each prediction with its primary and secondary type emojis
- **Best Names** - Show the shortest localized name, romanized for nicknames
- **Bot Status** - Check if the bot is online

## Commands

| Command | Usage | Description |
|---------|-------|-------------|
| `v!suggestname <pokemon>` | `v!suggestname pikachu` | Get name suggestions for a Pokémon |
| `v!savename <id> <nickname>` | `v!savename 12345 Sparky` | Save a nickname for your Pokémon |
| `v!mynames` | `v!mynames` | View all your saved Pokémon names |
| `v!deletename <id>` | `v!deletename 12345` | Delete a saved Pokémon name |
| `v!ping` | `v!ping` | Check bot status and latency |
| `v!api` | `v!api` | Display API and spawn-recognition performance |
| `v!servers` | `v!servers` | List every connected Discord server and ID |
| `v!premium` | `v!premium` | Show the current server's premium tier |
| `v!premium add <tier> <server_id>` | `v!premium add gold 123456789` | Owner-only tier grant from the main server |
| `v!r` | `v!r` | Resume a channel paused after a MissingNo spawn |
| `v!r add <pokemon> <@user>` | `v!r add Pikachu @user` | Reserve a Pokémon for a member (restricted) |
| `v!r remove <pokemon> [@user]` | `v!r remove Pikachu @user` | Remove a Pokémon reserve (restricted) |
| `v!r list [@user]` | `v!r list @user` | List all server reserves or one member's reserves |
| `v!sh [pokemon]` | `v!sh Pikachu` | Start/switch a hunt, or show your current hunt and chain |
| `v!sh clear` | `v!sh clear` | Clear your shiny hunt |
| `v!permission <role_id>` | `v!permission 123456789` | Grant a role restricted-command access |
| `v!training` | `v!training` | Show reviewed training images in the review channel |
| `v!export_training` | `v!export_training` | Download reviewed images for retraining |
| `v!help [page]` | `v!help 1` | Paginated command explanations |
| `v!commands [page]` | `v!commands 1` | Categorized command list |

In channel `1531476097970212915`, spawn guesses below 50% confidence include
**Yes/No** review buttons. Yes saves the image under the predicted Pokémon
folder. No opens a modal for the correct Pokémon name, creating that folder
when necessary. Higher-confidence guesses use normal naming output. Reviewed
images can be downloaded with `v!export_training` before retraining. The
threshold can be changed with `REVIEW_CONFIDENCE_THRESHOLD`.

MissingNo detection immediately denies Pokétwo's Send Messages permission in
the current channel and asks staff not to catch it. Administrators configure a
restricted staff role with `v!permission <role_id>`; that role can use `v!r`
to restore Pokétwo's previous permissions. The bot requires **Manage
Channels** permission for this pause/resume feature.

Spawn recognition and MissingNo handling require Bronze, Silver, or Gold
premium access. Other informational and configuration commands remain usable.

Multiple members can shiny hunt the same Pokémon. `shinyhunt:` pings them
beneath the best name. An active reservation replaces the shiny-hunt line with
the reserved member. Chain tracking is not stored.

Active incense counts expire automatically after 90 seconds without a Pokétwo
spawn in that channel. Override the inactivity window with
`INCENSE_INACTIVITY_SECONDS`.

The bot uses the Pokémon-named folders in `pokemon_images/training_data` to build
the recognition model. Rebuild it after changing the training images:

```bash
pip install -r requirements-train.txt
python tools/build_pokemon_model.py
python tools/build_pokemon_types.py
python tools/build_pokemon_names.py
```

The source images are ignored by Git. Commit and deploy the generated model,
encoder, `pokemon_types.json`, `pokemon_best_names.json`, and
`pokemon_aliases.json` files.

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
Pokétwo spawn
Bot:
Charizard 99.95%

User: v!savename 54321 Inferno
Bot: ✅ Name Saved!
Pokémon 54321 is now named Inferno

User: v!mynames
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
