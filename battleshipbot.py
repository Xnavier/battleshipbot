import discord
from discord.ext import commands
from discord import app_commands, Embed
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import os
import random

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

uri = MONGO_URI
client = MongoClient(uri, server_api=ServerApi('1'))
db = client["battleship"]
collection = db["games"]

AUTHORIZED_ADMINS = ["214078497331740672", "231804191448760320"]


def is_admin(user: discord.Member) -> bool:
    return user.guild_permissions.administrator or str(user.id) in AUTHORIZED_ADMINS


# Emoji numbers 0-10
NUM_EMOJIS = [
    "0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣",
    "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"
]

def render_board_with_sunk(board, hits, ships, sunk_ships):
    width = len(board[0])
    height = len(board)

    number_emojis = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    header = "   " + "".join(number_emojis[:width]) #+ "\n"

    rows = []
    for y in range(height):
        row_label = chr(65 + y)
        row_str = f"{row_label:>2} "
        for x in range(width):
            pos = (y, x)
            cell = board[y][x]
            if pos in hits:
                if cell > 0:
                    ship_index = cell - 1
                    if ship_index in sunk_ships:
                        row_str += "⬛"
                    else:
                        row_str += "🟥"
                else:
                    row_str += "⬜"
            else:
                row_str += "🟦"
        rows.append(row_str)

    return "```\n" + header + "\n" + "\n".join(rows) + "\n```"

def is_ship_sunk(ship_coords, hits):
    return all(coord in hits for coord in ship_coords)


def all_ships_sunk(ships, hits):
    return all(is_ship_sunk(ship, hits) for ship in ships)


def generate_ship_pool(target_tiles):
    base_lengths = [5, 4, 3, 3, 2]
    pool = []
    while sum(pool) + min(base_lengths) <= target_tiles:
        choices = base_lengths.copy()
        random.shuffle(choices)
        for length in choices:
            if sum(pool) + length <= target_tiles:
                pool.append(length)
    if sum(pool) < target_tiles:
        return pool
    while sum(pool) > target_tiles:
        pool.pop()
    return pool


def place_ships(width, height, ship_lengths):
    board = [[0] * width for _ in range(height)]
    ships = []
    ship_id = 1
    max_total_attempts = 1000

    for length in ship_lengths:
        attempts = 0
        while attempts < max_total_attempts:
            attempts += 1
            orientation = random.choices(["H", "V", "D", "A"], weights=[4, 4, 1, 1])[0]

            if orientation == "H":
                x = random.randint(0, width - length)
                y = random.randint(0, height - 1)
                coords = [(y, x + i) for i in range(length)]
            elif orientation == "V":
                x = random.randint(0, width - 1)
                y = random.randint(0, height - length)
                coords = [(y + i, x) for i in range(length)]
            elif orientation == "D":
                x = random.randint(0, width - length)
                y = random.randint(0, height - length)
                coords = [(y + i, x + i) for i in range(length)]
            else:
                x = random.randint(length - 1, width - 1)
                y = random.randint(0, height - length)
                coords = [(y + i, x - i) for i in range(length)]

            if any(board[y][x] != 0 for y, x in coords):
                continue

            touching_ships = set()
            for y, x in coords:
                for dy in [-1, 0, 1]:
                    for dx in [-1, 0, 1]:
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < height and 0 <= nx < width:
                            if board[ny][nx] > 0 and (ny, nx) not in coords:
                                touching_ships.add(board[ny][nx])

            if len(touching_ships) >= 3:
                continue
            if len(touching_ships) == 2 and random.random() < 0.9:
                continue
            if len(touching_ships) == 1 and random.random() < 0.6:
                continue

            for y, x in coords:
                board[y][x] = ship_id
            ships.append(coords)
            ship_id += 1
            break
        else:
            raise ValueError("Too many failed placement attempts")

    return board, ships


@bot.tree.command(name="start", description="Start a new battleship game")
@app_commands.describe(width="Board width (max 11)", height="Board height", ships="Total number of ship tiles")
async def start(interaction: discord.Interaction, width: int, height: int, ships: int):
    await interaction.response.defer()
    if width < 1 or width > 11 or height < 5 or ships < 2:
        await interaction.followup.send("Width must be between 1 and 11. Height >= 5. At least 2 ship tiles.", ephemeral=True)
        return

    ship_pool = generate_ship_pool(ships)
    try:
        board1, ships1 = place_ships(width, height, ship_pool)
        board2, ships2 = place_ships(width, height, ship_pool)
    except ValueError:
        await interaction.followup.send("Failed to place ships. Try a larger board or fewer ships.", ephemeral=True)
        return

    game_id = str(random.randint(1000, 9999))
    collection.insert_one({
        "game_id": game_id,
        "width": width,
        "height": height,
        "board1": board1,
        "board2": board2,
        "ships1": ships1,
        "ships2": ships2,
        "hits1": [],
        "hits2": [],
        "sunk_ships1": [],
        "sunk_ships2": [],
        "channel1": None,
        "channel2": None,
        "teamname1": None,
        "teamname2": None
    })

    await interaction.followup.send(f"New game created! Game ID: {game_id}\nUse `/join` in two channels to play.")


@bot.tree.command(name="shoot", description="Shoot at a coordinate on the board")
@app_commands.describe(row="Letter A-Z", column="Number 0-10")
async def shoot(interaction: discord.Interaction, row: str, column: int):
    await interaction.response.defer(ephemeral=True)

    row = row.upper()
    y = ord(row) - 65
    x = column
    cid = interaction.channel.id

    game = collection.find_one({"$or": [{"channel1": cid}, {"channel2": cid}]})
    if not game:
        await interaction.followup.send("Channel not linked to any game.", ephemeral=True)
        return

    team = 1 if game["channel1"] == cid else 2
    opp = 3 - team

    if not (0 <= y < game["height"] and 0 <= x < game["width"]):
        await interaction.followup.send("Invalid coordinate.", ephemeral=True)
        return

    pos = (y, x)
    hits = set(tuple(p) for p in game.get(f"hits{team}", []))
    if pos in hits:
        await interaction.followup.send("Already shot there.", ephemeral=True)
        return

    hits.add(pos)
    sunk_key = f"sunk_ships{team}"
    sunk_ships = set(game.get(sunk_key, []))

    board = game[f"board{opp}"]
    ships = [[tuple(coord) for coord in ship] for ship in game[f"ships{opp}"]]

    result = "\U0001f4a6 Miss!"
    if board[y][x] > 0:
        ship_idx = board[y][x] - 1
        if ship_idx not in sunk_ships and is_ship_sunk(ships[ship_idx], hits):
            sunk_ships.add(ship_idx)
            result = "\U0001f4a3 Ship Sunk!"
        else:
            result = "\U0001f525 Hit!"

    collection.update_one(
        {"game_id": game["game_id"]},
        {"$set": {f"hits{team}": list(hits), sunk_key: list(sunk_ships)}}
    )

    extra = ""
    if all_ships_sunk(ships, hits):
        extra = "\n\U0001f389 **You have sunk all your opponent's ships, but may keep shooting.**"

    embed = Embed(title=f"Team {team} Target Grid", description=render_board_with_sunk(board, hits, ships, sunk_ships))
    await interaction.channel.send(content=result + extra, embed=embed)
    await interaction.followup.send("Shot processed.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

bot.run(DISCORD_TOKEN)