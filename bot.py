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
MENU, ADD_WORD, QUIZ_ANSWER, DELETE_WORD, IMPORT = range(5)

# ─── Database ───
DB_PATH = os.getenv("DB_PATH", "vocab.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            translation TEXT NOT NULL,
            context TEXT DEFAULT ''
        )"""
    )
    # Миграция: добавляем столбец context, если его нет
    try:
        conn.execute("ALTER TABLE words ADD COLUMN context TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # столбец уже существует
    conn.commit()
    return conn


def db_add_word(user_id: int, word: str, translation: str, context: str = ""):
    conn = get_db()
    conn.execute(
        "INSERT INTO words (user_id, word, translation, context) VALUES (?, ?, ?, ?)",
        (user_id, word, translation, context),
    )
    conn.commit()
    conn.close()


def db_add_words_bulk(user_id: int, words_list: list[tuple[str, str, str]]) -> tuple[int, int, list[str]]:
    """Массовое добавление. Возвращает (добавлено, пропущено_дубликатов, список_ошибок)."""
    conn = get_db()
    added = 0
    skipped = 0
    errors = []

    for word, translation, ctx in words_list:
        exists = conn.execute(
            "SELECT 1 FROM words WHERE user_id = ? AND LOWER(word) = LOWER(?) AND LOWER(COALESCE(context, '')) = LOWER(?)",
            (user_id, word, ctx),
        ).fetchone()
        if exists:
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO words (user_id, word, translation, context) VALUES (?, ?, ?, ?)",
            (user_id, word, translation, ctx),
        )
        added += 1

    conn.commit()
    conn.close()
    return added, skipped, errors


def parse_word_line(line: str) -> tuple[str, str, str] | None:
    """Парсит строку формата 'word - translation - context'. Возвращает None при ошибке."""
    line = line.strip()
    if not line or " - " not in line:
        return None
    parts = [p.strip() for p in line.split(" - ")]
    word = parts[0]
    translation = parts[1] if len(parts) >= 2 else ""
    ctx = parts[2] if len(parts) >= 3 else ""
    if not word or not translation:
        return None
    return word, translation, ctx


def db_get_words(user_id: int) -> list[tuple[str, str, str]]:
    conn = get_db()
    rows = conn.execute(
        "SELECT word, translation, COALESCE(context, '') FROM words WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return rows


def db_word_exists(user_id: int, word: str, context: str = "") -> bool:
    """Проверяет дубликат по слову + контексту. Одно слово с разным контекстом — ок."""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM words WHERE user_id = ? AND LOWER(word) = LOWER(?) AND LOWER(COALESCE(context, '')) = LOWER(?)",
        (user_id, word, context),
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


def db_get_words_with_ids(user_id: int) -> list[tuple[int, str, str, str]]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id, word, translation, COALESCE(context, '') FROM words WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return rows


# ─── Keyboards ───
def main_menu_kb():
    return ReplyKeyboardMarkup(
        [["📝 Добавить слово", "🧠 Тест"], ["📋 Мои слова", "🗑 Удалить слово"], ["📥 Импорт"]],
        resize_keyboard=True,
    )


# ─── Handlers ───
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Привет! 👋 Я помогу тебе учить английские слова.\n\n"
        "📝 *Добавить слово* — сохранить новое слово с переводом\n"
        "📥 *Импорт* — загрузить список слов разом\n"
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
            "• *apple - яблоко*\n"
            "• *run - бежать - he runs fast* (с контекстом)\n\n"
            "Контекст необязателен, но помогает запомнить\n"
            "разные значения одного слова.\n\n"
            "/cancel — вернуться в меню",
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

    if text == "📥 Импорт":
        await update.message.reply_text(
            "📥 *Массовый импорт*\n\n"
            "Отправь список слов — каждое с новой строки:\n\n"
            "`apple - яблоко`\n"
            "`run - бежать - he runs fast`\n"
            "`spot - место - save me a spot`\n\n"
            "Или отправь *.txt файл* с таким списком.\n\n"
            "/cancel — вернуться в меню",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return IMPORT

    await update.message.reply_text("Выбери действие из меню 👇", reply_markup=main_menu_kb())
    return MENU


# ── Add word ──
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if " - " not in text:
        await update.message.reply_text(
            "❌ Неверный формат. Используй дефис:\n"
            "*apple - яблоко*\n"
            "*run - бежать - he runs fast*",
            parse_mode="Markdown",
        )
        return ADD_WORD

    parts = [p.strip() for p in text.split(" - ")]
    word = parts[0]
    translation = parts[1] if len(parts) >= 2 else ""
    word_context = parts[2] if len(parts) >= 3 else ""

    if not word or not translation:
        await update.message.reply_text("❌ Слово и перевод не могут быть пустыми.")
        return ADD_WORD

    if db_word_exists(update.effective_user.id, word, word_context):
        label = f"*{word}*" if not word_context else f"*{word}* ({word_context})"
        await update.message.reply_text(
            f"⚠️ {label} уже есть в словаре. Введи другое.",
            parse_mode="Markdown",
        )
        return ADD_WORD

    db_add_word(update.effective_user.id, word, translation, word_context)

    saved_text = f"✅ *{word}* → *{translation}*"
    if word_context:
        saved_text += f"\n💬 _{word_context}_"

    kb = ReplyKeyboardMarkup([["📝 Добавить ещё", "🏠 В меню"]], resize_keyboard=True)
    await update.message.reply_text(saved_text, parse_mode="Markdown", reply_markup=kb)
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

    lines = []
    for i, (w, t, c) in enumerate(words, 1):
        line = f"{i}. *{w}* → {t}"
        if c:
            line += f"  _({c})_"
        lines.append(line)

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

    # Сохраняем список для поиска по номеру
    context.user_data["delete_words"] = words

    return await _show_delete_list(update.message, words)


async def _show_delete_list(msg, words: list) -> int:
    """Показывает нумерованный список слов для удаления."""
    lines = []
    for i, (wid, w, t, c) in enumerate(words, 1):
        line = f"{i}. *{w}* → {t}"
        if c:
            line += f"  _({c})_"
        lines.append(line)

    kb = ReplyKeyboardMarkup([["🏠 В меню"]], resize_keyboard=True)

    # Разбиваем на чанки если список большой
    chunk = []
    length = 0
    for line in lines:
        if length + len(line) > 3500:
            await msg.reply_text("\n".join(chunk), parse_mode="Markdown")
            chunk = []
            length = 0
        chunk.append(line)
        length += len(line)

    header = f"🗑 *Удаление слов* ({len(words)} шт.)\n\nВведи *номер* или *слово* для удаления:\n\n"
    if chunk:
        await msg.reply_text(
            header + "\n".join(chunk),
            parse_mode="Markdown",
            reply_markup=kb,
        )

    return DELETE_WORD


async def delete_word_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if text == "🏠 В меню":
        context.user_data.pop("delete_words", None)
        await update.message.reply_text("🏠 Главное меню", reply_markup=main_menu_kb())
        return MENU

    words = context.user_data.get("delete_words", [])
    if not words:
        await update.message.reply_text("Список устарел. Попробуй снова.", reply_markup=main_menu_kb())
        return MENU

    user_id = update.effective_user.id
    deleted = False
    deleted_word = ""

    # Попытка удалить по номеру
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(words):
            wid = words[idx][0]
            deleted, deleted_word = db_delete_by_id(wid, user_id)
        else:
            await update.message.reply_text(f"❌ Нет слова с номером *{text}*. Введи от 1 до {len(words)}.", parse_mode="Markdown")
            return DELETE_WORD
    else:
        # Попытка удалить по слову
        deleted = db_delete_word(user_id, text)
        deleted_word = text

    if deleted:
        await update.message.reply_text(f"🗑 *{deleted_word}* — удалено.", parse_mode="Markdown")

        # Обновляем список
        remaining = db_get_words_with_ids(user_id)
        context.user_data["delete_words"] = remaining

        if not remaining:
            context.user_data.pop("delete_words", None)
            await update.message.reply_text("📭 Словарь пуст.", reply_markup=main_menu_kb())
            return MENU

        return await _show_delete_list(update.message, remaining)
    else:
        await update.message.reply_text(f"❌ Слово *{deleted_word}* не найдено.", parse_mode="Markdown")
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

    word, _, ctx = words[idx]
    num = idx + 1
    total = context.user_data["quiz_total"]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Пропустить", callback_data="quiz_skip")],
        [InlineKeyboardButton("❌ Закончить тест", callback_data="quiz_stop")],
    ])

    question = f"*[{num}/{total}]* Переведи: *{word}*"
    if ctx:
        question += f"\n💬 _{ctx}_"

    msg = update.message or update.callback_query.message
    await msg.reply_text(question, parse_mode="Markdown", reply_markup=kb)
    return QUIZ_ANSWER


async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    idx = context.user_data["quiz_index"]
    words = context.user_data["quiz_words"]
    _, correct_translation, _ = words[idx]

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
        _, correct_translation, _ = words[idx]

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


# ── Import (bulk) ──
async def import_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка многострочного текстового сообщения с импортом."""
    text = update.message.text.strip()
    lines = text.splitlines()
    return await _process_import(update, context, lines)


