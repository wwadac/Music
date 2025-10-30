import logging
import asyncio
import json
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# === Настройки ===
BOT_TOKEN = "8244258907:AAGSOfk1CMoBku1ChaL-lTEjWdFG7ll_EYo"
ADMIN_IDS = [6893832048]
PUBLIC_MODE = True
CONFIG_FILE = "user_configs.json"

# === Конфигурация ===
class UserConfig:
    def __init__(self):
        self.source_chat_id = None
        self.backup_chat_id = None
        self.is_active = False
        self.forward_mode = "forward"
        self.content_types = {
            "text": True,
            "photo": True,
            "video": True,
            "document": True,
            "audio": True,
            "voice": True,
            "sticker": True,
            "poll": True,
            "location": True
        }

    def to_dict(self):
        return {
            "source_chat_id": self.source_chat_id,
            "backup_chat_id": self.backup_chat_id,
            "is_active": self.is_active,
            "forward_mode": self.forward_mode,
            "content_types": self.content_types
        }

    @classmethod
    def from_dict(cls, data):
        config = cls()
        config.source_chat_id = data.get("source_chat_id")
        config.backup_chat_id = data.get("backup_chat_id")
        config.is_active = data.get("is_active", False)
        config.forward_mode = data.get("forward_mode", "forward")
        config.content_types = data.get("content_types", {
            "text": True, "photo": True, "video": True, "document": True,
            "audio": True, "voice": True, "sticker": True, "poll": True, "location": True
        })
        return config

# Глобальная переменная для хранения конфигов
user_configs = {}

# === Функции для работы с файлом конфигурации ===
def save_configs():
    """Сохраняет все конфиги пользователей в файл"""
    try:
        config_data = {}
        for user_id, config in user_configs.items():
            config_data[str(user_id)] = config.to_dict()

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        logging.info("Конфигурации сохранены")
    except Exception as e:
        logging.error(f"Ошибка сохранения конфигураций: {e}")

def load_configs():
    """Загружает конфиги пользователей из файла"""
    global user_configs
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            user_configs = {}
            for user_id_str, config_dict in config_data.items():
                user_id = int(user_id_str)
                user_configs[user_id] = UserConfig.from_dict(config_dict)
            logging.info("Конфигурации загружены")
        else:
            user_configs = {}
            logging.info("Файл конфигураций не найден, создан новый")
    except Exception as e:
        logging.error(f"Ошибка загрузки конфигураций: {e}")
        user_configs = {}

# === Логирование ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# === Проверки доступа ===
def check_access(user_id: int) -> bool:
    return PUBLIC_MODE or user_id in ADMIN_IDS

async def is_admin(bot, user_id, chat_id) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logging.error(f"Ошибка проверки прав: {e}")
        return False

# === Клавиатуры ===
def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    config = user_configs.get(user_id, UserConfig())
    buttons = [
        [
            InlineKeyboardButton("📌 Установить основной канал", callback_data="set_source"),
            InlineKeyboardButton("📌 Установить резервный канал", callback_data="set_backup")
        ],
        [
            InlineKeyboardButton("🔧 Настройки контента", callback_data="content_settings"),
            InlineKeyboardButton("⚙️ Настройки пересылки", callback_data="forward_settings")
        ],
        [
            InlineKeyboardButton("🟢 Активировать" if not config.is_active else "🔴 Деактивировать",
                               callback_data="toggle_status")
        ]
    ]

    if user_id in ADMIN_IDS:
        buttons.append([
            InlineKeyboardButton("🌐 Режим: " + ("Публичный" if PUBLIC_MODE else "Приватный"),
                               callback_data="change_mode")
        ])

    return InlineKeyboardMarkup(buttons)

def get_content_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    config = user_configs.get(user_id, UserConfig())
    buttons = []
    content_types = list(config.content_types.keys())

    for i in range(0, len(content_types), 2):
        row = []
        for j in range(i, min(i+2, len(content_types))):
            content_type = content_types[j]
            enabled = config.content_types[content_type]
            row.append(InlineKeyboardButton(
                f"{'✅' if enabled else '❌'} {content_type.capitalize()}",
                callback_data=f"toggle_{content_type}"
            ))
        buttons.append(row)

    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(buttons)

