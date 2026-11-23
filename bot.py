"""
WWP nail studio — Telegram-бот записи с Mini App.

/start → кнопка «💅 Открыть приложение» → клиент выбирает услугу, дату и время →
бот сохраняет запись, занимает окошко и присылает заявку мастеру.

Команды мастера:
  /bookings                 — ближайшие записи
  /free 2026-11-24 12:00    — освободить окошко (если клиент отменил)
"""
import asyncio
import json
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, MenuButtonDefault, Message, ReplyKeyboardMarkup, WebAppInfo
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
BOOKINGS_PATH = os.path.join(HERE, "bookings.json")
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


# ---------- записи ----------
def load_bookings() -> list:
    try:
        with open(BOOKINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_bookings(items: list):
    with open(BOOKINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def upcoming() -> list:
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    return sorted((b for b in load_bookings() if b["slot"] >= now), key=lambda b: b["slot"])


def app_keyboard() -> ReplyKeyboardMarkup:
    # Ссылка несёт занятые окошки, чтобы приложение их зачеркнуло.
    # Именно reply-кнопка: только с неё приложение может вернуть заявку боту (sendData).
    busy = ",".join(b["slot"] for b in upcoming())
    url = WEBAPP_URL + (("?busy=" + busy) if busy else "")
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="💅 Открыть приложение", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
    )


def is_admin(message: Message) -> bool:
    return bool(ADMIN_ID) and message.from_user.id == ADMIN_ID


# ---------- клиент ----------
@dp.message(CommandStart())
async def start(message: Message):
    global ADMIN_ID
    if not ADMIN_ID:
        ADMIN_ID = message.from_user.id
        save_env("ADMIN_ID", str(ADMIN_ID))
        await message.answer(
            "👑 Вы назначены мастером — заявки клиентов будут приходить сюда.\n\n"
            "/bookings — ближайшие записи\n/free 2026-11-24 12:00 — освободить окошко"
        )
    await message.answer(
        "Добро пожаловать в WWP nail studio 🤍\n\n"
        f"Здесь можно записаться к мастеру {MASTER_NAME} на маникюр 💅\n"
        "А во время процедуры — расклад Таро или разбор матрицы судьбы, "
        "натальной карты, чакр в подарок 🔮\n\n"
        "Нажмите кнопку внизу, чтобы открыть приложение 👇",
        reply_markup=app_keyboard(),
    )


@dp.message(F.web_app_data)
async def on_order(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
        slot = data["slot"]
        datetime.strptime(slot, "%Y-%m-%dT%H:%M")
    except (json.JSONDecodeError, KeyError, ValueError):
        await message.answer("Не получилось прочитать заявку, попробуйте ещё раз 🙏", reply_markup=app_keyboard())
        return

    bookings = load_bookings()
    if any(b["slot"] == slot for b in bookings):
        await message.answer(
            "Ой, это время только что заняли 😔 Откройте приложение и выберите другое окошко.",
            reply_markup=app_keyboard(),
        )
        return

    u = message.from_user
    who = f"@{u.username}" if u.username else u.full_name
    items = "\n".join(f"• {i}" for i in data.get("items", []))
    total = data.get("total")
    total_text = f"{total:,} ₽".replace(",", " ") if total else "уточнит мастер"
    when = data.get("when", slot)
    comment = data.get("comment") or "—"

    bookings.append({"slot": slot, "when": when, "user_id": u.id, "who": who, "items": data.get("items", [])})
    save_bookings(bookings)

    await message.answer(
        f"Готово! Вы записаны 🤍\n\n🗓 {when}\n{items}\n\nИтого: {total_text}\n\n"
        "Мастер напишет вам, чтобы подтвердить запись.",
        reply_markup=app_keyboard(),
    )

    if ADMIN_ID:
        mood = MOODS.get(data.get("mood"), "")
        await bot.send_message(
            ADMIN_ID,
            "🆕 Новая запись\n\n"
            f"🗓 {when}\n"
            f"Клиент: {who} (id {u.id})\n"
            f"{items}\n"
            + (f"Атмосфера: {mood}\n" if mood else "")
            + f"Итого: {total_text}\n"
            f"Комментарий: {comment}\n\n"
            f"Написать клиенту: tg://user?id={u.id}",
        )


# ---------- мастер ----------
@dp.message(Command("bookings"))
async def list_bookings(message: Message):
    if not is_admin(message):
        return
    items = upcoming()
    if not items:
        await message.answer("Ближайших записей нет.")
        return
    text = "\n\n".join(f"🗓 {b['when']}\n{b['who']}\n" + "\n".join(b["items"]) for b in items)
    await message.answer("Ближайшие записи:\n\n" + text)


@dp.message(Command("free"))
async def free_slot(message: Message):
    if not is_admin(message):
        return
    parts = (message.text or "").split()[1:]
    slot = "T".join(parts) if len(parts) == 2 else (parts[0] if parts else "")
    bookings = load_bookings()
    left = [b for b in bookings if b["slot"] != slot]
    if len(left) == len(bookings):
        await message.answer("Не нашёл такую запись. Пример: /free 2026-11-24 12:00")
        return
    save_bookings(left)
    await message.answer(f"Окошко {slot.replace('T', ' ')} снова свободно ✅", reply_markup=app_keyboard())


async def main():
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    print("Бот WWP запущен! Не закрывайте это окно. Остановить: Ctrl+C")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
