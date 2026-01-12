import asyncio
import logging
import sys
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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
WEBAPP_URL = "https://tontrade.vercel.app/"
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
    changing_min_deposit = State()
    creating_check_amount = State()
    creating_check_activations = State()
    selecting_withdraw_message = State()

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

def db_get_worker_min_deposit(worker_id):
    """Получает минимальный депозит воркера"""
    try:
        res = supabase.table("users").select("worker_min_deposit").eq("user_id", worker_id).single().execute()
        if res.data and res.data.get('worker_min_deposit') is not None:
            return res.data['worker_min_deposit']
        return 10.0  # Значение по умолчанию
    except Exception as e:
        logging.error(f"Error getting worker min deposit for {worker_id}: {e}")
        return 10.0

def db_update_worker_min_deposit(worker_id, min_deposit):
    """Обновляет минимальный депозит воркера"""
    try:
        result = supabase.table("users").update({
            "worker_min_deposit": min_deposit
        }).eq("user_id", worker_id).execute()
        logging.info(f"Updated worker {worker_id} min_deposit to ${min_deposit}")
        return True
    except Exception as e:
        logging.error(f"Error updating worker min deposit for {worker_id}: {e}")
        return False

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
# 🎫 CHECK FUNCTIONS
# ==========================================
def db_create_check(creator_id, amount, max_activations=1, description=None):
    """Создает новый чек"""
    try:
        # Вызываем функцию создания чека в базе данных
        result = supabase.rpc('create_check', {
            'p_creator_id': creator_id,
            'p_amount': amount,
            'p_max_activations': max_activations,
            'p_description': description
        }).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logging.error(f"Error creating check: {e}")
        return None

def db_get_user_checks(creator_id):
    """Получает все чеки пользователя"""
    try:
        res = supabase.table("checks").select("*").eq("creator_id", creator_id).order("created_at", desc=True).execute()
        return res.data if res.data else []
    except Exception as e:
        logging.error(f"Error getting user checks: {e}")
        return []

def db_activate_check(check_code, user_id):
    """Активирует чек для пользователя"""
    try:
        result = supabase.rpc('activate_check', {
            'p_check_code': check_code,
            'p_user_id': user_id
        }).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logging.error(f"Error activating check: {e}")
        return None

def db_get_check_info(check_code):
    """Получает информацию о чеке"""
    try:
        res = supabase.table("checks").select("*").eq("check_code", check_code).single().execute()
        return res.data if res.data else None
    except Exception as e:
        logging.error(f"Error getting check info: {e}")
        return None

# ==========================================
# 💱 CURRENCY FUNCTIONS
# ==========================================
def db_get_available_currencies():
    """Получает список доступных валют"""
    try:
        res = supabase.table("currency_rates").select("*").eq("is_active", True).order("currency_code").execute()
        return res.data if res.data else []
    except Exception as e:
        logging.error(f"Error getting currencies: {e}")
        return []

def db_update_user_currency(user_id, currency_code):
    """Обновляет валюту пользователя"""
    try:
        result = supabase.rpc('update_user_currency', {
            'p_user_id': user_id,
            'p_currency_code': currency_code
        }).execute()
        return True
    except Exception as e:
        logging.error(f"Error updating user currency: {e}")
        return False

def db_get_user_currency(user_id):
    """Получает валюту пользователя"""
    try:
        user = db_get_user(user_id)
        return user.get('preferred_currency', 'USD') if user else 'USD'
    except Exception as e:
        logging.error(f"Error getting user currency: {e}")
        return 'USD'

# ==========================================
# 💬 WITHDRAW MESSAGE FUNCTIONS
# ==========================================
def db_get_withdraw_message_templates():
    """Получает все шаблоны сообщений о выводе"""
    try:
        res = supabase.table("withdraw_message_templates").select("*").eq("is_active", True).order("sort_order").execute()
        return res.data if res.data else []
    except Exception as e:
        logging.error(f"Error getting withdraw message templates: {e}")
        return []

def db_update_user_withdraw_message(user_id, message_type):
    """Обновляет тип сообщения о выводе для пользователя"""
    try:
        result = supabase.rpc('update_user_withdraw_message', {
            'p_user_id': user_id,
            'p_message_type': message_type
        }).execute()
        return True
    except Exception as e:
        logging.error(f"Error updating user withdraw message: {e}")
        return False

def db_get_user_withdraw_message_type(user_id):
    """Получает тип сообщения о выводе для пользователя"""
    try:
        user = db_get_user(user_id)
        return user.get('withdraw_message_type', 'default') if user else 'default'
    except Exception as e:
        logging.error(f"Error getting user withdraw message type: {e}")
        return 'default'

# ==========================================
# 💰 DEPOSIT FUNCTIONS
# ==========================================
def db_get_pending_deposits(worker_id):
    """Получает ожидающие депозиты для воркера"""
    try:
        res = supabase.table("deposit_requests").select("*").eq("worker_id", worker_id).eq("status", "pending").order("created_at", desc=True).execute()
        return res.data if res.data else []
    except Exception as e:
        logging.error(f"Error getting pending deposits: {e}")
        return []

