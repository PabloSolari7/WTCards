import asyncio
import random
import sqlite3
import time
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton


# --- ВСТАВЬТЕ ВАШИ ДАННЫЕ НИЖЕ ---
TOKEN = "9201193460:AAH_ip4vvxrotIRNKNxjQF6His3TeLu-X4I"
ADMIN_ID = 1563482370  # СЮДА ВСТАВЬТЕ ВАШ ID (БЕЗ КАВЫЧЕК!)
DEFAULT_COOLDOWN = 30 # Перезарядка по умолчанию (в минутах)
BP_STEP = 20000    # Сколько очков нужно на каждый уровень БП (20000, 40000, 60000...)
BP_MAX_LEVEL = 30  # Максимальный уровень боевого пропуска
#--------------------------------

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

try:
  cur.execute("ALTER TABLE users ADD COLUMN claimed_bp INTEGER DEFAULT 0")
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

def get_bp_info(points: int):
    level = min(points // BP_STEP, BP_MAX_LEVEL)
    if level >= BP_MAX_LEVEL:
        return BP_MAX_LEVEL, BP_MAX_LEVEL * BP_STEP, "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 (МАКС.)"
    
    next_lvl_pts = (level + 1) * BP_STEP
    current_in_lvl = points - (level * BP_STEP)
    filled = int((current_in_lvl / BP_STEP) * 10)
    bar = "🟩" * filled + "⬜️" * (10 - filled)
    return level, next_lvl_pts, bar

def claim_bp_rewards(uid: int, current_lvl: int):
  cur.execute("SELECT claimed_bp FROM users WHERE user_id = ?", (uid,))
  row = cur.fetchone()
  claimed = row[0] if row and row[0] is not None else 0

  if current_lvl <= claimed:
    return []

  cur.execute("SELECT id, name, nation, rarity FROM cards WHERE LOWER(rarity) LIKE '%редк%'")
  rares = cur.fetchall()

  cur.execute("SELECT id, name, nation, rarity FROM cards WHERE LOWER(rarity) LIKE '%эпич%'")
  epics = cur.fetchall()

  cur.execute("SELECT id, name, nation, rarity FROM cards WHERE LOWER(rarity) LIKE '%легенд%'")
  legs = cur.fetchall()

  cur.execute("SELECT id, name, nation, rarity FROM cards")
  all_c = cur.fetchall()
  if not all_c:
    return []
  if not rares:
    rares = all_c
  if not epics:
    epics = all_c
  if not legs:
    legs = all_c

  rewards_given = []

  for lvl in range(claimed + 1, current_lvl + 1):
    if lvl <= 5:
      card = random.choice(rares)
      tag = "🔵 РЕДКАЯ"
    elif lvl <= 15:
      card = random.choice(epics)
      tag = "🟣 ЭПИЧЕСКАЯ"
    else:
      card = random.choice(legs)
      tag = "🟡 ЛЕГЕНДАРНАЯ"
    
    cid, name, nation, rarity = card
    cur.execute("INSERT INTO inventory (user_id, card_id) VALUES (?, ?)", (uid, cid))
    rewards_given.append(f"• **Ур. {lvl}** ({tag}): {name} [{nation}]")

  cur.execute("UPDATE users SET claimed_bp = ? WHERE user_id = ?", (current_lvl, uid))
  conn.commit()
  return rewards_given

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
def build_list_page(page: int = 0):
  cur.execute("SELECT id, name, nation, rarity, points, weight FROM cards")
  rows = cur.fetchall()
  if not rows:
    return "База карточек пуста.", None

  per_page = 20
  total_pages = (len(rows) - 1) // per_page + 1
  page = max(0, min(page, total_pages - 1))

  start = page * per_page
  chunk = rows[start:start + per_page]

  lines = [
      f"🆔 {cid} — {name} [{nation}] ({rarity}) | +{pts} очк. | шанс: {weight}"
      for cid, name, nation, rarity, pts, weight in chunk
  ]
  text = f"📋 Список карточек (Стр. {page + 1}/{total_pages}, всего: {len(rows)}):\n\n" + "\n".join(lines)

  buttons = []
  if page > 0:
    buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"list_page:{page - 1}"))
  if page < total_pages - 1:
    buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"list_page:{page + 1}"))

  kb = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None
  return text, kb

# Просмотр списка всех карточек со страницами (ТОЛЬКО ДЛЯ АДМИНА)
@dp.message(Command("list"))
async def list_cards(message: Message):
  if message.from_user.id != ADMIN_ID:
    return
  text, kb = build_list_page(0)
  await message.reply(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("list_page:"))