def get_forward_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Forward", callback_data="set_forward")],
        [InlineKeyboardButton("Copy", callback_data="set_copy")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
    ])

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not check_access(user_id):
        await update.message.reply_text("⛔ Бот доступен только администраторам.")
        return

    if user_id not in user_configs:
        user_configs[user_id] = UserConfig()

    config = user_configs[user_id]
    mode_status = "🌐 Режим: " + ("Публичный" if PUBLIC_MODE else "Приватный")

    text = (
        "👀 <b>Панель управления ботом</b>\n\n"
        f"{mode_status}\n"
        f"🔹 Статус: {'🟢 Активен' if config.is_active else '🔴 Выключен'}\n"
        f"🔹 Режим: {'Forward' if config.forward_mode == 'forward' else 'Copy'}\n"
        f"🔹 Основной канал: {config.source_chat_id or '❌ Не установлен'}\n"
        f"🔹 Резервный канал: {config.backup_chat_id or '❌ Не установлен'}\n\n"
        "🆘 Помощь: /help"
    )

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Только для администраторов!")
        return

    global PUBLIC_MODE
    PUBLIC_MODE = not PUBLIC_MODE

    mode = "ОБЩЕДОСТУПНЫЙ" if PUBLIC_MODE else "ПРИВАТНЫЙ"
    await update.message.reply_text(f"✅ Режим изменен на: {mode}")
    await start(update, context)

# === Обработчики кнопок ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not check_access(user_id):
        await query.answer("⛔ Нет доступа!", show_alert=True)
        return

    if user_id not in user_configs:
        user_configs[user_id] = UserConfig()

    config = user_configs[user_id]
    await query.answer()
    data = query.data

    if data == "toggle_status":
        config.is_active = not config.is_active
        save_configs()
        await admin(update, context)

    elif data == "content_settings":
        await query.edit_message_text("🔧 Настройки контента:", reply_markup=get_content_settings_keyboard(user_id))

    elif data == "forward_settings":
        await query.edit_message_text("⚙️ Настройки пересылки:", reply_markup=get_forward_settings_keyboard())

    elif data.startswith("toggle_"):
        content_type = data[7:]
        if content_type in config.content_types:
            config.content_types[content_type] = not config.content_types[content_type]
            save_configs()
            await query.edit_message_text("🔧 Настройки контента:", reply_markup=get_content_settings_keyboard(user_id))

    elif data == "set_forward":
        config.forward_mode = "forward"
        save_configs()
        await query.edit_message_text("✅ Режим пересылки установлен: Forward")
        await asyncio.sleep(1)
        await query.edit_message_text("⚙️ Настройки пересылки:", reply_markup=get_forward_settings_keyboard())

    elif data == "set_copy":
        config.forward_mode = "copy"
        save_configs()
        await query.edit_message_text("✅ Режим пересылки установлен: Copy")
        await asyncio.sleep(1)
        await query.edit_message_text("⚙️ Настройки пересылки:", reply_markup=get_forward_settings_keyboard())

    elif data in ["set_source", "set_backup"]:
        await query.edit_message_text(f"📥 Введите ID {'основного' if data == 'set_source' else 'резервного'} канала:")
        context.user_data['action'] = data

    elif data == "change_mode":
        global PUBLIC_MODE
        PUBLIC_MODE = not PUBLIC_MODE
        mode = "Публичный" if PUBLIC_MODE else "Приватный"
        await query.answer(f"Режим изменен на: {mode}", show_alert=True)
        await admin(update, context)

    elif data == "back_to_main":
        await admin(update, context)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
    config = user_configs.get(user_id, UserConfig())
    mode_status = "🌐 Режим: " + ("Публичный" if PUBLIC_MODE else "Приватный")

    text = (
        "👀️ <b>Панель управления ботом</b>\n\n"
        f"{mode_status}\n"
        f"🔹 Статус: {'🟢 Активен' if config.is_active else '🔴 Выключен'}\n"
        f"🔹 Режим: {'Forward' if config.forward_mode == 'forward' else 'Copy'}\n"
        f"🔹 Основной канал: {config.source_chat_id or '❌ Не установлен'}\n"
        f"🔹 Резервный канал: {config.backup_chat_id or '❌ Не установлен'}"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))
    elif update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(user_id))

