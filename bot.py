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
BOT_TOKEN = "7769124785:AAE46Zt6jh9IPVt4IB4u0j8kgEVg2NpSYa0"
ADMIN_IDS = [844012884, 8162019020]

SUPABASE_URL = "https://wzpywfedbowlosmvecos.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Ind6cHl3ZmVkYm93bG9zbXZlY29zIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYzNTAyMzksImV4cCI6MjA4MTkyNjIzOX0.TmAYsmA8iwSpLPKOHIZM7jf3GLE3oeT7wD-l0ALwBPw"

WEBAPP_URL = "https://tontrade.vercel.app/"
API_PORT = 8080

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
    entering_check_code = State()  # Ввод кода чека для активации

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
        user_data["preferred_currency"] = "RUB"  # Дефолтная валюта - рубли
        user_data["notifications_enabled"] = True
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
        return 10.0
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
        return True

# ==========================================
# 🎫 CHECK FUNCTIONS
# ==========================================
def db_create_check(creator_id, amount, max_activations=1, description=None):
    """Создает новый чек"""
    try:
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
# 🎹 KEYBOARDS - УЛУЧШЕННЫЕ
# ==========================================
def kb_start(support_username, user_id):
    """Главная клавиатура приветствия"""
    builder = InlineKeyboardBuilder()
    webapp_url_with_id = f"{WEBAPP_URL}?tgid={user_id}"
    builder.button(text="Открыть приложение", web_app=types.WebAppInfo(url=webapp_url_with_id))
    clean_support = support_username.replace("@", "")
    builder.button(text="Чеки", callback_data="checks_menu")
    builder.button(text="Настройки", callback_data="settings_menu")
    builder.button(text="Техподдержка", url=f"https://t.me/{clean_support}")
    builder.adjust(1, 3)
    return builder.as_markup()

