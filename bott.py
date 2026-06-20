import logging
import sqlite3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8832068359:AAFTo6UmfCKMnKwV0VIK2wLcNfIanDSDRak"
WELCOME_IMG = "https://ibb.co/Ngj0sYz9"
OWNER_USERNAME = "@SoulXHacker18"
ADMIN_ID = 8782420732  #⚠️ Isse apni Telegram User ID se replace karein

DEFAULT_TEMPLATE = (
    "🎁 *NEW GIVEAWAY STARTED* 🎁\n\n"
    "Is contest me participate karne ke liye niche link par click karke details submit karein!"
)

# Enable Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect("giveaway.db")
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    ''')
    
    # 2. Giveaways Table (Added custom_text column)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            channel_id TEXT,
            channel_title TEXT,
            invite_link TEXT,
            channel_post_id INTEGER,
            participant_count INTEGER DEFAULT 0,
            custom_text TEXT
        )
    ''')
    
    # Older db installation upgrade check
    try:
        cursor.execute("ALTER TABLE giveaways ADD COLUMN custom_text TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # 3. Participants Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER,
            user_id INTEGER,
            username TEXT,
            UNIQUE(giveaway_id, user_id)
        )
    ''')
    
    # 4. Votes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER,
            candidate_id INTEGER,
            voter_id INTEGER,
            UNIQUE(giveaway_id, voter_id)
        )
    ''')
    
    # 5. Participant Posts Table (For dynamic inline post edits on new votes)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS participant_posts (
            giveaway_id INTEGER,
            user_id INTEGER,
            message_id INTEGER,
            UNIQUE(giveaway_id, user_id)
        )
    ''')
    
    conn.commit()
    conn.close()


def get_db_connection():
    conn = sqlite3.connect("giveaway.db")
    conn.row_factory = sqlite3.Row
    return conn


# Database Helper Functions
def save_user(user_id, username):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving user to DB: {e}")


def save_giveaway(creator_id, channel_id, channel_title, invite_link, custom_text):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO giveaways (creator_id, channel_id, channel_title, invite_link, custom_text) VALUES (?, ?, ?, ?, ?)",
        (creator_id, str(channel_id), channel_title, invite_link, custom_text)
    )
    gw_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return gw_id


def update_channel_post_id(giveaway_id, post_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE giveaways SET channel_post_id = ? WHERE id = ?",
        (post_id, giveaway_id)
    )
    conn.commit()
    conn.close()


def get_giveaway(giveaway_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def get_user_giveaways(creator_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM giveaways WHERE creator_id = ?", (creator_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def add_participant(giveaway_id, user_id, username):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO participants (giveaway_id, user_id, username) VALUES (?, ?, ?)",
            (giveaway_id, user_id, username or f"User_{user_id}")
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False


def is_already_participated(giveaway_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def add_vote(giveaway_id, candidate_id, voter_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO votes (giveaway_id, candidate_id, voter_id) VALUES (?, ?, ?)",
            (giveaway_id, candidate_id, voter_id)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False


def get_votes_count(giveaway_id, candidate_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM votes WHERE giveaway_id = ? AND candidate_id = ?", (giveaway_id, candidate_id))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_total_participants(giveaway_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def save_participant_post(giveaway_id, user_id, message_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO participant_posts (giveaway_id, user_id, message_id) VALUES (?, ?, ?)",
        (giveaway_id, user_id, message_id)
    )
    conn.commit()
    conn.close()


# ==================== BOT HANDLERS ====================

async def check_membership(chat_id, user_id, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    args = context.args

    # Save User to DB
    save_user(user_id, username)

    # Check for Deep Links
    if args:
        start_payload = args[0]
        
        # Scenario 1: Participation Deep Link
        if start_payload.startswith("gw_"):
            try:
                giveaway_id = int(start_payload.split("_")[1])
            except (IndexError, ValueError):
                await update.message.reply_text("❌ *Invalid Giveaway Link.*", parse_mode="Markdown")
                return

            gw = get_giveaway(giveaway_id)
            if not gw:
                await update.message.reply_text("❌ *Yeh giveaway active nahi hai ya delete ho chuka hai.*", parse_mode="Markdown")
                return

            # Welcome Participation Message
            caption = (
                f"🎉 *WELCOME TO GIVEAWAY PARTICIPATION* 🎉\n\n"
                f"Is giveaway me enter hone ke liye aapko niche diye gaye channel ko join karna hoga.\n\n"
                f"📢 *Target Channel:* `{gw['channel_title']}`\n"
                f"⚡ *Status:* Join & Register to verify."
            )
            keyboard = [
                [InlineKeyboardButton("📢 Join Channel", url=gw['invite_link'])],
                [InlineKeyboardButton("🎁 Register/Participate Now", callback_data=f"join_gw_{giveaway_id}")]
            ]
            await update.message.reply_text(
                caption, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode="Markdown"
            )
            return

        # Scenario 2: Unique Voting Deep Link
        elif start_payload.startswith("vote_"):
            try:
                parts = start_payload.split("_")
                giveaway_id = int(parts[1])
                candidate_id = int(parts[2])
            except (IndexError, ValueError):
                await update.message.reply_text("❌ *Invalid Voting Link.*", parse_mode="Markdown")
                return

            gw = get_giveaway(giveaway_id)
            if not gw:
                await update.message.reply_text("❌ *Yeh giveaway active nahi hai.*", parse_mode="Markdown")
                return

            if user_id == candidate_id:
                await update.message.reply_text("❌ *Aap apne aap ko vote nahi de sakte!*", parse_mode="Markdown")
                return

            caption = (
                f"🗳️ *SECURE VOTING SYSTEM* 🗳️\n\n"
                f"Aap ek participant ko vote de rahe hain.\n"
                f"Vote count tabhi hoga jab aap target channel ke subscriber honge."
            )
            keyboard = [
                [InlineKeyboardButton("📢 Join Channel", url=gw['invite_link'])],
                [InlineKeyboardButton("🗳️ Submit Vote", callback_data=f"submitvote_{giveaway_id}_{candidate_id}")]
            ]
            await update.message.reply_text(
                caption, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode="Markdown"
            )
            return

    # Dynamic Welcome Message
    keyboard = [
        [InlineKeyboardButton("➕ New Giveaway", callback_data="new_gw"),
         InlineKeyboardButton("🎁 My Giveaways", callback_data="my_gws")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        f"🏆 *🎯 ADVANCED GIVEAWAY & VOTING SYSTEM 🎯*\n\n"
        f"👋 Hello *{update.effective_user.first_name}*!\n"
        f"Welcome to the high-performance giveaway platform.\n\n"
        f"⚡ *System Features:*\n"
        f"├─ Force Join Checking 🔐\n"
        f"├─ Real-Time Vote Counter 📊\n"
        f"└─ Anti-Spam Verification 🛡️\n\n"
        f"👑 *Developer:* {OWNER_USERNAME}\n\n"
        f"Apne actions manage karne ke liye niche control menu check karein:"
    )

    try:
        await update.message.reply_photo(
            photo=WELCOME_IMG,
            caption=welcome_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "new_gw":
        context.user_data['state'] = 'WAITING_CHANNEL_ID'
        await query.message.reply_text(
            "⚙️ *GIVEAWAY INITIALIZATION*\n\n"
            "1. Sabse pehle bot ko apne channel me *Admin* banayein.\n"
            "2. Uske baad channel ka *Username* (jaise `@mychannel`) ya *ID* (jaise `-10012345678`) yahan send karein:",
            parse_mode="Markdown"
        )
        await query.answer()

    elif data == "my_gws":
        gws = get_user_giveaways(user_id)
        if not gws:
            await query.message.reply_text("❌ Aapne abhi tak koi giveaway create nahi kiya hai.")
        else:
            text = "🎁 *Aapke Active Giveaways:*\n\n"
            for idx, gw in enumerate(gws, 1):
                text += f"{idx}. *Channel:* `{gw['channel_title']}` | *Participants:* `{gw['participant_count']}`\n"
            await query.message.reply_text(text, parse_mode="Markdown")
        await query.answer()

    elif data == "confirm_create":
        temp_data = context.user_data.get('temp_gw')
        if not temp_data:
            await query.answer("Session expired. Phir se try karein.", show_alert=True)
            return

        # Save to DB
        gw_id = save_giveaway(
            creator_id=user_id,
            channel_id=temp_data['channel_id'],
            channel_title=temp_data['channel_title'],
            invite_link=temp_data['invite_link'],
            custom_text=temp_data['custom_text']
        )

        bot_username = context.bot.username
        deep_link = f"https://t.me/{bot_username}?start=gw_{gw_id}"

        # Resolve custom text post or fallback
        base_post_text = temp_data['custom_text'] if temp_data['custom_text'] else DEFAULT_TEMPLATE
        post_text = f"{base_post_text}\n\n📊 *Current Participants:* `0`"
        kb = [[InlineKeyboardButton("🎁 Register / Participate Here", url=deep_link)]]

        try:
            channel_msg = await context.bot.send_message(
                chat_id=temp_data['channel_id'],
                text=post_text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown"
            )
            # Update post ID in DB
            update_channel_post_id(gw_id, channel_msg.message_id)

            success_text = (
                f"✅ *GIVEAWAY LIVE!*\n\n"
                f"📢 Channel me post successfully send ho gayi hai.\n"
                f"🔗 *Deep Link:* {deep_link}"
            )
            await query.edit_message_text(success_text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Channel post verification failed: {e}")

        context.user_data.pop('temp_gw', None)
        await query.answer()

    elif data == "cancel_create":
        context.user_data.pop('temp_gw', None)
        context.user_data['state'] = None
        await query.edit_message_text("❌ Creation process abort kar diya gaya.")
        await query.answer()

    # User registers
    elif data.startswith("join_gw_"):
        giveaway_id = int(data.split("_")[2])
        gw = get_giveaway(giveaway_id)
        if not gw:
            await query.answer("Giveaway active nahi hai.", show_alert=True)
            return

        # Force Join check
        is_joined = await check_membership(gw['channel_id'], user_id, context)
        if is_joined:
            is_new = add_participant(giveaway_id, user_id, query.from_user.username)
            if is_new:
                # Update main list count
                total_parts = get_total_participants(giveaway_id)
                bot_username = context.bot.username
                deep_link = f"https://t.me/{bot_username}?start=gw_{giveaway_id}"

                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE giveaways SET participant_count = ? WHERE id = ?", (total_parts, giveaway_id))
                    conn.commit()
                    conn.close()

                    # Dynamic Custom Text
                    base_post_text = gw['custom_text'] if gw['custom_text'] else DEFAULT_TEMPLATE
                    new_post_text = f"{base_post_text}\n\n📊 *Current Participants:* `{total_parts}`"

                    await context.bot.edit_message_text(
                        chat_id=gw['channel_id'],
                        message_id=gw['channel_post_id'],
                        text=new_post_text,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Register / Participate Here", url=deep_link)]]),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.warning(f"Error updating channel status: {e}")

                # Unique vote link generation
                vote_link = f"https://t.me/{bot_username}?start=vote_{giveaway_id}_{user_id}"

                # Participant Vote Post in Channel
                candidate_votes = get_votes_count(giveaway_id, user_id)

                participant_text = (
                    f"👤 Participant: {query.from_user.mention_html()}\n\n"
                    f"🗳 Votes: {candidate_votes}"
                )

                vote_button = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"🗳 Vote ({candidate_votes})",
                            url=vote_link
                        )
                    ]
                ])

                try:
                    participant_msg = await context.bot.send_message(
                        chat_id=gw['channel_id'],
                        text=participant_text,
                        reply_markup=vote_button,
                        parse_mode="HTML"
                    )
                    
                    # Message index save in SQL
                    save_participant_post(giveaway_id, user_id, participant_msg.message_id)
                except Exception as e:
                    logger.error(f"Participant direct posting failed: {e}")

                success_msg = (
                    f"🎉 *Registration Completed!* 🎉\n\n"
                    f"Aap successfully index ho chuke hain.\n"
                    f"🔗 Niche diya gaya link apne dosto ke sath share karein votes collect karne ke liye:\n\n"
                    f"`{vote_link}`"
                )
                await query.edit_message_text(success_msg, parse_mode="Markdown")
            else:
                await query.answer("Aap is giveaway me pehle se registered hain!", show_alert=True)
        else:
            await query.answer("❌ Error: Pehle channel join karein!", show_alert=True)

    # Vote submission
    elif data.startswith("submitvote_"):
        parts = data.split("_")
        giveaway_id = int(parts[1])
        candidate_id = int(parts[2])

        gw = get_giveaway(giveaway_id)
        if not gw:
            await query.answer("Giveaway active nahi hai.", show_alert=True)
            return

        # Force Join check
        is_joined = await check_membership(gw['channel_id'], user_id, context)
        if is_joined:
            vote_registered = add_vote(giveaway_id, candidate_id, user_id)
            if vote_registered:
                await query.answer("🗳️ Aapka vote successfully register ho gaya!", show_alert=True)
                
                # Dynamic participant message edit sync
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT message_id FROM participant_posts WHERE giveaway_id=? AND user_id=?",
                    (giveaway_id, candidate_id)
                )
                row = cursor.fetchone()

                if row:
                    msg_id = row[0]
                    total_candidate_votes = get_votes_count(giveaway_id, candidate_id)
                    
                    vote_link = (
                        f"https://t.me/{context.bot.username}"
                        f"?start=vote_{giveaway_id}_{candidate_id}"
                    )

                    try:
                        await context.bot.edit_message_text(
                            chat_id=gw['channel_id'],
                            message_id=msg_id,
                            text=(
                                f"👤 Participant ID: {candidate_id}\n\n"
                                f"🗳 Votes: {total_candidate_votes}"
                            ),
                            reply_markup=InlineKeyboardMarkup([
                                [
                                    InlineKeyboardButton(
                                        f"🗳 Vote ({total_candidate_votes})",
                                        url=vote_link
                                    )
                                ]
                            ])
                        )
                    except Exception as e:
                        logger.error(f"Editing dynamic user post failed: {e}")
                
                conn.close()

                await query.edit_message_text(
                    f"✅ *Vote counts synchronized!*\n"
                    f"📊 Candidate ke paas ab total *{get_votes_count(giveaway_id, candidate_id)}* votes hain.",
                    parse_mode="Markdown"
                )
            else:
                await query.answer("❌ Aap is giveaway me pehle hi vote de chuke hain!", show_alert=True)
        else:
            await query.answer("❌ Pehle channel join karein tabhi vote consider hoga!", show_alert=True)


async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get('state')

    # Step 1: Channel Username/ID confirmation
    if state == 'WAITING_CHANNEL_ID':
        channel_input = update.message.text.strip()
        try:
            chat = await context.bot.get_chat(channel_input)
            
            # Bot admin validation check
            bot_member = await chat.get_member(context.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    "❌ *Bot us channel me Admin nahi hai.* Pehle use setup karein aur link bhejein.",
                    parse_mode="Markdown"
                )
                return

            # Invite link resolving
            invite_link = chat.invite_link
            if not invite_link:
                if chat.username:
                    invite_link = f"https://t.me/{chat.username}"
                else:
                    try:
                        created_link = await context.bot.create_chat_invite_link(chat.id)
                        invite_link = created_link.invite_link
                    except Exception:
                        invite_link = None

            if not invite_link:
                await update.message.reply_text(
                    "❌ *Invite link automatic check fail ho gaya.* Bot permissions review karein.",
                    parse_mode="Markdown"
                )
                return

            # Save partially to session
            context.user_data['temp_gw'] = {
                'channel_id': chat.id,
                'channel_title': chat.title,
                'invite_link': invite_link
            }
            
            # Change state to request custom text
            context.user_data['state'] = 'WAITING_GIVEAWAY_TEXT'
            await update.message.reply_text(
                "📝 *GIVEAWAY DESCRIPTION / POST*\n\n"
                "Ab aap is giveaway ke bare me jo text message channel me post karna chahte hain, wo mujhe bhejein.\n"
                "Isme aap giveaway rules, prizes aur specifications detail me likh sakte hain.\n\n"
                "👉 Agar aap default text/layout chahte hain, toh `/skip` send karein.",
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Error checking channel database: {e}")
            await update.message.reply_text(
                "❌ *Verification Fail!* Sahi target channel ID ya username send karein."
            )

    # Step 2: Custom post verification
    elif state == 'WAITING_GIVEAWAY_TEXT':
        text_input = update.message.text.strip()
        
        if text_input.lower() == '/skip':
            context.user_data['temp_gw']['custom_text'] = None
            display_text = "*(Default Template)*"
        else:
            context.user_data['temp_gw']['custom_text'] = text_input
            display_text = f"\n\n_\"{text_input}\"_"

        context.user_data['state'] = None  # Reset states

        keyboard = [
            [InlineKeyboardButton("✅ Confirm & Create", callback_data="confirm_create")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_create")]
        ]
        
        await update.message.reply_text(
            f"📢 *CONFIRM GIVEAWAY DETAILS!*\n\n"
            f"📌 *Channel:* `{context.user_data['temp_gw']['channel_title']}`\n"
            f"📝 *Giveaway Post:* {display_text}\n\n"
            f"Kya aap is setup ke sath giveaway launch karna chahte hain?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Kripya commands ya direct buttons ka use karein.")


# ==================== ADMIN PANEL FUNCTIONS ====================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM giveaways")
    giveaways = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM participants")
    participants = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM votes")
    votes = cursor.fetchone()[0]

    conn.close()

    text = f"""
📊 *BOT REAL-TIME STATISTICS*

👥 Total Database Users: `{users}`
🎁 Total Giveaways Created: `{giveaways}`
🎉 Total Valid Registrations: `{participants}`
🗳 Total Casted Votes: `{votes}`
"""
    await update.message.reply_text(text, parse_mode="Markdown")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage:\n`/broadcast text message here`", parse_mode="Markdown")
        return

    msg = " ".join(context.args)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    success = 0
    failed = 0

    status = await update.message.reply_text("📡 *Broadcasting transmission started...*", parse_mode="Markdown")

    for user in users:
        try:
            await context.bot.send_message(user[0], msg)
            success += 1
        except Exception:
            failed += 1

    await status.edit_text(
        f"✅ *TRANSMISSION COMPLETED*\n\n"
        f"📤 Sent Successfully: `{success}`\n"
        f"❌ Fail/Blocked: `{failed}`\n"
        f"👥 Reach: `{success + failed}`",
        parse_mode="Markdown"
    )


async def broadcast_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("⚠️ Reply to a photo with `/bphoto` to broadcast.", parse_mode="Markdown")
        return

    photo = update.message.reply_to_message.photo[-1].file_id
    caption = update.message.reply_to_message.caption or ""

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    success = 0
    failed = 0

    status = await update.message.reply_text("🖼️ *Photo broadcast in progress...*", parse_mode="Markdown")

    for user in users:
        try:
            await context.bot.send_photo(user[0], photo=photo, caption=caption)
            success += 1
        except Exception:
            failed += 1

    await status.edit_text(
        f"✅ *PHOTO TRANSMISSION COMPLETED*\n\n"
        f"📤 Sent Successfully: `{success}`\n"
        f"❌ Fail/Blocked: `{failed}`\n"
        f"👥 Reach: `{success + failed}`",
        parse_mode="Markdown"
    )


# ==================== MAIN INITIALIZER ====================

def main():
    # Database initialization
    init_db()

    # Application construction
    app = Application.builder().token(BOT_TOKEN).build()

    # Register Command Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("bphoto", broadcast_photo))

    # Register Callback Handlers
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Text Message Handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    # Start polling
    logger.info("Application is polling and ready...")
    app.run_polling()


if __name__ == "__main__":
    main()