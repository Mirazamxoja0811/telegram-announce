import sys
import os
import asyncio
import logging
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pyrogram import Client, filters, enums, idle
from pyrogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PhoneNumberInvalid,
    PasswordHashInvalid,
    RPCError,
    FloodWait
)

import database as db
import keyboards as kb
import scheduler as sc

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("TelegramAnnounceBot")

# Load environment variables
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("❌ ERROR: .env faylida API_ID, API_HASH yoki BOT_TOKEN kiritilmagan!")
    print("Iltimos, .env faylini to'ldiring!")

# Bot API Client
bot = Client(
    "announce_bot_service",
    api_id=int(API_ID) if API_ID and API_ID.isdigit() else 0,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Storage for dynamic Userbot clients: {user_id: Client}
active_user_clients = {}

# Storage for temporary user state (FSM): {user_id: {"state": str, ...}}
user_states = {}

# Storage for temporary group selection cache: {user_id: {"groups": list, "selected": set}}
group_selection_cache = {}


# --- USERBOT MANAGEMENT HELPERS ---

async def get_or_create_user_client(user_id: int):
    """
    DB dagi session_string bo'yicha userbot Pyrogram clientini faollashtiradi.
    """
    if user_id in active_user_clients:
        cli = active_user_clients[user_id]
        if cli.is_connected:
            return cli
        else:
            try:
                await cli.start()
                return cli
            except Exception:
                pass

    user_data = await db.get_user(user_id)
    session_str = user_data.get("session_string")
    if not session_str:
        return None

    try:
        user_cli = Client(
            name=f"user_session_{user_id}",
            api_id=int(API_ID),
            api_hash=API_HASH,
            session_string=session_str,
            in_memory=True
        )
        await user_cli.start()
        active_user_clients[user_id] = user_cli
        return user_cli
    except Exception as e:
        logger.error(f"Failed to start Userbot client for {user_id}: {e}")
        return None


# --- BOT HANDLERS ---

@bot.on_message(filters.private, group=-1)
async def log_incoming_messages(client: Client, message: Message):
    user_name = message.from_user.first_name if message.from_user else "Foydalanuvchi"
    print(f"📩 Telegramdan xabar keldi [{user_name}]: {message.text or '[Media]'}", flush=True)
    logger.info(f"📩 Telegramdan xabar keldi [{user_name}]: {message.text or '[Media]'}")

@bot.on_message((filters.command("start") | filters.regex(r"^/start")) & filters.private)
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    user_data = await db.get_user(user_id)
    user_states.pop(user_id, None)

    is_active = bool(user_data.get("is_active"))
    session_str = user_data.get("session_string")

    status_account = "🟢 Ulangan" if session_str else "🔴 Ulanmagan (Profilni ulash kerak)"

    welcome_text = (
        f"👋 **Assalomu alaykum, {message.from_user.first_name}!**\n\n"
        f"Ushbu bot orqali siz shaxsiy Telegram profilingiz nomidan guruhlarga "
        f"avtomatik ravishda e'lon va xabarlar tarqatishingiz mumkin.\n\n"
        f"📱 **Profil holati:** {status_account}\n"
        f"⏱ **Vaqt oralig'i:** `{user_data.get('interval_minutes', 10)}` minut\n"
        f"⚡️ **Tarqatish holati:** {'🟢 FAOL' if is_active else '⏹ TO\'XTATILGAN'}\n\n"
        f"Boshlash uchun pastdagi tugmalardan foydalaning:"
    )

    await message.reply_text(
        welcome_text,
        reply_markup=kb.main_keyboard(is_active=is_active)
    )

@bot.on_message(filters.private & filters.contact)
async def contact_menu_handler(client: Client, message: Message):
    state_data = user_states.get(message.from_user.id, {})
    if state_data.get("state") == "WAITING_PHONE":
        await process_phone_input(message)


@bot.on_message(filters.private & filters.text & ~filters.regex(r"^/"))
async def text_menu_handler(client: Client, message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    state_data = user_states.get(user_id, {})
    current_state = state_data.get("state")

    # Cancel command check
    if text == "❌ Bekor qilish" or text == "/cancel":
        user_states.pop(user_id, None)
        user_data = await db.get_user(user_id)
        await message.reply_text(
            "🔴 Amaliyot bekor qilindi.",
            reply_markup=kb.main_keyboard(is_active=bool(user_data.get("is_active")))
        )
        return

    # FSM State processing
    if current_state == "WAITING_PHONE":
        await process_phone_input(message)
        return
    elif current_state == "WAITING_CODE":
        await process_code_input(message)
        return
    elif current_state == "WAITING_PASSWORD":
        await process_password_input(message)
        return
    elif current_state == "WAITING_MESSAGE":
        await process_message_input(message)
        return
    elif current_state == "WAITING_CUSTOM_INTERVAL":
        await process_custom_interval_input(message)
        return

    # Menu Buttons Handlers
    user_data = await db.get_user(user_id)
    is_active = bool(user_data.get("is_active"))

    if text == "📊 Holati (Dashboard)":
        await show_dashboard(message)

    elif text in ["▶️ Tarqatishni boshlash", "⏹ Tarqatishni to'xtatish"]:
        await toggle_broadcast(message)

    elif text == "📥 Guruhlarni tanlash":
        await open_groups_menu(message)

    elif text == "⏱ Vaqtni belgilash":
        await message.reply_text(
            "⏱ **Xabarlarni yuborish oralig'ini tanlang:**\n"
            "Bot belgilangan har X minutda bir xil e'loningizni barcha saqlangan guruhlarga yuborib turadi.",
            reply_markup=kb.interval_keyboard()
        )

    elif text == "📝 Xabarni sozlash":
        user_states[user_id] = {"state": "WAITING_MESSAGE"}
        cancel_kb = ReplyKeyboardMarkup([[KeyboardButton("❌ Bekor qilish")]], resize_keyboard=True)
        await message.reply_text(
            "📝 **Tarqatiladigan xabarni yuboring:**\n\n"
            "Siz oddiy matn, rasmli matn yoki videoli matn yuborishingiz mumkin.\n"
            "Siz yuborgan xabar xuddi shunday shaklda profilingiz nomidan guruhlarga boradi.",
            reply_markup=cancel_kb
        )

    elif text == "⚡️ 1 marta yuborib ko'rish":
        user_cli = await get_or_create_user_client(user_id)
        if not user_cli:
            await message.reply_text("❌ **Profil ulangan emas!**\nIltimos, avval '🔑 Akkauntni ulash' tugmasi orqali profilingizni ulang.")
            return
        await sc.run_broadcast_for_user(user_id, user_cli, bot, is_manual_trigger=True)

    elif text == "🔑 Akkauntni ulash / Almashtirish":
        user_states[user_id] = {"state": "WAITING_PHONE"}
        cancel_kb = ReplyKeyboardMarkup([[KeyboardButton("❌ Bekor qilish")]], resize_keyboard=True)
        await message.reply_text(
            "📲 **Telegram profilingiz telefon raqamini kiritib yuboring:**\n"
            "Format: `+998901234567`\n\n"
            "⚠️ *Eslatma: Bot profilingiz nomidan guruhlarga xabar yuborishi uchun xavfsiz SMS-kod orqali tasdiqlanadi.*",
            reply_markup=kb.phone_keyboard()
        )

    elif text == "❓ Yordam va Qo'llanma":
        help_text = (
            "📖 **Botdan foydalanish bo'yicha yo'riqnoma:**\n\n"
            "1️⃣ **Akkauntni ulash:** '🔑 Akkauntni ulash' tugmasini bosing va telefon raqamingiz hamda kodingizni kiriting.\n"
            "2️⃣ **Guruhlarni tanlash:** '📥 Guruhlarni tanlash' tugmasini bosing, profilingizdagi barcha guruhlar ro'yxati chiqadi. Kerakli guruhlarga belgi qo'ying va '💾 SAQLASH' tugmasini bosing.\n"
            "3️⃣ **Xabar kiritish:** '📝 Xabarni sozlash' tugmasini bosib e'loningizni yuboring.\n"
            "4️⃣ **Vaqtni sozlash:** '⏱ Vaqtni belgilash' bo'limidan har necha minutda yuborilishini belgilang (Masalan: 10 minut).\n"
            "5️⃣ **Boshlash:** '▶️ Tarqatishni boshlash' tugmasini bosing!\n\n"
            "💡 *Bot har 10 minutda (yoki siz belgilagan vaqtda) fonda e'loningizni barcha guruhlarga yuborib turadi!*"
        )
        await message.reply_text(help_text)


# --- MEDIA MESSAGE RECEIVER ---

@bot.on_message(filters.private & (filters.photo | filters.video))
async def media_message_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state_data = user_states.get(user_id, {})
    if state_data.get("state") == "WAITING_MESSAGE":
        await process_message_input(message)


# --- DASHBOARD & BROADCAST TOGGLE ---

async def show_dashboard(message: Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    groups = await db.get_selected_groups(user_id)
    
    session_str = user.get("session_string")
    acc_status = "🟢 Ulangan" if session_str else "🔴 Ulanmagan"
    is_act = bool(user.get("is_active"))
    broad_status = "🟢 YUBORILMOQDA (FAOL)" if is_act else "⏹ TO'XTATILGAN"

    msg_type = user.get("message_type", "text")
    msg_text = user.get("message_text") or user.get("message_caption")
    if not msg_text and not user.get("message_file_id"):
        msg_preview = "❌ Kiritilmagan"
    else:
        msg_preview = f"[{msg_type.upper()}] " + ((msg_text[:40] + "...") if msg_text else "Media fayl")

    dashboard_text = (
        f"📊 **SIZNING BOT HOLATl (DASHBOARD)**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Profil ulanishi:** {acc_status}\n"
        f"⚡️ **Tarqatish holati:** {broad_status}\n"
        f"⏱ **Vaqt oralig'i:** Har `{user.get('interval_minutes', 10)}` minutda\n"
        f"👥 **Tanlangan guruhlar:** `{len(groups)}` ta guruh\n"
        f"📝 **Xabar kontenti:** {msg_preview}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )
    await message.reply_text(dashboard_text, reply_markup=kb.main_keyboard(is_active=is_act))


async def toggle_broadcast(message: Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    is_active = bool(user.get("is_active"))

    if not is_active:
        # Check requirements
        if not user.get("session_string"):
            await message.reply_text("❌ **Boshlash uchun avval profilingizni ulashingiz kerak!** ('🔑 Akkauntni ulash' tugmasi)")
            return
        
        groups = await db.get_selected_groups(user_id)
        if not groups:
            await message.reply_text("❌ **Hech qanday guruh tanlanmagan!**\nAvval '📥 Guruhlarni tanlash' tugmasi orqali guruhlarni tanlang.")
            return

        if not user.get("message_text") and not user.get("message_file_id"):
            await message.reply_text("❌ **Tarqatish uchun xabar kiritilmagan!**\n'📝 Xabarni sozlash' bo'limidan e'loningizni kiriting.")
            return

        # Start job
        await db.update_user(user_id, is_active=1)
        user_cli = await get_or_create_user_client(user_id)
        sc.schedule_user_job(user_id, user.get("interval_minutes", 10), user_cli, bot)
        
        await message.reply_text(
            "🚀 **AVTO-TARQATISH MUVAFFAQIYATLI BOSHLANDI!**\n\n"
            f"Bot har `{user.get('interval_minutes', 10)}` minutda e'loningizni `{len(groups)}` ta guruhga profil nomidan yuborib turadi.",
            reply_markup=kb.main_keyboard(is_active=True)
        )
    else:
        # Stop job
        await db.update_user(user_id, is_active=0)
        sc.stop_user_job(user_id)
        await message.reply_text(
            "⏹ **Avto-tarqatish to'xtatildi.**",
            reply_markup=kb.main_keyboard(is_active=False)
        )


# --- GROUP SELECTION LOGIC ---

async def open_groups_menu(message: Message):
    user_id = message.from_user.id
    user_cli = await get_or_create_user_client(user_id)
    
    if not user_cli:
        await message.reply_text("❌ **Profilingiz ulangan emas!**\nIltimos, '🔑 Akkauntni ulash' tugmasi orqali profilingizni ulang.")
        return

    loading_msg = await message.reply_text("🔄 **Profilingizdagi barcha guruhlar ro'yxati yuklanmoqda...**\nIltimos, biroz kuting...")

    all_groups = []
    try:
        async for dialog in user_cli.get_dialogs():
            if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                all_groups.append({
                    "group_id": dialog.chat.id,
                    "group_title": dialog.chat.title or "Nomsiz Guruh"
                })
            unique_groups = {}
            for group in all_groups:
                title = group["group_title"]
                existing = unique_groups.get(title)
                if existing is None or (group["group_id"] < -1000000000000 and existing["group_id"] > -1000000000000):
                    unique_groups[title] = group
            all_groups = list(unique_groups.values())
    except Exception as e:
        logger.error(f"Error fetching dialogs for {user_id}: {e}")
        await loading_msg.edit_text("❌ Guruhlarni yuklashda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
        return

    db_selected = await db.get_selected_groups(user_id)
    available_ids = {group["group_id"] for group in all_groups}
    selected_set = {
        group["group_id"] for group in db_selected
        if group["group_id"] in available_ids
    }

    group_selection_cache[user_id] = {
        "groups": all_groups,
        "selected": selected_set
    }

    await loading_msg.delete()
    await message.reply_text(
        f"📥 **GURUHLARNI TANLASH MENYUSI**\n\n"
        f"Jami profildagi guruhlar: `{len(all_groups)}` ta\n"
        f"Hozirda tanlangan: `{len(selected_set)}` ta\n\n"
        f"Tugmalarni bosish orqali kerakli guruhlarni tanlang:",
        reply_markup=kb.groups_keyboard(all_groups, selected_set, page=0)
    )


# --- CALLBACK QUERY HANDLER FOR MULTI-SELECT & INTERVALS ---

@bot.on_callback_query()
async def callback_handler(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data

    if data == "nop":
        await callback.answer()
        return

    if data == "cancel_action":
        await callback.message.delete()
        await callback.answer("Bekor qilindi.")
        return

    # --- NUMERIC KEYPAD CALLBACKS FOR SMS LOGIN CODE ---
    if data.startswith("num_"):
        state_data = user_states.get(user_id, {})
        if state_data.get("state") != "WAITING_CODE":
            await callback.answer("⚠️ Seans faol emas. Qaytadan /start bosing.", show_alert=True)
            return

        entered_code = state_data.get("entered_code", "")
        phone = state_data.get("phone", "")
        temp_client = state_data.get("temp_client")

        action = data.replace("num_", "")

        if action.isdigit():
            if len(entered_code) < 5:
                entered_code += action
                state_data["entered_code"] = entered_code

        elif action == "del":
            if len(entered_code) > 0:
                entered_code = entered_code[:-1]
                state_data["entered_code"] = entered_code

        elif action == "clear":
            entered_code = ""
            state_data["entered_code"] = ""

        elif action == "resend":
            try:
                code_info = await temp_client.send_code(phone)
                state_data["phone_code_hash"] = code_info.phone_code_hash
                state_data["entered_code"] = ""
                entered_code = ""
                await callback.answer("📩 Yangi kod yuborildi!", show_alert=True)
            except Exception as e:
                await callback.answer(f"❌ Kod yuborishda xatolik: {e}", show_alert=True)
                return

        # Render display
        digits = list(entered_code) + ["_"] * (5 - len(entered_code))
        disp_code = "  ".join(digits[:5])

        if len(entered_code) < 5:
            try:
                await callback.message.edit_text(
                    f"📩 `{phone}` raqamiga Telegram tasdiqlash kodi yuborildi!\n\n"
                    f"📱 **Kiritilayotgan kod:** ` {disp_code} `\n\n"
                    f"Pastdagi raqamli tugmalarni bosib kodni tering yoki klaviaturadan yozing:",
                    reply_markup=kb.code_keypad_keyboard()
                )
            except Exception:
                pass
            await callback.answer()

        elif len(entered_code) == 5:
            await callback.answer("⏳ Kod tekshirilmoqda...")
            await verify_and_sign_in(user_id, entered_code, callback.message)
            return

    # --- INTERVAL CALLBACKS ---
    if data.startswith("set_int_"):
        val = data.replace("set_int_", "")
        if val == "custom":
            user_states[user_id] = {"state": "WAITING_CUSTOM_INTERVAL"}
            await callback.message.edit_text(
                "✍️ **Vaqt oralig'ini minutda kiriting:**\n(Masalan: `7`, `20`, `45`...)"
            )
            await callback.answer()
            return
        
        minutes = int(val)
        await db.update_user(user_id, interval_minutes=minutes)
        user = await db.get_user(user_id)
        if user.get("is_active"):
            user_cli = await get_or_create_user_client(user_id)
            sc.schedule_user_job(user_id, minutes, user_cli, bot)

        await callback.message.edit_text(f"✅ **Vaqt oralig'i har `{minutes}` minutga o'zgartirildi!**")
        await callback.answer("Vaqt saqlandi!")
        return

    # --- MULTI-SELECT GROUP CALLBACKS ---
    if data == "refresh_groups":
        await callback.message.delete()
        await open_groups_menu(callback.message)
        await callback.answer()
        return

    if data == "close_groups":
        await callback.message.delete()
        await callback.answer("Yopildi.")
        return

    cache = group_selection_cache.get(user_id)

    if data.startswith("grp_"):
        if not cache:
            await callback.answer("⚠️ Seans muddati o'tdi. Menyu qaytadan oching.", show_alert=True)
            return

        all_groups = cache["groups"]
        selected_set = cache["selected"]

        if data.startswith("grp_page_"):
            page = int(data.replace("grp_page_", ""))
            await callback.message.edit_reply_markup(
                reply_markup=kb.groups_keyboard(all_groups, selected_set, page=page)
            )
            await callback.answer()

        elif data.startswith("grp_toggle_"):
            payload = data.replace("grp_toggle_", "")
            g_id_str, page_str = payload.rsplit("_", 1)
            group_id = int(g_id_str)
            page = int(page_str)

            if group_id in selected_set:
                selected_set.remove(group_id)
            else:
                selected_set.add(group_id)

            await callback.message.edit_reply_markup(
                reply_markup=kb.groups_keyboard(all_groups, selected_set, page=page)
            )
            await callback.answer()

        elif data.startswith("grp_select_all_"):
            page = int(data.replace("grp_select_all_", ""))
            for g in all_groups:
                selected_set.add(g["group_id"])

            await callback.message.edit_reply_markup(
                reply_markup=kb.groups_keyboard(all_groups, selected_set, page=page)
            )
            await callback.answer("Barchasi tanlandi!")

        elif data.startswith("grp_clear_all_"):
            page = int(data.replace("grp_clear_all_", ""))
            selected_set.clear()

            await callback.message.edit_reply_markup(
                reply_markup=kb.groups_keyboard(all_groups, selected_set, page=page)
            )
            await callback.answer("Ro'yxat tozalandi!")

    elif data == "save_groups":
        if not cache:
            await callback.answer("Xatolik yuz berdi.", show_alert=True)
            return

        selected_set = cache["selected"]
        all_groups_map = {g["group_id"]: g["group_title"] for g in cache["groups"]}

        await db.clear_selected_groups(user_id)
        groups_to_save = [
            {"group_id": gid, "group_title": all_groups_map.get(gid, "Guruh")}
            for gid in selected_set
        ]
        await db.select_all_groups(user_id, groups_to_save)

        group_selection_cache.pop(user_id, None)

        await callback.message.edit_text(
            f"✅ **MUVAFFAQIYATLI SAQLANDI!**\n\nJami `{len(selected_set)}` ta guruh saqlandi."
        )
        await callback.answer("Saqlandi!")


# --- INPUT PROCESSORS ---

async def process_custom_interval_input(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if not text.isdigit() or int(text) <= 0:
        await message.reply_text("❌ Iltimos, faqat musbat raqam kiriting (masalan: 15):")
        return

    minutes = int(text)
    user_states.pop(user_id, None)
    await db.update_user(user_id, interval_minutes=minutes)

    user = await db.get_user(user_id)
    if user.get("is_active"):
        user_cli = await get_or_create_user_client(user_id)
        sc.schedule_user_job(user_id, minutes, user_cli, bot)

    await message.reply_text(
        f"✅ **Vaqt oralig'i har `{minutes}` minutga belgilandi!**",
        reply_markup=kb.main_keyboard(is_active=bool(user.get("is_active")))
    )


async def process_message_input(message: Message):
    user_id = message.from_user.id
    
    if message.text:
        await db.update_user(
            user_id,
            message_type="text",
            message_text=message.text,
            message_file_id=None,
            message_caption=None
        )
    elif message.photo:
        file_id = message.photo.file_id
        caption = message.caption or ""
        await db.update_user(
            user_id,
            message_type="photo",
            message_text=None,
            message_file_id=file_id,
            message_caption=caption
        )
    elif message.video:
        file_id = message.video.file_id
        caption = message.caption or ""
        await db.update_user(
            user_id,
            message_type="video",
            message_text=None,
            message_file_id=file_id,
            message_caption=caption
        )
    else:
        await message.reply_text("⚠️ Faqat matn, rasm yoki video yuborishingiz mumkin!")
        return

    user_states.pop(user_id, None)
    user_data = await db.get_user(user_id)
    
    await message.reply_text(
        "✅ **Tarqatiladigan xabaringiz muvaffaqiyatli saqlandi!**",
        reply_markup=kb.main_keyboard(is_active=bool(user_data.get("is_active")))
    )


# --- PHONE LOGIN FLOW PROCESSORS ---

async def verify_and_sign_in(user_id: int, code: str, target_msg: Message):
    state_data = user_states.get(user_id, {})
    temp_client: Client = state_data.get("temp_client")
    phone = state_data.get("phone")
    phone_code_hash = state_data.get("phone_code_hash")

    if not temp_client:
        await target_msg.reply_text("❌ Seans xatoligi. Qaytadan /start bosing.")
        user_states.pop(user_id, None)
        return

    try:
        await temp_client.sign_in(phone_number=phone, phone_code_hash=phone_code_hash, phone_code=code)
        
        session_string = await temp_client.export_session_string()
        await db.update_user(user_id, phone_number=phone, session_string=session_string)

        active_user_clients[user_id] = temp_client
        user_states.pop(user_id, None)

        await target_msg.edit_text(
            "🎉 **PROFILINGIZ MUVAFFAQIYATLI ULANDI!**\n\n"
            "Endi '📥 Guruhlarni tanlash' tugmasi orqali e'lon yuboriladigan guruhlarni belgilashingiz mumkin.",
            reply_markup=None
        )
        await target_msg.reply_text(
            "Asosiy menyu:",
            reply_markup=kb.main_keyboard()
        )
    except SessionPasswordNeeded:
        user_states[user_id]["state"] = "WAITING_PASSWORD"
        await target_msg.edit_text(
            "🔐 **Akkauntingizda ikki bosqichli tasdiqlash (2FA Parol) yoqilgan!**\n\n"
            "Iltimos, Telegram parolingizni kiritib yuboring:",
            reply_markup=None
        )
    except PhoneCodeInvalid:
        state_data["entered_code"] = ""
        disp_code = " _ " * 5
        await target_msg.edit_text(
            f"❌ **Tasdiqlash kodi noto'g'ri kiritildi!**\n\n"
            f"📩 `{phone}` raqamiga yuborilgan 5 xonali kodni qayta tering:\n"
            f"📱 **Kiritilayotgan kod:** `{disp_code}`",
            reply_markup=kb.code_keypad_keyboard()
        )
    except PhoneCodeExpired:
        await temp_client.disconnect()
        user_states.pop(user_id, None)
        await target_msg.edit_text(
            "❌ **Kodning amal qilish muddati tugadi.**\nIltimos, '🔑 Akkauntni ulash' tugmasi orqali qaytadan ulaning.",
            reply_markup=None
        )
    except Exception as e:
        await temp_client.disconnect()
        user_states.pop(user_id, None)
        logger.error(f"Sign in error: {e}")
        await target_msg.edit_text(f"❌ Xatolik yuz berdi: {e}", reply_markup=None)


async def process_phone_input(message: Message):
    user_id = message.from_user.id
    if message.contact:
        if message.contact.user_id and message.contact.user_id != user_id:
            await message.reply_text(
                "❌ Iltimos, o'zingizning telefon raqamingizni yuboring.",
                reply_markup=kb.phone_keyboard()
            )
            return
        phone = message.contact.phone_number.replace(" ", "")
    else:
        phone = (message.text or "").strip().replace(" ", "")

    if not phone.startswith("+"):
        await message.reply_text(
            "❌ Raqam `+` belgisi bilan boshlanishi kerak. Qaytadan yuboring:",
            reply_markup=kb.phone_keyboard()
        )
        return

    status_msg = await message.reply_text("⏳ **Telegram tasdiqlash kodi yuborilmoqda...**")

    temp_client = Client(
        name=f"temp_user_{user_id}",
        api_id=int(API_ID),
        api_hash=API_HASH,
        in_memory=True
    )
    
    try:
        await temp_client.connect()
        code_info = await temp_client.send_code(phone)
        
        user_states[user_id] = {
            "state": "WAITING_CODE",
            "phone": phone,
            "phone_code_hash": code_info.phone_code_hash,
            "temp_client": temp_client,
            "entered_code": ""
        }

        disp_code = " _ " * 5
        await status_msg.edit_text(
            f"📩 `{phone}` raqamiga Telegram tasdiqlash kodi yuborildi!\n\n"
            f"📱 **Kiritilayotgan kod:** `{disp_code}`\n\n"
            f"Pastdagi raqamli tugmalarni bosib kodni tering yoki klaviaturadan yozing:",
            reply_markup=kb.code_keypad_keyboard()
        )
    except PhoneNumberInvalid:
        await temp_client.disconnect()
        await status_msg.edit_text("❌ Telegram telefon raqami noto'g'ri kiritildi. Qaytadan kiriting:")
    except Exception as e:
        await temp_client.disconnect()
        logger.error(f"Send code error for {phone}: {e}")
        await status_msg.edit_text(f"❌ Kodni yuborishda xatolik: {e}")


async def process_code_input(message: Message):
    import re
    user_id = message.from_user.id
    code = re.sub(r'\D', '', message.text or "")
    
    if not code:
        await message.reply_text("⚠️ Kod topilmadi. Iltimos, kelgan 5 xonali kodni yuboring (Masalan: 12345):")
        return
        
    status_msg = await message.reply_text("⏳ **Kod tekshirilmoqda...**")
    await verify_and_sign_in(user_id, code, status_msg)


async def process_password_input(message: Message):
    user_id = message.from_user.id
    password = message.text.strip()
    state_data = user_states.get(user_id, {})
    temp_client: Client = state_data.get("temp_client")

    if not temp_client:
        await message.reply_text("❌ Seans xatoligi. Qayta urining.")
        user_states.pop(user_id, None)
        return

    status_msg = await message.reply_text("⏳ Parol tekshirilmoqda...")

    try:
        await temp_client.check_password(password)
        session_string = await temp_client.export_session_string()
        await db.update_user(user_id, session_string=session_string)

        active_user_clients[user_id] = temp_client
        user_states.pop(user_id, None)

        await status_msg.edit_text(
            "🎉 **PROFILINGIZ MUVAFFAQIYATLI ULANDI!**\n\n"
            "Endi '📥 Guruhlarni tanlash' tugmasi orqali e'lon yuboriladigan guruhlarni belgilashingiz mumkin."
        )
        await status_msg.reply_text("Asosiy menyu:", reply_markup=kb.main_keyboard())
    except PasswordHashInvalid:
        await status_msg.edit_text("❌ Parol noto'g'ri kiritildi. Qaytadan kiriting:")
    except Exception as e:
        await temp_client.disconnect()
        user_states.pop(user_id, None)
        logger.error(f"2FA error: {e}")
        await status_msg.edit_text(f"❌ Xatolik yuz berdi: {e}")


# --- STARTUP FUNCTION ---

async def main():
    print("🚀 Bot ishga tushmoqda...", flush=True)
    
    # Check if .env has placeholder values
    if not API_ID or not API_HASH or not BOT_TOKEN or API_ID == "12345678" or "your_api_hash" in str(API_HASH):
        print("\n" + "=" * 60)
        print("❌ XATOLIK: .env FAYLIDAGI SOZLAMALAR TO'LDIRILMAGAN!")
        print("=" * 60)
        print("Siz hali .env fayliga haqiqiy Telegram API ma'lumotlarini kiritmadingiz.\n")
        print("📌 Qadamlar:")
        print("1. https://my.telegram.org saytiga kirib API_ID va API_HASH oling.")
        print("2. @BotFather botidan yangi bot yaratib BOT_TOKEN oling.")
        print("3. Telegram_announce/.env faylini ochib ularni yozing va saqlang.")
        print("=" * 60 + "\n")
        return

    await db.init_db()
    sc.start_scheduler()
    
    try:
        await bot.start()
        bot_info = await bot.get_me()
        print(f"🤖 Bot muvaffaqiyatli faollashdi: @{bot_info.username}", flush=True)
        print("Bot tayyor! Telegramda /start tugmasini bosing.", flush=True)
        await idle()
    except FloodWait as e:
        print("\n" + "=" * 60)
        print(f"⚠️ TELEGRAM FLOOD WAIT DETEKT QILINDI ({e.value} sekund):")
        print(f"Telegram serverlari {round(e.value / 60)} daqiqa kutishni talab qilmoqda.")
        print("💡 TEZKOR YECHIM: Wait vaqtini kutmaslik uchun @BotFather botiga kirib,")
        print("   botingiz uchun /revoke bosing va yangi BOT_TOKEN olib .env fayliga yozing!")
        print("=" * 60)
        return
    except RPCError as e:
        print("\n" + "=" * 60)
        print("❌ TELEGRAM API XATOLIGI DETEKT QILINDI:")
        print(f"Batafsil xato: {e}")
        print("=" * 60)
        session_file = "announce_bot_service.session"
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                print("🧹 Eski/Buzilgan session fayli tozalandi.")
            except Exception:
                pass
        return
    except Exception as e:
        print(f"❌ Kutilmagan xatolik yuz berdi: {e}", flush=True)
        return
    finally:
        if bot.is_connected:
            await bot.stop()

if __name__ == "__main__":
    try:
        bot.run(main())
    except KeyboardInterrupt:
        print("\nBot to'xtatildi.")