def kb_worker():
    """Воркер панель - inline кнопки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="Мои мамонты", callback_data="my_mammoths")
    builder.button(text="Промокоды", callback_data="promo_menu")
    builder.button(text="Мин. депозит", callback_data="set_min_deposit")
    builder.button(text="Мануал", url="https://telegra.ph/IRL--WEB-TRADE-MANUAL-12-30")
    builder.button(text="Инструкция", url="https://telegra.ph/WORKER-MANUAL--TonTrader-01-12")
    builder.adjust(1, 2, 2)
    return builder.as_markup()

def kb_worker_reply():
    """Reply клавиатура для быстрого доступа к воркер-панели"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Воркер панель"), KeyboardButton(text="Главное меню")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def kb_admin_reply():
    """Reply клавиатура для админ-панели"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Админ панель"), KeyboardButton(text="Главное меню")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def kb_mammoth_control(user_id, luck, is_kyc):
    """Управление мамонтом"""
    builder = InlineKeyboardBuilder()
    luck_map = {"win": "ВИН", "lose": "ЛУЗ", "default": "РАНДОМ"}
    builder.button(text=f"Удача: {luck_map.get(luck, 'РАНДОМ')}", callback_data=f"menu_luck_{user_id}")
    builder.button(text="Баланс", callback_data=f"set_balance_{user_id}")
    kyc_text = "Снять KYC" if is_kyc else "Дать KYC"
    builder.button(text=kyc_text, callback_data=f"toggle_kyc_{user_id}")
    builder.button(text="Паста", callback_data=f"set_withdraw_msg_{user_id}")
    builder.button(text="Сообщение", callback_data=f"send_msg_{user_id}")
    builder.button(text="Назад", callback_data="my_mammoths")
    builder.adjust(2, 2, 2)
    return builder.as_markup()

def kb_luck_select(user_id):
    """Выбор удачи"""
    builder = InlineKeyboardBuilder()
    builder.button(text="Всегда выигрывает", callback_data=f"set_luck_{user_id}_win")
    builder.button(text="Всегда проигрывает", callback_data=f"set_luck_{user_id}_lose")
    builder.button(text="Случайный результат", callback_data=f"set_luck_{user_id}_default")
    builder.button(text="Назад", callback_data=f"open_mammoth_{user_id}")
    builder.adjust(1)
    return builder.as_markup()

def kb_admin():
    """Админ панель"""
    builder = InlineKeyboardBuilder()
    builder.button(text="Изменить Support", callback_data="adm_sup")
    builder.button(text="Реквизиты стран", callback_data="adm_countries")
    builder.adjust(1)
    return builder.as_markup()

def kb_countries():
    """Клавиатура со списком стран"""
    builder = InlineKeyboardBuilder()
    countries = db_get_country_bank_details()
    
    for country in countries:
        builder.button(
            text=f"{country['country_name']} ({country['currency']})", 
            callback_data=f"country_{country['id']}"
        )
    
    builder.button(text="Назад", callback_data="back_admin")
    builder.adjust(1)
    return builder.as_markup()

# Валюты с курсами (rate = сколько единиц валюты за 1 USD)
CURRENCIES = {
    "RUB": {"name": "Российский рубль", "symbol": "₽", "rate": 89.5},
    "KZT": {"name": "Казахский тенге", "symbol": "₸", "rate": 450.0},
    "UAH": {"name": "Украинская гривна", "symbol": "₴", "rate": 41.5},
    "USD": {"name": "Доллар США", "symbol": "$", "rate": 1.0},
    "EUR": {"name": "Евро", "symbol": "€", "rate": 0.92},
}

# Дефолтная валюта
DEFAULT_CURRENCY = "RUB"

def kb_settings(user):
    """Клавиатура настроек"""
    builder = InlineKeyboardBuilder()
    
    currency = user.get('preferred_currency', DEFAULT_CURRENCY)
    notifications = user.get('notifications_enabled', True)
    notif_text = "Выкл. уведомления" if notifications else "Вкл. уведомления"
    
    builder.button(text=f"Валюта: {currency}", callback_data="settings_currency")
    builder.button(text=notif_text, callback_data="settings_notifications")
    builder.button(text="Назад", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()

def kb_currency_select(current_currency):
    """Выбор валюты"""
    builder = InlineKeyboardBuilder()
    
    for code, data in CURRENCIES.items():
        prefix = "• " if code == current_currency else ""
        builder.button(
            text=f"{prefix}{data['symbol']} {data['name']}", 
            callback_data=f"set_currency_{code}"
        )
    
    builder.button(text="Назад", callback_data="settings_menu")
    builder.adjust(1)
    return builder.as_markup()

def kb_back_to(callback_data: str, text: str = "Назад"):
    """Универсальная кнопка назад"""
    builder = InlineKeyboardBuilder()
    builder.button(text=text, callback_data=callback_data)
    return builder.as_markup()

# ==========================================
# 📝 ТЕКСТОВЫЕ ШАБЛОНЫ - ПРОФЕССИОНАЛЬНЫЕ
# ==========================================
def get_welcome_text():
    """Приветственное сообщение"""
    return (
        "🚀 <b>TonTrader</b>\n\n"
        "<blockquote>💎 Торговля криптовалютой нового поколения\n"
        "⚡️ Мгновенные сделки без комиссий\n"
        "🔐 Безопасность на уровне банков</blockquote>\n\n"
        "<i>Нажмите кнопку ниже, чтобы открыть терминал</i>"
    )

def get_worker_panel_text(user_id, count, promo_count, min_deposit, ref_link):
    """Текст воркер-панели"""
    return (
        "⚡️ <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>👤 <b>ID:</b> <code>{user_id}</code>\n"
        f"🦣 <b>Мамонтов:</b> {count}\n"
        f"🎁 <b>Промокодов:</b> {promo_count}\n"
        f"💰 <b>Мин. депозит:</b> ${min_deposit:.2f}</blockquote>\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "<i>Отправьте эту ссылку потенциальным клиентам</i>"
    )

def get_mammoth_profile_text(m, withdraw_name):
    """Профиль мамонта"""
    kyc_status = "✅ Верифицирован" if m.get('is_kyc') else "❌ Не пройдена"
    luck_map = {"win": "🟢 Выигрыш", "lose": "🔴 Проигрыш", "default": "🎲 Случайно"}
    luck_text = luck_map.get(m.get('luck', 'default'), '🎲 Случайно')
    
    return (
        "🦣 <b>ПРОФИЛЬ КЛИЕНТА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>👤 <b>Username:</b> {m.get('username', 'Не указан')}\n"
        f"🆔 <b>ID:</b> <code>{m['user_id']}</code>\n"
        f"📱 <b>Имя:</b> {m.get('full_name', 'Не указано')}</blockquote>\n\n"
        f"💰 <b>Баланс:</b> <code>${m.get('balance', 0):.2f}</code>\n"
        f"🍀 <b>Режим удачи:</b> {luck_text}\n"
        f"🛡 <b>KYC:</b> {kyc_status}\n"
        f"💬 <b>Паста вывода:</b> {withdraw_name}"
    )

def get_admin_panel_text(settings, countries_count):
    """Текст админ-панели"""
    return (
        "👑 <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>📞 <b>Support:</b> @{settings.get('support_username')}\n"
        f"🏦 <b>Стран:</b> {countries_count}\n"
        f"💰 <b>Мин. депозит:</b> ${settings.get('min_deposit')}</blockquote>\n\n"
        "<i>Выберите действие из меню ниже</i>"
    )

def get_checks_menu_text(balance, active_count, total_count):
    """Меню чеков"""
    return (
        "🎫 <b>СИСТЕМА ЧЕКОВ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>Чеки позволяют мгновенно передавать средства "
        "любому пользователю Telegram. Создайте чек и поделитесь ссылкой.</blockquote>\n\n"
        f"💰 <b>Ваш баланс:</b> <code>${balance:.2f}</code>\n"
        f"📋 <b>Активных чеков:</b> {active_count}\n"
        f"📊 <b>Всего создано:</b> {total_count}"
    )

# ==========================================
# 🚀 КОМАНДА /start
# ==========================================
@dp.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: types.Message, command: CommandObject):
    """Обработка deeplink для чеков и рефералов"""
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    photo_url = await get_user_photo_url(user_id)
    args = command.args
    
    # Проверяем, это чек или реферал
    if args and args.startswith('check_'):
        check_code = args.replace('check_', '')
        db_upsert_user(user_id, username, full_name, None, photo_url)
        
        result = db_activate_check(check_code, user_id)
        
        if result:
            success = result.get('success')
            msg = result.get('message')
            amount = result.get('amount', 0)
            
            if success:
                await message.answer(
                    "✅ <b>ЧЕК УСПЕШНО АКТИВИРОВАН</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"<blockquote>💰 Зачислено: <b>${amount:.2f}</b>\n"
                    f"🎫 Код: <code>{check_code}</code></blockquote>\n\n"
                    "<i>Средства уже на вашем балансе. Откройте терминал для торговли.</i>",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "⚠️ <b>НЕ УДАЛОСЬ АКТИВИРОВАТЬ ЧЕК</b>\n\n"
                    f"<blockquote>{msg}</blockquote>",
                    parse_mode="HTML"
                )
        
        settings = db_get_settings()
        welcome = get_welcome_text()
        await send_welcome_with_photo(message, welcome, settings, user_id)
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
                "🦣 <b>НОВЫЙ КЛИЕНТ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<blockquote>👤 {f'@{username}' if username else 'Без username'}\n"
                f"🆔 <code>{user_id}</code>\n"
                f"📱 {full_name}</blockquote>\n\n"
                "<i>Клиент зарегистрирован по вашей ссылке</i>"
            )
            await bot.send_message(referrer_id, notify_text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Notify error: {e}")
    
    settings = db_get_settings()
    welcome = get_welcome_text()
    await send_welcome_with_photo(message, welcome, settings, user_id)

@dp.message(CommandStart())
async def cmd_start_simple(message: types.Message):
    """Обработка обычного /start без параметров"""
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    photo_url = await get_user_photo_url(user_id)
    db_upsert_user(user_id, username, full_name, None, photo_url)
    
    settings = db_get_settings()
    welcome = get_welcome_text()
    await send_welcome_with_photo(message, welcome, settings, user_id)

async def send_welcome_with_photo(message: types.Message, welcome: str, settings: dict, user_id: int):
    """Отправка приветствия с фото"""
    try:
        from aiogram.types import FSInputFile
        import os
        photo_path = os.path.join(os.path.dirname(__file__), "welcome.jpg")
        
        if os.path.exists(photo_path) and os.path.isfile(photo_path):
            photo = FSInputFile(photo_path)
            await message.answer_photo(
                photo, 
                caption=welcome, 
                parse_mode="HTML", 
                reply_markup=kb_start(settings.get('support_username', 'support'), user_id)
            )
        else:
            await message.answer(
                welcome, 
                parse_mode="HTML", 
                reply_markup=kb_start(settings.get('support_username', 'support'), user_id)
            )
    except Exception as e:
        logging.error(f"Error sending photo: {e}")
        await message.answer(
            welcome, 
            parse_mode="HTML", 
            reply_markup=kb_start(settings.get('support_username', 'support'), user_id)
        )

# ==========================================
# ⚡️ КОМАНДА /worker
# ==========================================
@dp.message(Command("worker"))
async def cmd_worker(message: types.Message):
    """Воркер панель"""
    user_id = message.from_user.id
    mammoths = db_get_mammoths(user_id)
    count = len(mammoths) if mammoths else 0
    promos = db_get_worker_promos(user_id)
    promo_count = len(promos) if promos else 0
    min_deposit = db_get_worker_min_deposit(user_id)
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = get_worker_panel_text(user_id, count, promo_count, min_deposit, ref_link)
    
    await message.answer(text, parse_mode="HTML", reply_markup=kb_worker())
    await message.answer(
        "📱 <i>Используйте меню ниже для быстрого доступа</i>", 
        parse_mode="HTML", 
        reply_markup=kb_worker_reply()
    )

# Reply кнопки для воркера
@dp.message(F.text == "Воркер панель")
async def worker_panel_button(message: types.Message):
    await cmd_worker(message)

@dp.message(F.text == "Главное меню")
async def main_menu_button(message: types.Message):
    """Возврат в главное меню"""
    user_id = message.from_user.id
    settings = db_get_settings()
    welcome = get_welcome_text()
    
    await message.answer("<i>Возвращаемся в главное меню...</i>", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await send_welcome_with_photo(message, welcome, settings, user_id)

@dp.message(F.text == "Админ панель")
async def admin_panel_button(message: types.Message):
    """Быстрый доступ к админ-панели через reply кнопку"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Доступ запрещен", parse_mode="HTML")
        return
    await cmd_admin(message)

