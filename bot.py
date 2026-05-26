import os
import sqlite3
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# ─── Logging ───
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── States ───
MENU, ADD_WORD, QUIZ_ANSWER, DELETE_WORD = range(4)

# ─── Database ───
DB_PATH = os.getenv("DB_PATH", "vocab.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            translation TEXT NOT NULL
        )"""
    )
    conn.commit()
    return conn


def db_add_word(user_id: int, word: str, translation: str):
    conn = get_db()
    conn.execute("INSERT INTO words (user_id, word, translation) VALUES (?, ?, ?)", (user_id, word, translation))
    conn.commit()
    conn.close()


def db_get_words(user_id: int) -> list[tuple[str, str]]:
    conn = get_db()
    rows = conn.execute("SELECT word, translation FROM words WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return rows


def db_word_exists(user_id: int, word: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM words WHERE user_id = ? AND LOWER(word) = LOWER(?)", (user_id, word)
    ).fetchone()
    conn.close()
    return row is not None


def db_delete_word(user_id: int, word: str) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM words WHERE user_id = ? AND LOWER(word) = LOWER(?)", (user_id, word))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def db_delete_by_id(word_id: int, user_id: int) -> tuple[bool, str]:
    """Удаляет слово по id, возвращает (успех, слово)."""
    conn = get_db()
    row = conn.execute("SELECT word FROM words WHERE id = ? AND user_id = ?", (word_id, user_id)).fetchone()
    if not row:
        conn.close()
        return False, ""
    conn.execute("DELETE FROM words WHERE id = ? AND user_id = ?", (word_id, user_id))
    conn.commit()
    conn.close()
    return True, row[0]


def db_get_words_with_ids(user_id: int) -> list[tuple[int, str, str]]:
    conn = get_db()
    rows = conn.execute("SELECT id, word, translation FROM words WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return rows


# ─── Keyboards ───
def main_menu_kb():
    return ReplyKeyboardMarkup(
        [["📝 Добавить слово", "🧠 Тест"], ["📋 Мои слова", "🗑 Удалить слово"]],
        resize_keyboard=True,
    )


# ─── Handlers ───
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Привет! 👋 Я помогу тебе учить английские слова.\n\n"
        "📝 *Добавить слово* — сохранить новое слово с переводом\n"
        "🧠 *Тест* — проверить себя\n"
        "📋 *Мои слова* — посмотреть весь словарь\n"
        "🗑 *Удалить слово* — убрать слово из словаря",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
    return MENU


# ── Menu router ──
async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text

    if text == "📝 Добавить слово":
        await update.message.reply_text(
            "Введи слово и перевод через дефис:\n\n"
            "Например: *apple - яблоко*\n\n"
            "Или отправь /cancel чтобы вернуться.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADD_WORD

    if text == "🧠 Тест":
        return await start_quiz(update, context)

    if text == "📋 Мои слова":
        return await show_words(update, context)

    if text == "🗑 Удалить слово":
        return await delete_word_start(update, context)

    await update.message.reply_text("Выбери действие из меню 👇", reply_markup=main_menu_kb())
    return MENU


# ── Add word ──
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if " - " not in text:
        await update.message.reply_text(
            "❌ Неверный формат. Используй дефис:\n*apple - яблоко*",
            parse_mode="Markdown",
        )
        return ADD_WORD

    parts = text.split(" - ", 1)
    word = parts[0].strip()
    translation = parts[1].strip()

    if not word or not translation:
        await update.message.reply_text("❌ Слово и перевод не могут быть пустыми.")
        return ADD_WORD

    if db_word_exists(update.effective_user.id, word):
        await update.message.reply_text(
            f"⚠️ Слово *{word}* уже есть в твоём словаре. Введи другое слово.",
            parse_mode="Markdown",
        )
        return ADD_WORD

    db_add_word(update.effective_user.id, word, translation)

    kb = ReplyKeyboardMarkup([["📝 Добавить ещё", "🏠 В меню"]], resize_keyboard=True)
    await update.message.reply_text(
        f"✅ Сохранено: *{word}* → *{translation}*",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    return ADD_WORD


async def add_word_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text

    if text == "📝 Добавить ещё":
        await update.message.reply_text(
            "Введи слово и перевод через дефис:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADD_WORD

    if text == "🏠 В меню":
        await update.message.reply_text("Главное меню 👇", reply_markup=main_menu_kb())
        return MENU

    # Если пользователь сразу вводит слово вместо нажатия кнопки
    return await add_word(update, context)


# ── Show words ──
async def show_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    words = db_get_words(update.effective_user.id)

    if not words:
        await update.message.reply_text("📭 Словарь пуст. Добавь первое слово!", reply_markup=main_menu_kb())
        return MENU

    lines = [f"{i}. *{w}* → {t}" for i, (w, t) in enumerate(words, 1)]

    # Телеграм ограничивает длину сообщения
    chunk = []
    length = 0
    for line in lines:
        if length + len(line) > 3500:
            await update.message.reply_text("\n".join(chunk), parse_mode="Markdown")
            chunk = []
            length = 0
        chunk.append(line)
        length += len(line)

    if chunk:
        await update.message.reply_text(
            f"📋 *Твой словарь ({len(words)} слов):*\n\n" + "\n".join(chunk),
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )

    return MENU


# ── Delete word (interactive) ──
async def delete_word_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    words = db_get_words_with_ids(update.effective_user.id)

    if not words:
        await update.message.reply_text("📭 Словарь пуст — нечего удалять.", reply_markup=main_menu_kb())
        return MENU

    # Показываем слова инлайн-кнопками (по 2 в ряд)
    buttons = []
    row = []
    for wid, word, translation in words:
        row.append(InlineKeyboardButton(f"❌ {word}", callback_data=f"del_{wid}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🏠 В меню", callback_data="del_cancel")])

    await update.message.reply_text(
        "🗑 *Нажми на слово, чтобы удалить его:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return DELETE_WORD


async def delete_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "del_cancel":
        await query.message.reply_text("🏠 Главное меню", reply_markup=main_menu_kb())
        return MENU

    word_id = int(query.data.replace("del_", ""))
    deleted, word = db_delete_by_id(word_id, update.effective_user.id)

    if deleted:
        await query.message.reply_text(f"🗑 Слово *{word}* удалено.", parse_mode="Markdown")
    else:
        await query.message.reply_text("❌ Слово уже удалено.")

    # Показываем обновлённый список или возвращаемся в меню
    remaining = db_get_words_with_ids(update.effective_user.id)
    if not remaining:
        await query.message.reply_text("📭 Словарь пуст.", reply_markup=main_menu_kb())
        return MENU

    buttons = []
    row = []
    for wid, w, t in remaining:
        row.append(InlineKeyboardButton(f"❌ {w}", callback_data=f"del_{wid}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🏠 В меню", callback_data="del_cancel")])

    await query.message.reply_text(
        "🗑 *Удалить ещё?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return DELETE_WORD


# ── Delete by command (fallback) ──
async def delete_word_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Укажи слово: /delete apple")
        return MENU

    word = parts[1].strip()
    if db_delete_word(update.effective_user.id, word):
        await update.message.reply_text(f"🗑 Слово *{word}* удалено.", parse_mode="Markdown", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text(f"❌ Слово *{word}* не найдено.", parse_mode="Markdown", reply_markup=main_menu_kb())
    return MENU


# ── Quiz ──
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    words = db_get_words(update.effective_user.id)

    if len(words) < 3:
        await update.message.reply_text(
            "📭 Нужно минимум *3 слова* в словаре, чтобы начать тест.\n"
            f"Сейчас у тебя: {len(words)}",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return MENU

    random.shuffle(words)
    context.user_data["quiz_words"] = words
    context.user_data["quiz_index"] = 0
    context.user_data["quiz_correct"] = 0
    context.user_data["quiz_wrong"] = 0
    context.user_data["quiz_skipped"] = 0
    context.user_data["quiz_total"] = len(words)

    await update.message.reply_text(
        f"🧠 *Тест начался!* ({len(words)} слов)\n\nНапиши перевод или нажми «Пропустить».",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    return await send_quiz_question(update, context)


async def send_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    idx = context.user_data["quiz_index"]
    words = context.user_data["quiz_words"]

    if idx >= len(words):
        return await finish_quiz(update, context)

    word, _ = words[idx]
    num = idx + 1
    total = context.user_data["quiz_total"]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Пропустить", callback_data="quiz_skip")],
        [InlineKeyboardButton("❌ Закончить тест", callback_data="quiz_stop")],
    ])

    msg = update.message or update.callback_query.message
    await msg.reply_text(
        f"*[{num}/{total}]* Переведи: *{word}*",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    return QUIZ_ANSWER


async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    idx = context.user_data["quiz_index"]
    words = context.user_data["quiz_words"]
    _, correct_translation = words[idx]

    user_answer = update.message.text.strip().lower()
    correct = correct_translation.strip().lower()

    # Поддержка нескольких вариантов через запятую
    correct_variants = [v.strip() for v in correct.split(",")]

    if user_answer in correct_variants:
        context.user_data["quiz_correct"] += 1
        await update.message.reply_text("✅ Правильно!")
    else:
        context.user_data["quiz_wrong"] += 1
        await update.message.reply_text(f"❌ Неправильно. Верный ответ: *{correct_translation}*", parse_mode="Markdown")

    context.user_data["quiz_index"] += 1
    return await send_quiz_question(update, context)


async def quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "quiz_skip":
        idx = context.user_data["quiz_index"]
        words = context.user_data["quiz_words"]
        _, correct_translation = words[idx]

        context.user_data["quiz_skipped"] += 1
        context.user_data["quiz_index"] += 1

        await query.message.reply_text(f"⏭ Пропущено. Ответ: *{correct_translation}*", parse_mode="Markdown")
        return await send_quiz_question(update, context)

    if query.data == "quiz_stop":
        return await finish_quiz(update, context)

    return QUIZ_ANSWER


async def finish_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    correct = context.user_data["quiz_correct"]
    wrong = context.user_data["quiz_wrong"]
    skipped = context.user_data["quiz_skipped"]
    total = correct + wrong + skipped

    if total == 0:
        await (update.message or update.callback_query.message).reply_text(
            "Тест отменён.", reply_markup=main_menu_kb()
        )
        return MENU

    pct = round(correct / total * 100) if total > 0 else 0

    # Эмодзи в зависимости от результата
    if pct >= 80:
        emoji = "🏆"
    elif pct >= 50:
        emoji = "👍"
    else:
        emoji = "💪"

    msg = update.message or update.callback_query.message
    await msg.reply_text(
        f"{emoji} *Тест завершён!*\n\n"
        f"✅ Правильно: *{correct}*\n"
        f"❌ Неправильно: *{wrong}*\n"
        f"⏭ Пропущено: *{skipped}*\n"
        f"📊 Результат: *{pct}%* ({correct}/{total})",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )

    # Очистка данных теста
    for key in list(context.user_data.keys()):
        if key.startswith("quiz_"):
            del context.user_data[key]

    return MENU


# ── Cancel ──
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🏠 Главное меню", reply_markup=main_menu_kb())
    return MENU


# ─── Main ───
def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set!")

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU: [
                MessageHandler(filters.Regex("^(📝 Добавить слово|🧠 Тест|📋 Мои слова|🗑 Удалить слово)$"), menu_router),
                CommandHandler("delete", delete_word_cmd),
            ],
            ADD_WORD: [
                MessageHandler(filters.Regex("^(📝 Добавить ещё|🏠 В меню)$"), add_word_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_word),
            ],
            QUIZ_ANSWER: [
                CallbackQueryHandler(quiz_callback, pattern="^quiz_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, quiz_answer),
            ],
            DELETE_WORD: [
                CallbackQueryHandler(delete_word_callback, pattern="^del_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            CommandHandler("delete", delete_word_cmd),
        ],
    )

    app.add_handler(conv)

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
