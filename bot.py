"""
WWP nail studio — два Telegram-бота в одной программе.

@wwpnailsbot        — для клиентов: /start → «💅 Открыть приложение» → запись.
@wwpnails_admin_bot — для команды: сюда приходят уведомления о записях.
                      Две роли: 💅 мастер и 🛡 админ. Первый, кто нажмёт /start, — админ;
                      остальные выбирают роль, админ одобряет.
  /bookings                 — ближайшие записи (мастер и админ)
  /free 2026-12-02 12:00    — освободить окошко (мастер и админ)
  /team                     — команда: сменить роль, убрать (только админ)

Занятые окошки бот публикует в файл busy.json на GitHub — приложение читает его
при каждом открытии, поэтому все клиенты сразу видят, какое время уже занято.
"""
import asyncio
import base64
import html
import json
import logging
import os
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           MenuButtonDefault, Message, ReplyKeyboardMarkup, WebAppInfo)
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
BOOKINGS_PATH = os.path.join(HERE, "bookings.json")
load_dotenv(ENV_PATH)

GITHUB_REPO = "icouldxlie/wwpnailsbot"
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://icouldxlie.github.io/wwpnailsbot/")
MASTER_NAME = os.environ.get("MASTER_NAME", "Вера")


def save_env(key: str, value: str):
    """Записывает или заменяет строку KEY=value в .env."""
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l and not l.startswith(key + "=")]
    except FileNotFoundError:
        lines = []
    lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def ask(key: str, prompt: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        value = input(prompt).strip()
        save_env(key, value)
    return value


BOT_TOKEN = ask("BOT_TOKEN", "1/3 Вставьте токен бота @wwpnailsbot и нажмите Enter: ")
ADMIN_BOT_TOKEN = ask("ADMIN_BOT_TOKEN", "2/3 Вставьте токен бота уведомлений @wwpnails_admin_bot и нажмите Enter: ")
GITHUB_TOKEN = ask("GITHUB_TOKEN", "3/3 Вставьте ключ GitHub (github_pat_...) и нажмите Enter: ")
TEAM_PATH = os.path.join(HERE, "team.json")
ROLES = {"admin": "🛡 Админ", "master": "💅 Мастер"}


def load_team() -> dict:
    """Команда студии: {telegram_id: "admin" | "master"}."""
    try:
        with open(TEAM_PATH, encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        # переход со старой версии: все, кто раньше получал записи, становятся админами
        old = (os.environ.get("ADMIN_IDS", "") + "," + os.environ.get("ADMIN_ID", "")).split(",")
        return {int(x): "admin" for x in old if x.strip().isdigit()}


def save_team():
    with open(TEAM_PATH, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in TEAM.items()}, f, ensure_ascii=False, indent=1)


TEAM = load_team()
save_team()

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)              # клиентский бот
admin_bot = Bot(ADMIN_BOT_TOKEN)  # бот уведомлений для мастера
dp = Dispatcher()
admin_dp = Dispatcher()

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


async def publish_busy():
    """Записывает занятые окошки в busy.json на GitHub, чтобы их видели все клиенты."""
    busy = [b["slot"] for b in upcoming()]
    body = json.dumps({"busy": busy, "updated": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False)
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/busy.json"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    try:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.get(url) as r:
                sha = (await r.json()).get("sha") if r.status == 200 else None
            payload = {"message": "Обновить занятые окошки", "content": base64.b64encode(body.encode()).decode()}
            if sha:
                payload["sha"] = sha
            async with s.put(url, json=payload) as r:
                if r.status not in (200, 201):
                    logging.warning("GitHub: не удалось обновить busy.json (%s): %s", r.status, await r.text())
                else:
                    logging.info("busy.json обновлён: %s", busy)
    except Exception as e:  # noqa: BLE001 — запись не должна падать из-за GitHub
        logging.warning("GitHub недоступен: %s", e)


def app_keyboard() -> ReplyKeyboardMarkup:
    # Занятые окошки передаются и в ссылке (на случай, если GitHub недоступен).
    # Именно reply-кнопка: только с неё приложение может вернуть заявку боту (sendData).
    busy = ",".join(b["slot"] for b in upcoming())
    url = WEBAPP_URL + (("?busy=" + busy) if busy else "")
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="💅 Открыть приложение", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
    )