async def cb_list_page(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return await callback.answer("Недоступно", show_alert=True)
  page = int(callback.data.split(":")[1])
  text, kb = build_list_page(page)
  await callback.message.edit_text(text, reply_markup=kb)
  await callback.answer()

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

  cur.execute("SELECT points FROM users WHERE user_id = ?", (uid,))
  old_pts, = cur.fetchone()
  old_lvl, _, _ = get_bp_info(old_pts)

  new_pts = old_pts + pts
  new_lvl, _, _ = get_bp_info(new_pts)

  cur.execute("UPDATE users SET last_spin = ?, points = ? WHERE user_id = ?", (now, new_pts, uid))
  cur.execute("INSERT INTO inventory (user_id, card_id) VALUES (?, ?)", (uid, card_id))
  conn.commit()

  lvl_up_text = ""
  if new_lvl > old_lvl:
    lvl_up_text = f"\n\n🎉 **НОВЫЙ УРОВЕНЬ БОЕВОГО ПРОПУСКА: {new_lvl} ур.!**"

  caption = (
      f"🎖 **Новая боевая машина!**\n\n"
      f"🚜 **Техника:** {name}\n"
      f"🌍 **Нация:** {nation}\n"
      f"✨ **Редкость:** {rarity}\n"
      f"🏆 **Очки:** +{pts}{lvl_up_text}"
  )
  await message.reply_photo(photo=file_id, caption=caption, parse_mode="Markdown")

RARITY_CONFIG = [
    ("common", "⚪️ Обычные", "%обыч%"),
    ("rare", "🔵 Редкие", "%редк%"),
    ("epic", "🟣 Эпические", "%эпич%"),
    ("legend", "🟡 Легендарные", "%легенд%")
]

def get_rarity_info(r_code: str):
  for code, label, pattern in RARITY_CONFIG:
    if code == r_code:
      return label, pattern
  return "⚪️ Обычные", "%обыч%"

def build_hangar_page(uid: int, first_name: str, page: int = 0):
  cur.execute("SELECT points FROM users WHERE user_id = ?", (uid,))
  points, = cur.fetchone()
  bp_lvl, next_pts, bp_bar = get_bp_info(points)

  cur.execute("""
      SELECT c.name, c.nation, c.rarity, COUNT(i.card_id)
      FROM inventory i JOIN cards c ON i.card_id = c.id
      WHERE i.user_id = ? GROUP BY c.id
  """, (uid,))
  rows = cur.fetchall()

  per_page = 10
  if not rows:
    inv_text = "Пока пусто. Напишите «танк»!"
    kb = None
    page_header = ""
  else:
    total_pages = (len(rows) - 1) // per_page + 1
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    chunk = rows[start:start + per_page]

    inv_lines = [f"• **{name}** [{nation}] ({rarity}) — {cnt} шт." for name, nation, rarity, cnt in chunk]
    inv_text = "\n".join(inv_lines)
    page_header = f" (Стр. {page + 1}/{total_pages})"

    nav_buttons = []
    if page > 0:
      nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"hangar_page:{uid}:{page - 1}"))
    if page < total_pages - 1:
      nav_buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"hangar_page:{uid}:{page + 1}"))

    kb_rows = []
    if nav_buttons:
      kb_rows.append(nav_buttons)
    kb_rows.append([InlineKeyboardButton(text="🖼 Посмотреть карточки", callback_data=f"rar_menu:{uid}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

  text = (
      f"👤 **Танкист:** {first_name}\n"
      f"🏆 **Очки:** {points}\n"
      f"🎖 **Боевой пропуск:** {bp_lvl}/{BP_MAX_LEVEL} ур. ({points}/{next_pts})\n"
      f"{bp_bar}\n\n"
      f"🚜 **Ваш ангар{page_header}:**\n{inv_text}"
  )
  return text, kb

def build_rarity_menu(uid: int):
  kb_rows = []
  for code, label, pattern in RARITY_CONFIG:
    cur.execute("""
        SELECT COUNT(DISTINCT c.id)
        FROM inventory i JOIN cards c ON i.card_id = c.id
        WHERE i.user_id = ? AND LOWER(c.rarity) LIKE ?
    """, (uid, pattern))
    cnt, = cur.fetchone()
    kb_rows.append([InlineKeyboardButton(text=f"{label} ({cnt} шт.)", callback_data=f"rar_list:{uid}:{code}:0")])

  kb_rows.append([InlineKeyboardButton(text="🔙 Вернуться в профиль", callback_data=f"hangar_back:{uid}")])
  kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
  text = "🗂 **Каталог вашей техники**\n\nВыберите редкость, чтобы открыть список машин:"
  return text, kb

def build_rarity_list_page(uid: int, r_code: str, page: int = 0):
  label, pattern = get_rarity_info(r_code)
  cur.execute("""
      SELECT c.id, c.name, c.nation, COUNT(i.card_id)
      FROM inventory i JOIN cards c ON i.card_id = c.id
      WHERE i.user_id = ? AND LOWER(c.rarity) LIKE ?
      GROUP BY c.id ORDER BY c.id ASC
  """, (uid, pattern))
  rows = cur.fetchall()

  if not rows:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К выбору редкости", callback_data=f"rar_menu:{uid}")]
    ])
    return f"{label}\n\nУ вас пока нет танков этой редкости.", kb

  per_page = 10
  total_pages = (len(rows) - 1) // per_page + 1
  page = max(0, min(page, total_pages - 1))
  start = page * per_page
  chunk = rows[start:start + per_page]

  lines = []
  kb_rows = []
  temp_row = []

  for idx, (cid, name, nation, cnt) in enumerate(chunk, start=start + 1):
    lines.append(f"{idx}. **{name}** [{nation}] — {cnt} шт.")
    btn_text = name if len(name) <= 18 else name[:16] + ".."
    temp_row.append(InlineKeyboardButton(text=f"🚜 {btn_text}", callback_data=f"view_card:{uid}:{r_code}:{page}:{cid}"))
    if len(temp_row) == 2:
      kb_rows.append(temp_row)
      temp_row = []

  if temp_row:
    kb_rows.append(temp_row)

  nav_buttons = []
  if page > 0:
    nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"rar_list:{uid}:{r_code}:{page - 1}"))
  if page < total_pages - 1:
    nav_buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"rar_list:{uid}:{r_code}:{page + 1}"))
  if nav_buttons:
    kb_rows.append(nav_buttons)

  kb_rows.append([InlineKeyboardButton(text="🔙 К выбору редкости", callback_data=f"rar_menu:{uid}")])
  kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

  text = (
      f"{label} (Стр. {page + 1}/{total_pages})\n"
      f"Нажмите на кнопку с названием танка, чтобы посмотреть карточку:\n\n" + "\n".join(lines)
  )
  return text, kb