# ==========================================
# 🦣 УПРАВЛЕНИЕ МАМОНТАМИ
# ==========================================
@dp.callback_query(F.data == "my_mammoths")
async def show_mammoths(call: types.CallbackQuery):
    """Список мамонтов"""
    mammoths = db_get_mammoths(call.from_user.id)
    
    builder = InlineKeyboardBuilder()
    if mammoths:
        for m in mammoths:
            balance = m.get('balance', 0)
            name = m.get('full_name', 'Клиент')[:20]
            builder.button(text=f"👤 {name} • ${balance:.0f}", callback_data=f"open_mammoth_{m['user_id']}")
    else:
        builder.button(text="Пока нет клиентов", callback_data="ignore")
    builder.button(text="В панель", callback_data="back_worker")
    builder.adjust(1)
    
    await call.message.edit_text(
        "🦣 <b>ВАШИ КЛИЕНТЫ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<i>Всего: {len(mammoths) if mammoths else 0}</i>",
        parse_mode="HTML", 
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "back_worker")
async def back_worker(call: types.CallbackQuery):
    """Возврат в воркер панель"""
    user_id = call.from_user.id
    mammoths = db_get_mammoths(user_id)
    count = len(mammoths) if mammoths else 0
    promos = db_get_worker_promos(user_id)
    promo_count = len(promos) if promos else 0
    min_deposit = db_get_worker_min_deposit(user_id)
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = get_worker_panel_text(user_id, count, promo_count, min_deposit, ref_link)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_worker())

@dp.callback_query(F.data.startswith("open_mammoth_"))
async def open_mammoth(call: types.CallbackQuery):
    """Открыть профиль мамонта"""
    target_id = int(call.data.split("_")[2])
    m = db_get_user(target_id)
    
    if not m:
        await call.answer("⚠️ Клиент не найден в базе данных", show_alert=True)
        return
    
    withdraw_type = m.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
    withdraw_name = current_template['title'] if current_template else 'Стандартная'
    
    text = get_mammoth_profile_text(m, withdraw_name)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))

# === LUCK ===
@dp.callback_query(F.data.startswith("menu_luck_"))
async def menu_luck(call: types.CallbackQuery):
    """Меню выбора удачи"""
    target_id = int(call.data.split("_")[2])
    await call.message.edit_text(
        "🍀 <b>РЕЖИМ УДАЧИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>Выберите, как будут завершаться сделки клиента:</blockquote>",
        parse_mode="HTML",
        reply_markup=kb_luck_select(target_id)
    )

@dp.callback_query(F.data.startswith("set_luck_"))
async def set_luck(call: types.CallbackQuery):
    """Установка удачи"""
    parts = call.data.split("_")
    target_id = int(parts[2])
    mode = parts[3]
    db_update_field(target_id, "luck", mode)
    
    luck_names = {"win": "Выигрыш", "lose": "Проигрыш", "default": "Случайно"}
    await call.answer(f"✅ Режим: {luck_names.get(mode, mode)}")
    
    m = db_get_user(target_id)
    withdraw_type = m.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
    withdraw_name = current_template['title'] if current_template else 'Стандартная'
    
    text = get_mammoth_profile_text(m, withdraw_name)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))

# === KYC ===
@dp.callback_query(F.data.startswith("toggle_kyc_"))
async def toggle_kyc(call: types.CallbackQuery):
    """Переключение KYC"""
    target_id = int(call.data.split("_")[2])
    user = db_get_user(target_id)
    new_status = not user.get('is_kyc')
    db_update_field(target_id, "is_kyc", new_status)
    
    status_text = "выдан" if new_status else "снят"
    await call.answer(f"✅ KYC {status_text}")
    
    m = db_get_user(target_id)
    withdraw_type = m.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
    withdraw_name = current_template['title'] if current_template else 'Стандартная'
    
    text = get_mammoth_profile_text(m, withdraw_name)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))

# === BALANCE ===
@dp.callback_query(F.data.startswith("set_balance_"))
async def ask_balance(call: types.CallbackQuery, state: FSMContext):
    """Запрос нового баланса"""
    target_id = int(call.data.split("_")[2])
    user = db_get_user(target_id)
    current_balance = user.get('balance', 0) if user else 0
    
    await state.update_data(target_id=target_id)
    await state.set_state(WorkerStates.changing_balance)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data=f"open_mammoth_{target_id}")
    
    await call.message.edit_text(
        "💰 <b>ИЗМЕНЕНИЕ БАЛАНСА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Текущий баланс: <b>${current_balance:.2f}</b></blockquote>\n\n"
        "Введите новую сумму в USD:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.message(WorkerStates.changing_balance)
async def set_balance(message: types.Message, state: FSMContext):
    """Установка нового баланса"""
    try:
        new_balance = float(message.text.replace(',', '.').strip())
        data = await state.get_data()
        target_id = data['target_id']
        db_update_field(target_id, "balance", new_balance)
        
        await state.clear()
        
        m = db_get_user(target_id)
        withdraw_type = m.get('withdraw_message_type', 'default')
        templates = db_get_withdraw_message_templates()
        current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
        withdraw_name = current_template['title'] if current_template else 'Стандартная'
        
        text = (
            f"✅ <b>Баланс обновлен:</b> <code>${new_balance:.2f}</code>\n\n"
            + get_mammoth_profile_text(m, withdraw_name)
        )
        await message.answer(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))
        
    except ValueError:
        await message.answer(
            "⚠️ <b>Некорректный формат</b>\n\n"
            "<i>Введите число, например: 100 или 250.50</i>",
            parse_mode="HTML"
        )