async def notify_master(text: str, roles=("admin", "master"), **kwargs):
    """Отправляет сообщение команде (по умолчанию — и мастерам, и админам)."""
    targets = [uid for uid, r in TEAM.items() if r in roles]
    if not targets:
        logging.warning("В боте уведомлений ещё никого нет — нажмите там /start.")
    for uid in targets:
        try:
            await admin_bot.send_message(uid, text, parse_mode="HTML", **kwargs)
        except Exception as e:  # noqa: BLE001
            logging.warning("Не удалось отправить сообщение %s: %s", uid, e)


# ---------- клиентский бот ----------
@dp.message(CommandStart())
async def start(message: Message):
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

    mood = MOODS.get(data.get("mood"), "")
    day, _, hours = when.partition(" · ")
    e = html.escape
    client = (f"@{e(u.username)} ({e(u.full_name)})" if u.username
              else f'<a href="tg://user?id={u.id}">{e(u.full_name)}</a> (без юзернейма)')
    await notify_master(
        "🆕 <b>Новая запись</b>\n\n"
        f"📅 Дата: <b>{e(day)}</b>\n"
        f"🕐 Время: <b>{e(hours or slot[11:])}</b>\n"
        f"👤 Клиент: {client}\n\n"
        + "\n".join(f"💅 {e(i)}" for i in data.get("items", []) if not i.startswith("Атмосфера")) + "\n"
        + (f"Атмосфера: {mood}\n" if mood else "")
        + f"Итого: <b>{total_text}</b>\n"
        f"Комментарий: {e(comment)}\n\n"
        f'<a href="tg://user?id={u.id}">✉️ Написать клиенту</a>'
    )
    await publish_busy()


# ---------- бот уведомлений (для команды) ----------
def role_of(obj):
    return TEAM.get(obj.from_user.id)


def is_admin(obj) -> bool:
    return role_of(obj) == "admin"


def is_team(obj) -> bool:
    return role_of(obj) in ROLES


def help_text(role: str) -> str:
    text = (f"Ваша роль: {ROLES[role]}\n\nСюда приходят все новые записи 🤍\n\n"
            "/bookings — ближайшие записи\n"
            "/free 2026-12-02 12:00 — освободить окошко")
    if role == "admin":
        text += "\n/team — команда: роли и доступ"
    return text


async def user_name(uid: int) -> str:
    try:
        ch = await admin_bot.get_chat(uid)
        return f"@{ch.username}" if ch.username else (ch.full_name or str(uid))
    except Exception:  # noqa: BLE001
        return str(uid)


@admin_dp.message(CommandStart())
async def admin_start(message: Message):
    u = message.from_user
    if not TEAM:  # самый первый человек становится админом
        TEAM[u.id] = "admin"
        save_team()
    if is_team(message):
        await message.answer(help_text(role_of(message)))
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💅 Я мастер", callback_data="want:master"),
        InlineKeyboardButton(text="🛡 Я админ", callback_data="want:admin"),
    ]])
    await message.answer("Это бот команды студии WWP 🤍\nКто вы?", reply_markup=kb)


@admin_dp.callback_query(F.data.startswith("want:"))
async def on_want(call: CallbackQuery):
    role = call.data.split(":")[1]
    u = call.from_user
    who = f"@{u.username}" if u.username else u.full_name
    await call.message.edit_text(f"Вы выбрали: {ROLES[role]}\nЗапрос отправлен админу студии — как только его одобрят, сюда начнут приходить записи.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Разрешить", callback_data=f"ok:{u.id}:{role}"),
        InlineKeyboardButton(text="✖️ Нет", callback_data=f"no:{u.id}"),
    ]])
    await notify_master(
        f"🔑 {html.escape(who)} ({html.escape(u.full_name)}) хочет в команду как <b>{ROLES[role]}</b>.",
        roles=("admin",), reply_markup=kb,
    )
    await call.answer()


