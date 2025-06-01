import pygame as pg
import websocket
import json
import threading
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

pg.init()

# Colors
BLACK = pg.Color('black')
WHITE = pg.Color('white')
RED = pg.Color('red')
BLUE = pg.Color('blue')
GREEN = pg.Color('green')
YELLOW = pg.Color('yellow')
GRAY = pg.Color('gray')

# Screen setup
screen = pg.display.set_mode((800, 800))
clock = pg.time.Clock()

# Checkerboard
tile_size = 80
width, height = 8 * tile_size, 8 * tile_size
background = pg.Surface((width, height))
for y in range(0, height, tile_size):
    for x in range(0, width, tile_size):
        color = WHITE if (x // tile_size + y // tile_size) % 2 == 0 else BLACK
        pg.draw.rect(background, color, (x, y, tile_size, tile_size))

# Game state
board = [[None for _ in range(8)] for _ in range(8)]
current_player = 1
moves_left = {"1": 100, "2": 100}  # Use string keys
last_action = {"1": None, "2": None}
selected = None
valid_moves = []
message = ""
game_over = False
winner = None
font = pg.font.SysFont(None, 30)

# WebSocket
ws = None
player_id = int(input("Enter player ID (1 or 2): "))

def on_message(ws, msg):
    global board, current_player, moves_left, last_action, selected, valid_moves, message, game_over, winner
    try:
        data = json.loads(msg)
        logger.info(f"Received message: {data}")
        if data.get('type') == 'valid_moves':
            valid_moves = data['valid_moves']
            selected = tuple(data['selected'])
            logger.info(f"Updated valid_moves: {valid_moves}, selected: {selected}")
        elif data.get('type') == 'error':
            message = data['message']
            logger.info(f"Error message: {message}")
        else:
            board = data['board']
            current_player = data['current_player']
            moves_left = data['moves_left']
            last_action = data['last_action']
            game_over = data['game_over']
            winner = data['winner']
            selected = None
            valid_moves = []
            message = ""
            logger.info(f"Updated board state: current_player={current_player}, game_over={game_over}")
            p1_pawns = sum(1 for row in board for cell in row if cell and cell['player'] == 'P1')
            p2_pawns = sum(1 for row in board for cell in row if cell and cell['player'] == 'P2')
            logger.info(f"Board has {p1_pawns} P1 pawns, {p2_pawns} P2 pawns")
    except Exception as e:
        logger.error(f"Error processing message: {e}")

def on_error(ws, error):
    logger.error(f"WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    logger.info(f"WebSocket closed: status={close_status_code}, msg={close_msg}")

def connect_websocket():
    global ws
    ws = websocket.WebSocketApp(
        f"ws://localhost:8000/ws/{player_id}",
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    threading.Thread(target=ws.run_forever, daemon=True).start()
    logger.info(f"Connecting to ws://localhost:8000/ws/{player_id}")

connect_websocket()

game_exit = False
while not game_exit:
    for event in pg.event.get():
        if event.type == pg.QUIT:
            game_exit = True
        elif event.type == pg.MOUSEBUTTONDOWN and moves_left.get(str(player_id), 0) > 0 and not game_over:
            if player_id != current_player:
                continue
            mouse_x, mouse_y = event.pos
            board_x = (mouse_x - 100) // tile_size
            board_y = (mouse_y - 100) // tile_size
            if 0 <= board_x < 8 and 0 <= board_y < 8:
                if selected is None and board[board_y][board_x] and board[board_y][board_x]['player'] == f'P{player_id}':
                    ws.send(json.dumps({
                        'action': 'select',
                        'player': player_id,
                        'row': board_y,
                        'col': board_x
                    }))
                    logger.info(f"Sent select: row={board_y}, col={board_x}")
                elif (board_y, board_x) in valid_moves:
                    ws.send(json.dumps({
                        'action': 'move',
                        'player': player_id,
                        'row': board_y,
                        'col': board_x,
                        'selected': selected
                    }))
                    logger.info(f"Sent move: row={board_y}, col={board_x}")
                    selected = None
                    valid_moves = []
        elif event.type == pg.KEYDOWN and event.key == pg.K_SPACE and player_id == current_player and not game_over:
            ws.send(json.dumps({
                'action': 'skip',
                'player': player_id
            }))
            logger.info("Sent skip")

    # Draw
    screen.fill((60, 70, 90))
    screen.blit(background, (100, 100))

    # Draw pawns and numbers
    for row in range(8):
        for col in range(8):
            if board[row][col]:
                center_x = 100 + col * tile_size + tile_size // 2
                center_y = 100 + row * tile_size + tile_size // 2
                color = RED if board[row][col]['player'] == 'P1' else BLUE
                pg.draw.circle(screen, color, (center_x, center_y), tile_size // 3)
                next_move = board[row][col]['moves'] + 1
                distance = 1 if next_move % 2 == 1 else 2
                number_text = font.render(str(distance), True, WHITE)
                text_rect = number_text.get_rect(center=(center_x, center_y))
                screen.blit(number_text, text_rect)

    # Highlight selected pawn
    if selected:
        row, col = selected
        center_x = 100 + col * tile_size + tile_size // 2
        center_y = 100 + row * tile_size + tile_size // 2
        pg.draw.circle(screen, GREEN, (center_x, center_y), tile_size // 3, 3)

    # Highlight valid moves
    for row, col in valid_moves:
        center_x = 100 + col * tile_size + tile_size // 2
        center_y = 100 + row * tile_size + tile_size // 2
        pg.draw.circle(screen, YELLOW, (center_x, center_y), tile_size // 6)

    # Draw HUD
    try:
        text = font.render(f"P1 Moves Left: {moves_left['1']}  P2 Moves Left: {moves_left['2']}", True, WHITE)
        screen.blit(text, (20, 20))
    except KeyError as e:
        logger.error(f"HUD render error: {e}")
        text = font.render("Moves Left: Error", True, WHITE)
        screen.blit(text, (20, 20))
    turn_text = font.render(f"Player {current_player}'s Turn" if not game_over else f"Game Over: {winner} Wins" if winner else "Game Over: Draw", True, WHITE)
    screen.blit(turn_text, (20, 40))
    skip_text = font.render("Press SPACE to Skip" if not game_over else "", True, WHITE)
    screen.blit(skip_text, (20, 60))
    if message:
        msg_text = font.render(message, True, GRAY)
        screen.blit(msg_text, (20, 80))

    pg.display.flip()
    clock.tick(30)

pg.quit()
if ws:
    ws.close()
logger.info("Client closed")