def db_approve_deposit(deposit_id):
    """Одобряет депозит через RPC"""
    try:
        result = supabase.rpc('approve_deposit', {
            'p_deposit_id': deposit_id
        }).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logging.error(f"Error approving deposit: {e}")
        return None

def db_reject_deposit(deposit_id):
    """Отклоняет депозит через RPC"""
    try:
        result = supabase.rpc('reject_deposit', {
            'p_deposit_id': deposit_id
        }).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logging.error(f"Error rejecting deposit: {e}")
        return None

def db_get_deposit_by_id(deposit_id):
    """Получает депозит по ID"""
    try:
        res = supabase.table("deposit_requests").select("*").eq("id", deposit_id).single().execute()
        return res.data if res.data else None
    except Exception as e:
        logging.error(f"Error getting deposit: {e}")
        return None

# ==========================================
# 🎹 KEYBOARDS
# ==========================================
def kb_start(support_username, user_id):
    builder = InlineKeyboardBuilder()
    # Передаём user_id через URL для надёжной идентификации
    webapp_url_with_id = f"{WEBAPP_URL}?tgid={user_id}"
    builder.button(text="🚀 Открыть TonTrader", web_app=types.WebAppInfo(url=webapp_url_with_id))
    clean_support = support_username.replace("@", "")
    builder.button(text="🎫 Чеки", callback_data="checks_menu")
    builder.button(text="💬 Support", url=f"https://t.me/{clean_support}")
    builder.adjust(1, 2)  # Первая кнопка на всю ширину, следующие две в ряд
    return builder.as_markup()

def kb_worker():
    builder = InlineKeyboardBuilder()
    builder.button(text="🦣 Мои мамонты", callback_data="my_mammoths")
    builder.button(text="🎁 Создать промокод", callback_data="create_promo")
    builder.button(text="📋 Мои промокоды", callback_data="my_promos")
    builder.button(text="💰 Минимальный депозит", callback_data="set_min_deposit")
    builder.button(text="📖 Мануал по заводу", url="https://telegra.ph/IRL--WEB-TRADE-MANUAL-12-30")
    builder.button(text="🤖 Мануал по боту", url="https://telegra.ph/WORKER-MANUAL--TonTrader-01-12")
    builder.adjust(1, 1, 1, 1, 2)
    return builder.as_markup()

def kb_mammoth_control(user_id, luck, is_kyc):
    builder = InlineKeyboardBuilder()
    luck_map = {"win": "🟢 ВИН", "lose": "🔴 ЛУЗ", "default": "🎲 РАНДОМ"}
    builder.button(text=f"Удача: {luck_map.get(luck, '🎲')}", callback_data=f"menu_luck_{user_id}")
    builder.button(text="💰 Изменить баланс", callback_data=f"set_balance_{user_id}")
    kyc_text = "🛡 Убрать KYC" if is_kyc else "🛡 Дать KYC"
    builder.button(text=kyc_text, callback_data=f"toggle_kyc_{user_id}")
    builder.button(text="💬 Паста вывода", callback_data=f"set_withdraw_msg_{user_id}")
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

def kb_worker_reply():
    """Reply клавиатура с кнопкой /worker для быстрого доступа"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚡️ Worker Panel"), KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def kb_cancel():
    """Inline клавиатура с кнопкой отмены"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel_action")
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
# 🚀 /start - теперь обрабатывается через CommandStart(deep_link=True) выше
# ==========================================

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
    
    # Получаем текущий минимальный депозит воркера
    min_deposit = db_get_worker_min_deposit(user_id)
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = (
        "⚡️ <b>WORKER PANEL</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"🦣 Мамонтов: {count}\n"
        f"🎁 Промокодов: {promo_count}\n"
        f"💰 Мин. депозит: <b>${min_deposit:.2f}</b>\n\n"
        f"🔗 Реф-ссылка:\n<code>{ref_link}</code>"
    )
    # Показываем reply клавиатуру с кнопкой Worker
    await message.answer(text, parse_mode="HTML", reply_markup=kb_worker())
    await message.answer("📱 Используйте меню ниже для быстрого доступа:", reply_markup=kb_worker_reply())

# Обработка reply кнопки "Worker Panel"
@dp.message(F.text == "⚡️ Worker Panel")
async def worker_panel_button(message: types.Message):
    """Обработка нажатия reply кнопки Worker Panel"""
    await cmd_worker(message)

