import os
import json
import random
import asyncio
import sqlite3
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ========== 配置 ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BASE_WEBHOOK_URL = os.getenv("BASE_WEBHOOK_URL")  # 例如 https://your-app.onrender.com
PORT = int(os.getenv("PORT", 8080))
WEBHOOK_PATH = "/webhook"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ========== 数据库 ==========
DB_PATH = "bot.db"

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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Казино", callback_data="casino")],
        [InlineKeyboardButton(text="📦 Кейсы", callback_data="cases")],
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inventory")],
        [InlineKeyboardButton(text="⭐ Вывод звёзд", callback_data="withdraw")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
    ])

def casino_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="x2 (шанс 48%)", callback_data="bet_2")],
        [InlineKeyboardButton(text="x3 (шанс 32%)", callback_data="bet_3")],
        [InlineKeyboardButton(text="x4 (шанс 24%)", callback_data="bet_4")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back")],
    ])

def cases_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Обычный кейс (100)", callback_data="open_common")],
        [InlineKeyboardButton(text="Редкий кейс (500)", callback_data="open_rare")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back")],
    ])

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
@router.message(CommandStart())
async def cmd_start(message: Message):
    db_init()
    get_user(message.from_user.id)
    await message.answer(
        f"Привет, {message.from_user.full_name}!\n\n"
        f"🎮 Добро пожаловать в игровой бот.\n"
        f"Нажми кнопку ниже, чтобы начать.",
        reply_markup=main_kb()
    )

@router.callback_query(F.data == "back")
async def cb_back(call: CallbackQuery):
    await call.message.edit_text("Главное меню:", reply_markup=main_kb())
    await call.answer()

@router.callback_query(F.data == "balance")
async def cb_balance(call: CallbackQuery):
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"💰 Баланс: <b>{user['balance']}</b> звёзд\n\n"
        f"🎒 Предметов в инвентаре: {sum(user['inventory'].values())}",
        reply_markup=main_kb()
    )
    await call.answer()

@router.callback_query(F.data == "casino")
async def cb_casino(call: CallbackQuery):
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"🎰 Казино\n\n"
        f"Твой баланс: <b>{user['balance']}</b>\n"
        f"Выбери множитель (ставка = 100):",
        reply_markup=casino_kb()
    )
    await call.answer()

@router.callback_query(F.data.startswith("bet_"))
async def cb_bet(call: CallbackQuery):
    mult = int(call.data.split("_")[1])
    user = get_user(call.from_user.id)
    bet = 100
    if user["balance"] < bet:
        await call.answer("Недостаточно звёзд!", show_alert=True)
        return

    chances = {2: 0.48, 3: 0.32, 4: 0.24}
    win_chance = chances[mult]

    if random.random() < win_chance:
        win = bet * mult
        update_balance(call.from_user.id, win - bet)  # 净赢 win - bet
        result = f"🎉 Победа! Ты выиграл <b>{win}</b> звёзд (x{mult})"
    else:
        update_balance(call.from_user.id, -bet)
        result = f"😢 Проигрыш. Потеряно <b>{bet}</b> звёзд."

    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"{result}\n\n💰 Новый баланс: <b>{user['balance']}</b>",
        reply_markup=casino_kb()
    )
    await call.answer()

@router.callback_query(F.data == "cases")
async def cb_cases(call: CallbackQuery):
    await call.message.edit_text(
        "📦 Выбери кейс:",
        reply_markup=cases_kb()
    )
    await call.answer()

@router.callback_query(F.data.startswith("open_"))
async def cb_open_case(call: CallbackQuery):
    case_type = call.data.replace("open_", "")
    price = CASE_PRICE[case_type]
    user = get_user(call.from_user.id)

    if user["balance"] < price:
        await call.answer("Недостаточно звёзд!", show_alert=True)
        return

    update_balance(call.from_user.id, -price)
    item = roll_case(case_type)
    update_inventory(call.from_user.id, item)

    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"📦 Ты открыл кейс и получил: <b>{item}</b>\n\n"
        f"💰 Баланс: <b>{user['balance']}</b>",
        reply_markup=cases_kb()
    )
    await call.answer()

@router.callback_query(F.data == "inventory")
async def cb_inventory(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user["inventory"]:
        text = "🎒 Инвентарь пуст."
    else:
        lines = [f"• {item}: {qty} шт." for item, qty in user["inventory"].items()]
        text = "🎒 Твой инвентарь:\n\n" + "\n".join(lines)
    await call.message.edit_text(text, reply_markup=main_kb())
    await call.answer()

@router.callback_query(F.data == "withdraw")
async def cb_withdraw(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if user["balance"] < 100:
        await call.answer("Минимум для вывода: 100 звёзд", show_alert=True)
        return

    amount = user["balance"]
    update_balance(call.from_user.id, -amount)
    req_id = create_withdraw(call.from_user.id, amount)

    await call.message.edit_text(
        f"⭐ Заявка на вывод <b>{amount}</b> звёзд создана.\n"
        f"ID заявки: <code>{req_id}</code>\n"
        f"Админ рассмотрит её в ближайшее время.",
        reply_markup=main_kb()
    )

    # 通知管理员
    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🔔 Новая заявка на вывод\n"
                f"Пользователь: <a href='tg://user?id={call.from_user.id}'>{call.from_user.full_name}</a>\n"
                f"ID: <code>{call.from_user.id}</code>\n"
                f"Сумма: <b>{amount}</b> звёзд\n"
                f"ID заявки: <code>{req_id}</code>\n\n"
                f"Подтвердить: /approve {req_id}\n"
                f"Отклонить: /reject {req_id}"
            )
        except Exception:
            pass
    await call.answer("Заявка создана!")

# ========== 管理命令 ==========
@router.message(Command("approve"))
async def cmd_approve(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /approve <id>")
        return
    req_id = int(args[1])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE withdraw_requests SET status='approved' WHERE id=? AND status='pending'", (req_id,))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Заявка {req_id} подтверждена.")

@router.message(Command("reject"))
async def cmd_reject(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /reject <id>")
        return
    req_id = int(args[1])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, amount FROM withdraw_requests WHERE id=? AND status='pending'", (req_id,))
    row = c.fetchone()
    if row:
        user_id, amount = row
        update_balance(user_id, amount)  # 退还
        c.execute("UPDATE withdraw_requests SET status='rejected' WHERE id=?", (req_id,))
        conn.commit()
    conn.close()
    await message.answer(f"❌ Заявка {req_id} отклонена, звёзды возвращены.")

# ========== Webhook 启动 ==========
async def on_startup(bot: Bot):
    await bot.set_webhook(f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}")

def main():
    db_init()

    app = web.Application()
    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    dp.startup.register(on_startup)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
