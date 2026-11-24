# Pokétwo Naming Bot 🎀

A Discord bot designed to help Pokétwo players manage and name their Pokémon collection!

## Features

- **Recognize Spawns** - Identify every Pokétwo spawn from its image and display confidence
- **Type Icons** - Prefix each prediction with its primary and secondary type emojis
- **Type Pings** - Choose Pokémon types to get pinged for, including dual-type spawns
- **Best Names** - Show the shortest localized name, romanized for nicknames
- **Bot Status** - Check if the bot is online

When Vivillon joins a server, it posts a naming introduction and the optional
support embed in the system channel or another accessible text channel. The
introduction points to `v!help` for command explanations. To
enable naming, join [Butterfly Garden](https://discord.gg/butterflygarden)
(server ID `1530949341013868635`) and open a ticket. You can also open a ticket
there for issues or questions. The bot needs permission to view the channel,
send messages, and embed links to post the introduction.

## Commands

Every `v!` command also works with a capital `V!` prefix.

| Command | Usage | Description |
|---------|-------|-------------|
| `v!ping` | `v!ping` | Check bot status and latency |
| `v!tp` / `v!typeping` | `v!tp` | Choose Pokémon types to receive spawn pings for |
| `v!support` | `v!support` | Show the optional GoFundMe support link |
| `v!tz <day\|night\|dawn\|dusk>` | `v!tz night` | Find one place in that local-time phase and get a Pokétwo timezone command |
| `v!sr <pokemon>` | `v!sr Pikachu` | Show a Pokémon's spawn rate and artwork |
| `v!report` | Reply to a Pokétwo catch announcement with `v!report` | Submit a stolen-reserve report when reserve evidence is available |
| `v!api` | `v!api` | Display API and spawn-recognition performance |
| `v!apislow` | `v!apislow` | Break down the slowest recent spawn response |
| `v!servers` | `v!servers` | List every connected Discord server and ID |
| `v!premium` | `v!premium` | Show the current server's premium tier |
| `v!premium add <tier> <server_id>` | `v!premium add gold 123456789` | Owner-only tier grant from the main server |
| `v!resume` | `v!resume` | Resume Pokétwo in the current channel (restricted) |
| `v!r all` | `v!r all` | Resume Pokétwo in every tracked paused channel in this server (restricted) |
| `v!pause` / `v!p` | `v!p` | Pause Pokétwo in the current channel (restricted) |
| `v!poff` | `v!poff` | Disable automatic pausing after confirmed incense purchases in this server (restricted) |
| `v!pon` | `v!pon` | Re-enable automatic pausing after confirmed incense purchases in this server (restricted) |
| `v!r add <pokemon,...> <@user>` | `v!r add Pikachu, Eevee @user` | Reserve multiple Pokémon for a member (restricted) |
| `v!r add all <pokemon,...> <@user>` | `v!r add all Arceus, Eevee @user` | Reserve all matching forms (restricted) |
| `v!r remove <pokemon,...|category> [@user]` | `v!r remove rare @user` | Remove Pokémon or all reserved members of a category (restricted) |
| `v!r e <@user>` | Reply to a reserve list with `v!r e @user` | Confirm an exchange of the user's reserves to members in the list (restricted) |
| `v!r search <pokemon>` | `v!r search Pikachu` | Show who has a Pokémon reserved in an embed |
| `v!r list [@user]` | `v!r list @user` | List all server reserves or one member's reserves |
| `v!reserve list [@user]` | `v!reserve list @user` | Long-form reserve list command |
| `v!r clear` | `v!r clear` | Confirm and clear all server reserves (restricted) |
| `v!grab` | Reply with `v!grab` | Preview a reserve list, add its unique users to ready-up, or manage reserves |
| `v!readyup` | `v!readyup` | Show a ready check for users added from `v!grab` (restricted) |
| `v!readyup clear` | `v!readyup clear` | Clear the server's ready-up queue and end its active check (restricted) |
| `h!grab` | Reply with `h!grab` | Same category support, delegated through h!r, then v!r |
| `v!sh [pokemon]` | `v!sh Pikachu` | Start/switch a hunt, or show your current hunt |
| `v!sh all <pokemon>` | `v!sh all Meowth` | Hunt every form of that Pokémon |
| `v!sh clear` | `v!sh clear` | Clear your shiny hunt |
| `v!cl add [all] <pokemon,...|category>` | `v!cl add Pikachu, Eevee` or `v!cl add rare` | Add Pokémon, a family, or every Pokémon in a server category to your collection |
| `v!cl remove <pokemon,...|category>` | `v!cl remove Pikachu, Eevee` or `v!cl remove rare` | Remove Pokémon or every Pokémon in a server category from your collection |
| `v!cl search <pokemon>` | `v!cl search Pikachu` | Check whether a Pokémon is in your own collection |
| `v!cl list` | `v!cl list` | List your own collection |
| `v!cl clear` | `v!cl clear` | Clear your own collection |
| `v!permission <role_id>` | `v!permission 123456789` | Grant a role restricted-command access |
| `v!training` | `v!training` | Show reviewed training images in the review channel |
| `v!export_training` | `v!export_training` | Download reviewed images for retraining |
| `v!help [page]` | `v!help 1` | Paginated command explanations |
| `v!commands [page]` | `v!commands 1` | Categorized command list |
| `v!box` | `v!box` | Show all boxes and how full they are (limit 7,500 each) |
| `v!box create <name>` | `v!box create Daycare` | Make a new box |
| `v!box append [box] [--c]` | Reply to a Pokétwo list with `v!box append Daycare` | Append the current page and follow page arrows; `--c` clears the box first |
| `v!box list [box]` | `v!box list Daycare` | Browse boxes or the Pokémon in one box |
| `v!box remove <box> <number\|Pokémon> [all]` | `v!box remove Daycare Pikachu all` | Delete stored Pokémon |
| `v!box transfer <from> <to> <number\|Pokémon> [all]` | `v!box transfer Daycare Eggs Pikachu` | Move Pokémon between boxes |
| `v!box copy <source> <new name>` | `v!box copy Daycare Backup` | Duplicate a box; add a destination to copy entries into an existing box |
| `v!box tag / untag / tags / tagged` | `v!box tag Daycare 1 egg-move` | Track and browse egg-move tags |
| `v!box rename / delete / clear / reset` | `v!box rename Daycare Eggs` | Rename, delete, or wipe boxes |
| `v!dc [box]` | `v!dc Daycare` | Show the selected number of compatible pairs from `v!dc menu`, with ready-to-paste commands for phone and PC |
| `/dc [box] [count]` | `/dc box:Daycare count:2` | Use your account's boxes in any server or DM, including as a user-installed app, and choose the number of pairs (defaults to one) |
| `v!dc menu` | `v!dc menu` | Change pair selection, output, and the number of pairs returned by `v!dc` |
| `v!boxhelp` | `v!boxhelp` | Show the full list of box commands |

Use quotes around multiword box names when a command has more than one box
argument, for example `v!box transfer "Main Box" "Egg Box" 1`.
`v!box append` reads the current page of a replied Pokétwo list and follows its
page-arrow edits for 30 minutes after the latest page change, or until the bot
restarts. Each Pokémon number is added only once per box; the status shows
the number newly added and the total currently stored. Pages not visited while
tracking are not imported. Pokémon stored before numbers were saved cannot be
deduplicated or used by `v!dc`; clear and re-import that box to replace them.
`v!dc` finds the selected number of pairs of distinct numbered Pokémon using
egg groups and gender; mixed-gender species need their gender visible in the
list that was appended.
The plain-text result shows the selected box name and pair count, with an
inline daycare command for phone copying and a fenced command block for PC
copying. Large pair lists are split across multiple messages.
The `/dc` box option suggests your boxes as you type; `count` must be at least
1 and returns up to the number of compatible pairs available.
Boxes and daycare preferences are saved per Discord account, so `/dc` can use
them in every server. Existing per-server data is merged on upgrade; boxes with
the same name but different contents remain available under server-labelled
names.

On startup, the bot posts the current `UPDATE_ANNOUNCEMENT` from
`announcements.py` to channel `1574489953444827146` once per announcement text.
Each update post pings the configured announcement role
`1574502724370825286`. Replace the summary with only the latest changes alongside
each bot update; do not append previous updates. Restarts with unchanged
announcement text do not post duplicates. The bot automatically
publishes each update to announcement-channel followers. The channel must be an
announcement channel and the bot needs permission to send messages there. If
publishing fails, the bot logs the error and retries the same message on the
next startup or reconnect.

In grabbed lists, `Booster` is treated as a heading rather than Flareon's
localized name when a Pokémon follows the member mention.

In channel `1531476097970212915`, spawn guesses below 50% confidence include
**Yes/No** review buttons. Yes saves the image under the predicted Pokémon
folder. No opens a modal for the correct Pokémon name, creating that folder
when necessary. Higher-confidence guesses use normal naming output. Reviewed
images can be downloaded with `v!export_training` before retraining. The
threshold can be changed with `REVIEW_CONFIDENCE_THRESHOLD`.

Multiple members can reserve the same Pokémon; each receives the reserve ping
when that Pokémon is recognized. Existing single-member reserves remain valid.
`v!r search <pokemon>` and `v!r list` are available to everyone.
`v!r add` and `v!r remove` are restricted to administrators and members with the
configured restricted role. Removing a category removes those Pokémon reserves
for all reserving members, or only the mentioned member when `@user` is supplied.
For collections and reserves, `Nidoran male` selects Nidoran♂ and
`Nidoran female` selects Nidoran♀. Use `v!cl add all Nidoran` or
`v!r add all Nidoran @user` to add both.

To report a stolen reserve, reply to Pokétwo's catch announcement with
`v!report`. The reporter must have a current Vivillon reserve for that Pokémon
or be mentioned in another naming bot's reserve ping on the corresponding
spawn. A report is rejected if the catcher also has a known reserve. If no
spawn is linked to the catch, Vivillon checks its own current reserves against
the name in the catch; other naming-bot reserves cannot be verified.
For Vivillon to use another naming bot's message as evidence, that message
must reply to the linked Pokétwo spawn before the catch, start with the Pokémon
name, and include user mentions on a `Reserve pings:` or `Reserved:` line
(in its content or embed). If a catch names only a species with custom forms,
one matching naming-bot prediction identifies the form; conflicting predictions
prevent the report. With no prediction, only a reserve of the name in the catch
is used and the report notes that the form is unverified. Predictions are
recognition guesses, not guarantees. Submitted reports mention the catcher and
reporter in channel `1532512015703085147`, with the catch link and trade thread
`1538294047095922748`. If a report fails unexpectedly, Vivillon replies with an
error and logs the exception for troubleshooting.

Reserve categories `gmax`, `eevos`, and `paradox` cost 35,000 PC; `rare`,
`regional`, and `events` cost 45,000 PC. The higher price applies when
categories overlap, and these category prices take precedence over spawn-rate
prices. Gigantamax catches cost 35,000 PC. Enchanted/Rotten Applin,
Oracle/Witch Meowscarada, Medusa/Statue Simipour, and Elixir/Cauldron Reuniclus
cost 45,000 PC. Other Pokémon use their nearest spawn-rate tier, interpolated
between listed prices and rounded to the nearest 2,500 PC, with a 2,500-PC
minimum and 50,000-PC maximum. Rates use the denominator in the
[Pokétwo chance CSV](https://gist.githubusercontent.com/WitherredAway/1bc525b05f4cd52555a2a18c331e0cf9/raw/a9c321427ad935b1de74660c0116731a001140ac/pokemon_chances.csv);
live rates may differ. Custom forms use their own listed rate when present, or
their species' rate otherwise. Reports are not sent when a rate is unavailable.

Normal naming output uses a transparent official Pokémon artwork thumbnail
from PokéAPI, selected for the predicted Pokémon form. The spawn image is still
used for recognition and low-confidence review. The catch command uses the
configured best name for each recognized Pokémon. A matching image in
`pokemon_sprites/<Pokémon name>.png` overrides the official artwork for custom
Pokétwo variants. When no custom sprite is available, custom variants use the
recognized spawn image instead of misleading base-species artwork.

For `v!grab` and `h!grab`, a category name before a user mention (for example,
`rare - @user - Pikachu`) appears as one `rare - @user` preview entry; confirming
adds every Pokémon in that category to the user. A space before a separating
hyphen is enough (for example, `@user ditto -pikachu`); unrecognized names are
skipped without discarding other valid names. The All forms toggle only
expands an entry when its original text requests all forms. Grab and reserve
exchange include regional forms for `all <Pokémon name>` (for example,
`all Articuno` includes Galarian Articuno). Exchange skips forms the original
user does not have reserved.

Click **Readyup** on a `v!grab` preview to add each mentioned user once to that
server's ready-up queue. Run `v!readyup` to show the Ready button and the
not-ready/ready user lists and ping everyone in the queue; only queued users can
mark themselves ready. When everyone is ready, the command runner is mentioned
in a follow-up message.
`v!readyup` and `v!readyup clear` are restricted to administrators and
configured restricted roles. Use `v!readyup clear` to clear the queue and end
the active check.

When Pokétwo confirms an incense purchase with `Incense has been bought` or
`You purchased an Incense for 50 shards!`, this bot pauses Pokétwo in that
channel and confirms the pause, or reports if it could not pause. This blocks
Pokétwo from sending messages; it does not send an incense pause command. Use
`v!poff` to disable this behavior in the server, or `v!pon` to re-enable it.
`v!p` manually pauses the current channel; `v!resume` resumes it, and restricted
staff can use `v!r all` to resume every tracked paused channel in the server.

MissingNo detection immediately denies Pokétwo's Send Messages permission in
the current channel, asks staff not to catch it, and pings role
`<@&1573065640762151003>`. Administrators configure a restricted staff role
with `v!permission <role_id>`; that role can use the restricted pause/resume
commands to restore Pokétwo's previous permissions. The bot requires
**Manage Channels** permission for this pause/resume feature. A MissingNo
reserve still receives a ping in the naming output.

Spawn recognition and MissingNo handling require Bronze, Silver, or Gold
premium access. Other informational and configuration commands remain usable.

Multiple members can shiny hunt the same Pokémon. `shinyhunt:` pings them in
the naming message. An active reservation replaces the shiny-hunt and collection
lines with the reserved member. Use `v!sh all <pokemon>` to hunt all forms,
including regional and custom forms, of the same species. A hunt for a single
form still only matches that form. Chain tracking is not stored.

Collections are personal and unrestricted: each member can only modify their
own collection. Use `v!cl add <category>` to add every Pokémon from a
server category to your collection. Spawn output lists shiny hunts before
collections. A reserve replaces both sections.

Active incense counts expire automatically after 90 seconds without a Pokétwo
spawn in that channel. Override the inactivity window with
`INCENSE_INACTIVITY_SECONDS`.

The image encoder uses one CPU inference thread to reduce overhead, while
classification and focused-image checks remain enabled. Predictions for the
latest 1,024 byte-identical spawn images are cached in memory until restart.
`v!api` reports recent download, inference, Discord send, and response timings;
cached predictions count as inference time too. Actual speed depends on the
host and network.
`v!apislow` shows download, inference, Discord send, other, and total time for
the slowest of the latest 100 completed recognitions since restart. Other time
includes scheduling, response preparation, and any MissingNo pause and alert.
The timing starts when spawn handling begins, after message tracking. Spawn
attachments are fetched from Discord's cached media URL first, with the original
attachment URL as a fallback.

The bot uses the Pokémon-named folders in `pokemon_images/training_data` to build
the recognition model. Rebuild it after changing the training images:

```bash
pip install -r requirements-train.txt
python tools/build_pokemon_model.py
python tools/build_pokemon_types.py
python tools/build_pokemon_names.py
python tools/build_pokemon_refinements.py
```

Store male Nidoran examples under `pokemon_images/training_data/Nidoran♂`;
`Nidoran` is the female class.

The source images are ignored by Git. Commit and deploy the generated model,
encoder, `pokemon_types.json`, `pokemon_sprite_ids.json`,
`pokemon_best_names.json`, `pokemon_aliases.json`, and `pokemon_species.json` files.

To teach the bot commonly confused Pokémon (Alolan Meowth/Rattata, Blipbug,
Deerling seasonal forms, Luxray, Pikipek, Smoliv, Finizen, Palafin, Hero Palafin, and
Squawkabilly plumage forms) after adding images to their folders, rebuild the
lightweight refinement file without retraining. Pass extra folder names to add
more classes:

```bash
python tools/build_pokemon_refinements.py
```

For Finizen and Palafin, recognition also checks the small pink/red mark to
distinguish their otherwise similar images.

Commit `pokemon_image_refinements.npz` afterwards.

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
3. Select permissions: `Send Messages`, `Read Message History`, `Embed Links`
4. Copy and open the generated URL

For stolen-reserve reports, also allow the bot to read message history in the
catch channel and send messages in channel `1532512015703085147`.

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

```

## Contributing

Feel free to add more Pokémon and name suggestions to `pokemon_suggestions.json`!

## License

This project is open source and available under the MIT License.

---

**Made with ❤️ for Pokétwo players**
