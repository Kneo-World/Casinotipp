import asyncio
import logging
import sqlite3
import threading
import random
import time
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    LabeledPrice, PreCheckoutQuery, SuccessfulPayment
)
from aiogram.utils.deep_linking import create_start_link
from flask import Flask, request, jsonify, send_from_directory

# ======================== НАСТРОЙКИ ============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))          # ID администратора
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:10000")  # URL веб-приложения
PORT = int(os.getenv("PORT", 10000))

# ======================== ИНИЦИАЛИЗАЦИЯ =========================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Flask приложение
flask_app = Flask(__name__, static_folder="webapp", static_url_path="")

# База данных SQLite
DB_PATH = "database.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 100
        )
    """)
    conn.commit()
    conn.close()

def get_balance(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO users (user_id, balance) VALUES (?, 100)", (user_id,))
        conn.commit()
        balance = 100
    else:
        balance = row[0]
    conn.close()
    return balance

def update_balance(user_id: int, amount: int) -> int:
    """Изменяет баланс на amount (может быть отрицательным) и возвращает новый баланс."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 100 + amount))
        new_balance = 100 + amount
    else:
        new_balance = row[0] + amount
        cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    conn.close()
    return new_balance

def set_balance(user_id: int, new_balance: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, new_balance))
    else:
        cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    conn.close()
    return new_balance

# Статистика
def get_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(balance) FROM users")
    count, total_balance = cur.fetchone()
    conn.close()
    return count or 0, total_balance or 0

# ================== ХРАНИЛИЩЕ АКТИВНЫХ ИГР CRASH =================
# Формат: { user_id : { "bet": int, "crash_point": float, "start_time": float, "multiplier": float } }
active_crash_games = {}

