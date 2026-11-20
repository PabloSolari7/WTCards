import asyncio
import random
import sqlite3
import time
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

# --- ВСТАВЬТЕ ВАШИ ДАННЫЕ НИЖЕ ---
TOKEN = "9201193460:AAH_ip4vvxrotIRNKNxjQF6His3TeLu-X4I"
ADMIN_ID = 1563482370 # СЮДА ВСТАВЬТЕ ВАШ ID (БЕЗ КАВЫЧЕК!)
COOLDOWN = 4 * 3600   # Перезарядка крутки (4 часа)
# --------------------------------

bot = Bot(token=TOKEN)
dp = Dispatcher()

conn = sqlite3.connect("tank_cards.db")
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, points INTEGER DEFAULT 0, last_spin INTEGER DEFAULT 0
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rarity TEXT, points INTEGER, file_id TEXT, weight INTEGER
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS inventory (
    user_id INTEGER, card_id INTEGER
)""")
conn.commit()

def register_user(user_id: int, username: str):
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username or "Танкист"))
    conn.commit()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    register_user(message.from_user.id, message.from_user.first_name)
    await message.reply(
        "🎖 **Добро пожаловать в Tank Cards!**\n\n"
        "Доступные команды:\n"
        "• `танк` или `/tank` — получить случайный танк\n"
        "• `ангар` или `/profile` — посмотреть коллекцию и очки\n"
        "• `топ` или `/top` — рейтинг игроков",
        parse_mode="Markdown"
    )

# Добавление карточки (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(F.photo, F.caption.startswith("/add"))
async def add_card(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        raw_text = message.caption.replace("/add", "", 1).strip()
        name, rarity, points, weight = [item.strip() for item in raw_text.split("|")]
        photo_id = message.photo[-1].file_id

        cur.execute(
            "INSERT INTO cards (name, rarity, points, file_id, weight) VALUES (?, ?, ?, ?, ?)",
            (name, rarity, int(points), photo_id, int(weight))
        )
        conn.commit()
        await message.reply(f"✅ Карточка добавлена!\n🚜 **{name}** | {rarity} | +{points} очк.", parse_mode="Markdown")
    except Exception:
        await message.reply(
            "❌ Ошибка! Прикрепите фото и напишите в подписи:\n"
            "`/add Название | Редкость | Очки | Шанс`\n\n"
            "Пример:\n`/add Т-34-85 | Обычный ⚪️ | 100 | 50`",
            parse_mode="Markdown"
        )

# Просмотр списка всех карточек с ID (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(Command("list"))
async def list_cards(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    cur.execute("SELECT id, name, rarity, points, weight FROM cards")
    rows = cur.fetchall()
    if not rows:
        return await message.reply("База карточек пуста.")
    text = "\n".join([f"🆔 **{r}** — {r} ({r}) | +{r} очк. | шанс: {r}" for r in rows])
    await message.reply(f"📋 **Список карточек:**\n\n{text}", parse_mode="Markdown")

# Удаление карточки по ID (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(Command("del"))
async def delete_card(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts.isdigit():
        return await message.reply("Укажите номер карточки, например: `/del 1`", parse_mode="Markdown")
    
    card_id = int(parts)
    cur.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    cur.execute("DELETE FROM inventory WHERE card_id = ?", (card_id,))
    conn.commit()
    await message.reply(f"🗑 Карточка **#{card_id}** удалена!", parse_mode="Markdown")

# Выбивание танка (крутка)
@dp.message(Command("tank"))
@dp.message(F.text.lower().in_({"танк", "крутить", "карточка"}))
async def spin_tank(message: Message):
    uid = message.from_user.id
    register_user(uid, message.from_user.first_name)

    cur.execute("SELECT id, name, rarity, points, file_id, weight FROM cards")
    all_cards = cur.fetchall()
    if not all_cards:
        return await message.reply("⚙️ В базе пока нет танков. Админ скоро добавит карточки!")

    cur.execute("SELECT last_spin FROM users WHERE user_id = ?", (uid,))
    last_spin = cur.fetchone()
    now = int(time.time())

    if now - last_spin < COOLDOWN:
        rem = COOLDOWN - (now - last_spin)
        hours, mins = rem // 3600, (rem % 3600) // 60
        return await message.reply(f"⏳ Перезарядка! Следующий танк через **{hours} ч. {mins} мин.**", parse_mode="Markdown")

    chosen = random.choices(all_cards, weights=[c for c in all_cards], k=1)
    card_id, name, rarity, pts, file_id, _ = chosen

    cur.execute("UPDATE users SET last_spin = ?, points = points + ? WHERE user_id = ?", (now, pts, uid))
    cur.execute("INSERT INTO inventory (user_id, card_id) VALUES (?, ?)", (uid, card_id))
    conn.commit()

    caption = (
        f"🎖 **Новая боевая машина!**\n\n"
        f"🚜 **Техника:** {name}\n"
        f"✨ **Редкость:** {rarity}\n"
        f"🏆 **Очки:** +{pts}"
    )
    await message.reply_photo(photo=file_id, caption=caption, parse_mode="Markdown")

# Профиль и ангар
@dp.message(Command("profile"))
@dp.message(F.text.lower().in_({"ангар", "профиль"}))
async def my_hangar(message: Message):
    uid = message.from_user.id
    register_user(uid, message.from_user.first_name)

    cur.execute("SELECT points FROM users WHERE user_id = ?", (uid,))
    points = cur.fetchone()

    cur.execute("""
        SELECT c.name, c.rarity, COUNT(i.card_id)
        FROM inventory i JOIN cards c ON i.card_id = c.id
        WHERE i.user_id = ? GROUP BY c.id
    """, (uid,))
    rows = cur.fetchall()
    inv_text = "\n".join([f"• **{r}** ({r}) — {r} шт." for r in rows]) or "Пока пусто. Напишите «танк»!"

    text = f"👤 **Танкист:** {message.from_user.first_name}\n🏆 **Очки:** {points}\n\n🚜 **Ваш ангар:**\n{inv_text}"
    await message.reply(text, parse_mode="Markdown")

# Топ игроков
@dp.message(Command("top"))
@dp.message(F.text.lower() == "топ")
async def top_players(message: Message):
    cur.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10")
    rows = cur.fetchall()
    top_text = "\n".join([f"{i+1}. **{r}** — {r} очк." for i, r in enumerate(rows)]) or "Рейтинг пуст."
    await message.reply(f"🏆 **Топ-10 танкистов:**\n\n{top_text}", parse_mode="Markdown")

async def main():
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