@admin_dp.callback_query(F.data.startswith("ok:") | F.data.startswith("no:"))
async def on_access(call: CallbackQuery):
    if not is_admin(call):
        await call.answer("Это может сделать только админ", show_alert=True)
        return
    parts = call.data.split(":")
    uid = int(parts[1])
    if parts[0] == "ok":
        TEAM[uid] = parts[2]
        save_team()
        await call.message.edit_text(call.message.text + f"\n\n✅ Добавлен как {ROLES[parts[2]]}")
        try:
            await admin_bot.send_message(uid, "Доступ одобрен ✅\n\n" + help_text(parts[2]))
        except Exception:  # noqa: BLE001
            pass
    else:
        await call.message.edit_text(call.message.text + "\n\n✖️ Отклонено")
    await call.answer()


async def team_view():
    rows, lines = [], []
    for uid, role in sorted(TEAM.items(), key=lambda x: x[1]):
        name = await user_name(uid)
        lines.append(f"{ROLES[role]} — {html.escape(name)}")
        other = "master" if role == "admin" else "admin"
        rows.append([
            InlineKeyboardButton(text=f"{name}: сделать {ROLES[other]}", callback_data=f"role:{uid}:{other}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del:{uid}"),
        ])
    return "Команда студии:\n\n" + "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@admin_dp.message(Command("team"))
async def show_team(message: Message):
    if not is_admin(message):
        return
    text, kb = await team_view()
    await message.answer(text, reply_markup=kb)


@admin_dp.callback_query(F.data.startswith("role:") | F.data.startswith("del:"))
async def on_team_edit(call: CallbackQuery):
    if not is_admin(call):
        await call.answer("Это может сделать только админ", show_alert=True)
        return
    parts = call.data.split(":")
    uid = int(parts[1])
    new_team = dict(TEAM)
    if parts[0] == "role":
        new_team[uid] = parts[2]
    else:
        new_team.pop(uid, None)
    if "admin" not in new_team.values():
        await call.answer("В команде должен остаться хотя бы один админ", show_alert=True)
        return
    TEAM.clear(); TEAM.update(new_team); save_team()
    text, kb = await team_view()
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Готово ✅")


@admin_dp.message(Command("bookings"))
async def list_bookings(message: Message):
    if not is_team(message):
        return
    items = upcoming()
    if not items:
        await message.answer("Ближайших записей нет.")
        return
    text = "\n\n".join(f"🗓 {b['when']}\n{b['who']}\n" + "\n".join(b["items"]) for b in items)
    await message.answer("Ближайшие записи:\n\n" + text)


@admin_dp.message(Command("free"))
async def free_slot(message: Message):
    if not is_team(message):
        return
    parts = (message.text or "").split()[1:]
    slot = "T".join(parts) if len(parts) == 2 else (parts[0] if parts else "")
    bookings = load_bookings()
    left = [b for b in bookings if b["slot"] != slot]
    if len(left) == len(bookings):
        await message.answer("Не нашёл такую запись. Пример: /free 2026-12-02 12:00")
        return
    save_bookings(left)
    await publish_busy()
    await message.answer(f"Окошко {slot.replace('T', ' ')} снова свободно ✅")


async def main():
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    await publish_busy()
    if not TEAM:
        print("👉 Откройте @wwpnails_admin_bot и нажмите «Старт» — первый человек станет админом.")
    print("Боты WWP запущены! Не закрывайте это окно. Остановить: Ctrl+C")
    await asyncio.gather(dp.start_polling(bot, handle_signals=False), admin_dp.start_polling(admin_bot, handle_signals=False))


if __name__ == "__main__":
    asyncio.run(main())