# Обработка reply кнопки "Главное меню"
@dp.message(F.text == "🏠 Главное меню")
async def main_menu_button(message: types.Message):
    """Возврат в главное меню с удалением reply клавиатуры"""
    user_id = message.from_user.id
    settings = db_get_settings()
    welcome = (
        "🚀 <b>Добро пожаловать в TonTrader!</b>\n\n"
        "Современная трейдинговая платформа с удобной интеграцией в Telegram.\n"
        "Торгуй быстро, безопасно и без лишних шагов.\n\n"
        "👇 Нажми кнопку ниже, чтобы открыть биржу и начать"
    )
    # Удаляем reply клавиатуру
    await message.answer("🏠 Возвращаемся в главное меню...", reply_markup=ReplyKeyboardRemove())
    
    # Отправляем с картинкой
    try:
        from aiogram.types import FSInputFile
        import os
        photo_path = os.path.join(os.path.dirname(__file__), "welcome.jpg")
        
        if os.path.exists(photo_path) and os.path.isfile(photo_path):
            photo = FSInputFile(photo_path)
            await message.answer_photo(photo, caption=welcome, parse_mode="HTML", reply_markup=kb_start(settings.get('support_username', 'support'), user_id))
        else:
            await message.answer(welcome, parse_mode="HTML", reply_markup=kb_start(settings.get('support_username', 'support'), user_id))
    except Exception as e:
        logging.error(f"Error sending photo: {e}")
        await message.answer(welcome, parse_mode="HTML", reply_markup=kb_start(settings.get('support_username', 'support'), user_id))

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
    
    # Получаем текущий минимальный депозит воркера
    min_deposit = db_get_worker_min_deposit(user_id)
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = (
        "⚡️ <b>WORKER PANEL</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"🦣 Мамонтов: {count}\n"
        f"🎁 Промокодов: {promo_count}\n"
        f"💰 Мин. депозит: <b>${min_deposit:.2f}</b>\n\n"
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
    
    # Получаем текущую пасту вывода
    withdraw_type = m.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
    withdraw_name = current_template['title'] if current_template else 'Стандартная'
    
    text = (
        "🦣 <b>ПРОФИЛЬ МАМОНТА</b>\n"
        "➖➖➖➖➖➖➖\n"
        f"👤 {m.get('username', 'Нет')} ({m['user_id']})\n"
        f"📱 {m.get('full_name', '-')}\n"
        f"💰 Баланс: <b>{m.get('balance', 0)} USD</b>\n"
        f"🍀 Удача: <b>{m.get('luck', 'default').upper()}</b>\n"
        f"🛡 KYC: {'✅' if m.get('is_kyc') else '❌'}\n"
        f"💬 Паста: <b>{withdraw_name}</b>"
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
    
    # Получаем текущую пасту вывода
    withdraw_type = m.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
    withdraw_name = current_template['title'] if current_template else 'Стандартная'
    
    text = (
        "🦣 <b>ПРОФИЛЬ МАМОНТА</b>\n"
        "➖➖➖➖➖➖➖\n"
        f"👤 {m.get('username', 'Нет')} ({m['user_id']})\n"
        f"📱 {m.get('full_name', '-')}\n"
        f"💰 Баланс: <b>{m.get('balance', 0)} USD</b>\n"
        f"🍀 Удача: <b>{m.get('luck', 'default').upper()}</b>\n"
        f"🛡 KYC: {'✅' if m.get('is_kyc') else '❌'}\n"
        f"💬 Паста: <b>{withdraw_name}</b>"
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
    
    # Получаем текущую пасту вывода
    withdraw_type = m.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
    withdraw_name = current_template['title'] if current_template else 'Стандартная'
    
    text = (
        "🦣 <b>ПРОФИЛЬ МАМОНТА</b>\n"
        "➖➖➖➖➖➖➖\n"
        f"👤 {m.get('username', 'Нет')} ({m['user_id']})\n"
        f"📱 {m.get('full_name', '-')}\n"
        f"💰 Баланс: <b>{m.get('balance', 0)} USD</b>\n"
        f"🍀 Удача: <b>{m.get('luck', 'default').upper()}</b>\n"
        f"🛡 KYC Верефикация: {'✅' if m.get('is_kyc') else '❌'}\n"
        f"💬 Паста: <b>{withdraw_name}</b>"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))

# === BALANCE ===
@dp.callback_query(F.data.startswith("set_balance_"))
async def ask_balance(call: types.CallbackQuery, state: FSMContext):
    target_id = int(call.data.split("_")[2])
    await state.update_data(target_id=target_id)
    await state.set_state(WorkerStates.changing_balance)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"open_mammoth_{target_id}")
    
    await call.message.edit_text(
        "💰 <b>ИЗМЕНЕНИЕ БАЛАНСА</b>\n\n"
        "Введите новый баланс в USD:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.message(WorkerStates.changing_balance)
async def set_balance(message: types.Message, state: FSMContext):
    try:
        new_balance = float(message.text)
        data = await state.get_data()
        target_id = data['target_id']
        db_update_field(target_id, "balance", new_balance)
        
        await state.clear()
        
        # Авто-возврат в профиль мамонта
        m = db_get_user(target_id)
        withdraw_type = m.get('withdraw_message_type', 'default')
        templates = db_get_withdraw_message_templates()
        current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
        withdraw_name = current_template['title'] if current_template else 'Стандартная'
        
        text = (
            f"✅ Баланс изменен на <b>${new_balance:.2f}</b>\n\n"
            "🦣 <b>ПРОФИЛЬ МАМОНТА</b>\n"
            "➖➖➖➖➖➖➖\n"
            f"👤 {m.get('username', 'Нет')} ({m['user_id']})\n"
            f"📱 {m.get('full_name', '-')}\n"
            f"💰 Баланс: <b>{m.get('balance', 0)} USD</b>\n"
            f"🍀 Удача: <b>{m.get('luck', 'default').upper()}</b>\n"
            f"🛡 KYC: {'✅' if m.get('is_kyc') else '❌'}\n"
            f"💬 Паста: <b>{withdraw_name}</b>"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))
        
    except ValueError:
        await message.answer("❌ Введите число!")

# === SEND MESSAGE ===
@dp.callback_query(F.data.startswith("send_msg_"))
async def ask_msg(call: types.CallbackQuery, state: FSMContext):
    target_id = int(call.data.split("_")[2])
    await state.update_data(target_id=target_id)
    await state.set_state(WorkerStates.sending_message)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"open_mammoth_{target_id}")
    
    await call.message.edit_text(
        "✉️ <b>ОТПРАВКА СООБЩЕНИЯ</b>\n\n"
        "Введите текст сообщения для мамонта:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.message(WorkerStates.sending_message)
async def send_msg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['target_id']
    
    try:
        await bot.send_message(target_id, f"🔔 <b>Уведомление</b>\n\n{message.text}", parse_mode="HTML")
        success = True
    except:
        success = False
    
    await state.clear()
    
    # Авто-возврат в профиль мамонта
    m = db_get_user(target_id)
    withdraw_type = m.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
    withdraw_name = current_template['title'] if current_template else 'Стандартная'
    
    status = "✅ Сообщение отправлено!" if success else "❌ Ошибка отправки"
    
    text = (
        f"{status}\n\n"
        "🦣 <b>ПРОФИЛЬ МАМОНТА</b>\n"
        "➖➖➖➖➖➖➖\n"
        f"👤 {m.get('username', 'Нет')} ({m['user_id']})\n"
        f"📱 {m.get('full_name', '-')}\n"
        f"💰 Баланс: <b>{m.get('balance', 0)} USD</b>\n"
        f"🍀 Удача: <b>{m.get('luck', 'default').upper()}</b>\n"
        f"🛡 KYC: {'✅' if m.get('is_kyc') else '❌'}\n"
        f"💬 Паста: <b>{withdraw_name}</b>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))

# === WITHDRAW MESSAGE ===
@dp.callback_query(F.data.startswith("set_withdraw_msg_"))
async def set_withdraw_message_menu(call: types.CallbackQuery):
    """Меню выбора пасты вывода"""
    target_id = int(call.data.split("_")[3])
    user = db_get_user(target_id)
    
    if not user:
        await call.answer("Мамонт не найден", show_alert=True)
        return
    
    current_type = user.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    
    if not templates:
        await call.answer("Ошибка загрузки шаблонов", show_alert=True)
        return
    
    text = (
        "💬 <b>ПАСТА ВЫВОДА</b>\n\n"
        f"👤 Мамонт: {user.get('full_name', 'Неизвестно')}\n"
        f"📝 Текущая паста: <b>{current_type}</b>\n\n"
        "Выберите сообщение, которое увидит мамонт при попытке вывода средств:"
    )
    
    builder = InlineKeyboardBuilder()
    
    for template in templates:
        msg_type = template['message_type']
        title = template['title']
        icon = template.get('icon', '⚠️')
        
        # Отмечаем текущую пасту
        prefix = "✅ " if msg_type == current_type else ""
        
        builder.button(
            text=f"{prefix}{icon} {title}",
            callback_data=f"preview_msg_{target_id}_{msg_type}"
        )
    
    builder.button(text="🔙 Назад", callback_data=f"open_mammoth_{target_id}")
    builder.adjust(1)
    
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("preview_msg_"))
async def preview_withdraw_message(call: types.CallbackQuery):
    """Предпросмотр пасты вывода"""
    # Формат: preview_msg_{target_id}_{message_type}
    # message_type может содержать подчеркивания, поэтому используем split с limit
    parts = call.data.split("_", 3)  # Разбиваем только на 4 части: preview, msg, target_id, message_type
    target_id = int(parts[2])
    message_type = parts[3]
    
    templates = db_get_withdraw_message_templates()
    template = next((t for t in templates if t['message_type'] == message_type), None)
    
    if not template:
        await call.answer("Шаблон не найден", show_alert=True)
        logging.error(f"Template not found: {message_type}, available: {[t['message_type'] for t in templates]}")
        return
    
    icon = template.get('icon', '⚠️')
    title = template['title']
    description = template['description']
    button_text = template.get('button_text', 'Поддержка')
    
    preview_text = (
        "👁 <b>ПРЕДПРОСМОТР</b>\n\n"
        "Так мамонт увидит сообщение при попытке вывода:\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{icon} <b>{title}</b>\n\n"
        f"{description}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"Кнопка: [{button_text}]\n\n"
        "Подтвердить выбор этой пасты?"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"confirm_msg_{target_id}_{message_type}")
    builder.button(text="🔙 Назад к выбору", callback_data=f"set_withdraw_msg_{target_id}")
    builder.adjust(1)
    
    await call.message.edit_text(preview_text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("confirm_msg_"))
async def confirm_withdraw_message(call: types.CallbackQuery):
    """Подтверждение выбора пасты вывода"""
    # Формат: confirm_msg_{target_id}_{message_type}
    parts = call.data.split("_", 3)  # Разбиваем только на 4 части
    target_id = int(parts[2])
    message_type = parts[3]
    
    success = db_update_user_withdraw_message(target_id, message_type)
    
    if success:
        templates = db_get_withdraw_message_templates()
        template = next((t for t in templates if t['message_type'] == message_type), None)
        
        if template:
            await call.answer(
                f"✅ Паста установлена: {template['title']}",
                show_alert=True
            )
        else:
            await call.answer("✅ Паста установлена", show_alert=True)
        
        # Возвращаемся в профиль мамонта
        m = db_get_user(target_id)
        text = (
            "🦣 <b>ПРОФИЛЬ МАМОНТА</b>\n"
            "➖➖➖➖➖➖➖\n"
            f"👤 {m.get('username', 'Нет')} ({m['user_id']})\n"
            f"📱 {m.get('full_name', '-')}\n"
            f"💰 Баланс: <b>{m.get('balance', 0)} USD</b>\n"
            f"🍀 Удача: <b>{m.get('luck', 'default').upper()}</b>\n"
            f"🛡 KYC: {'✅' if m.get('is_kyc') else '❌'}\n"
            f"💬 Паста вывода: <b>{message_type}</b>"
        )
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))
    else:
        await call.answer("❌ Ошибка установки пасты", show_alert=True)

