import asyncio
import random
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram.errors import FloodWait, RPCError
import database as db

logger = logging.getLogger("scheduler")

scheduler = AsyncIOScheduler()

def start_scheduler():
    if not scheduler.running:
        scheduler.start()

# Track active user jobs: {user_id: job_instance}
user_jobs = {}

async def run_broadcast_for_user(user_id: int, user_client, bot_client, is_manual_trigger: bool = False, immediate_report: bool = False):
    """
    Userbot profil nomidan tanlangan guruhlarga xabar yuborish funksiyasi.
    """
    if not user_client:
        if is_manual_trigger:
            await bot_client.send_message(user_id, "❌ **Profil ulangan emas!**\n'🔑 Akkauntni ulash' bo'limi orqali profilingizni ulang.")
        return

    if not user_client.is_connected:
        try:
            await user_client.start()
        except Exception as e:
            logger.error(f"Could not connect userbot for user {user_id}: {e}")
            if is_manual_trigger:
                await bot_client.send_message(user_id, f"❌ **Profilga ulanishda xatolik:** {e}")
            return

    user = await db.get_user(user_id)
    if not user:
        return
    
    if not is_manual_trigger and user.get("is_active") != 1:
        logger.info(f"User {user_id} broadcasts are disabled.")
        return

    sub_end_str = user.get("subscription_end")
    if sub_end_str:
        sub_end = datetime.fromisoformat(sub_end_str)
        if datetime.now() > sub_end:
            if is_manual_trigger:
                await bot_client.send_message(user_id, "❌ **Obunangiz muddati tugagan yoki mavjud emas!**\nIltimos, '💎 Obuna bo'lish' tugmasi orqali obuna sotib oling.")
            else:
                await bot_client.send_message(user_id, "❌ **Obunangiz muddati tugadi!** Avto-tarqatish to'xtatildi.\nIltimos, '💎 Obuna bo'lish' orqali obunani yangilang.")
                await db.update_user(user_id, is_active=0)
            return
            
        time_left = sub_end - datetime.now()
        if 0 < time_left.total_seconds() < 86400:
            warned_date = user.get("sub_warning_date")
            today = datetime.now().strftime("%Y-%m-%d")
            if warned_date != today:
                await bot_client.send_message(
                    user_id,
                    f"⚠️ Pro obunangiz tugashiga 1 kun qoldi.\n\n"
                    f"⏰ Ertaga obuna muddati tugaydi.\n"
                    f"Avto xabar ishlashida uzilish bo'lmasligi uchun bugun uzaytirib qo'ying.\n\n"
                    f"⭐️ Pro obunani hozir yangilashingiz mumkin.\n"
                    f"📅 Tugash vaqti: {sub_end.strftime('%d.%m.%Y %H:%M')}"
                )
                await db.update_user(user_id, sub_warning_date=today)
    else:
        if is_manual_trigger:
            await bot_client.send_message(user_id, "❌ **Obunangiz mavjud emas!**\nIltimos, '💎 Obuna bo'lish' tugmasi orqali obuna sotib oling.")
        return

    groups = await db.get_selected_groups(user_id)
    if not groups:
        if is_manual_trigger:
            await bot_client.send_message(user_id, "⚠️ **Hali hech qanday guruh tanlanmagan!**\nIltimos, avval '📥 Guruhlarni tanlash' menyusidan guruhlarni tanlang.")
        return

    msg_type = user.get("message_type", "text")
    msg_text = user.get("message_text")
    msg_file_id = user.get("message_file_id")
    msg_caption = user.get("message_caption")

    if not msg_text and not msg_file_id:
        if is_manual_trigger:
            await bot_client.send_message(user_id, "⚠️ **Tarqatish uchun xabar kiritilmagan!**\nIltimos, '📝 Xabarni sozlash' menyusi orqali e'lon matnini yoki rasmini yuboring.")
        return

    success_count = 0
    fail_count = 0

    if is_manual_trigger or immediate_report:
        status_msg = await bot_client.send_message(user_id, f"🚀 **Xabar tarqatish boshlandi...**\nJami tanlangan guruhlar: `{len(groups)}` ta")

    fetched_dialogs = False

    for g in groups:
        group_id = g["group_id"]
        group_title = g["group_title"]

        try:
            # Xabarni unikal qilish uchun ko'rinmas belgi qo'shamiz (hash spam filterga tushmaslik uchun)
            unique_suffix = f"\n\n\u200c"
            
            async def _send():
                if msg_type == "text":
                    await user_client.send_message(chat_id=group_id, text=msg_text + unique_suffix)
                elif msg_type == "photo":
                    await user_client.send_photo(chat_id=group_id, photo=msg_file_id, caption=(msg_caption or "") + unique_suffix)
                elif msg_type == "video":
                    await user_client.send_video(chat_id=group_id, video=msg_file_id, caption=(msg_caption or "") + unique_suffix)

            try:
                await _send()
            except Exception as e:
                if "PEER_ID_INVALID" in str(e) and not fetched_dialogs:
                    logger.warning(f"PeerIdInvalid for {group_id}. Fetching dialogs to build cache...")
                    async for _ in user_client.get_dialogs(limit=200): pass
                    fetched_dialogs = True
                    await _send() # Retry sending
                else:
                    raise e
            
            success_count += 1
            # Anti-spam delay between groups (5 to 12 seconds)
            await asyncio.sleep(random.uniform(5.0, 12.0))

        except FloodWait as e:
            logger.warning(f"FloodWait encountered for user {user_id}: {e.value} seconds")
            fail_count += 1
            await asyncio.sleep(e.value + 1)
        except RPCError as e:
            logger.error(f"Failed to send to group {group_title} ({group_id}): {e}")
            fail_count += 1
        except Exception as e:
            logger.error(f"Unexpected error sending to {group_id}: {e}")
            fail_count += 1

    report_text = (
        f"📊 **Xabar tarqatish yakunlandi!**\n\n"
        f"✅ Muvaffaqiyatli yuborildi: `{success_count}` ta guruhga\n"
        f"❌ Xatolik yuz berdi: `{fail_count}` ta guruhda\n"
        f"👥 Jami saqlangan guruhlar: `{len(groups)}` ta"
    )

    if success_count > 0:
        await db.increment_sent_count(user_id, success_count)

    if is_manual_trigger or immediate_report:
        try:
            await bot_client.send_message(user_id, report_text)
        except Exception as e:
            logger.error(f"Failed to send report to bot user {user_id}: {e}")

    # Yangi tasodifiy interval bilan keyingi tarqatishni rejalashtirish
    if not is_manual_trigger:
        next_run_minutes = random.randint(5, 15)
        run_date = datetime.now() + timedelta(minutes=next_run_minutes)
        
        job_id = f"user_broadcast_{user_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            
        job = scheduler.add_job(
            run_broadcast_for_user,
            "date",
            run_date=run_date,
            id=job_id,
            args=[user_id, user_client, bot_client, False, False],
            replace_existing=True
        )
        user_jobs[user_id] = job
        logger.info(f"Rescheduled next broadcast for user {user_id} in {next_run_minutes} minutes.")

def schedule_user_job(user_id: int, interval_minutes: int, user_client, bot_client, immediate_report: bool = False):
    """
    Foydalanuvchi uchun interval bo'yicha fonda vazifa yaratadi yoki yangilaydi.
    """
    job_id = f"user_broadcast_{user_id}"
    
    # Exisitng job bo'lsa o'chirish
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    # Birinchi ishga tushishni tezroq rejalashtiramiz
    run_date = datetime.now() if immediate_report else (datetime.now() + timedelta(seconds=random.randint(10, 30)))

    job = scheduler.add_job(
        run_broadcast_for_user,
        "date",
        run_date=run_date,
        id=job_id,
        args=[user_id, user_client, bot_client, False, immediate_report],
        replace_existing=True
    )
    user_jobs[user_id] = job
    logger.info(f"Initial scheduled broadcast job for user {user_id} to start in a few seconds.")

def stop_user_job(user_id: int):
    job_id = f"user_broadcast_{user_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if user_id in user_jobs:
        del user_jobs[user_id]
    logger.info(f"Stopped broadcast job for user {user_id}.")
