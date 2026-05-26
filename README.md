# 🧠 Vocab Bot — Telegram-бот для изучения слов

## Быстрый деплой на Railway

### 1. Создай бота в Telegram
- Открой [@BotFather](https://t.me/BotFather) в Telegram
- Отправь `/newbot`, придумай имя
- Скопируй токен (вида `7123456789:AAH...`)

### 2. Загрузи код на GitHub
```bash
git init
git add .
git commit -m "init"
git remote add origin https://github.com/ТВОЙ_ЮЗЕРНЕЙМ/vocab-bot.git
git branch -M main
git push -u origin main
```

### 3. Деплой на Railway
1. Зайди на [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Выбери свой репозиторий `vocab-bot`
3. Перейди во вкладку **Variables** и добавь:
   - `BOT_TOKEN` = твой токен от BotFather
4. Перейди во вкладку **Settings** → **Networking** → убедись что порт не нужен (бот работает через polling)
5. Добавь **Volume** для сохранения базы данных:
   - Settings → Volumes → Mount → путь: `/app`
   - Добавь переменную `DB_PATH` = `/app/data/vocab.db`

Railway автоматически соберёт Docker-образ и запустит бота.

### 4. Готово!
Открой своего бота в Telegram и отправь `/start` 🎉

## Команды бота
- `/start` — главное меню
- `/delete слово` — удалить слово из словаря
- `/cancel` — отменить текущее действие
