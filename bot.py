import asyncio
import random
import sqlite3
import time
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

# --- ВСТАВЬТЕ ВАШИ ДАННЫЕ НИЖЕ ---
TOKEN = "9201193460:AAH_ip4vvxrotIRNKNxjQF6His3TeLu-X4I"
ADMIN_ID = 1563482370  # СЮДА ВСТАВЬТЕ ВАШ ID (БЕЗ КАВЫЧЕК!)
DEFAULT_COOLDOWN = 30 # Перезарядка по умолчанию (в минутах)
# --------------------------------

bot = Bot(token=TOKEN)
dp = Dispatcher()

conn = sqlite3.connect("tank_cards.db")
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, points INTEGER DEFAULT 0, last_spin INTEGER DEFAULT 0
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    nation TEXT DEFAULT 'Не указана',
    rarity TEXT,
    points INTEGER,
    file_id TEXT,
    weight INTEGER
)""")
# Аккуратно добавляем колонку nation в старую базу, если её там ещё нет
try:
    cur.execute("ALTER TABLE cards ADD COLUMN nation TEXT DEFAULT 'Не указана'")
except sqlite3.OperationalError:
    pass

cur.execute("""CREATE TABLE IF NOT EXISTS inventory (
    user_id INTEGER, card_id INTEGER
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value INTEGER
)""")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('cooldown_mins', ?)", (DEFAULT_COOLDOWN,))
conn.commit()

def get_cooldown_seconds() -> int:
    cur.execute("SELECT value FROM settings WHERE key = 'cooldown_mins'")
    mins, = cur.fetchone()
    return mins * 60

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

# Изменение перезарядки в минутах (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(Command("cd"))
async def set_cooldown(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        cur_mins = get_cooldown_seconds() // 60
        return await message.reply(f"⏱ Текущий кулдаун: **{cur_mins} мин.**\nЧтобы изменить, напишите: `/cd 30`", parse_mode="Markdown")
    
    num_str = parts.pop(1)
    if not num_str.isdigit():
        return await message.reply("Укажите время в минутах числом, например: `/cd 15`", parse_mode="Markdown")
    
    new_mins = int(num_str)
    cur.execute("UPDATE settings SET value = ? WHERE key = 'cooldown_mins'", (new_mins,))
    conn.commit()
    await message.reply(f"✅ Новая перезарядка установлена: **{new_mins} мин.**", parse_mode="Markdown")

# Добавление новой карточки (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(F.photo, F.caption.startswith("/add"))
async def add_card(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        raw_text = message.caption.replace("/add", "", 1).strip()
        parts = raw_text.split("|")
        name = parts.pop(0).strip()
        nation = parts.pop(0).strip()
        rarity = parts.pop(0).strip()
        points = int(parts.pop(0).strip())
        weight = int(parts.pop(0).strip())
        photo_id = message.photo.pop().file_id

        cur.execute(
            "INSERT INTO cards (name, nation, rarity, points, file_id, weight) VALUES (?, ?, ?, ?, ?, ?)",
            (name, nation, rarity, points, photo_id, weight)
        )
        conn.commit()
        await message.reply(
            f"✅ Карточка добавлена!\n"
            f"🚜 **{name}** | {nation} | {rarity} | +{points} очк.",
            parse_mode="Markdown"
        )
    except Exception:
        await message.reply(
            "❌ Ошибка! Прикрепите фото и напишите в подписи 5 параметров:\n"
            "`/add Название | Нация | Редкость | Очки | Шанс`\n\n"
            "Пример:\n`/add Т-34-85 | СССР 🚩 | Обычный ⚪️ | 100 | 95`",
            parse_mode="Markdown"
        )

# Быстрая установка/смена НАЦИИ по ID карточки (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(Command("nation"))
async def set_nation(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        return await message.reply(
            "Укажите ID карточки и нацию, например:\n`/nation 1 СССР 🚩`",
            parse_mode="Markdown"
        )
    card_id = int(parts[1])
    new_nation = parts[2].strip()
    cur.execute("UPDATE cards SET nation = ? WHERE id = ?", (new_nation, card_id))
    conn.commit()
    await message.reply(f"🌍 Нация карточки **#{card_id}** обновлена на: **{new_nation}**", parse_mode="Markdown")

# Полное редактирование карточки по ID (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(Command("edit"))
async def edit_card(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        raw_text = message.text.replace("/edit", "", 1).strip()
        parts = raw_text.split("|")
        card_id = int(parts.pop(0).strip())
        name = parts.pop(0).strip()
        nation = parts.pop(0).strip()
        rarity = parts.pop(0).strip()
        points = int(parts.pop(0).strip())
        weight = int(parts.pop(0).strip())

        cur.execute(
            "UPDATE cards SET name = ?, nation = ?, rarity = ?, points = ?, weight = ? WHERE id = ?",
            (name, nation, rarity, points, weight, card_id)
        )
        conn.commit()
        await message.reply(
            f"✏️ Карточка **#{card_id}** обновлена!\n"
            f"🚜 **{name}** | {nation} | {rarity} | +{points} очк. | шанс: {weight}",
            parse_mode="Markdown"
        )
    except Exception:
        await message.reply(
            "❌ Ошибка формата! Пишите так:\n"
            "`/edit ID | Название | Нация | Редкость | Очки | Шанс`\n\n"
            "Пример:\n`/edit 1 | Т-34-85 | СССР 🚩 | Обычный ⚪️ | 150 | 95`",
            parse_mode="Markdown"
        )

# Просмотр списка всех карточек с ID (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(Command("list"))
async def list_cards(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    cur.execute("SELECT id, name, nation, rarity, points, weight FROM cards")
    rows = cur.fetchall()
    if not rows:
        return await message.reply("База карточек пуста.")
    lines = []
    for cid, name, nation, rarity, pts, weight in rows:
        lines.append(f"🆔 {cid} — {name} [{nation}] ({rarity}) | +{pts} очк. | шанс: {weight}")
    await message.reply("📋 Список карточек:\n\n" + "\n".join(lines))

# Удаление карточки по ID (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(Command("del"))
async def delete_card(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply("Укажите номер карточки, например: /del 1")
    num_str = parts.pop(1)
    if not num_str.isdigit():
        return await message.reply("Номер должен быть числом, например: /del 1")
    
    card_id = int(num_str)
    cur.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    cur.execute("DELETE FROM inventory WHERE card_id = ?", (card_id,))
    conn.commit()
    await message.reply(f"🗑 Карточка #{card_id} удалена!")

# Выбивание танка (крутка)
@dp.message(Command("tank"))
@dp.message(F.text.lower().in_({"танк", "крутить", "карточка"}))
async def spin_tank(message: Message):
    uid = message.from_user.id
    register_user(uid, message.from_user.first_name)

    cur.execute("SELECT id, name, nation, rarity, points, file_id, weight FROM cards")
    all_cards = cur.fetchall()
    if not all_cards:
        return await message.reply("⚙️ В базе пока нет танков. Админ скоро добавит карточки!")

    cur.execute("SELECT last_spin FROM users WHERE user_id = ?", (uid,))
    last_spin, = cur.fetchone()
    now = int(time.time())
    cooldown_sec = get_cooldown_seconds()

    if now - last_spin < cooldown_sec:
        rem = cooldown_sec - (now - last_spin)
        hours, mins = rem // 3600, (rem % 3600) // 60
        secs = rem % 60
        if hours > 0:
            time_str = f"{hours} ч. {mins} мин."
        elif mins > 0:
            time_str = f"{mins} мин. {secs} сек."
        else:
            time_str = f"{secs} сек."
        return await message.reply(f"⏳ Перезарядка! Следующий танк через **{time_str}**", parse_mode="Markdown")

    weights_list = [w for _, _, _, _, _, _, w in all_cards]
    chosen_list = random.choices(all_cards, weights=weights_list, k=1)
    card_id, name, nation, rarity, pts, file_id, _ = chosen_list.pop()

    cur.execute("UPDATE users SET last_spin = ?, points = points + ? WHERE user_id = ?", (now, pts, uid))
    cur.execute("INSERT INTO inventory (user_id, card_id) VALUES (?, ?)", (uid, card_id))
    conn.commit()

    caption = (
        f"🎖 **Новая боевая машина!**\n\n"
        f"🚜 **Техника:** {name}\n"
        f"🌍 **Нация:** {nation}\n"
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
    points, = cur.fetchone()

    cur.execute("""
        SELECT c.name, c.nation, c.rarity, COUNT(i.card_id)
        FROM inventory i JOIN cards c ON i.card_id = c.id
        WHERE i.user_id = ? GROUP BY c.id
    """, (uid,))
    rows = cur.fetchall() 
    inv_lines = [f"• **{name}** [{nation}] ({rarity}) — {cnt} шт." for name, nation, rarity, cnt in rows]
    inv_text = "\n".join(inv_lines) or "Пока пусто. Напишите «танк»!"

    text = f"👤 **Танкист:** {message.from_user.first_name}\n🏆 **Очки:** {points}\n\n🚜 **Ваш ангар:**\n{inv_text}"
    await message.reply(text, parse_mode="Markdown")

# Топ игроков
@dp.message(Command("top"))
@dp.message(F.text.lower() == "топ")
async def top_players(message: Message):
    cur.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10")
    rows = cur.fetchall()
    top_lines = [f"{i+1}. **{uname}** — {pts} очк." for i, (uname, pts) in enumerate(rows)]
    top_text = "\n".join(top_lines) or "Рейтинг пуст."
    await message.reply(f"🏆 **Топ-10 танкистов:**\n\n{top_text}", parse_mode="Markdown")

async def main():
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