# === SEND MESSAGE ===
@dp.callback_query(F.data.startswith("send_msg_"))
async def ask_msg(call: types.CallbackQuery, state: FSMContext):
    """Запрос сообщения для отправки"""
    target_id = int(call.data.split("_")[2])
    user = db_get_user(target_id)
    
    await state.update_data(target_id=target_id)
    await state.set_state(WorkerStates.sending_message)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data=f"open_mammoth_{target_id}")
    
    await call.message.edit_text(
        "✉️ <b>ОТПРАВКА СООБЩЕНИЯ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Получатель: {user.get('full_name', 'Клиент')}</blockquote>\n\n"
        "Введите текст сообщения:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.message(WorkerStates.sending_message)
async def send_msg(message: types.Message, state: FSMContext):
    """Отправка сообщения мамонту"""
    data = await state.get_data()
    target_id = data['target_id']
    
    try:
        await bot.send_message(
            target_id, 
            f"🔔 <b>Уведомление от TonTrader</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{message.text}",
            parse_mode="HTML"
        )
        success = True
    except Exception as e:
        logging.error(f"Error sending message to {target_id}: {e}")
        success = False
    
    await state.clear()
    
    m = db_get_user(target_id)
    withdraw_type = m.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    current_template = next((t for t in templates if t['message_type'] == withdraw_type), None)
    withdraw_name = current_template['title'] if current_template else 'Стандартная'
    
    status = "✅ <b>Сообщение доставлено</b>" if success else "⚠️ <b>Не удалось доставить сообщение</b>\n<i>Возможно, пользователь заблокировал бота</i>"
    
    text = f"{status}\n\n" + get_mammoth_profile_text(m, withdraw_name)
    await message.answer(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))

# === WITHDRAW MESSAGE ===
@dp.callback_query(F.data.startswith("set_withdraw_msg_"))
async def set_withdraw_message_menu(call: types.CallbackQuery):
    """Меню выбора пасты вывода"""
    target_id = int(call.data.split("_")[3])
    user = db_get_user(target_id)
    
    if not user:
        await call.answer("⚠️ Клиент не найден", show_alert=True)
        return
    
    current_type = user.get('withdraw_message_type', 'default')
    templates = db_get_withdraw_message_templates()
    
    if not templates:
        await call.answer("⚠️ Шаблоны не загружены", show_alert=True)
        return
    
    text = (
        "💬 <b>ПАСТА ВЫВОДА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Клиент: {user.get('full_name', 'Неизвестно')}\n"
        f"Текущая: <b>{current_type}</b></blockquote>\n\n"
        "<i>Выберите сообщение для показа при выводе:</i>"
    )
    
    builder = InlineKeyboardBuilder()
    
    for template in templates:
        msg_type = template['message_type']
        title = template['title']
        icon = template.get('icon', '⚠️')
        prefix = "✅ " if msg_type == current_type else ""
        
        builder.button(
            text=f"{prefix}{icon} {title}",
            callback_data=f"preview_msg_{target_id}_{msg_type}"
        )
    
    builder.button(text="Назад", callback_data=f"open_mammoth_{target_id}")
    builder.adjust(1)
    
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("preview_msg_"))
async def preview_withdraw_message(call: types.CallbackQuery):
    """Предпросмотр пасты вывода"""
    parts = call.data.split("_", 3)
    target_id = int(parts[2])
    message_type = parts[3]
    
    templates = db_get_withdraw_message_templates()
    template = next((t for t in templates if t['message_type'] == message_type), None)
    
    if not template:
        await call.answer("⚠️ Шаблон не найден", show_alert=True)
        return
    
    icon = template.get('icon', '⚠️')
    title = template['title']
    description = template['description']
    button_text = template.get('button_text', 'Поддержка')
    
    preview_text = (
        "👁 <b>ПРЕДПРОСМОТР</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Клиент увидит это при попытке вывода:</i>\n\n"
        f"<blockquote>{icon} <b>{title}</b>\n\n"
        f"{description}</blockquote>\n\n"
        f"🔘 Кнопка: <code>[{button_text}]</code>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Применить", callback_data=f"confirm_msg_{target_id}_{message_type}")
    builder.button(text="К выбору", callback_data=f"set_withdraw_msg_{target_id}")
    builder.adjust(2)
    
    await call.message.edit_text(preview_text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("confirm_msg_"))
async def confirm_withdraw_message(call: types.CallbackQuery):
    """Подтверждение выбора пасты вывода"""
    parts = call.data.split("_", 3)
    target_id = int(parts[2])
    message_type = parts[3]
    
    success = db_update_user_withdraw_message(target_id, message_type)
    
    if success:
        templates = db_get_withdraw_message_templates()
        template = next((t for t in templates if t['message_type'] == message_type), None)
        
        await call.answer(f"✅ Установлено: {template['title'] if template else message_type}", show_alert=True)
        
        m = db_get_user(target_id)
        text = get_mammoth_profile_text(m, template['title'] if template else message_type)
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_mammoth_control(target_id, m.get('luck'), m.get('is_kyc')))
    else:
        await call.answer("⚠️ Ошибка сохранения", show_alert=True)