# Профиль и ангар со страницами
@dp.message(Command("profile"))
@dp.message(F.text.lower().in_({"ангар", "профиль"}))
async def my_hangar(message: Message):
  uid = message.from_user.id
  register_user(uid, message.from_user.first_name)
  text, kb = build_hangar_page(uid, message.from_user.first_name, 0)
  await message.reply(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("hangar_page:"))
async def cb_hangar_page(callback: CallbackQuery):
  _, target_uid_str, page_str = callback.data.split(":")
  target_uid = int(target_uid_str)
  if callback.from_user.id != target_uid:
    return await callback.answer("Это ангар другого игрока!", show_alert=True)

  page = int(page_str)
  text, kb = build_hangar_page(target_uid, callback.from_user.first_name, page)
  await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
  await callback.answer()

@dp.callback_query(F.data.startswith("rar_menu:"))
async def cb_rar_menu(callback: CallbackQuery):
  _, target_uid_str = callback.data.split(":")
  target_uid = int(target_uid_str)
  if callback.from_user.id != target_uid:
    return await callback.answer("Это ангар другого игрока!", show_alert=True)

  text, kb = build_rarity_menu(target_uid)
  if callback.message.photo:
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
  else:
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
  await callback.answer()

@dp.callback_query(F.data.startswith("rar_list:"))
async def cb_rar_list(callback: CallbackQuery):
  _, target_uid_str, r_code, page_str = callback.data.split(":")
  target_uid = int(target_uid_str)
  if callback.from_user.id != target_uid:
    return await callback.answer("Это ангар другого игрока!", show_alert=True)

  page = int(page_str)
  text, kb = build_rarity_list_page(target_uid, r_code, page)
  if callback.message.photo:
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
  else:
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
  await callback.answer()