# === Обработчик сообщений ===
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not check_access(user_id):
        await update.message.reply_text("⛔ Бот доступен только администраторам.")
        return

    if user_id not in user_configs:
        user_configs[user_id] = UserConfig()

    config = user_configs[user_id]

    if 'action' not in context.user_data:
        return

    text = update.message.text.strip()
    action = context.user_data['action']

    try:
        if action in ['set_source', 'set_backup']:
            if text.startswith('https://t.me/'):
                username = text.split('/')[-1]
                chat = await update.get_bot().get_chat(f"@{username}")
                chat_id = chat.id
            else:
                chat_id = int(text)

            if not await is_admin(update.get_bot(), user_id, chat_id):
                await update.message.reply_text("❌ Вы не администратор этого канала!")
                return

            if action == 'set_source':
                config.source_chat_id = chat_id
                await update.message.reply_text(f"✅ Основной канал установлен: {chat_id}")
            else:
                config.backup_chat_id = chat_id
                await update.message.reply_text(f"✅ Резервный канал установлен: {chat_id}")

            save_configs()
            del context.user_data['action']
            await admin(update, context)

    except (ValueError, IndexError):
        await update.message.reply_text("❌ Неверный формат. Введите ID канала или ссылку вида https://t.me/username")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# === Обработчик постов ===
async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post:
        return

    post = update.channel_post

    for user_id, config in user_configs.items():
        if config.is_active and post.chat.id == config.source_chat_id and config.backup_chat_id:
            content_type = None
            if post.text and config.content_types["text"]:
                content_type = "text"
            elif post.photo and config.content_types["photo"]:
                content_type = "photo"
            elif post.video and config.content_types["video"]:
                content_type = "video"
            elif post.document and config.content_types["document"]:
                content_type = "document"
            elif post.audio and config.content_types["audio"]:
                content_type = "audio"
            elif post.voice and config.content_types["voice"]:
                content_type = "voice"
            elif post.sticker and config.content_types["sticker"]:
                content_type = "sticker"
            elif post.poll and config.content_types["poll"]:
                content_type = "poll"
            elif post.location and config.content_types["location"]:
                content_type = "location"

            if not content_type:
                continue

            try:
                if config.forward_mode == "forward":
                    await post.forward(config.backup_chat_id)
                else:
                    await context.bot.copy_message(
                        chat_id=config.backup_chat_id,
                        from_chat_id=post.chat.id,
                        message_id=post.message_id
                    )
            except Exception as e:
                logging.error(f"Ошибка пересылки: {e}")

# === Обработчик ошибок ===
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Ошибка: {context.error}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📌 <b>Бот для резервного копирования каналов</b>

⚡ <b>Что делает:</b>
Автоматически пересылает новые сообщения из основного канала в резервный

🛠 <b>Как настроить:</b>
1. Добавьте бота в оба канала как админа
2. Укажите основной и резервный каналы
3. Выберите типы контента для пересылки
4. Включите бота кнопкой "Активировать"

🔧 <b>Команды:</b>
/start - открыть меню
/help - эта подсказка

⚠ <b>Важно:</b>
• Бот должен быть админом в обоих каналах
• Поддерживаются: текст, фото, видео, документы
• Можно пересылать как ссылкой, так и копией
"""
    await update.message.reply_text(help_text, parse_mode="HTML")

# === Запуск ===
if __name__ == '__main__':
    # Загружаем конфиги при запуске
    load_configs()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mode", set_mode))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, channel_post_handler))
    app.add_error_handler(error_handler)

    print("✅ Бот запущен!")
    app.run_polling()