# ==========================================
# 🎁 ПРОМОКОДЫ
# ==========================================
@dp.callback_query(F.data == "promo_menu")
async def promo_menu(call: types.CallbackQuery):
    """Меню промокодов"""
    creator_id = call.from_user.id
    promos = db_get_worker_promos(creator_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать промокод", callback_data="create_promo")
    if promos:
        builder.button(text="Мои промокоды", callback_data="my_promos")
    builder.button(text="В панель", callback_data="back_worker")
    builder.adjust(1)
    
    await call.message.edit_text(
        "🎁 <b>ПРОМОКОДЫ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>Создавайте промокоды для привлечения клиентов. "
        "При активации клиент получит бонус на баланс.</blockquote>\n\n"
        f"📊 <b>Создано:</b> {len(promos) if promos else 0}",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "create_promo")
async def create_promo_start(call: types.CallbackQuery, state: FSMContext):
    """Начало создания промокода"""
    await state.set_state(WorkerStates.creating_promo_code)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="promo_menu")
    
    await call.message.edit_text(
        "🎁 <b>СОЗДАНИЕ ПРОМОКОДА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>Шаг 1 из 3</blockquote>\n\n"
        "Введите код промокода:\n"
        "<i>Только латинские буквы, цифры, дефисы</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.message(WorkerStates.creating_promo_code)
async def create_promo_code(message: types.Message, state: FSMContext):
    """Ввод кода промокода"""
    code = message.text.strip().upper()
    
    if not code.replace('_', '').replace('-', '').isalnum():
        await message.answer(
            "⚠️ <b>Недопустимые символы</b>\n\n"
            "<i>Используйте только буквы, цифры, дефисы и подчеркивания</i>",
            parse_mode="HTML"
        )
        return
    
    if len(code) < 3 or len(code) > 20:
        await message.answer(
            "⚠️ <b>Неверная длина</b>\n\n"
            "<i>Код должен быть от 3 до 20 символов</i>",
            parse_mode="HTML"
        )
        return
    
    if db_check_promo_exists(code):
        await message.answer(
            "⚠️ <b>Код занят</b>\n\n"
            "<i>Промокод с таким названием уже существует</i>",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(promo_code=code)
    await state.set_state(WorkerStates.creating_promo_amount)
    await message.answer(
        "🎁 <b>СОЗДАНИЕ ПРОМОКОДА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Шаг 2 из 3\n"
        f"Код: <code>{code}</code></blockquote>\n\n"
        "Введите сумму бонуса в USD:",
        parse_mode="HTML"
    )

@dp.message(WorkerStates.creating_promo_amount)
async def create_promo_amount(message: types.Message, state: FSMContext):
    """Ввод суммы бонуса"""
    try:
        amount = float(message.text.replace(',', '.').strip())
        if amount <= 0 or amount > 1000:
            await message.answer(
                "⚠️ <b>Недопустимая сумма</b>\n\n"
                "<i>Укажите от 0.01 до 1000 USD</i>",
                parse_mode="HTML"
            )
            return
        
        data = await state.get_data()
        await state.update_data(promo_amount=amount)
        await state.set_state(WorkerStates.creating_promo_activations)
        await message.answer(
            "🎁 <b>СОЗДАНИЕ ПРОМОКОДА</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<blockquote>Шаг 3 из 3\n"
            f"Код: <code>{data['promo_code']}</code>\n"
            f"Бонус: <b>${amount:.2f}</b></blockquote>\n\n"
            "Введите макс. количество активаций (1-10000):",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer(
            "⚠️ <b>Некорректный формат</b>\n\n"
            "<i>Введите число, например: 50 или 25.5</i>",
            parse_mode="HTML"
        )

@dp.message(WorkerStates.creating_promo_activations)
async def create_promo_activations(message: types.Message, state: FSMContext):
    """Ввод количества активаций и создание промокода"""
    try:
        activations = int(message.text.strip())
        if activations <= 0 or activations > 10000:
            await message.answer(
                "⚠️ <b>Недопустимое значение</b>\n\n"
                "<i>Укажите от 1 до 10000</i>",
                parse_mode="HTML"
            )
            return
        
        data = await state.get_data()
        code = data['promo_code']
        amount = data['promo_amount']
        creator_id = message.from_user.id
        
        promo = db_create_promo_code(creator_id, code, amount, activations)
        await state.clear()
        
        if promo:
            mammoths = db_get_mammoths(creator_id)
            count = len(mammoths) if mammoths else 0
            promos = db_get_worker_promos(creator_id)
            promo_count = len(promos) if promos else 0
            min_deposit = db_get_worker_min_deposit(creator_id)
            
            bot_info = await bot.get_me()
            ref_link = f"https://t.me/{bot_info.username}?start={creator_id}"
            
            text = (
                "✅ <b>ПРОМОКОД СОЗДАН</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<blockquote>🎁 Код: <code>{code}</code>\n"
                f"💰 Бонус: <b>${amount:.2f}</b>\n"
                f"🔢 Активаций: <b>{activations}</b></blockquote>\n\n"
                + get_worker_panel_text(creator_id, count, promo_count, min_deposit, ref_link)
            )
            await message.answer(text, parse_mode="HTML", reply_markup=kb_worker())
        else:
            await message.answer(
                "⚠️ <b>Ошибка создания</b>\n\n"
                "<i>Попробуйте еще раз позже</i>",
                parse_mode="HTML"
            )
        
    except ValueError:
        await message.answer(
            "⚠️ <b>Некорректный формат</b>\n\n"
            "<i>Введите целое число</i>",
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "my_promos")
async def show_my_promos(call: types.CallbackQuery):
    """Список промокодов"""
    creator_id = call.from_user.id
    promos = db_get_worker_promos(creator_id)
    
    if not promos:
        builder = InlineKeyboardBuilder()
        builder.button(text="Создать первый", callback_data="create_promo")
        builder.button(text="Назад", callback_data="promo_menu")
        builder.adjust(1)
        
        await call.message.edit_text(
            "📋 <b>МОИ ПРОМОКОДЫ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<i>У вас пока нет промокодов</i>",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        return
    
    text = "📋 <b>МОИ ПРОМОКОДЫ</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for promo in promos[:10]:
        status = "🟢" if promo.get('is_active') else "🔴"
        activations = promo.get('current_activations', 0)
        max_activations = promo.get('max_activations', 0)
        
        text += (
            f"{status} <code>{promo['code']}</code>\n"
            f"   💰 ${promo['reward_amount']:.2f} • 📊 {activations}/{max_activations}\n\n"
        )
    
    if len(promos) > 10:
        text += f"<i>... и еще {len(promos) - 10}</i>\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать новый", callback_data="create_promo")
    builder.button(text="Назад", callback_data="promo_menu")
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
    builder.button(text="Отмена", callback_data="back_worker")
    
    await call.message.edit_text(
        "💰 <b>МИНИМАЛЬНЫЙ ДЕПОЗИТ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Текущее значение: <b>${current_min:.2f}</b></blockquote>\n\n"
        "Эта сумма отображается у всех ваших рефералов как минимальная для пополнения.\n\n"
        "Введите новую сумму в USD:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.message(WorkerStates.changing_min_deposit)
async def save_min_deposit(message: types.Message, state: FSMContext):
    """Сохранение нового минимального депозита"""
    try:
        new_min_deposit = float(message.text.replace(',', '.').strip())
        
        if new_min_deposit < 0:
            await message.answer(
                "⚠️ <b>Недопустимое значение</b>\n\n"
                "<i>Сумма не может быть отрицательной</i>",
                parse_mode="HTML"
            )
            return
        
        if new_min_deposit > 100000:
            await message.answer(
                "⚠️ <b>Слишком большая сумма</b>\n\n"
                "<i>Максимум: $100,000</i>",
                parse_mode="HTML"
            )
            return
        
        worker_id = message.from_user.id
        success = db_update_worker_min_deposit(worker_id, new_min_deposit)
        
        await state.clear()
        
        if success:
            mammoths = db_get_mammoths(worker_id)
            count = len(mammoths) if mammoths else 0
            promos = db_get_worker_promos(worker_id)
            promo_count = len(promos) if promos else 0
            
            bot_info = await bot.get_me()
            ref_link = f"https://t.me/{bot_info.username}?start={worker_id}"
            
            text = (
                f"✅ <b>Минимальный депозит обновлен:</b> <code>${new_min_deposit:.2f}</code>\n\n"
                + get_worker_panel_text(worker_id, count, promo_count, new_min_deposit, ref_link)
            )
            await message.answer(text, parse_mode="HTML", reply_markup=kb_worker())
            logging.info(f"Worker {worker_id} changed min_deposit to ${new_min_deposit:.2f}")
        else:
            await message.answer(
                "⚠️ <b>Ошибка сохранения</b>\n\n"
                "<i>Попробуйте позже или обратитесь к администратору</i>",
                parse_mode="HTML"
            )
        
    except ValueError:
        await message.answer(
            "⚠️ <b>Некорректный формат</b>\n\n"
            "<i>Введите число, например: 500 или 1000.50</i>",
            parse_mode="HTML"
        )

# ==========================================
# 👑 АДМИН ПАНЕЛЬ
# ==========================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Админ панель"""
    logging.info(f"/admin from {message.from_user.id}, ADMIN_IDS={ADMIN_IDS}")
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ <b>Доступ запрещен</b>", parse_mode="HTML")
        return
    
    settings = db_get_settings()
    countries = db_get_country_bank_details()
    
    text = get_admin_panel_text(settings, len(countries))
    await message.answer(text, parse_mode="HTML", reply_markup=kb_admin())
    await message.answer(
        "📱 <i>Используйте меню ниже для быстрого доступа</i>", 
        parse_mode="HTML", 
        reply_markup=kb_admin_reply()
    )

@dp.callback_query(F.data == "adm_sup")
async def adm_sup(call: types.CallbackQuery, state: FSMContext):
    """Изменение support username"""
    settings = db_get_settings()
    await state.set_state(AdminStates.changing_support)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="back_admin")
    
    await call.message.edit_text(
        "📞 <b>ИЗМЕНЕНИЕ SUPPORT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Текущий: @{settings.get('support_username')}</blockquote>\n\n"
        "Введите новый @username:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.message(AdminStates.changing_support)
async def save_sup(message: types.Message, state: FSMContext):
    """Сохранение support username"""
    new_support = message.text.replace("@", "").strip()
    success = db_update_settings("support_username", new_support)
    await state.clear()
    
    if success:
        settings = db_get_settings()
        countries = db_get_country_bank_details()
        
        text = f"✅ <b>Support обновлен:</b> @{new_support}\n\n" + get_admin_panel_text(settings, len(countries))
        await message.answer(text, parse_mode="HTML", reply_markup=kb_admin())
    else:
        await message.answer(
            "⚠️ <b>Ошибка сохранения</b>\n\n"
            "<i>Проверьте логи или обратитесь к разработчику</i>",
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "adm_countries")
async def adm_countries(call: types.CallbackQuery):
    """Список стран для редактирования реквизитов"""
    countries = db_get_country_bank_details()
    
    if not countries:
        await call.message.edit_text(
            "⚠️ <b>Страны не найдены</b>\n\n"
            "<i>Проверьте базу данных</i>",
            parse_mode="HTML"
        )
        return
    
    text = (
        "🏦 <b>РЕКВИЗИТЫ ПО СТРАНАМ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Выберите страну для редактирования:</i>"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_countries())

@dp.callback_query(F.data.startswith("country_"))
async def show_country_details(call: types.CallbackQuery, state: FSMContext):
    """Детали страны"""
    country_id = int(call.data.split("_")[1])
    
    try:
        res = supabase.table("country_bank_details").select("*").eq("id", country_id).single().execute()
        country = res.data
        
        if not country:
            await call.answer("⚠️ Страна не найдена", show_alert=True)
            return
        
        text = (
            f"🏦 <b>{country['country_name']}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<blockquote>💱 Валюта: <b>{country['currency']}</b>\n"
            f"📊 Курс к USD: <b>{country['exchange_rate']}</b></blockquote>\n\n"
            f"💳 <b>Текущие реквизиты:</b>\n"
            f"<code>{country['bank_details']}</code>"
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="Изменить", callback_data=f"edit_country_{country_id}")
        builder.button(text="К списку", callback_data="adm_countries")
        builder.adjust(2)
        
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        
    except Exception as e:
        logging.error(f"Error showing country details: {e}")
        await call.answer("⚠️ Ошибка загрузки", show_alert=True)

@dp.callback_query(F.data.startswith("edit_country_"))
async def edit_country_bank(call: types.CallbackQuery, state: FSMContext):
    """Редактирование реквизитов страны"""
    country_id = int(call.data.split("_")[2])
    
    try:
        res = supabase.table("country_bank_details").select("*").eq("id", country_id).single().execute()
        country = res.data
        
        if not country:
            await call.answer("⚠️ Страна не найдена", show_alert=True)
            return
        
        await state.update_data(country_id=country_id, country_name=country['country_name'])
        await state.set_state(AdminStates.changing_country_bank)
        
        builder = InlineKeyboardBuilder()
        builder.button(text="Отмена", callback_data=f"country_{country_id}")
        
        await call.message.edit_text(
            f"✏️ <b>РЕДАКТИРОВАНИЕ: {country['country_name']}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<blockquote>Текущие реквизиты:\n<code>{country['bank_details']}</code></blockquote>\n\n"
            "Введите новые реквизиты:\n"
            "<i>Название банка, номер карты/счета, имя получателя</i>",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logging.error(f"Error starting country edit: {e}")
        await call.answer("⚠️ Ошибка", show_alert=True)

@dp.message(AdminStates.changing_country_bank)
async def save_country_bank(message: types.Message, state: FSMContext):
    """Сохранение реквизитов страны"""
    data = await state.get_data()
    country_id = data.get('country_id')
    country_name = data.get('country_name')
    
    if len(message.text.strip()) < 10:
        await message.answer(
            "⚠️ <b>Слишком короткие реквизиты</b>\n\n"
            "<i>Минимум 10 символов</i>",
            parse_mode="HTML"
        )
        return
    
    try:
        result = supabase.table("country_bank_details").update({
            "bank_details": message.text.strip()
        }).eq("id", country_id).execute()
        
        await state.clear()
        
        if result.data and len(result.data) > 0:
            text = (
                f"✅ <b>Реквизиты сохранены</b>\n\n"
                f"<blockquote>🏦 {country_name}\n"
                f"<code>{message.text.strip()}</code></blockquote>\n\n"
                "🏦 <b>РЕКВИЗИТЫ ПО СТРАНАМ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "<i>Выберите страну для редактирования:</i>"
            )
            await message.answer(text, parse_mode="HTML", reply_markup=kb_countries())
        else:
            await message.answer(
                "⚠️ <b>Ошибка сохранения</b>\n\n"
                "<i>Проверьте подключение к базе данных</i>",
                parse_mode="HTML"
            )
            
    except Exception as e:
        logging.error(f"Error saving country bank details: {e}")
        await state.clear()
        await message.answer(
            f"Критическая ошибка\n\n"
            f"<code>{str(e)}</code>",
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "back_admin")
async def back_admin(call: types.CallbackQuery, state: FSMContext):
    """Возврат в админ панель"""
    await state.clear()
    settings = db_get_settings()
    countries = db_get_country_bank_details()
    
    text = get_admin_panel_text(settings, len(countries))
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_admin())

# ==========================================
# НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ
# ==========================================
@dp.callback_query(F.data == "settings_menu")
async def settings_menu(call: types.CallbackQuery):
    """Меню настроек"""
    user_id = call.from_user.id
    user = db_get_user(user_id)
    
    if not user:
        await call.answer("Пользователь не найден", show_alert=True)
        return
    
    currency = user.get('preferred_currency', 'USD')
    currency_data = CURRENCIES.get(currency, CURRENCIES['USD'])
    notifications = user.get('notifications_enabled', True)
    notif_status = "Включены" if notifications else "Выключены"
    
    text = (
        "<b>НАСТРОЙКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Валюта: <b>{currency_data['symbol']} {currency_data['name']}</b>\n"
        f"Уведомления: <b>{notif_status}</b></blockquote>\n\n"
        "<i>Выберите параметр для изменения</i>"
    )
    
    try:
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb_settings(user))
    except:
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_settings(user))
        except:
            await call.message.answer(text, parse_mode="HTML", reply_markup=kb_settings(user))

@dp.callback_query(F.data == "settings_currency")
async def settings_currency(call: types.CallbackQuery):
    """Выбор валюты"""
    user = db_get_user(call.from_user.id)
    current_currency = user.get('preferred_currency', 'USD') if user else 'USD'
    
    text = (
        "<b>ВЫБОР ВАЛЮТЫ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>Выберите валюту для отображения баланса и сумм в приложении.</blockquote>\n\n"
        f"Текущая: <b>{current_currency}</b>"
    )
    
    try:
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb_currency_select(current_currency))
    except:
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_currency_select(current_currency))
        except:
            await call.message.answer(text, parse_mode="HTML", reply_markup=kb_currency_select(current_currency))

