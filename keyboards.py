from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_keyboard(is_active: bool = False):
    """
    Yoshi katta insonlar uchun oson, katta va tushunarli menyu.
    """
    toggle_btn = "⏹ Tarqatishni to'xtatish" if is_active else "▶️ Tarqatishni boshlash"
    
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("📊 Holati (Dashboard)"), KeyboardButton(toggle_btn)],
            [KeyboardButton("📥 Guruhlarni tanlash"), KeyboardButton("⏱ Vaqtni belgilash")],
            [KeyboardButton("📝 Xabarni sozlash"), KeyboardButton("⚡️ 1 marta yuborib ko'rish")],
            [KeyboardButton("🔑 Akkauntni ulash / Almashtirish"), KeyboardButton("❓ Yordam va Qo'llanma")]
        ],
        resize_keyboard=True
    )

def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("📱 Raqamni yuborish", request_contact=True)],
            [KeyboardButton("❌ Bekor qilish")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def interval_keyboard():
    """
    Tayyor vaqt variantlari inline tugmalar ko'rinishida
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡️ 5 minut", callback_data="set_int_5"),
            InlineKeyboardButton("⏱ 10 minut", callback_data="set_int_10"),
            InlineKeyboardButton("⏱ 15 minut", callback_data="set_int_15")
        ],
        [
            InlineKeyboardButton("⏱ 30 minut", callback_data="set_int_30"),
            InlineKeyboardButton("⏳ 1 soat (60m)", callback_data="set_int_60"),
            InlineKeyboardButton("⏳ 2 soat (120m)", callback_data="set_int_120")
        ],
        [
            InlineKeyboardButton("✍️ Boshqa vaqt kiritish (Minutda)", callback_data="set_int_custom")
        ],
        [
            InlineKeyboardButton("🔙 Orqaga", callback_data="cancel_action")
        ]
    ])

def code_keypad_keyboard(entered_code: str = ""):
    """
    Inline tugmali SMS-kod terish klaviaturasi (Elderly & anti-expire friendly).
    """
    buttons = [
        [
            InlineKeyboardButton("1️⃣", callback_data="num_1"),
            InlineKeyboardButton("2️⃣", callback_data="num_2"),
            InlineKeyboardButton("3️⃣", callback_data="num_3")
        ],
        [
            InlineKeyboardButton("4️⃣", callback_data="num_4"),
            InlineKeyboardButton("5️⃣", callback_data="num_5"),
            InlineKeyboardButton("6️⃣", callback_data="num_6")
        ],
        [
            InlineKeyboardButton("7️⃣", callback_data="num_7"),
            InlineKeyboardButton("8️⃣", callback_data="num_8"),
            InlineKeyboardButton("9️⃣", callback_data="num_9")
        ],
        [
            InlineKeyboardButton("⌫ O'chirish", callback_data="num_del"),
            InlineKeyboardButton("0️⃣", callback_data="num_0"),
            InlineKeyboardButton("🧹 Tozalash", callback_data="num_clear")
        ],
        [
            InlineKeyboardButton("🔄 Kodni qayta yuborish", callback_data="num_resend"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_action")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def groups_keyboard(all_groups: list, selected_ids: set, page: int = 0, per_page: int = 6):
    """
    Guruhlarni tanlash uchun ko'p tanlovli (multi-select) pagination menyusi.
    all_groups: list of dict [{"group_id": int, "group_title": str}]
    selected_ids: set of int
    """
    total_groups = len(all_groups)
    if total_groups == 0:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Qayta yangilash", callback_data="refresh_groups")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="close_groups")]
        ])

    total_pages = (total_groups + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))

    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_page_groups = all_groups[start_idx:end_idx]

    buttons = []

    # Fast Actions Header
    buttons.append([
        InlineKeyboardButton("⚡️ Barchasini tanlash", callback_data=f"grp_select_all_{page}"),
        InlineKeyboardButton("🧹 Tozalash", callback_data=f"grp_clear_all_{page}")
    ])

    # Group Toggle Buttons
    for g in current_page_groups:
        g_id = g["group_id"]
        g_title = g["group_title"]
        is_sel = g_id in selected_ids
        icon = "✅" if is_sel else "⬜️"
        # Truncate title if too long
        display_title = g_title[:28] + "..." if len(g_title) > 28 else g_title
        btn_text = f"{icon} {display_title}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"grp_toggle_{g_id}_{page}")])

    # Navigation bar
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"grp_page_{page - 1}"))
    else:
        nav_row.append(InlineKeyboardButton(" ➖ ", callback_data="nop"))

    nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="nop"))

    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"grp_page_{page + 1}"))
    else:
        nav_row.append(InlineKeyboardButton(" ➖ ", callback_data="nop"))

    buttons.append(nav_row)

    # Save / Close Button
    buttons.append([
        InlineKeyboardButton(f"💾 SAQLASH ({len(selected_ids)} ta tanlandi)", callback_data="save_groups")
    ])

    return InlineKeyboardMarkup(buttons)

def confirm_clear_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Ha, barchasini tozalash", callback_data="confirm_clear_groups"),
            InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data="cancel_action")
        ]
    ])
