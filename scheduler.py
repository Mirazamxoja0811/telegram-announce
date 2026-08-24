import asyncio
import random
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram.errors import FloodWait, PeerIdInvalid, RPCError
import database as db

logger = logging.getLogger("scheduler")

scheduler = AsyncIOScheduler()

def start_scheduler():
    if not scheduler.running:
        scheduler.start()

# Track active user jobs: {user_id: job_instance}
user_jobs = {}

async def run_broadcast_for_user(user_id: int, user_client, bot_client, is_manual_trigger: bool = False):
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

    status_msg = None
    if is_manual_trigger:
        status_msg = await bot_client.send_message(user_id, f"🚀 **Xabar tarqatish boshlandi...**\nJami tanlangan guruhlar: `{len(groups)}` ta")

    for g in groups:
        group_id = g["group_id"]
        group_title = g["group_title"]

        try:
            if msg_type == "text":
                await user_client.send_message(chat_id=group_id, text=msg_text)
            elif msg_type == "photo":
                await user_client.send_photo(chat_id=group_id, photo=msg_file_id, caption=msg_caption or "")
            elif msg_type == "video":
                await user_client.send_video(chat_id=group_id, video=msg_file_id, caption=msg_caption or "")
            
            success_count += 1
            # Anti-spam delay between groups (2 to 4.5 seconds)
            await asyncio.sleep(random.uniform(2.5, 4.5))

        except FloodWait as e:
            logger.warning(f"FloodWait encountered for user {user_id}: {e.value} seconds")
            fail_count += 1
            await asyncio.sleep(e.value + 1)
        except PeerIdInvalid:
            logger.warning(f"Removing unavailable group {group_title} ({group_id}) for user {user_id}")
            await db.remove_selected_group(user_id, group_id)
            fail_count += 1
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

    if status_msg:
        try:
            await status_msg.edit_text(report_text)
        except Exception as e:
            logger.error(f"Failed to update broadcast status for user {user_id}: {e}")

def schedule_user_job(user_id: int, interval_minutes: int, user_client, bot_client):
    """
    Foydalanuvchi uchun interval bo'yicha fonda vazifa yaratadi yoki yangilaydi.
    """
    job_id = f"user_broadcast_{user_id}"
    
    # Exisitng job bo'lsa o'chirish
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    job = scheduler.add_job(
        run_broadcast_for_user,
        "interval",
        minutes=interval_minutes,
        id=job_id,
        args=[user_id, user_client, bot_client, False],
        replace_existing=True
    )
    user_jobs[user_id] = job
    logger.info(f"Scheduled broadcast job for user {user_id} every {interval_minutes} minutes.")

def stop_user_job(user_id: int):
    job_id = f"user_broadcast_{user_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if user_id in user_jobs:
        del user_jobs[user_id]
    logger.info(f"Stopped broadcast job for user {user_id}.")