@dp.callback_query(F.data.startswith("set_currency_"))
async def set_currency(call: types.CallbackQuery):
    """Установка валюты"""
    currency_code = call.data.replace("set_currency_", "")
    user_id = call.from_user.id
    
    if currency_code not in CURRENCIES:
        await call.answer("Неизвестная валюта", show_alert=True)
        return
    
    # Обновляем в БД
    db_update_field(user_id, "preferred_currency", currency_code)
    
    currency_data = CURRENCIES[currency_code]
    await call.answer(f"Валюта изменена: {currency_data['symbol']} {currency_data['name']}")
    
    # Возвращаемся в настройки
    user = db_get_user(user_id)
    notifications = user.get('notifications_enabled', True) if user else True
    notif_status = "Включены" if notifications else "Выключены"
    
    text = (
        "<b>НАСТРОЙКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Валюта: <b>{currency_data['symbol']} {currency_data['name']}</b>\n"
        f"Уведомления: <b>{notif_status}</b></blockquote>\n\n"
        "<i>Выберите параметр для изменения</i>"
    )
    
    try:
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb_settings(user))
    except:
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_settings(user))
        except:
            pass

@dp.callback_query(F.data == "settings_notifications")
async def settings_notifications(call: types.CallbackQuery):
    """Переключение уведомлений"""
    user_id = call.from_user.id
    user = db_get_user(user_id)
    
    current_status = user.get('notifications_enabled', True) if user else True
    new_status = not current_status
    
    # Обновляем в БД
    db_update_field(user_id, "notifications_enabled", new_status)
    
    status_text = "включены" if new_status else "выключены"
    await call.answer(f"Уведомления {status_text}")
    
    # Обновляем меню
    user = db_get_user(user_id)
    currency = user.get('preferred_currency', 'USD') if user else 'USD'
    currency_data = CURRENCIES.get(currency, CURRENCIES['USD'])
    notif_status = "Включены" if new_status else "Выключены"
    
    text = (
        "<b>НАСТРОЙКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Валюта: <b>{currency_data['symbol']} {currency_data['name']}</b>\n"
        f"Уведомления: <b>{notif_status}</b></blockquote>\n\n"
        "<i>Выберите параметр для изменения</i>"
    )
    
    try:
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb_settings(user))
    except:
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_settings(user))
        except:
            pass