@dp.callback_query(F.data.startswith("view_card:"))
async def cb_view_card(callback: CallbackQuery):
  _, target_uid_str, r_code, page_str, cid_str = callback.data.split(":")
  target_uid = int(target_uid_str)
  if callback.from_user.id != target_uid:
    return await callback.answer("Это ангар другого игрока!", show_alert=True)

  cid = int(cid_str)
  cur.execute("""
      SELECT c.name, c.nation, c.rarity, c.points, c.file_id, COUNT(i.card_id)
      FROM inventory i JOIN cards c ON i.card_id = c.id
      WHERE i.user_id = ? AND c.id = ? GROUP BY c.id
  """, (target_uid, cid))
  row = cur.fetchone()
  if not row:
    return await callback.answer("Карточка не найдена!", show_alert=True)

  name, nation, rarity, pts, file_id, cnt = row
  caption = (
      f"🚜 **Техника:** {name}\n"
      f"🌍 **Нация:** {nation}\n"
      f"✨ **Редкость:** {rarity}\n"
      f"🏆 **Очки за карту:** +{pts}\n"
      f"📦 **В ангаре:** {cnt} шт."
  )
  kb = InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="🔙 Назад к списку", callback_data=f"rar_list:{target_uid}:{r_code}:{page_str}")]
  ])

  await callback.message.delete()
  await callback.message.answer_photo(photo=file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
  await callback.answer()

@dp.callback_query(F.data.startswith("hangar_back:"))
async def cb_hangar_back(callback: CallbackQuery):
  _, target_uid_str = callback.data.split(":")
  target_uid = int(target_uid_str)
  if callback.from_user.id != target_uid:
    return await callback.answer("Это ангар другого игрока!", show_alert=True)

  text, kb = build_hangar_page(target_uid, callback.from_user.first_name, 0)
  if callback.message.photo:
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
  else:
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
  await callback.answer()

# Топ игроков
@dp.message(Command("top"))
@dp.message(F.text.lower() == "топ")
async def top_players(message: Message):
    cur.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10")
    rows = cur.fetchall()
    top_lines = [f"{i+1}. {uname} — {pts} очк." for i, (uname, pts) in enumerate(rows)]
    top_text = "\n".join(top_lines) or "Рейтинг пуст."
    await message.reply(f"🏆 **Топ-10 танкистов:**\n\n{top_text}")

# Боевой пропуск
@dp.message(Command("bp"))
@dp.message(F.text.lower().in_({"бп", "пропуск", "боевой пропуск"}))
async def battle_pass(message: Message):
  uid = message.from_user.id
  register_user(uid, message.from_user.first_name)

  cur.execute("SELECT points, claimed_bp FROM users WHERE user_id = ?", (uid,))
  points, claimed = cur.fetchone()
  claimed = claimed or 0
  bp_lvl, next_pts, bp_bar = get_bp_info(points)

  if bp_lvl >= BP_MAX_LEVEL:
    status_text = "🏆 Вы достигли максимального 30 уровня Боевого пропуска!"
  else:
    need = next_pts - points
    status_text = f"До **{bp_lvl + 1} уровня** осталось: **{need} очк.**"

  unclaimed = max(0, bp_lvl - claimed)
  reward_hint = ""
  if unclaimed > 0:
    reward_hint = f"\n\n🎁 **Доступно наград для получения: {unclaimed} шт.!**\nНапишите **`забрать`**, чтобы открыть их!"

  text = (
      f"🎖 **БОЕВОЙ ПРОПУСК (Сезон 1)**\n\n"
      f"📊 **Ваш уровень:** {bp_lvl} из {BP_MAX_LEVEL}\n"
      f"💰 **Всего очков:** {points} / {next_pts}\n"
      f"{bp_bar}\n\n"
      f"{status_text}{reward_hint}"
  )
  await message.reply(text, parse_mode="Markdown")

# Получение наград Боевого пропуска
@dp.message(Command("claim"))
@dp.message(F.text.lower().in_({"забрать", "награда", "награды"}))
async def claim_bp(message: Message):
  uid = message.from_user.id
  register_user(uid, message.from_user.first_name)

  cur.execute("SELECT points FROM users WHERE user_id = ?", (uid,))
  points, = cur.fetchone()
  bp_lvl, _, _ = get_bp_info(points)

  rewards = claim_bp_rewards(uid, bp_lvl)
  if not rewards:
    return await message.reply("📭 У вас пока нет несобранных наград Боевого пропуска. Крутите танки, чтобы повысить уровень!")

  rewards_text = "\n".join(rewards)
  await message.reply(
      f"🎉 **Вы забрали награды Боевого пропуска!**\n\n"
      f"{rewards_text}\n\n"
      f"🚜 Все машины уже отправлены в ваш ангар!",
      parse_mode="Markdown"
  )


async def main():
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
