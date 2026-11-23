"""
Telegram-бот записи к мастеру с Mini App.

Пользователь жмёт /start → под полем ввода появляется кнопка «💅 Открыть приложение».
В приложении выбирает услугу → нажимает «Записаться» → бот получает заявку,
благодарит клиента и пересылает заявку мастеру (ADMIN_ID).
"""
import asyncio
import json
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH)


def save_env(key: str, value: str):
    with open(ENV_PATH, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")


BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    BOT_TOKEN = input("Вставьте токен бота от @BotFather и нажмите Enter: ").strip()
    save_env("BOT_TOKEN", BOT_TOKEN)

WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://icouldxlie.github.io/vera-nails/")
# Telegram ID мастера — сюда придут заявки. Если не задан, мастером станет первый, кто нажмёт /start.
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0) or 0)
MASTER_NAME = os.environ.get("MASTER_NAME", "Вера")

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

MOODS = {"silence": "☁️ хочет посидеть в тишине", "talk": "🌸 хочет поговорить с мастером"}


def app_keyboard() -> ReplyKeyboardMarkup:
    # Именно reply-кнопка: только с неё приложение может вернуть заявку боту (sendData)
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="💅 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )


@dp.message(CommandStart())
async def start(message: Message):
    global ADMIN_ID
    if not ADMIN_ID:
        ADMIN_ID = message.from_user.id
        save_env("ADMIN_ID", str(ADMIN_ID))
        await message.answer("👑 Вы назначены мастером — заявки клиентов будут приходить сюда.")
    await message.answer(
        f"Привет! Я помощник мастера {MASTER_NAME} 🤍\n\n"
        "Здесь можно записаться на маникюр, Таро, разбор матрицы судьбы, "
        "натальной карты или чакр.\n\n"
        "Нажмите кнопку внизу, чтобы открыть приложение 👇",
        reply_markup=app_keyboard(),
    )


@dp.message(F.web_app_data)
async def on_order(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
    except json.JSONDecodeError:
        await message.answer("Не получилось прочитать заявку, попробуйте ещё раз 🙏")
        return

    items = "\n".join(f"• {i}" for i in data.get("items", []))
    total = data.get("total")
    total_text = f"{total:,} ₽".replace(",", " ") if total else "уточнит мастер"
    comment = data.get("comment") or "—"

    await message.answer(
        f"Спасибо! Заявка отправлена мастеру 🤍\n\n{items}\n\nИтого: {total_text}\n\n"
        "Скоро с вами свяжутся, чтобы подтвердить дату и время.",
        reply_markup=app_keyboard(),
    )

    if ADMIN_ID:
        u = message.from_user
        who = f"@{u.username}" if u.username else u.full_name
        mood = MOODS.get(data.get("mood"), "")
        await bot.send_message(
            ADMIN_ID,
            "🆕 Новая запись\n\n"
            f"Клиент: {who} (id {u.id})\n"
            f"{items}\n"
            + (f"Атмосфера: {mood}\n" if mood else "")
            + f"Итого: {total_text}\n"
            f"Комментарий: {comment}\n\n"
            f"Написать клиенту: tg://user?id={u.id}",
        )


async def main():
    # Дополнительно — кнопка «Записаться» рядом с полем ввода (меню бота)
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Записаться", web_app=WebAppInfo(url=WEBAPP_URL)))
    print("Бот запущен! Не закрывайте это окно. Остановить: Ctrl+C")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
