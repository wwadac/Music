import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes,
)
from datetime import datetime

# ---------- НАСТРОЙКИ ----------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
ALLOWED_EXTENSIONS = ['.py', '.txt', '.json', '.mcpack', '.mcaddon', '.png', '.jpg', '.jpeg']
SUBSCRIPTION_PRICE = 299  # руб.
ADMIN_IDS = [6893832048]   # замените на свой TG-ID
FILES_PER_PAGE = 5

# ---------- СОСТОЯНИЯ ----------
WAITING_FOR_FILE, WAITING_FOR_NAME, WAITING_FOR_EXTENSION, WAITING_FOR_SEARCH = range(4)

# ---------- ХРАНИЛИЩА ----------
user_files = {}
subscribed_users = set()
file_search_cache = {}

# ---------- УТИЛИТЫ ----------
async def get_file_size(bot, file_id: str) -> int:
    try:
        file = await bot.get_file(file_id)
        return file.file_size or 0
    except Exception:
        return 0

# ---------- ОБЩИЕ ФУНКЦИИ ----------
def user_id_from_update(update: Update) -> int:
    if update.callback_query:
        return update.callback_query.from_user.id
    return update.effective_user.id

# ---------- КОМАНДЫ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    welcome = (
        f"👋 Привет, {user.first_name}!\n\n"
        "📁 Просто отправь мне файл и выбери действие.\n"
        "🔹 Можно изменить имя/расширение\n"
        "🔹 Подписка за 299₽ — доступ ко всем файлам\n\n"
        "📏 Макс. размер: 100 МБ\n📌 Разрешены:\n"
    ) + "\n".join(f"• {e}" for e in ALLOWED_EXTENSIONS)

    kb = [
        [InlineKeyboardButton("💳 Подписка", callback_data="cmd_subscribe")],
        [InlineKeyboardButton("🔐 Приватность", callback_data="cmd_privacy")],
        [InlineKeyboardButton("📂 Просмотр файлов", callback_data="cmd_browse")],
        [InlineKeyboardButton("🔍 Поиск", callback_data="cmd_search")],
    ]
    await update.message.reply_text(welcome, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    context.user_data['state'] = WAITING_FOR_FILE

async def subscription_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = user_id_from_update(update)
    txt = (
        "✅ У вас активная подписка!\n\n"
        "Вы можете просматривать и скачивать все файлы, загруженные в бота.\n\n"
        "Используйте:\n"
        "/browse - просмотр файлов\n"
        "/search - поиск файлов\n"
        "/privacy - настройки приватности"
    ) if user_id in subscribed_users else (
        "🔒 Премиум-подписка\n\n"
        "💰 Стоимость: 299 руб./месяц\n\n"
        "Возможности:\n"
        "• Просмотр всех файлов других пользователей\n"
        "• Скачивание файлов в один клик\n"
        "• Поиск по файлам\n"
        "• Статистика популярных файлов\n\n"
        "Для покупки свяжитесь с @admin"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(txt)
    else:
        await update.message.reply_text(txt)

async def toggle_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = user_id_from_update(update)
    files = user_files.get(user_id, [])
    if not files:
        txt = "У вас еще нет загруженных файлов."
        if update.callback_query:
            await update.callback_query.message.reply_text(txt)
        else:
            await update.message.reply_text(txt)
        return

    kb = [
        [InlineKeyboardButton("🔓 Сделать все публичными", callback_data="set_all_public")],
        [InlineKeyboardButton("🔒 Сделать все приватными", callback_data="set_all_private")],
        [InlineKeyboardButton("📋 Управлять отдельными файлами", callback_data="manage_individual")],
    ]
    txt = "🔐 Настройки приватности файлов:\n\n• Публичные — видны подписчикам\n• Приватные — только вам"
    if update.callback_query:
        await update.callback_query.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))

async def search_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = user_id_from_update(update)
    if user_id not in subscribed_users:
        txt = "🔒 Поиск файлов доступен только подписчикам."
        if update.callback_query:
            await update.callback_query.message.reply_text(txt)
        else:
            await update.message.reply_text(txt)
        return
    txt = "🔍 Введите поисковый запрос (имя или расширение):"
    if update.callback_query:
        await update.callback_query.message.reply_text(txt)
    else:
        await update.message.reply_text(txt)
    context.user_data['state'] = WAITING_FOR_SEARCH

async def browse_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = user_id_from_update(update)
    if user_id not in subscribed_users:
        txt = "🔒 Доступно только подписчикам."
        if update.callback_query:
            await update.callback_query.message.reply_text(txt)
        else:
            await update.message.reply_text(txt)
        return

    public_files = [f for uid, files in user_files.items()
                    if uid != user_id for f in files if f.get('public', True)]
    if not public_files:
        txt = "📭 Пока нет публичных файлов."
        if update.callback_query:
            await update.callback_query.message.reply_text(txt)
        else:
            await update.message.reply_text(txt)
        return

    file_search_cache[user_id] = [public_files, 0]
    await show_files_page(update, context, user_id, 0)

