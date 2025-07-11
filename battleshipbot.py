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
    """Checks if the user is a server admin or in the authorized admin list."""
    return user.guild_permissions.administrator or str(user.id) in AUTHORIZED_ADMINS

# --- Helper Functions ---

def render_board(board, hits, ships):
    width = len(board[0])
    height = len(board)

    header = "   " + " ".join(f"{i+1:2}" for i in range(width)) + "\n"
    rows = []
    for y in range(height):
        row_str = f"{chr(65 + y):>2} "
        for x in range(width):
            pos = (y, x)
            cell = board[y][x]
            if pos in hits:
                if cell > 0:
                    ship_index = cell - 1
                    if is_ship_sunk(ships[ship_index], hits):
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
        return pool  # tolerate 1 short
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
            orientation = random.choices(
                ["H", "V", "D", "A"], weights=[4, 4, 1, 1], k=1
            )[0]

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
            else:  # "A"
                x = random.randint(length - 1, width - 1)
                y = random.randint(0, height - length)
                coords = [(y + i, x - i) for i in range(length)]

            if any(board[y][x] != 0 for y, x in coords):
                continue

            # Check adjacency
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

# --- Discord Commands ---

@bot.tree.command(name="start", description="Start a new battleship game")
@app_commands.describe(width="Board width", height="Board height", ships="Total number of ship tiles")
async def start(interaction: discord.Interaction, width: int, height: int, ships: int):
    await interaction.response.defer()
    if width < 5 or height < 5 or ships < 2:
        await interaction.followup.send("Minimum board size is 5x5 and at least 2 ship tiles.", ephemeral=True)
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
        "channel1": None,
        "channel2": None
    })

    await interaction.followup.send(f"New game created! Game ID: {game_id}\nUse `/join` in two channels to play.")

@bot.tree.command(name="join", description="Join a battleship game in this channel")
@app_commands.describe(gameid="The ID of the game to join")
async def join(interaction: discord.Interaction, gameid: str):
    await interaction.response.defer(ephemeral=True)

    game = collection.find_one({"game_id": gameid})
    if not game:
        await interaction.followup.send("Game not found.", ephemeral=True)
        return

    cid = interaction.channel.id
    if game["channel1"] is None:
        collection.update_one({"game_id": gameid}, {"$set": {"channel1": cid}})
        team = 1
    elif game["channel2"] is None and game["channel1"] != cid:
        collection.update_one({"game_id": gameid}, {"$set": {"channel2": cid}})
        team = 2
    else:
        await interaction.followup.send("Game already has two channels.", ephemeral=True)
        return

    opp_team = 3 - team
    hits = set(tuple(pos) for pos in game[f"hits{opp_team}"])
    board = game[f"board{opp_team}"]

    embed = Embed(title=f"Team {team} Target Grid", description=render_board(board, hits))
    await interaction.channel.send(f"You joined game {gameid} as Team {team}.", embed=embed)
    await interaction.followup.send("Successfully joined the game.", ephemeral=True)

@bot.tree.command(name="shoot", description="Shoot at a coordinate on the board")
@app_commands.describe(row="Letter A-Z", column="Number 1+" )
async def shoot(interaction: discord.Interaction, row: str, column: int):
    await interaction.response.defer(ephemeral=True)

    row = row.upper()
    y = ord(row) - 65
    x = column - 1
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
    hits = set(tuple(p) for p in game[f"hits{team}"])
    if pos in hits:
        await interaction.followup.send("Already shot there.", ephemeral=True)
        return

    hits.add(pos)
    collection.update_one({"game_id": game["game_id"]}, {"$set": {f"hits{team}": list(hits)}})

    board = game[f"board{opp}"]
    ships = game[f"ships{opp}"]
    result = "💦 Miss!"

    if board[y][x] > 0:
        ship_idx = board[y][x] - 1
        if is_ship_sunk(ships[ship_idx], hits):
            result = "💣 Ship Sunk!"
        else:
            result = "🔥 Hit!"

    extra = ""
    if all_ships_sunk(ships, hits):
        extra = "\n🎉 **You have sunk all your opponent's ships, but may keep shooting.**"

    embed = Embed(title=f"Team {team} Target Grid", description=render_board(board, hits))
    await interaction.channel.send(content=result + extra, embed=embed)
    await interaction.followup.send("Shot processed.", ephemeral=True)

@bot.tree.command(name="delete", description="Delete a battleship game by its game ID (admin only)")
@app_commands.describe(gameid="The ID of the game to delete")
async def delete(interaction: discord.Interaction, gameid: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    result = collection.delete_one({"game_id": gameid})
    if result.deleted_count > 0:
        await interaction.response.send_message(f"Game with ID `{gameid}` has been deleted.", ephemeral=True)
    else:
        await interaction.response.send_message(f"No game with ID `{gameid}` was found.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

bot.run(DISCORD_TOKEN)