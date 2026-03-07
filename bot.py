import os
import logging
import threading
import random
import time
import json
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    LabeledPrice, PreCheckoutQuery
)
from flask import Flask, request, jsonify, send_from_directory
import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:10000")
PORT = int(os.getenv("PORT", 10000))
DATABASE_URL = os.getenv("DATABASE_URL")  # для PostgreSQL

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
flask_app = Flask(__name__, static_folder="webapp", static_url_path="")

# ========== ПОДКЛЮЧЕНИЕ К БД ==========
import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3

def get_db_connection():
    if DATABASE_URL:
        # PostgreSQL
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    else:
        # SQLite fallback
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        # PostgreSQL syntax
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                loses INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0,
                total_deposit INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS duel_games (
                id SERIAL PRIMARY KEY,
                player1 BIGINT NOT NULL,
                bet1 INTEGER NOT NULL,
                player2 BIGINT DEFAULT NULL,
                bet2 INTEGER DEFAULT NULL,
                status VARCHAR(20) DEFAULT 'waiting',
                winner BIGINT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount INTEGER NOT NULL,
                type VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        # SQLite syntax
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                loses INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0,
                total_deposit INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS duel_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player1 INTEGER NOT NULL,
                bet1 INTEGER NOT NULL,
                player2 INTEGER DEFAULT NULL,
                bet2 INTEGER DEFAULT NULL,
                status TEXT DEFAULT 'waiting',
                winner INTEGER DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    conn.commit()
    cur.close()
    conn.close()

# Вспомогательные функции для работы с пользователями
def get_user(user_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    else:
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        # Создаём нового пользователя с балансом 0
        if DATABASE_URL:
            cur.execute(
                "INSERT INTO users (user_id, balance, wins, loses, games_played, total_deposit) VALUES (%s, 0, 0, 0, 0, 0)",
                (user_id,)
            )
        else:
            cur.execute(
                "INSERT INTO users (user_id, balance, wins, loses, games_played, total_deposit) VALUES (?, 0, 0, 0, 0, 0)",
                (user_id,)
            )
        conn.commit()
        # Получаем только что созданного пользователя
        if DATABASE_URL:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        else:
            cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def update_balance(user_id: int, delta: int):
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (delta, user_id))
    else:
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
    conn.commit()
    cur.close()
    conn.close()

def set_balance(user_id: int, new_balance: int):
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("UPDATE users SET balance = %s WHERE user_id = %s", (new_balance, user_id))
    else:
        cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    cur.close()
    conn.close()

def add_stat(user_id: int, win: bool = False, lose: bool = False):
    conn = get_db_connection()
    cur = conn.cursor()
    if win:
        if DATABASE_URL:
            cur.execute("UPDATE users SET wins = wins + 1, games_played = games_played + 1 WHERE user_id = %s", (user_id,))
        else:
            cur.execute("UPDATE users SET wins = wins + 1, games_played = games_played + 1 WHERE user_id = ?", (user_id,))
    elif lose:
        if DATABASE_URL:
            cur.execute("UPDATE users SET loses = loses + 1, games_played = games_played + 1 WHERE user_id = %s", (user_id,))
        else:
            cur.execute("UPDATE users SET loses = loses + 1, games_played = games_played + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

def get_top_users(limit=10):
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT user_id, wins, loses, games_played, balance FROM users ORDER BY wins DESC LIMIT %s", (limit,))
    else:
        cur.execute("SELECT user_id, wins, loses, games_played, balance FROM users ORDER BY wins DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

# ========== ХРАНИЛИЩЕ АКТИВНЫХ ИГР (CRASH / DUEL) ==========
active_crash_games = {}  # user_id -> game data
active_duel_games = {}    # game_id -> game data (для быстрого доступа)

# ========== КОМАНДЫ БОТА ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    get_user(user_id)  # создаст запись, если нет
    text = (
        "🎰 <b>Добро пожаловать в Casino Bot</b>\n\n"
        "Доступные команды:\n"
        "/casino — открыть казино\n"
        "/balance — проверить баланс\n"
        "/deposit — пополнить баланс\n"
        "/withdraw — вывод средств (заглушка)\n"
        "/help — помощь\n"
        "/profile — профиль игрока\n"
        "/top — топ игроков\n"
        "/games — список игр\n"
    )
    # Кнопка для открытия WebApp
    webapp_button = InlineKeyboardButton(
        text="🎰 Открыть казино",
        web_app=WebAppInfo(url=WEBAPP_URL)
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[webapp_button]])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(f"💰 Ваш баланс: {user['balance']} монет")

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    user = get_user(message.from_user.id)
    text = (
        f"━━━━━━━━━━━━━━\n"
        f"👤 Профиль игрока\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Баланс: {user['balance']} Stars\n"
        f"🎮 Игр сыграно: {user['games_played']}\n"
        f"🏆 Побед: {user['wins']}\n"
        f"💔 Поражений: {user['loses']}\n"
        f"━━━━━━━━━━━━━━"
    )
    await message.answer(text)

@dp.message(Command("top"))
async def cmd_top(message: Message):
    top = get_top_users(10)
    if not top:
        await message.answer("Пока нет статистики.")
        return
    text = "🏆 <b>Топ игроков по победам</b>\n\n"
    for i, row in enumerate(top, 1):
        user_id, wins, loses, games, balance = row
        text += f"{i}. ID {user_id} — побед: {wins}, баланс: {balance}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("games"))
async def cmd_games(message: Message):
    text = (
        "🎮 <b>Доступные игры</b>\n\n"
        "🚀 Ракета — лови момент и забирай выигрыш до краша\n"
        "🎯 Дуэль рулетка — сразись с другим игроком за банк"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("deposit"))
async def cmd_deposit(message: Message):
    await message.answer_invoice(
        title="Пополнение баланса",
        description="1 Star = 1 монета",
        payload="topup",
        currency="XTR",
        prices=[LabeledPrice(label="Монеты", amount=1)],
        start_parameter="topup"
    )

@dp.message(Command("withdraw"))
async def cmd_withdraw(message: Message):
    await message.answer("💸 Вывод средств временно недоступен. Скоро появится!")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await cmd_start(message)  # просто показываем стартовое сообщение

@dp.message(Command("casino"))
async def cmd_casino(message: Message):
    # Открываем WebApp
    webapp_button = InlineKeyboardButton(
        text="🎰 Открыть казино",
        web_app=WebAppInfo(url=WEBAPP_URL)
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[webapp_button]])
    await message.answer("Нажмите кнопку ниже:", reply_markup=keyboard)

# Админ-команды
@dp.message(Command("addbalance"))
async def cmd_addbalance(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /addbalance user_id amount")
        return
    try:
        user_id = int(args[1])
        amount = int(args[2])
        update_balance(user_id, amount)
        await message.answer(f"Баланс пользователя {user_id} увеличен на {amount}.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(Command("setbalance"))
async def cmd_setbalance(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /setbalance user_id new_balance")
        return
    try:
        user_id = int(args[1])
        new_bal = int(args[2])
        set_balance(user_id, new_bal)
        await message.answer(f"Баланс пользователя {user_id} установлен на {new_bal}.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(Command("resetbalance"))
async def cmd_resetbalance(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /resetbalance user_id")
        return
    try:
        user_id = int(args[1])
        set_balance(user_id, 0)
        await message.answer(f"Баланс пользователя {user_id} сброшен в 0.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT COUNT(*), SUM(balance), SUM(wins), SUM(loses), SUM(games_played) FROM users")
    else:
        cur.execute("SELECT COUNT(*), SUM(balance), SUM(wins), SUM(loses), SUM(games_played) FROM users")
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        count, total_balance, total_wins, total_loses, total_games = row
        text = (
            f"📊 Статистика:\n"
            f"Пользователей: {count}\n"
            f"Общий баланс: {total_balance or 0}\n"
            f"Всего игр: {total_games or 0}\n"
            f"Побед: {total_wins or 0}\n"
            f"Поражений: {total_loses or 0}"
        )
        await message.answer(text)
    else:
        await message.answer("Нет данных.")

@dp.message(Command("giveall"))
async def cmd_giveall(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /giveall amount")
        return
    try:
        amount = int(args[1])
        conn = get_db_connection()
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute("UPDATE users SET balance = balance + %s", (amount,))
        else:
            cur.execute("UPDATE users SET balance = balance + ?", (amount,))
        conn.commit()
        cur.close()
        conn.close()
        await message.answer(f"Всем пользователям начислено {amount} монет.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# ========== ОПЛАТА ==========
@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message()
async def successful_payment_handler(message: Message):
    if message.successful_payment:
        user_id = message.from_user.id
        stars = message.successful_payment.total_amount
        update_balance(user_id, stars)
        # Запись в транзакции
        conn = get_db_connection()
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type) VALUES (%s, %s, 'deposit')",
                (user_id, stars)
            )
        else:
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type) VALUES (?, ?, 'deposit')",
                (user_id, stars)
            )
        conn.commit()
        cur.close()
        conn.close()
        await message.answer(f"Баланс пополнен на {stars} монет!")

# ========== FLASK: API И WEBAPP ==========
@flask_app.route("/")
def serve_index():
    return send_from_directory("webapp", "index.html")

@flask_app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("webapp", path)

# API для получения баланса
@flask_app.route("/get_balance", methods=["POST"])
def api_get_balance():
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    user = get_user(int(user_id))
    return jsonify({"balance": user["balance"], "wins": user["wins"], "loses": user["loses"], "games_played": user["games_played"]})

# API для игры "Ракета" (бывший Crash)
@flask_app.route("/bet_rocket", methods=["POST"])
def api_bet_rocket():
    data = request.get_json()
    user_id = data.get("user_id")
    bet = data.get("bet")
    if not user_id or not bet:
        return jsonify({"error": "user_id and bet required"}), 400
    user_id = int(user_id)
    bet = int(bet)
    user = get_user(user_id)
    if bet > user["balance"]:
        return jsonify({"error": "Insufficient balance"}), 400
    if bet <= 0:
        return jsonify({"error": "Bet must be positive"}), 400
    # Удерживаем ставку
    update_balance(user_id, -bet)
    # Генерируем точку краша (от 1.1 до 10.0)
    crash_point = round(random.uniform(1.1, 10.0), 2)
    active_crash_games[user_id] = {
        "bet": bet,
        "crash_point": crash_point,
        "start_time": time.time(),
        "multiplier": 1.0
    }
    return jsonify({"status": "ok", "crash_point": crash_point})

@flask_app.route("/rocket_status", methods=["POST"])
def api_rocket_status():
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    user_id = int(user_id)
    game = active_crash_games.get(user_id)
    if not game:
        return jsonify({"error": "No active game"}), 404
    elapsed = time.time() - game["start_time"]
    current_multiplier = 1.0 + elapsed * 0.5
    if current_multiplier >= game["crash_point"]:
        del active_crash_games[user_id]
        # Проигрыш
        add_stat(user_id, lose=True)
        return jsonify({"crashed": True, "multiplier": game["crash_point"]})
    else:
        event = None
        if random.random() < 0.1:
            event_type = random.choice(["green", "rocket"])
            if event_type == "green":
                event = {"type": "green", "text": "🟢 +1x"}
                game["multiplier"] += 1
            else:
                event = {"type": "rocket", "text": "🚀 -20%"}
                game["multiplier"] *= 0.8
        return jsonify({
            "crashed": False,
            "multiplier": round(current_multiplier, 2),
            "event": event
        })

@flask_app.route("/cashout_rocket", methods=["POST"])
def api_cashout_rocket():
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    user_id = int(user_id)
    game = active_crash_games.get(user_id)
    if not game:
        return jsonify({"error": "No active game"}), 404
    elapsed = time.time() - game["start_time"]
    current_multiplier = 1.0 + elapsed * 0.5
    if current_multiplier >= game["crash_point"]:
        del active_crash_games[user_id]
        add_stat(user_id, lose=True)
        return jsonify({"crashed": True, "win": 0})
    else:
        win = int(game["bet"] * current_multiplier)
        update_balance(user_id, win)
        del active_crash_games[user_id]
        add_stat(user_id, win=True)
        return jsonify({"win": win, "multiplier": round(current_multiplier, 2)})

# ========== API ДЛЯ ДУЭЛЬНОЙ РУЛЕТКИ ==========
@flask_app.route("/create_duel", methods=["POST"])
def api_create_duel():
    data = request.get_json()
    user_id = data.get("user_id")
    bet = data.get("bet")
    if not user_id or not bet:
        return jsonify({"error": "user_id and bet required"}), 400
    user_id = int(user_id)
    bet = int(bet)
    user = get_user(user_id)
    if bet > user["balance"]:
        return jsonify({"error": "Insufficient balance"}), 400
    if bet <= 0:
        return jsonify({"error": "Bet must be positive"}), 400

    # Удерживаем ставку
    update_balance(user_id, -bet)

    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute(
            "INSERT INTO duel_games (player1, bet1, status) VALUES (%s, %s, 'waiting') RETURNING id",
            (user_id, bet)
        )
        game_id = cur.fetchone()[0]
    else:
        cur.execute(
            "INSERT INTO duel_games (player1, bet1, status) VALUES (?, ?, 'waiting')",
            (user_id, bet)
        )
        game_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"game_id": game_id, "status": "waiting"})

@flask_app.route("/list_duels", methods=["GET"])
def api_list_duels():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT id, player1, bet1 FROM duel_games WHERE status = 'waiting' ORDER BY created_at DESC")
    else:
        cur.execute("SELECT id, player1, bet1 FROM duel_games WHERE status = 'waiting' ORDER BY created_at DESC")
    games = cur.fetchall()
    cur.close()
    conn.close()
    result = []
    for g in games:
        result.append({"id": g[0], "player1": g[1], "bet1": g[2]})
    return jsonify(result)

@flask_app.route("/join_duel", methods=["POST"])
def api_join_duel():
    data = request.get_json()
    user_id = data.get("user_id")
    game_id = data.get("game_id")
    bet = data.get("bet")  # сумма, которую хочет поставить второй игрок
    if not all([user_id, game_id, bet]):
        return jsonify({"error": "Missing parameters"}), 400
    user_id = int(user_id)
    game_id = int(game_id)
    bet = int(bet)

    conn = get_db_connection()
    cur = conn.cursor()
    # Получаем игру
    if DATABASE_URL:
        cur.execute("SELECT * FROM duel_games WHERE id = %s AND status = 'waiting'", (game_id,))
    else:
        cur.execute("SELECT * FROM duel_games WHERE id = ? AND status = 'waiting'", (game_id,))
    game = cur.fetchone()
    if not game:
        cur.close()
        conn.close()
        return jsonify({"error": "Game not found or already started"}), 404

    player1 = game[1] if DATABASE_URL else game["player1"]
    bet1 = game[2] if DATABASE_URL else game["bet1"]
    if user_id == player1:
        return jsonify({"error": "Cannot join your own game"}), 400

    user = get_user(user_id)
    if bet > user["balance"]:
        return jsonify({"error": "Insufficient balance"}), 400
    if bet <= 0:
        return jsonify({"error": "Bet must be positive"}), 400

    # Удерживаем ставку второго игрока
    update_balance(user_id, -bet)

    # Обновляем игру
    if DATABASE_URL:
        cur.execute(
            "UPDATE duel_games SET player2 = %s, bet2 = %s, status = 'active' WHERE id = %s",
            (user_id, bet, game_id)
        )
    else:
        cur.execute(
            "UPDATE duel_games SET player2 = ?, bet2 = ?, status = 'active' WHERE id = ?",
            (user_id, bet, game_id)
        )
    conn.commit()
    cur.close()
    conn.close()

    # Сохраняем в памяти для быстрого доступа
    active_duel_games[game_id] = {
        "player1": player1,
        "bet1": bet1,
        "player2": user_id,
        "bet2": bet,
        "status": "active"
    }
    return jsonify({"status": "active", "game_id": game_id})

@flask_app.route("/duel_status", methods=["POST"])
def api_duel_status():
    data = request.get_json()
    game_id = data.get("game_id")
    if not game_id:
        return jsonify({"error": "game_id required"}), 400
    game_id = int(game_id)
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT * FROM duel_games WHERE id = %s", (game_id,))
    else:
        cur.execute("SELECT * FROM duel_games WHERE id = ?", (game_id,))
    game = cur.fetchone()
    cur.close()
    conn.close()
    if not game:
        return jsonify({"error": "Game not found"}), 404
    # Преобразуем в dict
    if DATABASE_URL:
        columns = [desc[0] for desc in cur.description]
        game_dict = dict(zip(columns, game))
    else:
        game_dict = dict(game)
    return jsonify(game_dict)

@flask_app.route("/duel_spin", methods=["POST"])
def api_duel_spin():
    data = request.get_json()
    game_id = data.get("game_id")
    if not game_id:
        return jsonify({"error": "game_id required"}), 400
    game_id = int(game_id)
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT * FROM duel_games WHERE id = %s AND status = 'active'", (game_id,))
    else:
        cur.execute("SELECT * FROM duel_games WHERE id = ? AND status = 'active'", (game_id,))
    game = cur.fetchone()
    if not game:
        cur.close()
        conn.close()
        return jsonify({"error": "Game not active"}), 404

    if DATABASE_URL:
        player1 = game[1]
        bet1 = game[2]
        player2 = game[3]
        bet2 = game[4]
    else:
        player1 = game["player1"]
        bet1 = game["bet1"]
        player2 = game["player2"]
        bet2 = game["bet2"]

    total = bet1 + bet2
    # Определяем победителя случайно, но с весами
    r = random.randint(1, total)
    if r <= bet1:
        winner = player1
        win_amount = total
        # Начисляем выигрыш
        update_balance(player1, total)
        add_stat(player1, win=True)
        add_stat(player2, lose=True)
    else:
        winner = player2
        win_amount = total
        update_balance(player2, total)
        add_stat(player2, win=True)
        add_stat(player1, lose=True)

    # Обновляем статус игры
    if DATABASE_URL:
        cur.execute(
            "UPDATE duel_games SET status = 'finished', winner = %s WHERE id = %s",
            (winner, game_id)
        )
    else:
        cur.execute(
            "UPDATE duel_games SET status = 'finished', winner = ? WHERE id = ?",
            (winner, game_id)
        )
    conn.commit()
    cur.close()
    conn.close()

    # Удаляем из памяти
    if game_id in active_duel_games:
        del active_duel_games[game_id]

    return jsonify({"winner": winner, "win_amount": win_amount})

# ========== ЗАПУСК ==========
def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

async def main():
    init_db()
    # Сброс вебхука
    await bot.delete_webhook(drop_pending_updates=True)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
