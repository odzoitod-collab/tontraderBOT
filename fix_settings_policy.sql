-- ==========================================
-- 🔧 ИСПРАВЛЕНИЕ ПОЛИТИК ДЛЯ SETTINGS
-- ==========================================

-- Удаляем старые политики если есть
DROP POLICY IF EXISTS "Enable read settings" ON public.settings;
DROP POLICY IF EXISTS "Enable update settings" ON public.settings;
DROP POLICY IF EXISTS "Enable all for settings" ON public.settings;

-- Создаем новую политику "разрешить всё"
CREATE POLICY "Enable all for settings" 
ON public.settings 
FOR ALL 
USING (true) 
WITH CHECK (true);

-- Проверяем что RLS включен
ALTER TABLE public.settings ENABLE ROW LEVEL SECURITY;

-- Проверка
SELECT 
    schemaname,
    tablename,
    policyname,
    permissive,
    roles,
    cmd,
    qual,
    with_check
FROM pg_policies 
WHERE tablename = 'settings';
