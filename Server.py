from fastapi import FastAPI, WebSocket
import asyncio
import json
import uvicorn
import os
import mysql.connector
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Database connection
DB_HOST = os.environ.get("DB_HOST", "your-rds-endpoint")
DB_NAME = os.environ.get("DB_NAME", "game_db")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASS = os.environ.get("DB_PASS", "yourpassword")
DB_PORT = os.environ.get("DB_PORT", "3306")

def init_db():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
        )
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_records (
                game_id INT AUTO_INCREMENT PRIMARY KEY,
                player1_id VARCHAR(10),
                player2_id VARCHAR(10),
                winner VARCHAR(10),
                loser VARCHAR(10),
                timestamp DATETIME
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database init failed: {e}")

# Initialize board
def initialize_board():
    board = [[None for _ in range(8)] for _ in range(8)]
    for row in range(2):
        for col in range(8):
            board[row][col] = {'player': 'P1', 'moves': 0}
    for row in range(6, 8):
        for col in range(8):
            board[row][col] = {'player': 'P2', 'moves': 0}
    logger.info("Board initialized with pawns")
    return board

# Game state
board = initialize_board()
current_player = 1
moves_left = {"1": 100, "2": 100}  # Use string keys for consistency
last_action = {"1": None, "2": None}
clients = {1: None, 2: None}
game_over = False

def get_valid_moves(row, col, player):
    moves = []
    pawn = board[row][col]
    if not pawn or pawn['player'] != f'P{player}':
        return moves
    move_count = pawn['moves']
    max_steps = 1 if (move_count + 1) % 2 == 1 else 2
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    opponent = 'P2' if player == 1 else 'P1'

    for dr, dc in directions:
        for step in range(1, max_steps + 1):
            new_row, new_col = row + dr * step, col + dc * step
            if not (0 <= new_row < 8 and 0 <= new_col < 8):
                break
            if board[new_row][new_col] and board[new_row][new_col]['player'] == f'P{player}':
                break
            if step == max_steps:
                moves.append((new_row, new_col))
            if board[new_row][new_col] and board[new_row][new_col]['player'] == opponent:
                break
    return moves

def count_pawns():
    p1_pawns = sum(1 for row in board for cell in row if cell and cell['player'] == 'P1')
    p2_pawns = sum(1 for row in board for cell in row if cell and cell['player'] == 'P2')
    logger.info(f"P1 pawns: {p1_pawns}, P2 pawns: {p2_pawns}")
    return p1_pawns, p2_pawns

def save_game_result(winner, loser):
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
        )
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO game_records (player1_id, player2_id, winner, loser, timestamp) VALUES (%s, %s, %s, %s, %s)",
            ("P1", "P2", winner, loser, datetime.utcnow())
        )
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Saved game result: winner={winner}, loser={loser}")
    except Exception as e:
        logger.error(f"Failed to save game result: {e}")

async def broadcast_state():
    global game_over
    p1_pawns, p2_pawns = count_pawns()
    if moves_left["1"] <= 0 or moves_left["2"] <= 0 or p1_pawns == 0 or p2_pawns == 0:
        game_over = True
        winner = "Draw"
        loser = "None"
        if p1_pawns > p2_pawns or (moves_left["1"] <= 0 and p1_pawns >= p2_pawns):
            winner, loser = "P1", "P2"
        elif p2_pawns > p1_pawns or (moves_left["2"] <= 0 and p2_pawns >= p1_pawns):
            winner, loser = "P2", "P1"
        #save_game_result(winner, loser)

    state = {
        'board': board,
        'current_player': current_player,
        'moves_left': moves_left,
        'last_action': last_action,
        'game_over': game_over,
        'winner': winner if game_over else None
    }
    logger.info(f"Broadcasting state: current_player={current_player}, game_over={game_over}")
    for player, client in clients.items():
        if client:
            try:
                await client.send_json(state)
                logger.info(f"Sent state to player {player}")
            except Exception as e:
                logger.error(f"Failed to send state to player {player}: {e}")

@app.websocket("/ws/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: int):
    global game_over
    await websocket.accept()
    if player_id in [1, 2] and clients[player_id] is None:
        clients[player_id] = websocket
        logger.info(f"Player {player_id} connected")
        await broadcast_state()
        try:
            while True:
                data = await websocket.receive_json()
                logger.info(f"Received from player {player_id}: {data}")
                if game_over:
                    continue
                action = data.get('action')
                if data.get('player') != current_player:
                    continue

                if action == 'select':
                    row, col = data['row'], data['col']
                    if board[row][col] and board[row][col]['player'] == f'P{current_player}':
                        valid_moves = get_valid_moves(row, col, current_player)
                        await websocket.send_json({
                            'type': 'valid_moves',
                            'valid_moves': valid_moves,
                            'selected': (row, col)
                        })
                        logger.info(f"Sent valid moves to player {player_id}")

                elif action == 'move':
                    row, col = data['row'], data['col']
                    selected = data['selected']
                    old_row, old_col = selected
                    if (row, col) in get_valid_moves(old_row, old_col, current_player):
                        pawn = board[old_row][old_col]
                        pawn['moves'] += 1
                        board[old_row][old_col] = None
                        board[row][col] = pawn
                        moves_left[str(current_player)] -= 1
                        last_action[str(current_player)] = 'move'
                        current_player = 2 if current_player == 1 else 1
                        await broadcast_state()

                elif action == 'skip':
                    if last_action.get(str(current_player)) != 'skip':
                        last_action[str(current_player)] = 'skip'
                        current_player = 2 if current_player == 1 else 1
                        await broadcast_state()
                    else:
                        await websocket.send_json({'type': 'error', 'message': 'Cannot skip twice!'})

        except Exception as e:
            logger.error(f"Player {player_id} disconnected: {e}")
            clients[player_id] = None
            # Avoid double-close
            if websocket.client_state != 3:  # 3 = CLOSED
                await websocket.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)