# ==========================================
# СИСТЕМА ЧЕКОВ
# ==========================================
@dp.callback_query(F.data == "checks_menu")
async def checks_menu(call: types.CallbackQuery):
    """Главное меню чеков"""
    user_id = call.from_user.id
    user = db_get_user(user_id)
    
    if not user:
        await call.answer("Пользователь не найден", show_alert=True)
        return
    
    checks = db_get_user_checks(user_id)
    active_checks = [c for c in checks if c.get('is_active')]
    balance = user.get('balance', 0)
    
    text = get_checks_menu_text(balance, len(active_checks), len(checks))
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать чек", callback_data="create_check")
    builder.button(text="Ввести код", callback_data="enter_check_code")
    builder.button(text="Мои чеки", callback_data="my_checks")
    builder.button(text="Назад", callback_data="back_to_start")
    builder.adjust(2, 1, 1)
    
    # Пробуем редактировать caption (если это фото) или text
    try:
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=builder.as_markup())
    except Exception:
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        except Exception as e:
            logging.error(f"Error editing message in checks_menu: {e}")
            await call.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "enter_check_code")
async def enter_check_code_start(call: types.CallbackQuery, state: FSMContext):
    """Начало ввода кода чека"""
    await state.set_state(WorkerStates.entering_check_code)
    
    text = (
        "🎟 <b>АКТИВАЦИЯ ЧЕКА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>Введите код чека, который вам прислали.\n"
        "Код выглядит примерно так: <code>ABC123XYZ</code></blockquote>\n\n"
        "Введите код чека:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="checks_menu")
    
    try:
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=builder.as_markup())
    except:
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        except:
            await call.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(WorkerStates.entering_check_code)