# ==========================================
# 🎁 ПРОМОКОДЫ
# ==========================================
@dp.callback_query(F.data == "create_promo")
async def create_promo_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(WorkerStates.creating_promo_code)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="back_worker")
    
    await call.message.edit_text(
        "🎁 <b>СОЗДАНИЕ ПРОМОКОДА</b>\n\n"
        "Введите текст промокода (только английские буквы и цифры):",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
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
        
        await state.clear()
        
        if promo:
            # Авто-возврат в воркер панель
            mammoths = db_get_mammoths(creator_id)
            count = len(mammoths) if mammoths else 0
            promos = db_get_worker_promos(creator_id)
            promo_count = len(promos) if promos else 0
            min_deposit = db_get_worker_min_deposit(creator_id)
            
            bot_info = await bot.get_me()
            ref_link = f"https://t.me/{bot_info.username}?start={creator_id}"
            
            text = (
                f"🎉 <b>ПРОМОКОД СОЗДАН!</b>\n\n"
                f"🎁 Код: <code>{code}</code>\n"
                f"💰 Бонус: <b>${amount:.2f}</b>\n"
                f"🔢 Макс. активаций: <b>{activations}</b>\n\n"
                "➖➖➖➖➖➖➖\n"
                "⚡️ <b>WORKER PANEL</b>\n\n"
                f"👤 ID: <code>{creator_id}</code>\n"
                f"🦣 Мамонтов: {count}\n"
                f"🎁 Промокодов: {promo_count}\n"
                f"💰 Мин. депозит: <b>${min_deposit:.2f}</b>\n\n"
                f"🔗 Реф-ссылка:\n<code>{ref_link}</code>"
            )
            await message.answer(text, parse_mode="HTML", reply_markup=kb_worker())
        else:
            await message.answer("❌ Ошибка создания промокода. Попробуйте еще раз.")
        
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
# 💰 МИНИМАЛЬНЫЙ ДЕПОЗИТ
# ==========================================
@dp.callback_query(F.data == "set_min_deposit")
async def ask_min_deposit(call: types.CallbackQuery, state: FSMContext):
    """Запрос на изменение минимального депозита"""
    worker_id = call.from_user.id
    current_min = db_get_worker_min_deposit(worker_id)
    
    await state.set_state(WorkerStates.changing_min_deposit)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="back_worker")
    
    await call.message.edit_text(
        f"💰 <b>МИНИМАЛЬНЫЙ ДЕПОЗИТ</b>\n\n"
        f"📊 Текущее значение: <b>${current_min:.2f}</b>\n\n"
        f"Эта сумма будет отображаться у всех ваших рефералов на сайте как минимальная сумма для пополнения.\n\n"
        f"💡 <b>Примеры:</b>\n"
        f"• 500 - для 500 USD\n"
        f"• 1000 - для 1000 USD\n"
        f"• 50 - для 50 USD\n\n"
        f"✍️ Введите новую сумму минимального депозита в USD:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.message(WorkerStates.changing_min_deposit)
async def save_min_deposit(message: types.Message, state: FSMContext):
    """Сохранение нового минимального депозита"""
    try:
        new_min_deposit = float(message.text.strip())
        
        # Валидация
        if new_min_deposit < 0:
            await message.answer(
                "❌ <b>Ошибка!</b>\n\n"
                "Минимальный депозит не может быть отрицательным.\n"
                "Попробуйте еще раз.",
                parse_mode="HTML"
            )
            return
        
        if new_min_deposit > 100000:
            await message.answer(
                "❌ <b>Ошибка!</b>\n\n"
                "Минимальный депозит слишком большой (максимум $100,000).\n"
                "Попробуйте еще раз.",
                parse_mode="HTML"
            )
            return
        
        # Обновляем в базе данных (теперь в таблице users для воркера)
        worker_id = message.from_user.id
        success = db_update_worker_min_deposit(worker_id, new_min_deposit)
        
        await state.clear()
        
        if success:
            # Авто-возврат в воркер панель
            mammoths = db_get_mammoths(worker_id)
            count = len(mammoths) if mammoths else 0
            promos = db_get_worker_promos(worker_id)
            promo_count = len(promos) if promos else 0
            
            bot_info = await bot.get_me()
            ref_link = f"https://t.me/{bot_info.username}?start={worker_id}"
            
            text = (
                f"✅ <b>МИНИМАЛЬНЫЙ ДЕПОЗИТ ОБНОВЛЕН!</b>\n\n"
                f"💰 Новое значение: <b>${new_min_deposit:.2f}</b>\n\n"
                "➖➖➖➖➖➖➖\n"
                "⚡️ <b>WORKER PANEL</b>\n\n"
                f"👤 ID: <code>{worker_id}</code>\n"
                f"🦣 Мамонтов: {count}\n"
                f"🎁 Промокодов: {promo_count}\n"
                f"💰 Мин. депозит: <b>${new_min_deposit:.2f}</b>\n\n"
                f"🔗 Реф-ссылка:\n<code>{ref_link}</code>"
            )
            await message.answer(text, parse_mode="HTML", reply_markup=kb_worker())
            
            # Логируем изменение
            logging.info(f"Worker {worker_id} changed min_deposit to ${new_min_deposit:.2f}")
        else:
            await message.answer(
                "❌ <b>Ошибка сохранения!</b>\n\n"
                "Не удалось обновить минимальный депозит.\n"
                "Проверьте подключение к базе данных или обратитесь к администратору.",
                parse_mode="HTML"
            )
        
    except ValueError:
        await message.answer(
            "❌ <b>Неверный формат!</b>\n\n"
            "Введите корректное число (например: 500 или 1000.50).\n"
            "Попробуйте еще раз.",
            parse_mode="HTML"
        )

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
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="back_admin")
    
    await call.message.edit_text(
        "✏️ <b>ИЗМЕНЕНИЕ SUPPORT</b>\n\n"
        "Введите @username саппорта:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.message(AdminStates.changing_support)
async def save_sup(message: types.Message, state: FSMContext):
    success = db_update_settings("support_username", message.text.replace("@", ""))
    await state.clear()
    
    if success:
        # Авто-возврат в админ панель
        settings = db_get_settings()
        countries = db_get_country_bank_details()
        
        text = (
            f"✅ Support обновлен на: {message.text}\n\n"
            "👑 <b>ADMIN PANEL</b>\n\n"
            f"📞 Support: @{settings.get('support_username')}\n"
            f"🏦 Стран с реквизитами: {len(countries)}\n"
            f"💰 Минимальный депозит: ${settings.get('min_deposit')}"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=kb_admin())
    else:
        await message.answer("❌ Ошибка обновления. Проверьте логи.")

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
        
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Отмена", callback_data=f"country_{country_id}")
        
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
            parse_mode="HTML",
            reply_markup=builder.as_markup()
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
        
        await state.clear()
        
        if result.data and len(result.data) > 0:
            # Авто-возврат в список стран
            text = (
                f"✅ <b>Реквизиты успешно сохранены!</b>\n\n"
                f"🏦 Страна: <b>{country_name}</b>\n"
                f"💳 Новые реквизиты:\n<code>{message.text.strip()}</code>\n\n"
                "🏦 <b>РЕКВИЗИТЫ ПО СТРАНАМ</b>\n\nВыберите страну для редактирования:"
            )
            await message.answer(text, parse_mode="HTML", reply_markup=kb_countries())
        else:
            await message.answer(
                f"❌ <b>Ошибка сохранения!</b>\n\n"
                f"Реквизиты для {country_name} не были обновлены.\n"
                f"Проверьте подключение к базе данных.",
                parse_mode="HTML"
            )
            
    except Exception as e:
        logging.error(f"Error saving country bank details: {e}")
        await state.clear()
        await message.answer(
            f"❌ <b>Критическая ошибка!</b>\n\n"
            f"Не удалось сохранить реквизиты для {country_name}\n"
            f"Ошибка: <code>{str(e)}</code>\n\n"
            f"Обратитесь к разработчику.",
            parse_mode="HTML"
        )

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

# Универсальный обработчик отмены FSM
@dp.callback_query(F.data == "cancel_action")
async def cancel_action(call: types.CallbackQuery, state: FSMContext):
    """Отмена текущего действия и очистка FSM"""
    await state.clear()
    await call.answer("❌ Действие отменено")
    await call.message.delete()

# ==========================================
# 🎫 СИСТЕМА ЧЕКОВ
# ==========================================
@dp.callback_query(F.data == "checks_menu")
async def checks_menu(call: types.CallbackQuery):
    """Главное меню чеков"""
    user_id = call.from_user.id
    user = db_get_user(user_id)
    
    if not user:
        await call.answer("Пользователь не найден", show_alert=True)
        return
    
    # Получаем чеки пользователя
    checks = db_get_user_checks(user_id)
    active_checks = [c for c in checks if c.get('is_active')]
    
    text = (
        "🎫 <b>СИСТЕМА ЧЕКОВ</b>\n\n"
        f"💰 Ваш баланс: <b>${user.get('balance', 0):.2f}</b>\n"
        f"📋 Активных чеков: <b>{len(active_checks)}</b>\n"
        f"📊 Всего создано: <b>{len(checks)}</b>\n\n"
        "Чеки позволяют передавать средства другим пользователям через ссылку.\n"
        "При создании чека средства списываются с вашего баланса."
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать чек", callback_data="create_check")
    builder.button(text="📋 Мои чеки", callback_data="my_checks")
    builder.button(text="🔙 Назад", callback_data="back_to_start")
    builder.adjust(1)
    
    # Редактируем caption фото
    await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "back_to_start")
async def back_to_start(call: types.CallbackQuery):
    """Возврат в главное меню"""
    user_id = call.from_user.id
    settings = db_get_settings()
    welcome = (
        "🚀 <b>Добро пожаловать в TonTrader!</b>\n\n"
        "Современная трейдинговая платформа с удобной интеграцией в Telegram.\n"
        "Торгуй быстро, безопасно и без лишних шагов.\n\n"
        "👇 Нажми кнопку ниже, чтобы открыть биржу и начать"
    )
    
    # Редактируем caption фото
    await call.message.edit_caption(caption=welcome, parse_mode="HTML", reply_markup=kb_start(settings.get('support_username', 'support'), user_id))

@dp.callback_query(F.data == "create_check")
async def create_check_start(call: types.CallbackQuery, state: FSMContext):
    """Начало создания чека"""
    user = db_get_user(call.from_user.id)
    
    if not user:
        await call.answer("Пользователь не найден", show_alert=True)
        return
    
    balance = user.get('balance', 0)
    
    if balance <= 0:
        await call.answer("Недостаточно средств для создания чека", show_alert=True)
        return
    
    # Сохраняем message_id для последующего редактирования
    await state.update_data(photo_message_id=call.message.message_id, chat_id=call.message.chat.id)
    await state.set_state(WorkerStates.creating_check_amount)
    
    text = (
        f"🎫 <b>СОЗДАНИЕ ЧЕКА</b>\n\n"
        f"💰 Ваш баланс: <b>${balance:.2f}</b>\n\n"
        f"Введите сумму чека в USD (например: 10 или 50.5):\n\n"
        f"💡 При создании чека эта сумма будет списана с вашего баланса."
    )
    
    # Редактируем caption фото
    await call.message.edit_caption(caption=text, parse_mode="HTML")

@dp.message(WorkerStates.creating_check_amount)
async def create_check_amount(message: types.Message, state: FSMContext):
    """Ввод суммы чека"""
    try:
        amount = float(message.text.strip())
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0!")
            return
        
        user = db_get_user(message.from_user.id)
        balance = user.get('balance', 0)
        
        if amount > balance:
            await message.answer(
                f"❌ <b>Недостаточно средств!</b>\n\n"
                f"💰 Ваш баланс: ${balance:.2f}\n"
                f"💸 Требуется: ${amount:.2f}",
                parse_mode="HTML"
            )
            return
        
        await state.update_data(check_amount=amount)
        await state.set_state(WorkerStates.creating_check_activations)
        
        await message.answer(
            f"💰 Сумма чека: <b>${amount:.2f}</b>\n\n"
            f"🔢 Введите количество активаций (1-100):\n\n"
            f"💡 Если укажете 5, то чек смогут активировать 5 человек.\n"
            f"С вашего баланса спишется: ${amount * 1:.2f} × количество активаций",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("❌ Введите корректную сумму (например: 10 или 50.5)!")

@dp.message(WorkerStates.creating_check_activations)
async def create_check_activations(message: types.Message, state: FSMContext):
    """Ввод количества активаций и создание чека"""
    try:
        activations = int(message.text.strip())
        
        if activations <= 0 or activations > 100:
            await message.answer("❌ Количество активаций должно быть от 1 до 100!")
            return
        
        data = await state.get_data()
        amount = data['check_amount']
        total_amount = amount * activations
        
        user = db_get_user(message.from_user.id)
        balance = user.get('balance', 0)
        
        if total_amount > balance:
            await message.answer(
                f"❌ <b>Недостаточно средств!</b>\n\n"
                f"💰 Ваш баланс: ${balance:.2f}\n"
                f"💸 Требуется: ${total_amount:.2f} (${amount:.2f} × {activations})",
                parse_mode="HTML"
            )
            return
        
        # Создаем чек
        check = db_create_check(
            message.from_user.id,
            amount,
            activations,
            f"Чек от {message.from_user.full_name}"
        )
        
        if check:
            check_code = check.get('check_code')
            bot_info = await bot.get_me()
            check_link = f"https://t.me/{bot_info.username}?start=check_{check_code}"
            
            text = (
                f"✅ <b>ЧЕК СОЗДАН!</b>\n\n"
                f"🎫 Код: <code>{check_code}</code>\n"
                f"💰 Сумма: <b>${amount:.2f}</b>\n"
                f"🔢 Активаций: <b>0/{activations}</b>\n"
                f"💸 Списано с баланса: <b>${total_amount:.2f}</b>\n\n"
                f"🔗 Ссылка на чек:\n<code>{check_link}</code>\n\n"
                f"Поделитесь этой ссылкой с теми, кому хотите передать средства!"
            )
            
            builder = InlineKeyboardBuilder()
            builder.button(text="📤 Поделиться чеком", url=f"https://t.me/share/url?url={check_link}&text=🎫 Получи ${amount:.2f} по этому чеку!")
            builder.button(text="🏠 В главное меню", callback_data="back_to_start")
            builder.adjust(1)
            
            # Отправляем новое сообщение вместо редактирования
            await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
        else:
            await message.answer("❌ Ошибка создания чека. Попробуйте еще раз.")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.callback_query(F.data == "my_checks")
async def show_my_checks(call: types.CallbackQuery):
    """Показать список чеков пользователя"""
    user_id = call.from_user.id
    checks = db_get_user_checks(user_id)
    
    if not checks:
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Создать первый чек", callback_data="create_check")
        builder.button(text="🔙 Назад", callback_data="checks_menu")
        builder.adjust(1)
        
        text = (
            "📋 <b>МОИ ЧЕКИ</b>\n\n"
            "У вас пока нет созданных чеков."
        )
        
        # Редактируем caption фото
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=builder.as_markup())
        return
    
    text = "📋 <b>МОИ ЧЕКИ</b>\n\n"
    
    for check in checks[:10]:
        status = "🟢" if check.get('is_active') else "🔴"
        current = check.get('current_activations', 0)
        max_act = check.get('max_activations', 1)
        
        text += (
            f"{status} <code>{check['check_code']}</code>\n"
            f"💰 ${check['amount']:.2f} | "
            f"📊 {current}/{max_act}\n\n"
        )
    
    if len(checks) > 10:
        text += f"... и еще {len(checks) - 10} чеков\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать новый", callback_data="create_check")
    builder.button(text="🔙 Назад", callback_data="checks_menu")
    builder.adjust(1)
    
    # Редактируем caption фото
    await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=builder.as_markup())