# ======================== КОМАНДЫ БОТА ==========================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    get_balance(user_id)  # инициализация
    # Кнопка для открытия WebApp
    webapp_button = InlineKeyboardButton(
        text="🎰 Открыть казино",
        web_app=WebAppInfo(url=f"{WEBAPP_URL}")
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[webapp_button]])
    await message.answer(
        "Добро пожаловать в казино!\n"
        "Нажмите кнопку ниже, чтобы открыть мини‑приложение.",
        reply_markup=keyboard
    )

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
        new_bal = update_balance(user_id, amount)
        await message.answer(f"Баланс пользователя {user_id} изменён на {amount}. Новый баланс: {new_bal}")
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
        await message.answer(f"Баланс пользователя {user_id} установлен на {new_bal}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    count, total = get_stats()
    await message.answer(f"Всего пользователей: {count}\nОбщий баланс: {total}")

# ==================== ОПЛАТА ЧЕРЕЗ STARS ========================
@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    await message.answer_invoice(
        title="Пополнение баланса",
        description="1 Star = 1 монета",
        payload="topup",
        currency="XTR",
        prices=[LabeledPrice(label="Монеты", amount=1)],  # количество звёзд = amount
        start_parameter="topup"
    )

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message()
async def successful_payment_handler(message: Message):
    if message.successful_payment:
        user_id = message.from_user.id
        stars_amount = message.successful_payment.total_amount  # количество звёзд
        update_balance(user_id, stars_amount)  # 1 звезда = 1 монета
        await message.answer(f"Баланс пополнен на {stars_amount} монет!")

# ======================== FLASK: API И WEBAPP ===================
@flask_app.route("/")
def serve_index():
    return send_from_directory("webapp", "index.html")

@flask_app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("webapp", path)

@flask_app.route("/get_balance", methods=["POST"])
def api_get_balance():
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    balance = get_balance(int(user_id))
    return jsonify({"balance": balance})

@flask_app.route("/bet_crash", methods=["POST"])
def api_bet_crash():
    data = request.get_json()
    user_id = data.get("user_id")
    bet = data.get("bet")
    if not user_id or not bet:
        return jsonify({"error": "user_id and bet required"}), 400
    user_id = int(user_id)
    bet = int(bet)
    balance = get_balance(user_id)
    if bet > balance:
        return jsonify({"error": "Insufficient balance"}), 400
    if bet <= 0:
        return jsonify({"error": "Bet must be positive"}), 400

    # Удерживаем ставку
    update_balance(user_id, -bet)

    # Генерируем точку краша (от 1.1 до 10.0)
    crash_point = round(random.uniform(1.1, 10.0), 2)
    # Сохраняем игру
    active_crash_games[user_id] = {
        "bet": bet,
        "crash_point": crash_point,
        "start_time": time.time(),
        "multiplier": 1.0
    }
    return jsonify({"status": "ok", "crash_point": crash_point})

@flask_app.route("/crash_status", methods=["POST"])
def api_crash_status():
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    user_id = int(user_id)
    game = active_crash_games.get(user_id)
    if not game:
        return jsonify({"error": "No active game"}), 404

    # Рассчитываем текущий коэффициент (рост 0.5 в секунду, макс до crash_point)
    elapsed = time.time() - game["start_time"]
    current_multiplier = 1.0 + elapsed * 0.5
    if current_multiplier >= game["crash_point"]:
        # Краш – игра завершена
        del active_crash_games[user_id]
        return jsonify({"crashed": True, "multiplier": game["crash_point"]})
    else:
        # Генерируем случайные события (иногда)
        event = None
        if random.random() < 0.1:  # 10% шанс события
            event_type = random.choice(["green", "rocket"])
            if event_type == "green":
                event = {"type": "green", "text": "🟢 +1x"}
                game["multiplier"] += 1  # добавим к финальному, но пока не применяем
            else:
                event = {"type": "rocket", "text": "🚀 -20%"}
                game["multiplier"] *= 0.8
        return jsonify({
            "crashed": False,
            "multiplier": round(current_multiplier, 2),
            "event": event
        })

@flask_app.route("/cashout", methods=["POST"])
def api_cashout():
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
        # Уже краш – ставка проиграна
        del active_crash_games[user_id]
        return jsonify({"crashed": True, "win": 0})
    else:
        # Игрок забирает выигрыш
        win = int(game["bet"] * current_multiplier)
        update_balance(user_id, win)
        del active_crash_games[user_id]
        return jsonify({"win": win, "multiplier": round(current_multiplier, 2)})

@flask_app.route("/roulette_bet", methods=["POST"])
def api_roulette_bet():
    data = request.get_json()
    user_id = data.get("user_id")
    bet = data.get("bet")
    bet_type = data.get("type")   # "red", "black", "even", "odd", "number"
    number = data.get("number")    # если type == "number"

    if not all([user_id, bet, bet_type]):
        return jsonify({"error": "Missing parameters"}), 400
    user_id = int(user_id)
    bet = int(bet)
    balance = get_balance(user_id)
    if bet > balance:
        return jsonify({"error": "Insufficient balance"}), 400
    if bet <= 0:
        return jsonify({"error": "Bet must be positive"}), 400

    # Крутим колесо
    result_number = random.randint(0, 36)
    is_red = result_number in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    is_black = result_number not in (0, *[1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36])
    is_even = result_number != 0 and result_number % 2 == 0
    is_odd = result_number != 0 and result_number % 2 == 1

    win = 0
    if bet_type == "red" and is_red:
        win = bet * 2
    elif bet_type == "black" and is_black:
        win = bet * 2
    elif bet_type == "even" and is_even:
        win = bet * 2
    elif bet_type == "odd" and is_odd:
        win = bet * 2
    elif bet_type == "number" and number is not None and int(number) == result_number:
        win = bet * 36

    if win > 0:
        update_balance(user_id, win - bet)  # вычитаем уже удержанную ставку
    else:
        update_balance(user_id, -bet)  # удерживаем ставку (проигрыш)
    new_balance = get_balance(user_id)

    return jsonify({
        "result_number": result_number,
        "win": win,
        "new_balance": new_balance
    })

# ======================== ЗАПУСК БОТА И FLASK ===================
def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
