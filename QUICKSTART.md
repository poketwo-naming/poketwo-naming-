# Quick Start Guide 🚀

## Step 1: Get Your Discord Bot Token

1. Visit https://discord.com/developers/applications
2. Click "New Application" and name it "Pokétwo Naming Bot"
3. Go to "Bot" tab → Click "Add Bot"
4. Under TOKEN section, click "Copy"
5. Create a `.env` file in this folder and add:
   ```
   DISCORD_TOKEN=paste_your_token_here
   ```

## Step 2: Invite Bot to Your Server

1. In Developer Portal, go to OAuth2 → URL Generator
2. Check these scopes:
   - [x] bot
3. Check these permissions:
   - [x] Send Messages
   - [x] Read Messages/View Channels
   - [x] Embed Links
4. Copy the generated URL and open it in browser
5. Select your server and authorize

## Step 3: Run the Bot

### Option A: Run Locally
```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python main.py
```

You should see: `Your Bot Name has connected to Discord!`

### Option B: Deploy to Hosting

**Railway (Recommended)**
1. Go to https://railway.app
2. Click "New Project" → "Deploy from GitHub"
3. Connect your GitHub repository
4. Add variable: `DISCORD_TOKEN` = your_token
5. Railway will auto-deploy

**Render**
1. Go to https://render.com
2. Create "New" → "Web Service"
3. Connect GitHub repo
4. Set build: `pip install -r requirements.txt`
5. Set start: `python main.py`
6. Add env var: `DISCORD_TOKEN`

## Step 4: Test Your Bot

In your Discord server, type:
```
!ping
```

If the bot responds with latency, you're good to go! 🎉

## Try These Commands

```
!help_naming          - Show all commands
!suggestname pikachu  - Get name suggestions
!savename 123 Sparky  - Save a name
!mynames              - View your saved names
```

## Troubleshooting

**Bot not responding?**
- Make sure bot has "Send Messages" permission
- Check if `DISCORD_TOKEN` is correct in `.env`
- Verify bot is in your server

**Token error?**
- Create a `.env` file (not `.env.txt`)
- Format: `DISCORD_TOKEN=your_actual_token`
- Regenerate token if exposed

**Can't find token?**
- Go to Developer Portal
- Select your application
- Click "Bot" on left sidebar
- Copy token under TOKEN section

## Need Help?

Check the README.md for detailed documentation!

---

**Happy naming! 🎀**
