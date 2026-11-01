import os
import json
import random
import sqlite3
import threading
from datetime import datetime

import telebot
from telebot import types
from aiohttp import web

# ========== 配置 ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", 8080))

bot = telebot.TeleBot(BOT_TOKEN)

DB_PATH = "bot.db"

# ========== 数据库 ==========
def db_init():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 1000,
        inventory TEXT DEFAULT '{}'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT balance, inventory FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id, balance, inventory) VALUES (?, 1000, '{}')", (user_id,))
        conn.commit()
        row = (1000, '{}')
    conn.close()
    return {"balance": row[0], "inventory": json.loads(row[1])}

def update_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def update_inventory(user_id, item, qty=1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT inventory FROM users WHERE user_id=?", (user_id,))
    inv = json.loads(c.fetchone()[0])
    inv[item] = inv.get(item, 0) + qty
    c.execute("UPDATE users SET inventory=? WHERE user_id=?", (json.dumps(inv), user_id))
    conn.commit()
    conn.close()

def create_withdraw(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO withdraw_requests (user_id, amount, created_at) VALUES (?, ?, ?)",
              (user_id, amount, datetime.now().isoformat()))
    req_id = c.lastrowid
    conn.commit()
    conn.close()
    return req_id

# ========== 键盘 ==========
def main_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎰 Казино", callback_data="casino"))
    kb.add(types.InlineKeyboardButton("📦 Кейсы", callback_data="cases"))
    kb.add(types.InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"))
    kb.add(types.InlineKeyboardButton("⭐ Вывод звёзд", callback_data="withdraw"))
    kb.add(types.InlineKeyboardButton("💰 Баланс", callback_data="balance"))
    return kb

def casino_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("x2 (шанс 48%)", callback_data="bet_2"))
    kb.add(types.InlineKeyboardButton("x3 (шанс 32%)", callback_data="bet_3"))
    kb.add(types.InlineKeyboardButton("x4 (шанс 24%)", callback_data="bet_4"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back"))
    return kb

def cases_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Обычный кейс (100)", callback_data="open_common"))
    kb.add(types.InlineKeyboardButton("Редкий кейс (500)", callback_data="open_rare"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back"))
    return kb

# ========== 游戏逻辑 ==========
CASE_ITEMS = {
    "common": [
        {"name": "🪙 Монета", "weight": 50},
        {"name": "💎 Кристалл", "weight": 30},
        {"name": "🎁 Подарок", "weight": 15},
        {"name": "🌟 Звезда", "weight": 5},
    ],
    "rare": [
        {"name": "💎 Кристалл", "weight": 40},
        {"name": "🎁 Подарок", "weight": 35},
        {"name": "🌟 Звезда", "weight": 20},
        {"name": "👑 Корона", "weight": 5},
    ]
}

CASE_PRICE = {"common": 100, "rare": 500}

def roll_case(case_type):
    items = CASE_ITEMS[case_type]
    total = sum(i["weight"] for i in items)
    r = random.uniform(0, total)
    upto = 0
    for item in items:
        upto += item["weight"]
        if r <= upto:
            return item["name"]
    return items[-1]["name"]

# ========== 处理器 ==========
@bot.message_handler(commands=["start"])
def cmd_start(message):
    db_init()
    get_user(message.from_user.id)
    bot.send_message(
        message.chat.id,
        f"Привет, {message.from_user.full_name}!\n\n"
        f"🎮 Добро пожаловать в игровой бот.\n"
        f"Нажми кнопку ниже, чтобы начать.",
        reply_markup=main_kb()
    )

@bot.callback_query_handler(func=lambda call: call.data == "back")
def cb_back(call):
    bot.edit_message_text("Главное меню:", call.message.chat.id, call.message.message_id, reply_markup=main_kb())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "balance")
def cb_balance(call):
    user = get_user(call.from_user.id)
    bot.edit_message_text(
        f"💰 Баланс: <b>{user['balance']}</b> звёзд\n\n"
        f"🎒 Предметов в инвентаре: {sum(user['inventory'].values())}",
        call.message.chat.id, call.message.message_id,
        parse_mode="HTML", reply_markup=main_kb()
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "casino")
def cb_casino(call):
    user = get_user(call.from_user.id)
    bot.edit_message_text(
        f"🎰 Казино\n\n"
        f"Твой баланс: <b>{user['balance']}</b>\n"
        f"Выбери множитель (ставка = 100):",
        call.message.chat.id, call.message.message_id,
        parse_mode="HTML", reply_markup=casino_kb()
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("bet_"))
def cb_bet(call):
    mult = int(call.data.split("_")[1])
    user = get_user(call.from_user.id)
    bet = 100
    if user["balance"] < bet:
        bot.answer_callback_query(call.id, "Недостаточно звёзд!", show_alert=True)
        return

    chances = {2: 0.48, 3: 0.32, 4: 0.24}
    win_chance = chances[mult]

    if random.random() < win_chance:
        win = bet * mult
        update_balance(call.from_user.id, win - bet)
        result = f"🎉 Победа! Ты выиграл <b>{win}</b> звёзд (x{mult})"
    else:
        update_balance(call.from_user.id, -bet)
        result = f"😢 Проигрыш. Потеряно <b>{bet}</b> звёзд."

    user = get_user(call.from_user.id)
    bot.edit_message_text(
        f"{result}\n\n💰 Новый баланс: <b>{user['balance']}</b>",
        call.message.chat.id, call.message.message_id,
        parse_mode="HTML", reply_markup=casino_kb()
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "cases")
def cb_cases(call):
    bot.edit_message_text(
        "📦 Выбери кейс:",
        call.message.chat.id, call.message.message_id,
        reply_markup=cases_kb()
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("open_"))
def cb_open_case(call):
    case_type = call.data.replace("open_", "")
    price = CASE_PRICE[case_type]
    user = get_user(call.from_user.id)

    if user["balance"] < price:
        bot.answer_callback_query(call.id, "Недостаточно звёзд!", show_alert=True)
        return

    update_balance(call.from_user.id, -price)
    item = roll_case(case_type)
    update_inventory(call.from_user.id, item)

    user = get_user(call.from_user.id)
    bot.edit_message_text(
        f"📦 Ты открыл кейс и получил: <b>{item}</b>\n\n"
        f"💰 Баланс: <b>{user['balance']}</b>",
        call.message.chat.id, call.message.message_id,
        parse_mode="HTML", reply_markup=cases_kb()
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "inventory")
def cb_inventory(call):
    user = get_user(call.from_user.id)
    if not user["inventory"]:
        text = "🎒 Инвентарь пуст."
    else:
        lines = [f"• {item}: {qty} шт." for item, qty in user["inventory"].items()]
        text = "🎒 Твой инвентарь:\n\n" + "\n".join(lines)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=main_kb())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "withdraw")
def cb_withdraw(call):
    user = get_user(call.from_user.id)
    if user["balance"] < 100:
        bot.answer_callback_query(call.id, "Минимум для вывода: 100 звёзд", show_alert=True)
        return

    amount = user["balance"]
    update_balance(call.from_user.id, -amount)
    req_id = create_withdraw(call.from_user.id, amount)

    bot.edit_message_text(
        f"⭐ Заявка на вывод <b>{amount}</b> звёзд создана.\n"
        f"ID заявки: <code>{req_id}</code>\n"
        f"Админ рассмотрит её в ближайшее время.",
        call.message.chat.id, call.message.message_id,
        parse_mode="HTML", reply_markup=main_kb()
    )

    if ADMIN_ID:
        try:
            bot.send_message(
                ADMIN_ID,
                f"🔔 Новая заявка на вывод\n"
                f"Пользователь: <a href='tg://user?id={call.from_user.id}'>{call.from_user.full_name}</a>\n"
                f"ID: <code>{call.from_user.id}</code>\n"
                f"Сумма: <b>{amount}</b> звёзд\n"
                f"ID заявки: <code>{req_id}</code>\n\n"
                f"Подтвердить: /approve {req_id}\n"
                f"Отклонить: /reject {req_id}",
                parse_mode="HTML"
            )
        except Exception:
            pass
    bot.answer_callback_query(call.id, "Заявка создана!")

# ========== 管理命令 ==========
@bot.message_handler(commands=["approve"])
def cmd_approve(message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        bot.send_message(message.chat.id, "Использование: /approve <id>")
        return
    req_id = int(args[1])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE withdraw_requests SET status='approved' WHERE id=? AND status='pending'", (req_id,))
    conn.commit()
    conn.close()
    bot.send_message(message.chat.id, f"✅ Заявка {req_id} подтверждена.")

@bot.message_handler(commands=["reject"])
def cmd_reject(message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        bot.send_message(message.chat.id, "Использование: /reject <id>")
        return
    req_id = int(args[1])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, amount FROM withdraw_requests WHERE id=? AND status='pending'", (req_id,))
    row = c.fetchone()
    if row:
        user_id, amount = row
        update_balance(user_id, amount)
        c.execute("UPDATE withdraw_requests SET status='rejected' WHERE id=?", (req_id,))
        conn.commit()
    conn.close()
    bot.send_message(message.chat.id, f"❌ Заявка {req_id} отклонена, звёзды возвращены.")

# ========== HTTP-заглушка для Render ==========
async def health(request):
    return web.Response(text="OK")

def run_http_server():
    app = web.Application()
    app.router.add_get("/", health)
    web.run_app(app, host="0.0.0.0", port=PORT)

# ========== 启动 ==========
if __name__ == "__main__":
    db_init()
    # HTTP-сервер в отдельном потоке — чтобы Render видел открытый порт
    threading.Thread(target=run_http_server, daemon=True).start()
    # Бот в основном потоке
    bot.infinity_polling(skip_pending=True)