async def show_files_page(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, page: int) -> None:
    if user_id not in file_search_cache:
        if update.callback_query:
            await update.callback_query.message.reply_text("❌ Результаты устарели.")
        else:
            await update.message.reply_text("❌ Результаты устарели.")
        return

    files, _ = file_search_cache[user_id]
    total = (len(files) + FILES_PER_PAGE - 1) // FILES_PER_PAGE
    page = max(0, min(page, total - 1))
    start, end = page * FILES_PER_PAGE, min((page + 1) * FILES_PER_PAGE, len(files))

    msg = f"📂 Найдено файлов: {len(files)}  |  Страница {page + 1}/{total}\n\n"
    kb = []
    for i in range(start, end):
        f = files[i]
        size = await get_file_size(context.bot, f['file_id'])
        size_str = f"{size / 1024 / 1024:.1f}MB" if size > 1024 * 1024 else f"{size / 1024:.1f}KB"
        msg += f"📄 {f['filename']} ({size_str})\n"
        kb.append([InlineKeyboardButton(f"⬇️ {f['filename']}", callback_data=f"download_{i}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Назад", callback_data=f"page_{page - 1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"page_{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔍 Новый поиск", callback_data="new_search")])

    reply_markup = InlineKeyboardMarkup(kb)
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup)

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    user_id = update.callback_query.from_user.id
    if user_id not in file_search_cache:
        await update.callback_query.answer("❌ Файл недоступен", show_alert=True)
        return
    files, _ = file_search_cache[user_id]
    if not (0 <= idx < len(files)):
        await update.callback_query.answer("❌ Файл не найден", show_alert=True)
        return

    f = files[idx]
    try:
        await update.callback_query.answer("⏳ Загружаем...")
        tg_file = await context.bot.get_file(f['file_id'])
        path = await tg_file.download_to_drive()
        with open(path, 'rb') as fp:
            await context.bot.send_document(
                chat_id=update.callback_query.message.chat_id,
                document=fp,
                filename=f['filename'],
                caption=f"✅ {f['filename']}"
            )
        os.remove(path)
    except Exception as e:
        logger.error(e)
        await update.callback_query.answer("❌ Ошибка", show_alert=True)

# ---------- ОБРАБОТКА ДОКУМЕНТОВ ----------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get('state') != WAITING_FOR_FILE:
        return
    doc = update.message.document
    if doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text("⚠️ Файл > 100 МБ.")
        return

    context.user_data.update({
        'file_id': doc.file_id,
        'original_filename': doc.file_name,
        'original_extension': os.path.splitext(doc.file_name)[1],
        'new_extension': os.path.splitext(doc.file_name)[1]
    })

    kb = [
        [InlineKeyboardButton("✏️ Изменить имя", callback_data="change_name")],
        [InlineKeyboardButton("🔄 Изменить расширение", callback_data="change_ext")],
        [InlineKeyboardButton("✅ Сохранить как есть", callback_data="keep_as_is")],
    ]
    await update.message.reply_text(
        f"📄 <b>{doc.file_name}</b>  |  {doc.file_size / 1024 / 1024:.2f} МБ\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='HTML'
    )

# ---------- ОБРАБОТКА ТЕКСТА ----------
async def handle_filename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get('state') != WAITING_FOR_NAME:
        return
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Имя не может быть пустым.")
        return
    context.user_data['new_name'] = name
    ext = context.user_data['new_extension']
    kb = [
        [InlineKeyboardButton("✅ Сохранить", callback_data="confirm_save")],
        [InlineKeyboardButton("✏️ Изменить имя", callback_data="change_name")],
        [InlineKeyboardButton("🔄 Изменить расширение", callback_data="change_ext")],
    ]
    await update.message.reply_text(
        f"📄 Новое имя: <b>{name}{ext}</b>",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='HTML'
    )

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get('state') != WAITING_FOR_SEARCH:
        return
    query = update.message.text.strip().lower()
    user_id = update.effective_user.id
    if not query:
        await update.message.reply_text("❌ Пустой запрос")
        context.user_data['state'] = WAITING_FOR_FILE
        return

    found = [f for uid, files in user_files.items() if uid != user_id
             for f in files if f.get('public', True) and query in f['filename'].lower()]
    if not found:
        await update.message.reply_text("❌ Ничего не найдено")
        context.user_data['state'] = WAITING_FOR_FILE
        return

    file_search_cache[user_id] = [found, 0]
    await show_files_page(update, context, user_id, 0)

# ---------- СОХРАНЕНИЕ ----------
async def process_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    try:
        file_id = context.user_data['file_id']
        new_name = context.user_data.get('new_name', os.path.splitext(context.user_data['original_filename'])[0])
        new_ext = context.user_data.get('new_extension', context.user_data['original_extension'])
        new_filename = f"{new_name}{new_ext}"

        file = await context.bot.get_file(file_id)
        path = await file.download_to_drive()
        new_path = os.path.join(os.path.dirname(path), new_filename)
        os.rename(path, new_path)

        with open(new_path, 'rb') as fp:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=fp,
                filename=new_filename,
                caption=f"✅ Сохранено: {new_filename}",
                parse_mode='HTML'
            )

        user_files.setdefault(user_id, []).append({
            "file_id": file_id,
            "filename": new_filename,
            "public": True,
            "timestamp": datetime.now()
        })
        os.remove(new_path)
        context.user_data.clear()
        context.user_data['state'] = WAITING_FOR_FILE
        await query.delete_message()
    except Exception as e:
        logger.error(e)
        await query.edit_message_text("⚠️ Ошибка при обработке файла.")

# ---------- АДМИН ----------
async def admin_add_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Недостаточно прав")
        return
    if not context.args:
        await update.message.reply_text("Использование: /add_subscription <user_id>")
        return
    try:
        target = int(context.args[0])
        subscribed_users.add(target)
        await update.message.reply_text(f"✅ Пользователю {target} добавлена подписка")
    except ValueError:
        await update.message.reply_text("❌ Неверный ID")

# ---------- ОБРАБОТКА КНОПОК ----------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # Навигация / скачивание
    if data.startswith("download_"):
        await download_file(update, context, int(data[9:]))
    elif data.startswith("page_"):
        page = int(data[5:])
        file_search_cache[user_id][1] = page
        await show_files_page(update, context, user_id, page)
    elif data == "new_search":
        await search_files(query, context)

    # Работа с файлом
    elif data == "change_name":
        await query.edit_message_text("✏️ Введите новое имя файла (без расширения):")
        context.user_data['state'] = WAITING_FOR_NAME
    elif data == "change_ext":
        kb = [[InlineKeyboardButton(ext, callback_data=f"set_ext{ext}")] for ext in ALLOWED_EXTENSIONS]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])
        await query.edit_message_text("🔄 Выберите новое расширение:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("set_ext"):
        context.user_data['new_extension'] = data[7:]
        name = context.user_data.get('new_name', os.path.splitext(context.user_data['original_filename'])[0])
        kb = [
            [InlineKeyboardButton("✏️ Изменить имя", callback_data="change_name")],
            [InlineKeyboardButton("🔄 Изменить расширение", callback_data="change_ext")],
            [InlineKeyboardButton("✅ Сохранить", callback_data="confirm_save")],
        ]
        await query.edit_message_text(
            f"📄 Новое имя файла: <b>{name}{data[7:]}</b>",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='HTML'
        )
    elif data in ["keep_as_is", "confirm_save"]:
        await process_file(update, context)
    elif data == "back_to_main":
        kb = [
            [InlineKeyboardButton("✏️ Изменить имя", callback_data="change_name")],
            [InlineKeyboardButton("🔄 Изменить расширение", callback_data="change_ext")],
            [InlineKeyboardButton("✅ Сохранить как есть", callback_data="keep_as_is")],
        ]
        await query.edit_message_text(
            f"📄 Файл: <b>{context.user_data['original_filename']}</b>",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='HTML'
        )

    # Приватность
    elif data == "set_all_public":
        for f in user_files.get(user_id, []):
            f['public'] = True
        await query.edit_message_text("✅ Все файлы теперь публичные")
    elif data == "set_all_private":
        for f in user_files.get(user_id, []):
            f['public'] = False
        await query.edit_message_text("✅ Все файлы теперь приватные")
    elif data == "manage_individual":
        files = user_files.get(user_id, [])
        msg = "📋 Ваши файлы:\n\n"
        kb = []
        for i, f in enumerate(files, 1):
            status = "🔓" if f['public'] else "🔒"
            msg += f"{i}. {status} {f['filename']}\n"
            kb.append([InlineKeyboardButton(
                f"{'Скрыть' if f['public'] else 'Показать'} {f['filename']}",
                callback_data=f"toggle_{i - 1}")])
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_privacy")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("toggle_"):
        idx = int(data[7:])
        files = user_files.get(user_id, [])
        if 0 <= idx < len(files):
            files[idx]['public'] ^= True
            status = "публичный" if files[idx]['public'] else "приватный"
            await query.edit_message_text(f"✅ Файл теперь {status}")
    elif data == "back_to_privacy":
        await toggle_privacy(query, context)

    # Команды из /start
    elif data == "cmd_subscribe":
        await subscription_info(query, context)
        await query.delete_message()
    elif data == "cmd_privacy":
        await toggle_privacy(query, context)
        await query.delete_message()
    elif data == "cmd_browse":
        await browse_files(query, context)
        await query.delete_message()
    elif data == "cmd_search":
        await search_files(query, context)
        await query.delete_message()

# ---------- RUN ----------
def main() -> None:
    app = ApplicationBuilder().token("8244258907:AAGSOfk1CMoBku1ChaL-lTEjWdFG7ll_EYo").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", subscription_info))
    app.add_handler(CommandHandler("privacy", toggle_privacy))
    app.add_handler(CommandHandler("browse", browse_files))
    app.add_handler(CommandHandler("search", search_files))
    app.add_handler(CommandHandler("add_subscription", admin_add_subscription))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: (
        handle_filename(u, c) if c.user_data.get('state') == WAITING_FOR_NAME else
        handle_search(u, c)   if c.user_data.get('state') == WAITING_FOR_SEARCH else None
    )))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()

if __name__ == '__main__':
    main()
