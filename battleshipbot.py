import discord
from discord.ext import commands
from discord import app_commands, Embed
from pymongo import MongoClient
import random
import string
import os

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

db_client = MongoClient(os.environ["MONGO_URI"])
db = db_client["battleship"]
collection = db["games"]

TILE_EMOJIS = {
    "water": "🟦",
    "miss": "⬜",
    "hit": "🟥",
    "sunk": "⬛"
}

SHIP_SIZES = [5, 4, 3, 3, 2]  # Carrier, Battleship, Cruiser, Submarine, Destroyer

def generate_game_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def place_ships(width, height, total_tiles):
    board = [["water" for _ in range(width)] for _ in range(height)]
    ships = []
    placed_tiles = 0
    sizes = SHIP_SIZES.copy()
    while sizes and placed_tiles < total_tiles:
        size = sizes.pop(0)
        for _ in range(100):
            horizontal = random.choice([True, False])
            if horizontal:
                x = random.randint(0, width - size)
                y = random.randint(0, height - 1)
                if all(board[y][x + i] == "water" for i in range(size)):
                    for i in range(size):
                        board[y][x + i] = f"ship-{len(ships)}"
                    ships.append([(y, x + i) for i in range(size)])
                    placed_tiles += size
                    break
            else:
                x = random.randint(0, width - 1)
                y = random.randint(0, height - size)
                if all(board[y + i][x] == "water" for i in range(size)):
                    for i in range(size):
                        board[y + i][x] = f"ship-{len(ships)}"
                    ships.append([(y + i, x) for i in range(size)])
                    placed_tiles += size
                    break
    return board, ships

def render_board(board, hits):
    rows = []
    width = len(board[0])
    header = "⬛" + ''.join(f"{i+1:02}" for i in range(width))
    rows.append(header)
    for i, row in enumerate(board):
        row_str = chr(65 + i)
        for j, cell in enumerate(row):
            if (i, j) in hits:
                if cell.startswith("ship"):
                    row_str += TILE_EMOJIS["hit"]
                else:
                    row_str += TILE_EMOJIS["miss"]
            else:
                row_str += TILE_EMOJIS["water"]
        rows.append(row_str)
    return "\n".join(rows)

def is_ship_sunk(ship_cells, hits):
    return all(cell in hits for cell in ship_cells)

def all_ships_sunk(ships, hits):
    return all(is_ship_sunk(ship, hits) for ship in ships)

@bot.tree.command(name="start", description="Start a new battleship game")
@app_commands.describe(width="Width of board", height="Height of board", ships="Number of ship tiles")
async def start(interaction: discord.Interaction, width: int, height: int, ships: int):
    game_id = generate_game_id()
    board1, ships1 = place_ships(width, height, ships)
    board2, ships2 = place_ships(width, height, ships)

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
    await interaction.response.send_message(f"Game created with ID: **{game_id}**")

@bot.tree.command(name="join", description="Join a battleship game")
@app_commands.describe(gameid="The ID of the game to join")
async def join(interaction: discord.Interaction, gameid: str):
    game = collection.find_one({"game_id": gameid})
    if not game:
        await interaction.response.send_message("Game not found.", ephemeral=True)
        return

    update = {}
    if not game["channel1"]:
        update["channel1"] = interaction.channel.id
        team = 1
    elif not game["channel2"]:
        update["channel2"] = interaction.channel.id
        team = 2
    else:
        await interaction.response.send_message("Both teams have already joined.", ephemeral=True)
        return

    collection.update_one({"game_id": gameid}, {"$set": update})
    board = game[f"board{3 - team}"]
    hits = game[f"hits{3 - team}"]
    await interaction.response.send_message(f"Joined game {gameid} as Team {team}!\nHere is the opponent board:",
                                            embed=Embed(title=f"Team {team} Target Grid", description=render_board(board, hits)))

@bot.tree.command(name="shoot", description="Shoot a tile on the enemy board")
@app_commands.describe(row="Row letter", column="Column number")
async def shoot(interaction: discord.Interaction, row: str, column: int):
    row = row.upper()
    channel_id = interaction.channel.id
    game = collection.find_one({"$or": [{"channel1": channel_id}, {"channel2": channel_id}]})
    if not game:
        await interaction.response.send_message("You're not in a valid game.", ephemeral=True)
        return

    if game["channel1"] == channel_id:
        team = 1
        enemy_team = 2
    else:
        team = 2
        enemy_team = 1

    y = ord(row) - 65
    x = column - 1
    if not (0 <= y < game["height"] and 0 <= x < game["width"]):
        await interaction.response.send_message("Invalid coordinates.", ephemeral=True)
        return

    hits_key = f"hits{team}"
    board_key = f"board{enemy_team}"
    ships_key = f"ships{enemy_team}"

    hits = set(tuple(pos) for pos in game[hits_key])
    pos = (y, x)
    if pos in hits:
        await interaction.response.send_message("You already shot there.", ephemeral=True)
        return

    hits.add(pos)
    collection.update_one({"game_id": game["game_id"]}, {"$set": {hits_key: list(hits)}})

    board = game[board_key]
    ships = game[ships_key]

    cell = board[y][x]
    hit_result = "💦 Miss!"
    sunk = False
    if cell.startswith("ship"):
        hit_result = "🔥 Hit!"
        ship_index = int(cell.split("-")[1])
        if is_ship_sunk(ships[ship_index], hits):
            hit_result = "💣 Ship Sunk!"
            sunk = True

    all_sunk = all_ships_sunk(ships, hits)
    extra = "\n🎉 **You have sunk all your opponent's battleships, but you may continue to shoot tiles.**" if all_sunk else ""

    await interaction.response.send_message(
        content=hit_result + extra,
        embed=Embed(
            title=f"Team {team} Target Grid",
            description=render_board(board, hits)
        )
    )

bot.run(os.environ["DISCORD_TOKEN"])