async def import_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка .txt файла с импортом."""
    doc = update.message.document

    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ Поддерживаются только *.txt* файлы.", parse_mode="Markdown")
        return IMPORT

    file = await doc.get_file()
    content = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")
    lines = content.strip().splitlines()
    return await _process_import(update, context, lines)


async def _process_import(update: Update, context: ContextTypes.DEFAULT_TYPE, lines: list[str]) -> int:
    """Общая логика импорта для текста и файлов."""
    parsed = []
    bad_lines = []

    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        result = parse_word_line(line)
        if result:
            parsed.append(result)
        else:
            bad_lines.append(f"строка {i}: `{line[:50]}`")

    if not parsed:
        await update.message.reply_text(
            "❌ Не удалось распознать ни одного слова.\n\n"
            "Формат: `слово - перевод - контекст`\n"
            "Каждое слово с новой строки.",
            parse_mode="Markdown",
        )
        return IMPORT

    added, skipped, _ = db_add_words_bulk(update.effective_user.id, parsed)

    # Формируем отчёт
    report = f"📥 *Импорт завершён!*\n\n✅ Добавлено: *{added}*"
    if skipped:
        report += f"\n⏭ Дубликатов пропущено: *{skipped}*"
    if bad_lines:
        preview = bad_lines[:5]
        report += f"\n❌ Ошибок формата: *{len(bad_lines)}*"
        report += "\n" + "\n".join(preview)
        if len(bad_lines) > 5:
            report += f"\n...и ещё {len(bad_lines) - 5}"

    await update.message.reply_text(report, parse_mode="Markdown", reply_markup=main_menu_kb())
    return MENU


# ── Cancel ──async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
                MessageHandler(filters.Regex("^(📝 Добавить слово|🧠 Тест|📋 Мои слова|🗑 Удалить слово|📥 Импорт)$"), menu_router),
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
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_word_input),
            ],
            IMPORT: [
                MessageHandler(filters.Document.ALL, import_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, import_text),
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
