#!/usr/bin/env python3
"""
Скрипт для тестирования подключения к Supabase и проверки настроек
"""
from supabase import create_client, Client

# Конфигурация (те же данные что в bot.py)
SUPABASE_URL = "https://wzpywfedbowlosmvecos.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Ind6cHl3ZmVkYm93bG9zbXZlY29zIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYzNTAyMzksImV4cCI6MjA4MTkyNjIzOX0.TmAYsmA8iwSpLPKOHIZM7jf3GLE3oeT7wD-l0ALwBPw"

print("🔌 Подключение к Supabase...")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
print("✅ Подключено!\n")

# Тест 1: Чтение настроек
print("📖 Тест 1: Чтение настроек")
try:
    res = supabase.table("settings").select("*").execute()
    print(f"✅ Успешно! Найдено записей: {len(res.data)}")
    if res.data:
        for setting in res.data:
            print(f"   ID: {setting.get('id')}")
            print(f"   Support: {setting.get('support_username')}")
            print(f"   Реквизиты: {setting.get('bank_details')}")
    else:
        print("⚠️  Таблица пустая!")
except Exception as e:
    print(f"❌ Ошибка: {e}")

print("\n" + "="*50 + "\n")

# Тест 2: Обновление настроек
print("✏️  Тест 2: Обновление настроек")
try:
    # Получаем первую запись
    res = supabase.table("settings").select("*").limit(1).execute()
    if res.data and len(res.data) > 0:
        settings_id = res.data[0]['id']
        print(f"   Обновляем запись с ID: {settings_id}")
        
        # Пробуем обновить
        test_value = "TEST_SUPPORT_123"
        update_res = supabase.table("settings").update({
            "support_username": test_value
        }).eq("id", settings_id).execute()
        
        print(f"✅ Обновление выполнено!")
        print(f"   Результат: {update_res.data}")
        
        # Проверяем что обновилось
        check_res = supabase.table("settings").select("*").eq("id", settings_id).execute()
        if check_res.data and check_res.data[0]['support_username'] == test_value:
            print(f"✅ Проверка: значение изменилось на '{test_value}'")
            
            # Возвращаем обратно
            supabase.table("settings").update({
                "support_username": "etoooroSupport_Official"
            }).eq("id", settings_id).execute()
            print(f"✅ Значение восстановлено")
        else:
            print(f"⚠️  Значение не изменилось!")
    else:
        print("❌ Нет записей в таблице settings!")
except Exception as e:
    print(f"❌ Ошибка: {e}")

print("\n" + "="*50 + "\n")

# Тест 3: Проверка политик безопасности
print("🔒 Тест 3: Проверка политик (RLS)")
try:
    # Пробуем вставить новую запись (не должно работать если есть ограничения)
    insert_res = supabase.table("settings").insert({
        "support_username": "test",
        "bank_details": "test"
    }).execute()
    print(f"✅ Вставка разрешена (или RLS отключен)")
    
    # Удаляем тестовую запись
    if insert_res.data:
        test_id = insert_res.data[0]['id']
        supabase.table("settings").delete().eq("id", test_id).execute()
        print(f"✅ Тестовая запись удалена")
except Exception as e:
    print(f"⚠️  Вставка запрещена: {e}")

print("\n✅ Все тесты завершены!")
