import random
from collections import Counter

# Configuration
BOARD_WIDTH = 10
BOARD_HEIGHT = 10
SHIP_TILES = 17  # Standard Battleship count (5+4+3+3+2)

# Ship lengths from standard Battleship game
BASE_SHIP_LENGTHS = [5, 4, 3, 3, 2]

def generate_ship_pool(target_tiles):
    pool = []
    while sum(pool) < target_tiles:
        pool.extend(BASE_SHIP_LENGTHS)
    while sum(pool) > target_tiles:
        pool.pop()
    return pool

def place_ships(width, height, ships):
    board = [[0] * width for _ in range(height)]
    ship_coords_list = []
    ship_orientations = []
    ship_id = 1
    attempts_limit = 200

    for ship_length in ships:
        placed = False
        attempts = 0

        while not placed and attempts < attempts_limit:
            orientation = random.choices(
                ["H", "V", "D+", "D-"],
                weights=[40, 40, 10, 10],
                k=1
            )[0]
            x, y = random.randint(0, width - 1), random.randint(0, height - 1)

            if orientation == "H":
                if x + ship_length > width:
                    x = width - ship_length
                coords = [(y, x + i) for i in range(ship_length)]
            elif orientation == "V":
                if y + ship_length > height:
                    y = height - ship_length
                coords = [(y + i, x) for i in range(ship_length)]
            elif orientation == "D+":
                if x + ship_length > width or y + ship_length > height:
                    x = min(x, width - ship_length)
                    y = min(y, height - ship_length)
                coords = [(y + i, x + i) for i in range(ship_length)]
            elif orientation == "D-":
                if x - ship_length < -1 or y + ship_length > height:
                    x = max(x, ship_length - 1)
                    y = min(y, height - ship_length)
                coords = [(y + i, x - i) for i in range(ship_length)]
            else:
                continue

            # Check availability
            if all(0 <= cx < width and 0 <= cy < height and board[cy][cx] == 0 for cy, cx in coords):
                for cy, cx in coords:
                    board[cy][cx] = ship_id
                ship_coords_list.append(coords)
                ship_orientations.append(orientation)
                ship_id += 1
                placed = True

            attempts += 1

        if not placed:
            return None, None, None  # Failed to generate board

    return board, ship_coords_list, ship_orientations

# Run 20 simulations
orientation_counter = Counter()
failures = 0
for _ in range(20):
    pool = generate_ship_pool(SHIP_TILES)
    board, ships, orientations = place_ships(BOARD_WIDTH, BOARD_HEIGHT, pool)
    if board is None:
        print("⚠️ Failed to generate board.")
        failures += 1
        continue
    orientation_counter.update(orientations)

# Results
print("\n🎯 Ship Orientation Distribution (20 boards):")
for orientation in ["H", "V", "D+", "D-"]:
    print(f"{orientation}: {orientation_counter[orientation]:>3} ships")

if failures > 0:
    print(f"\n❌ Failed to generate {failures} board(s).")