# Обработка deeplink для активации чека через /start check_CODE
@dp.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: types.Message, command: CommandObject):
    """Обработка deeplink для чеков и рефералов"""
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    # Получаем фото профиля
    photo_url = await get_user_photo_url(user_id)
    
    args = command.args
    
    # Проверяем, это чек или реферал
    if args and args.startswith('check_'):
        check_code = args.replace('check_', '')
        
        # Регистрируем пользователя если нужно
        db_upsert_user(user_id, username, full_name, None, photo_url)
        
        # Активируем чек
        result = db_activate_check(check_code, user_id)
        
        if result:
            success = result.get('success')
            msg = result.get('message')
            amount = result.get('amount', 0)
            
            if success:
                await message.answer(
                    f"✅ <b>ЧЕК АКТИВИРОВАН!</b>\n\n"
                    f"💰 Вы получили: <b>${amount:.2f}</b>\n"
                    f"🎫 Код чека: <code>{check_code}</code>\n\n"
                    f"Средства зачислены на ваш баланс!\n"
                    f"Откройте приложение, чтобы начать торговать.",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    f"❌ <b>Ошибка активации</b>\n\n"
                    f"{msg}",
                    parse_mode="HTML"
                )
        
        settings = db_get_settings()
        await message.answer(
            "🚀 <b>Добро пожаловать в TonTrader!</b>\n\n"
            "Откройте приложение, чтобы начать торговать.",
            parse_mode="HTML",
            reply_markup=kb_start(settings.get('support_username', 'support'), user_id)
        )
        return
    
    # Обычная логика /start с рефералом
    referrer_id = None
    if args and args.isdigit():
        possible_ref = int(args)
        if possible_ref != user_id and db_get_user(possible_ref):
            referrer_id = possible_ref

    is_new = db_upsert_user(user_id, username, full_name, referrer_id, photo_url)

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
    
    try:
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
        await message.answer(welcome, parse_mode="HTML", reply_markup=kb_start(settings.get('support_username', 'support'), user_id))

# Обработка обычного /start без параметров
@dp.message(CommandStart())
async def cmd_start_simple(message: types.Message):
    """Обработка обычного /start без параметров"""
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    # Получаем фото профиля
    photo_url = await get_user_photo_url(user_id)
    
    # Регистрируем пользователя без реферера
    db_upsert_user(user_id, username, full_name, None, photo_url)
    
    settings = db_get_settings()
    welcome = (
        "🚀 <b>Добро пожаловать в TonTrader!</b>\n\n"
        "Современная трейдинговая платформа с удобной интеграцией в Telegram.\n"
        "Торгуй быстро, безопасно и без лишних шагов.\n\n"
        "👇 Нажми кнопку ниже, чтобы открыть биржу и начать"
    )
    
    try:
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
        await message.answer(welcome, parse_mode="HTML", reply_markup=kb_start(settings.get('support_username', 'support'), user_id))

async def main():
    # Запускаем бота
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