async def process_check_code(message: types.Message, state: FSMContext):
    """Обработка введенного кода чека"""
    check_code = message.text.strip().upper()
    user_id = message.from_user.id
    
    await state.clear()
    
    # Проверяем формат кода
    if len(check_code) < 3 or len(check_code) > 50:
        await message.answer(
            "⚠️ <b>Неверный формат кода</b>\n\n"
            "<i>Код должен быть от 3 до 50 символов</i>",
            parse_mode="HTML"
        )
        return
    
    # Пробуем активировать чек
    result = db_activate_check(check_code, user_id)
    
    if result:
        success = result.get('success')
        msg = result.get('message', '')
        amount = result.get('amount', 0)
        
        if success:
            text = (
                "✅ <b>ЧЕК УСПЕШНО АКТИВИРОВАН</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<blockquote>💰 Зачислено: <b>${amount:.2f}</b>\n"
                f"🎟 Код: <code>{check_code}</code></blockquote>\n\n"
                "<i>Средства уже на вашем балансе!</i>"
            )
            
            builder = InlineKeyboardBuilder()
            builder.button(text="К чекам", callback_data="checks_menu")
            builder.button(text="В меню", callback_data="back_to_start")
            builder.adjust(2)
            
            await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
        else:
            # Ошибка активации
            error_text = (
                "⚠️ <b>НЕ УДАЛОСЬ АКТИВИРОВАТЬ ЧЕК</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<blockquote>{msg}</blockquote>\n\n"
                "<i>Проверьте код и попробуйте снова</i>"
            )
            
            builder = InlineKeyboardBuilder()
            builder.button(text="Попробовать снова", callback_data="enter_check_code")
            builder.button(text="Назад", callback_data="checks_menu")
            builder.adjust(1)
            
            await message.answer(error_text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        # Чек не найден или ошибка БД
        error_text = (
            "⚠️ <b>ЧЕК НЕ НАЙДЕН</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<blockquote>Код: <code>{check_code}</code></blockquote>\n\n"
            "<i>Проверьте правильность кода и попробуйте снова</i>"
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="Попробовать снова", callback_data="enter_check_code")
        builder.button(text="Назад", callback_data="checks_menu")
        builder.adjust(1)
        
        await message.answer(error_text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "back_to_start")
async def back_to_start(call: types.CallbackQuery):
    """Возврат в главное меню"""
    user_id = call.from_user.id
    settings = db_get_settings()
    welcome = get_welcome_text()
    
    try:
        await call.message.edit_caption(
            caption=welcome, 
            parse_mode="HTML", 
            reply_markup=kb_start(settings.get('support_username', 'support'), user_id)
        )
    except:
        await call.message.edit_text(
            welcome, 
            parse_mode="HTML", 
            reply_markup=kb_start(settings.get('support_username', 'support'), user_id)
        )

@dp.callback_query(F.data == "create_check")
async def create_check_start(call: types.CallbackQuery, state: FSMContext):
    """Начало создания чека"""
    user = db_get_user(call.from_user.id)
    
    if not user:
        await call.answer("⚠️ Пользователь не найден", show_alert=True)
        return
    
    balance = user.get('balance', 0)
    
    if balance <= 0:
        await call.answer("⚠️ Недостаточно средств", show_alert=True)
        return
    
    await state.update_data(photo_message_id=call.message.message_id, chat_id=call.message.chat.id)
    await state.set_state(WorkerStates.creating_check_amount)
    
    text = (
        "🎫 <b>СОЗДАНИЕ ЧЕКА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>Шаг 1 из 2\n"
        f"Ваш баланс: <b>${balance:.2f}</b></blockquote>\n\n"
        "Введите сумму чека в USD:\n"
        "<i>При создании сумма будет списана с баланса</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="checks_menu")
    
    try:
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=builder.as_markup())
    except:
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        except:
            await call.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(WorkerStates.creating_check_amount)
async def create_check_amount(message: types.Message, state: FSMContext):
    """Ввод суммы чека"""
    try:
        amount = float(message.text.replace(',', '.').strip())
        
        if amount <= 0:
            await message.answer(
                "⚠️ <b>Недопустимая сумма</b>\n\n"
                "<i>Сумма должна быть больше 0</i>",
                parse_mode="HTML"
            )
            return
        
        user = db_get_user(message.from_user.id)
        balance = user.get('balance', 0)
        
        if amount > balance:
            await message.answer(
                "⚠️ <b>Недостаточно средств</b>\n\n"
                f"<blockquote>Баланс: ${balance:.2f}\n"
                f"Требуется: ${amount:.2f}</blockquote>",
                parse_mode="HTML"
            )
            return
        
        await state.update_data(check_amount=amount)
        await state.set_state(WorkerStates.creating_check_activations)
        
        await message.answer(
            "🎫 <b>СОЗДАНИЕ ЧЕКА</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<blockquote>Шаг 2 из 2\n"
            f"Сумма: <b>${amount:.2f}</b></blockquote>\n\n"
            "Введите количество активаций (1-100):\n"
            f"<i>С баланса спишется: ${amount:.2f} × кол-во</i>",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer(
            "⚠️ <b>Некорректный формат</b>\n\n"
            "<i>Введите число, например: 10 или 50.5</i>",
            parse_mode="HTML"
        )

@dp.message(WorkerStates.creating_check_activations)
async def create_check_activations(message: types.Message, state: FSMContext):
    """Ввод количества активаций и создание чека"""
    try:
        activations = int(message.text.strip())
        
        if activations <= 0 or activations > 100:
            await message.answer(
                "⚠️ <b>Недопустимое значение</b>\n\n"
                "<i>Укажите от 1 до 100</i>",
                parse_mode="HTML"
            )
            return
        
        data = await state.get_data()
        amount = data['check_amount']
        total_amount = amount * activations
        
        user = db_get_user(message.from_user.id)
        balance = user.get('balance', 0)
        
        if total_amount > balance:
            await message.answer(
                "⚠️ <b>Недостаточно средств</b>\n\n"
                f"<blockquote>Баланс: ${balance:.2f}\n"
                f"Требуется: ${total_amount:.2f}</blockquote>",
                parse_mode="HTML"
            )
            return
        
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
                "✅ <b>ЧЕК СОЗДАН</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<blockquote>🎫 Код: <code>{check_code}</code>\n"
                f"💰 Сумма: <b>${amount:.2f}</b>\n"
                f"🔢 Активаций: <b>0/{activations}</b>\n"
                f"💸 Списано: <b>${total_amount:.2f}</b></blockquote>\n\n"
                f"🔗 <b>Ссылка:</b>\n<code>{check_link}</code>\n\n"
                "<i>Поделитесь ссылкой для передачи средств</i>"
            )
            
            builder = InlineKeyboardBuilder()
            builder.button(text="Поделиться", url=f"https://t.me/share/url?url={check_link}&text=🎫 Получи ${amount:.2f} по этому чеку!")
            builder.button(text="В меню", callback_data="back_to_start")
            builder.adjust(1)
            
            await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
        else:
            await message.answer(
                "⚠️ <b>Ошибка создания</b>\n\n"
                "<i>Попробуйте еще раз</i>",
                parse_mode="HTML"
            )
        
        await state.clear()
    except ValueError:
        await message.answer(
            "⚠️ <b>Некорректный формат</b>\n\n"
            "<i>Введите целое число</i>",
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "my_checks")
async def show_my_checks(call: types.CallbackQuery):
    """Список чеков пользователя"""
    user_id = call.from_user.id
    checks = db_get_user_checks(user_id)
    
    if not checks:
        builder = InlineKeyboardBuilder()
        builder.button(text="Создать первый", callback_data="create_check")
        builder.button(text="Назад", callback_data="checks_menu")
        builder.adjust(1)
        
        text = (
            "📋 <b>МОИ ЧЕКИ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<i>У вас пока нет чеков</i>"
        )
        
        try:
            await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=builder.as_markup())
        except:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        return
    
    text = "📋 <b>МОИ ЧЕКИ</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for check in checks[:10]:
        status = "🟢" if check.get('is_active') else "🔴"
        current = check.get('current_activations', 0)
        max_act = check.get('max_activations', 1)
        
        text += (
            f"{status} <code>{check['check_code']}</code>\n"
            f"   💰 ${check['amount']:.2f} • 📊 {current}/{max_act}\n\n"
        )
    
    if len(checks) > 10:
        text += f"<i>... и еще {len(checks) - 10}</i>\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать новый", callback_data="create_check")
    builder.button(text="Назад", callback_data="checks_menu")
    builder.adjust(1)
    
    try:
        await call.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=builder.as_markup())
    except:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

# ==========================================
# 🔧 УТИЛИТЫ И ОБРАБОТЧИКИ
# ==========================================
@dp.callback_query(F.data == "ignore")
async def ignore(call: types.CallbackQuery):
    """Игнорирование нажатия"""
    await call.answer()

@dp.callback_query(F.data == "cancel_action")
async def cancel_action(call: types.CallbackQuery, state: FSMContext):
    """Универсальная отмена действия"""
    await state.clear()
    await call.answer("❌ Действие отменено")
    try:
        await call.message.delete()
    except:
        pass

# ==========================================
# 🚀 ЗАПУСК БОТА
# ==========================================
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
