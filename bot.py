import asyncio
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMember,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ConversationHandler,
    filters,
    ContextTypes,
    ApplicationHandlerStop,
)
from telegram.error import TelegramError, BadRequest

import pytz

from config import (
    BOT_TOKEN,
    GROUP_ID,
    ADMIN_IDS,
    IST,
    CAPTCHA_TIMEOUT,
    FLOOD_MSG_COUNT,
    FLOOD_TIME_WINDOW,
    FLOOD_MUTE_DURATION,
    DEAL_TIMEOUT_HOURS,
    WARNING_LIMIT,
    LOW_RATING_THRESHOLD,
    LOW_RATING_MIN_REVIEWS,
)
from db import (
    get_member,
    create_member,
    get_or_create_member,
    update_member,
    get_all_members,
    add_referral,
    get_referral_count,
    get_top_referrers,
    get_all_badges,
    set_badge_config,
    remove_badge_config,
    get_badge_for_count,
    get_next_badge,
    create_listing,
    search_listings,
    get_user_listings,
    delist_listing,
    expire_old_listings,
    get_active_listing_counts,
    get_scam_words,
    add_scam_word,
    remove_scam_word,
    add_warning,
    get_warnings,
    add_review,
    get_seller_reviews,
    get_seller_avg_rating,
    get_top_sellers_by_rating,
    create_deal,
    get_deal,
    update_deal,
    get_user_deals,
    cancel_expired_deals,
    add_trust_vote,
    get_top_by_trust,
    get_group_stats,
    set_verified,
    get_verified_sellers,
    get_card_cooldown,
    set_card_cooldown,
    record_deal_confirmation,
    record_cancel_request,
    get_member_by_username,
)
from keyboards import (
    main_menu,
    back_home,
    trust_profile_kb,
    verify_admin_kb,
    deal_propose_kb,
    deal_actions_kb,
    admin_panel_kb,
    seller_card_kb,
    _btn,
    PRIMARY, SUCCESS, DANGER,
)
import emoji_fx
from emoji_fx import decorate, h, entities_to_html

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# PERMISSIONS
# ─────────────────────────────────────────────────────────────────────────────

MUTED = ChatPermissions(can_send_messages=False)
UNMUTED = ChatPermissions(
    can_send_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_change_info=False,
    can_invite_users=True,
    can_pin_messages=False,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION STATES
# ─────────────────────────────────────────────────────────────────────────────

SELL_NAME, SELL_PRICE, SELL_DESC, SELL_PHOTO = range(4)
BUY_NAME, BUY_BUDGET, BUY_REQ = range(4, 7)
SEARCH_QUERY = 7

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if user_id in ADMIN_IDS:
        return True
    try:
        member = await context.bot.get_chat_member(GROUP_ID, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False


def username_display(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or str(user.id)


async def resolve_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg.reply_to_message:
        target = msg.reply_to_message.from_user
        return target.id, target.username or target.full_name
    if context.args:
        arg = context.args[0].lstrip("@")
        if arg.isdigit():
            return int(arg), arg
        member = await get_member_by_username(arg)
        if member:
            return member["user_id"], member.get("username", arg)
    return None, None


async def get_member_by_username(username: str):
    from db import get_supabase
    def _get():
        res = get_supabase().table("members").select("*").ilike("username", username).execute()
        return res.data[0] if res.data else None
    try:
        return await asyncio.to_thread(_get)
    except Exception:
        return None


async def edit_or_reply(update: Update, text: str, **kwargs):
    """Edit message if from callback, otherwise reply."""
    q = update.callback_query
    if q:
        try:
            await q.edit_message_text(text, **kwargs)
            return
        except (BadRequest, TelegramError):
            pass
        try:
            await update.effective_chat.send_message(text, **kwargs)
        except TelegramError:
            pass
    elif update.effective_message:
        await update.effective_message.reply_text(text, **kwargs)


async def post_seller_card(bot, seller_id: int, chat_id: int):
    member = await get_member(seller_id)
    if not member:
        return
    avg, count = await get_seller_avg_rating(seller_id)
    badge    = member.get("badge") or "—"
    verified = "✅ Yes" if member.get("is_verified") else "❌ No"
    rt       = member.get("avg_response_time") or 0
    deals    = member.get("total_deals") or 0
    trust    = member.get("trust_count") or 0
    username = member.get("username") or "N/A"
    full_name = member.get("full_name") or username

    text = decorate(
        "╔════════════════════════╗\n"
        "🏪 <b>SELLER SPOTLIGHT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Name: {h(full_name)}\n"
        f"🔗 Username: @{h(username)}\n"
        f"⏱️ Avg Response: {rt} mins\n"
        f"📦 Total Deals: {deals}\n"
        f"⭐ Rating: {avg}/5 ({count} reviews)\n"
        f"✅ Verified: {verified}\n"
        f"🏆 Badge: {h(badge)}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👍 Trust Votes: {trust}\n"
        "╚════════════════════════╝"
    )
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=trust_profile_kb(seller_id),
        )
    except TelegramError as e:
        logger.error(f"post_seller_card error: {e}")


async def check_and_update_badge(user_id, old_count, new_count, bot, chat_id, username):
    all_badges = await get_all_badges()
    earned = None
    for b in all_badges:
        if old_count < b["required_count"] <= new_count:
            earned = b
    if earned:
        await update_member(user_id, badge=earned["badge_name"])
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🎉 Congratulations @{username}!\n"
                    f"You earned the *{earned['badge_name']}* badge! 🏆\n"
                    f"Total Referrals: {new_count}"
                ),
                parse_mode="Markdown",
            )
        except TelegramError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 1 — VERIFICATION & SECURITY
# ─────────────────────────────────────────────────────────────────────────────

async def chat_member_updated(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result or result.chat.id != GROUP_ID:
        return
    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    if old_status not in [ChatMember.LEFT, ChatMember.BANNED] or new_status != ChatMember.MEMBER:
        return

    user = result.new_chat_member.user
    if user.is_bot:
        return

    user_id  = user.id
    username = user.username or user.full_name

    await get_or_create_member(user_id, user.username or "", user.full_name or "")

    try:
        await context.bot.restrict_chat_member(chat_id=GROUP_ID, user_id=user_id, permissions=MUTED)
    except TelegramError as e:
        logger.warning(f"Could not mute new member {user_id}: {e}")

    # Harder captcha: mix addition and multiplication, larger numbers
    op = random.choice(["+", "×"])
    if op == "+":
        a, b    = random.randint(10, 50), random.randint(10, 50)
        correct = a + b
    else:
        a, b    = random.randint(2, 12), random.randint(2, 12)
        correct = a * b
    # Generate two distinct wrong answers far enough from correct
    offsets = random.sample([-7, -5, -4, -3, 3, 4, 5, 7, 8, 10, 11], 2)
    wrong1, wrong2 = correct + offsets[0], correct + offsets[1]
    while wrong1 <= 0: wrong1 += 3
    while wrong2 <= 0: wrong2 += 3

    options = [
        (str(correct), f"captcha_{user_id}_1"),
        (str(wrong1),  f"captcha_{user_id}_0"),
        (str(wrong2),  f"captcha_{user_id}_0"),
    ]
    random.shuffle(options)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(text=opt[0], callback_data=opt[1])
            for opt in options
        ]
    ])

    try:
        msg = await context.bot.send_message(
            chat_id=GROUP_ID,
            text=decorate(
                f"👋 <b>Welcome @{username}!</b>\n"
                f"🔒 Prove you are human — <b>{a} {op} {b} = ?</b>\n"
                f"⏳ You have {CAPTCHA_TIMEOUT} seconds!"
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        if "pending_captcha" not in context.bot_data:
            context.bot_data["pending_captcha"] = {}
        context.bot_data["pending_captcha"][user_id] = {"msg_id": msg.message_id}
    except TelegramError as e:
        logger.error(f"Captcha send error: {e}")
        return

    context.job_queue.run_once(
        kick_unverified,
        when=CAPTCHA_TIMEOUT,
        data={"user_id": user_id, "chat_id": GROUP_ID},
        name=f"kick_if_not_verified_{user_id}",
    )


async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    if len(parts) != 3:
        return

    target_user_id = int(parts[1])
    is_correct     = parts[2] == "1"
    voter          = query.from_user

    if voter.id != target_user_id:
        await query.answer("This captcha is not for you! 😤", show_alert=True)
        return

    pending = context.bot_data.get("pending_captcha", {})
    if target_user_id not in pending:
        return

    captcha_info = pending.pop(target_user_id)
    msg_id = captcha_info.get("msg_id")

    for job in context.job_queue.get_jobs_by_name(f"kick_if_not_verified_{target_user_id}"):
        job.schedule_removal()

    try:
        await context.bot.delete_message(chat_id=GROUP_ID, message_id=msg_id)
    except TelegramError:
        pass

    if is_correct:
        try:
            await context.bot.restrict_chat_member(chat_id=GROUP_ID, user_id=target_user_id, permissions=UNMUTED)
        except TelegramError as e:
            logger.error(f"Unmute error: {e}")
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=decorate(
                    f"✅ <b>Welcome to AI Tools Buy/Sell, {h(username_display(voter))}!</b> 🎉\n"
                    "📋 Read the rules, explore listings, and enjoy trading! 🚀"
                ),
                parse_mode="HTML",
            )
        except TelegramError:
            pass
    else:
        try:
            await context.bot.ban_chat_member(chat_id=GROUP_ID, user_id=target_user_id)
            await context.bot.unban_chat_member(chat_id=GROUP_ID, user_id=target_user_id)
        except TelegramError as e:
            logger.error(f"Kick error: {e}")
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=f"❌ {username_display(voter)} answered the captcha wrong and was removed! 🚫",
            )
        except TelegramError:
            pass


async def kick_unverified(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id  = job_data["user_id"]
    chat_id  = job_data["chat_id"]

    pending = context.bot_data.get("pending_captcha", {})
    if user_id not in pending:
        return

    captcha_info = pending.pop(user_id)
    msg_id = captcha_info.get("msg_id")

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except TelegramError:
        pass

    try:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
    except TelegramError as e:
        logger.error(f"Kick unverified job error: {e}")

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ Captcha timeout — a user was removed for not completing verification.",
        )
    except TelegramError:
        pass


async def link_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    if msg.chat.id != GROUP_ID:
        return

    user = update.effective_user
    if not user or await is_admin(user.id, context):
        return

    if re.search(r'(https?://|www\.|t\.me/|@\w+\.\w+)', msg.text, re.IGNORECASE):
        try:
            await msg.delete()
        except TelegramError:
            pass
        until = datetime.now(timezone.utc) + timedelta(minutes=5)
        try:
            await context.bot.restrict_chat_member(
                chat_id=GROUP_ID, user_id=user.id, permissions=MUTED, until_date=until,
            )
        except TelegramError:
            pass
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=(
                    f"⚠️ {username_display(user)}, links are not allowed without admin permission!\n"
                    "You have been muted for 5 minutes. 🔇"
                ),
            )
        except TelegramError:
            pass


async def scam_word_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    if msg.chat.id != GROUP_ID:
        return

    user = update.effective_user
    if not user or await is_admin(user.id, context):
        return

    scam_words = context.bot_data.get("scam_words_cache", [])
    text_lower = msg.text.lower()
    for word in scam_words:
        if word.lower() in text_lower:
            try:
                await msg.delete()
            except TelegramError:
                pass
            try:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=(
                        f"🚨 {username_display(user)}, a scam-related keyword was detected!\n"
                        "Your message has been deleted. Please follow community rules. ⚠️"
                    ),
                )
            except TelegramError:
                pass
            break


async def anti_flood_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    if msg.chat.id != GROUP_ID:
        return

    user = update.effective_user
    if not user or await is_admin(user.id, context):
        return

    if "flood_tracker" not in context.bot_data:
        context.bot_data["flood_tracker"] = {}

    now     = time.time()
    tracker = context.bot_data["flood_tracker"]
    uid     = user.id

    tracker.setdefault(uid, [])
    tracker[uid] = [t for t in tracker[uid] if now - t < FLOOD_TIME_WINDOW]
    tracker[uid].append(now)

    if len(tracker[uid]) >= FLOOD_MSG_COUNT:
        tracker[uid] = []
        until = datetime.now(timezone.utc) + timedelta(seconds=FLOOD_MUTE_DURATION)
        try:
            await context.bot.restrict_chat_member(
                chat_id=GROUP_ID, user_id=uid, permissions=MUTED, until_date=until,
            )
        except TelegramError:
            pass
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=(
                    f"🌊 Anti-Flood! {username_display(user)} sent too many messages too fast!\n"
                    "Muted for 10 minutes. 🔇"
                ),
            )
        except TelegramError:
            pass


async def refresh_scam_words_job(context: ContextTypes.DEFAULT_TYPE):
    words = await get_scam_words()
    context.bot_data["scam_words_cache"] = words
    logger.info(f"Scam words refreshed: {len(words)} words")
    # Also reload emoji on every refresh cycle
    await emoji_fx.load()


# ── Emoji Capture ─────────────────────────────────────────────────────────────

_PACK_LINK_RE = re.compile(
    r"(?:https?://)?t\.me/(?:addemoji|addstickers)/(\w+)", re.IGNORECASE
)


async def _fetch_from_pack(bot, pack_name: str) -> tuple[int, list[str]]:
    """Fetch all custom emoji from a Telegram emoji pack by set name."""
    from db import save_custom_emoji
    try:
        sticker_set = await bot.get_sticker_set(pack_name)
    except TelegramError as e:
        return 0, [f"Error: {e}"]

    saved = 0
    details = []
    for sticker in sticker_set.stickers:
        custom_id = getattr(sticker, "custom_emoji_id", None)
        fallback  = sticker.emoji or ""
        if not custom_id or not fallback:
            continue
        keyword = emoji_fx.KEYWORD_HINTS.get(fallback, "")
        ok = await save_custom_emoji(fallback, custom_id, keyword)
        if ok:
            saved += 1
            details.append(fallback)

    if saved:
        await emoji_fx.reload()
    return saved, details


async def emoji_capture_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Capture custom animated emoji — from pack link OR direct emoji in message.

    Runs in group=-1 (before ConversationHandlers). Raises ApplicationHandlerStop
    when in capture mode so ConversationHandlers don't also consume the message.
    """
    user = update.effective_user
    if context.bot_data.get("emoji_capture_admin") != user.id:
        return  # not in capture mode — let other handlers proceed normally

    msg  = update.effective_message
    text = msg.text or msg.caption or ""

    # ── Case 1: admin sent a pack link ────────────────────────────────────────
    match = _PACK_LINK_RE.search(text)
    if match:
        pack_name = match.group(1)
        await msg.reply_text(f"⏳ Fetching emoji pack <b>{pack_name}</b>…", parse_mode="HTML")
        saved, details = await _fetch_from_pack(context.bot, pack_name)

        context.bot_data.pop("emoji_capture_admin", None)

        if saved == 0:
            err = details[0] if details else "Pack not found or no custom emoji in it."
            await msg.reply_text(
                f"❌ <b>Could not fetch pack.</b>\n\n{h(err)}\n\n"
                "Make sure the pack is an <b>emoji pack</b> (not a sticker pack) "
                "and the link is correct.",
                parse_mode="HTML",
                reply_markup=admin_panel_kb(),
            )
        else:
            detail_str = "  ".join(details[:30])
            more = f" (+{len(details)-30} more)" if len(details) > 30 else ""
            await msg.reply_text(
                f"✅ <b>Fetched {saved} emoji from pack!</b>\n\n"
                f"{detail_str}{more}\n\n"
                "All animated now in bot messages. ✨",
                parse_mode="HTML",
                reply_markup=admin_panel_kb(),
            )
        raise ApplicationHandlerStop  # don't let ConversationHandlers see this

    # ── Case 2: admin typed / forwarded message with custom emoji ─────────────
    from db import save_custom_emoji
    entities    = list(msg.entities or []) + list(msg.caption_entities or [])
    custom_ents = [e for e in entities if e.type == "custom_emoji"]

    if not custom_ents:
        await msg.reply_text(
            "❌ <b>Nothing captured.</b>\n\n"
            "Send either:\n"
            "• A pack link — <code>https://t.me/addemoji/PackName</code>\n"
            "• A message containing custom animated emoji",
            parse_mode="HTML",
        )
        raise ApplicationHandlerStop

    saved = 0
    details = []
    for ent in custom_ents:
        fallback  = text[ent.offset: ent.offset + ent.length]
        custom_id = ent.custom_emoji_id
        keyword   = emoji_fx.KEYWORD_HINTS.get(fallback, "")
        ok = await save_custom_emoji(fallback, custom_id, keyword)
        if ok:
            saved += 1
            details.append(fallback)

    await emoji_fx.reload()
    context.bot_data.pop("emoji_capture_admin", None)

    detail_str = "  ".join(details) if details else "none"
    await msg.reply_text(
        f"✅ <b>Captured {saved} custom emoji!</b>\n\n"
        f"Saved: {detail_str}\n\n"
        "They will now appear animated in bot messages. ✨",
        parse_mode="HTML",
        reply_markup=admin_panel_kb(),
    )
    raise ApplicationHandlerStop


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 2 — REFERRAL SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referred_by = None

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg[4:])
                if referrer_id != user.id:
                    referred_by = referrer_id
            except ValueError:
                pass

    await get_or_create_member(user.id, user.username or "", user.full_name or "", referred_by)

    if referred_by:
        old_count = await get_referral_count(referred_by)
        new_count = await add_referral(referred_by, user.id)
        if new_count:
            referrer = await get_member(referred_by)
            referrer_username = referrer.get("username", "") if referrer else ""
            await check_and_update_badge(
                referred_by, old_count, new_count,
                context.bot, GROUP_ID, referrer_username,
            )

    is_adm = await is_admin(user.id, context)
    text = decorate(
        f"👋 <b>Welcome {h(user.first_name)}!</b>\n\n"
        "🎉 Welcome to the <b>AI Tools Buy/Sell</b> community!\n\n"
        "✨ Tap a button below to get started 👇"
    )
    await update.effective_chat.send_message(
        text,
        parse_mode="HTML",
        reply_markup=main_menu(is_adm),
    )


async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{user.id}"
    await edit_or_reply(
        update,
        f"🔗 *Your Referral Link*\n\n`{link}`\n\nShare it and earn badges! 🏆",
        parse_mode="Markdown",
        reply_markup=back_home(),
    )


async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    member = await get_or_create_member(user.id, user.username or "", user.full_name or "")
    count  = member.get("referral_count", 0) if member else 0
    badge  = member.get("badge") or "No badge yet"

    next_b = await get_next_badge(count)
    next_text = ""
    if next_b:
        needed = next_b["required_count"] - count
        next_text = f"\n📈 Next: *{next_b['badge_name']}* — {needed} more referrals"

    await edit_or_reply(
        update,
        f"📊 *Your Stats*\n\n"
        f"👥 Total Referrals: *{count}*\n"
        f"🏆 Current Badge: *{badge}*"
        f"{next_text}",
        parse_mode="Markdown",
        reply_markup=back_home(),
    )


async def setbadge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    args = context.args
    if not args or len(args) < 2:
        return await update.message.reply_text("Usage: /setbadge <count> <name> [admin]")
    try:
        count = int(args[0])
    except ValueError:
        return await update.message.reply_text("❌ Count must be a number.")
    is_admin_level = args[-1].lower() == "admin"
    name_parts = args[1:-1] if is_admin_level else args[1:]
    badge_name = " ".join(name_parts)
    if not badge_name:
        return await update.message.reply_text("❌ Please provide a badge name.")
    ok = await set_badge_config(count, badge_name, is_admin_level)
    if ok:
        await update.message.reply_text(f"✅ Badge set: *{count}* → *{badge_name}*", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Error saving badge.")


async def editbadge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    args = context.args
    if not args or len(args) < 2:
        return await update.message.reply_text("Usage: /editbadge <count> <new_name>")
    try:
        count = int(args[0])
    except ValueError:
        return await update.message.reply_text("❌ Count must be a number.")
    new_name = " ".join(args[1:])
    ok = await set_badge_config(count, new_name)
    if ok:
        await update.message.reply_text(f"✅ Badge updated: *{count}* → *{new_name}*", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Error updating badge.")


async def removebadge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    if not context.args:
        return await update.message.reply_text("Usage: /removebadge <count>")
    try:
        count = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ Count must be a number.")
    ok = await remove_badge_config(count)
    if ok:
        await update.message.reply_text(f"✅ Badge removed for count *{count}*.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Error removing badge.")


async def badges(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_badges = await get_all_badges()
    if not all_badges:
        return await edit_or_reply(
            update, "🏆 No badge milestones configured yet.", reply_markup=back_home()
        )
    lines = ["🏆 *Badge Milestones:*\n"]
    for b in all_badges:
        admin_tag = " 👑" if b.get("is_admin_level") else ""
        lines.append(f"• *{b['required_count']}* referrals → {b['badge_name']}{admin_tag}")
    await edit_or_reply(update, "\n".join(lines), parse_mode="Markdown", reply_markup=back_home())


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = await get_top_referrers(10)
    if not top:
        return await edit_or_reply(update, "📊 No referral data yet.", reply_markup=back_home())
    lines = ["🏆 *Top Referrers:*\n"]
    for i, m in enumerate(top, 1):
        uname = f"@{m['username']}" if m.get("username") else m.get("full_name", "?")
        badge = m.get("badge") or ""
        count = m.get("referral_count", 0)
        lines.append(f"{i}. {uname} — {count} referrals {badge}")
    await edit_or_reply(update, "\n".join(lines), parse_mode="Markdown", reply_markup=back_home())


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 3 — BUY/SELL LISTINGS
# ─────────────────────────────────────────────────────────────────────────────

# ── SELL Conversation ─────────────────────────────────────────────────────────

async def sell_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await get_or_create_member(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.full_name or "",
    )
    target = update.effective_message or (update.callback_query and update.callback_query.message)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "🛒 *Create a Sell Listing!*\n\nWhat is the tool name? (e.g. ChatGPT Plus, Canva Pro)",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🛒 *Create a Sell Listing!*\n\nWhat is the tool name? (e.g. ChatGPT Plus, Canva Pro)",
            parse_mode="Markdown",
        )
    return SELL_NAME


async def sell_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sell_tool_name"] = update.message.text.strip()
    await update.message.reply_text("💰 What is the price? (e.g. 500 or 400-600)")
    return SELL_PRICE


async def sell_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sell_price"] = update.message.text.strip()
    await update.message.reply_text(
        "📝 Write a description — features, condition, what's included, etc."
    )
    return SELL_DESC


async def sell_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sell_description"] = update.message.text or ""
    context.user_data["sell_desc_entities"] = list(update.message.entities or [])
    await update.message.reply_text(
        "📸 Send a screenshot or photo (optional).\nType /skip if you don't want one."
    )
    return SELL_PHOTO


async def sell_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = None
    MAX_BYTES = 5 * 1024 * 1024  # 5 MB
    if update.message.photo:
        photo = update.message.photo[-1]
        if photo.file_size and photo.file_size > MAX_BYTES:
            await update.message.reply_text("❌ Image too large (max 5 MB). Send a smaller one or /skip.")
            return SELL_PHOTO
        file_id = photo.file_id
    elif update.message.document:
        doc = update.message.document
        if doc.file_size and doc.file_size > MAX_BYTES:
            await update.message.reply_text("❌ File too large (max 5 MB). Send a smaller one or /skip.")
            return SELL_PHOTO
        file_id = doc.file_id
    await _finalize_sell(update, context, update.effective_user, file_id)
    return ConversationHandler.END


async def sell_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _finalize_sell(update, context, update.effective_user, None)
    return ConversationHandler.END


async def _finalize_sell(update, context, user, file_id):
    tool_name    = context.user_data.get("sell_tool_name", "")
    price        = context.user_data.get("sell_price", "")
    description  = context.user_data.get("sell_description", "")
    desc_ents    = context.user_data.get("sell_desc_entities", [])

    listing = await create_listing(
        user_id=user.id, username=user.username or "",
        type_="sell", tool_name=tool_name,
        price=price, description=description, file_id=file_id,
    )
    if not listing:
        await update.message.reply_text("❌ Failed to create listing. Please try again.")
        return

    member       = await get_member(user.id)
    verified_tag = "✅" if member and member.get("is_verified") else ""
    date_str     = datetime.now(IST).strftime("%d %b %Y")
    uname_str    = f"@{user.username}" if user.username else user.full_name

    card = decorate(
        "🔥 <b>NEW LISTING — SELL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛒 Tool: {h(tool_name)}\n"
        f"💰 Price: ₹{h(price)}\n"
        f"📝 {entities_to_html(description, desc_ents)}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Seller: {h(uname_str)} {verified_tag}\n"
        f"📅 Posted: {date_str}\n"
        f"🆔 Listing ID: #{listing['id']}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🤝 DM the seller to start a deal!"
    )
    try:
        if file_id:
            await context.bot.send_photo(chat_id=GROUP_ID, photo=file_id, caption=card, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=GROUP_ID, text=card, parse_mode="HTML")
        await update.message.reply_text(
            f"✅ Listing posted! ID: #{listing['id']}",
            reply_markup=back_home(),
        )
    except TelegramError as e:
        logger.error(f"Post sell listing error: {e}")
        await update.message.reply_text("❌ Failed to post in group. Please try again.")


async def sell_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Sell listing cancelled.", reply_markup=back_home())
    return ConversationHandler.END


# ── BUY Conversation ──────────────────────────────────────────────────────────

async def buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await get_or_create_member(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.full_name or "",
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "🛍️ *Create a Buy Request!*\n\nWhich tool are you looking for? (e.g. Adobe CC, Midjourney)",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🛍️ *Create a Buy Request!*\n\nWhich tool are you looking for? (e.g. Adobe CC, Midjourney)",
            parse_mode="Markdown",
        )
    return BUY_NAME


async def buy_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["buy_tool_name"] = update.message.text.strip()
    await update.message.reply_text("💰 What is your budget? (e.g. 500)")
    return BUY_BUDGET


async def buy_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["buy_budget"] = update.message.text.strip()
    await update.message.reply_text(
        "📋 Any specific requirements? (version, duration, features) — or type /skip"
    )
    return BUY_REQ


async def buy_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.message.text or ""
    if req.strip() == "/skip":
        req = "No specific requirements"
        ents = []
    else:
        ents = list(update.message.entities or [])
    await _finalize_buy(update, context, req, ents)
    return ConversationHandler.END


async def buy_skip_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _finalize_buy(update, context, "No specific requirements", [])
    return ConversationHandler.END


async def _finalize_buy(update, context, requirement, req_ents=None):
    user      = update.effective_user
    tool_name = context.user_data.get("buy_tool_name", "")
    budget    = context.user_data.get("buy_budget", "")

    listing = await create_listing(
        user_id=user.id, username=user.username or "",
        type_="buy", tool_name=tool_name,
        price=budget, description=requirement,
    )
    if not listing:
        await update.message.reply_text("❌ Failed to create buy request. Please try again.")
        return

    date_str  = datetime.now(IST).strftime("%d %b %Y")
    uname_str = f"@{user.username}" if user.username else user.full_name

    card = decorate(
        "🛍️ <b>BUY REQUEST</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Tool: {h(tool_name)}\n"
        f"💰 Budget: ₹{h(budget)}\n"
        f"📋 Requirement: {entities_to_html(requirement, req_ents or [])}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Buyer: {h(uname_str)}\n"
        f"📅 Posted: {date_str}\n"
        f"🆔 Request ID: #{listing['id']}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💬 If you have this tool, DM the buyer!"
    )
    try:
        await context.bot.send_message(chat_id=GROUP_ID, text=card, parse_mode="HTML")
        await update.message.reply_text(
            f"✅ Buy request posted! ID: #{listing['id']}",
            reply_markup=back_home(),
        )
    except TelegramError as e:
        logger.error(f"Post buy listing error: {e}")
        await update.message.reply_text("❌ Failed to post in group. Please try again.")


async def buy_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Buy request cancelled.", reply_markup=back_home())
    return ConversationHandler.END


# ── Search Conversation ───────────────────────────────────────────────────────

async def search_start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry from 🔍 Search inline button."""
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🔍 *Search Listings*\n\nType a keyword (e.g. ChatGPT, Canva, Adobe):",
        parse_mode="Markdown",
    )
    return SEARCH_QUERY


async def search_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.strip()
    results = await search_listings(keyword)
    if not results:
        await update.message.reply_text(
            f"🔍 No listings found for *'{keyword}'*.",
            parse_mode="Markdown",
            reply_markup=back_home(),
        )
        return ConversationHandler.END

    rows = []
    lines = [f"🔍 <b>Search Results for '{h(keyword)}':</b>\n"]
    for i, r in enumerate(results[:10]):
        t     = "🔥 SELL" if r["type"] == "sell" else "🛍️ BUY"
        uname = f"@{r['username']}" if r.get("username") else r.get("full_name", "?")
        lines.append(f"{i+1}. {t} | <b>{h(r['tool_name'])}</b> | ₹{h(r.get('price','?'))} | {h(uname)}")
        rows.append([_btn(
            f"👤 {uname} — {r['tool_name'][:22]}",
            callback_data=f"profile_{r['user_id']}",
            style=PRIMARY,
        )])
    rows.append([_btn("🏠 Main Menu", callback_data="menu:home", style=PRIMARY)])
    await update.message.reply_text(
        decorate("\n".join(lines)),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return ConversationHandler.END


async def search_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Search cancelled.", reply_markup=back_home())
    return ConversationHandler.END


# ── Search / Manage (command-based) ──────────────────────────────────────────

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /search <keyword>")
    keyword = " ".join(context.args)
    results = await search_listings(keyword)
    if not results:
        return await update.message.reply_text(f"🔍 No listings found for '{keyword}'.")
    rows = []
    lines = [f"🔍 <b>Search Results for '{h(keyword)}':</b>\n"]
    for i, r in enumerate(results[:10]):
        t     = "🔥 SELL" if r["type"] == "sell" else "🛍️ BUY"
        uname = f"@{r['username']}" if r.get("username") else r.get("full_name", "?")
        lines.append(f"{i+1}. {t} | <b>{h(r['tool_name'])}</b> | ₹{h(r.get('price','?'))} | {h(uname)}")
        rows.append([_btn(
            f"👤 {uname} — {r['tool_name'][:22]}",
            callback_data=f"profile_{r['user_id']}",
            style=PRIMARY,
        )])
    rows.append([_btn("🏠 Main Menu", callback_data="menu:home", style=PRIMARY)])
    await update.message.reply_text(
        decorate("\n".join(lines)),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def mylistings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user     = update.effective_user
    listings = await get_user_listings(user.id)
    if not listings:
        return await edit_or_reply(update, "📋 You have no active listings.", reply_markup=back_home())
    from datetime import timezone as tz
    now   = datetime.now(tz.utc)
    lines = ["📋 <b>Your Active Listings:</b>\n"]
    for r in listings:
        t     = "🔥 SELL" if r["type"] == "sell" else "🛍️ BUY"
        uname = f"@{r['username']}" if r.get("username") else r.get("full_name", "?")
        exp_str = ""
        if r.get("expires_at"):
            try:
                exp_dt  = datetime.fromisoformat(r["expires_at"].replace("Z", "+00:00"))
                days    = max(0, (exp_dt - now).days)
                exp_str = f" | ⏳ {days}d left"
            except Exception:
                pass
        lines.append(f"• <b>#{r['id']}</b> | {t} | {h(r['tool_name'])} | ₹{h(r.get('price','?'))}{exp_str}")
    lines.append("\nTo remove: <code>/delist &lt;id&gt;</code>")
    await edit_or_reply(update, decorate("\n".join(lines)), parse_mode="HTML", reply_markup=back_home())


async def delist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /delist <listing_id>")
    try:
        listing_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ Please provide a valid listing ID.")
    ok = await delist_listing(listing_id, update.effective_user.id)
    if ok:
        await update.message.reply_text(f"✅ Listing #{listing_id} removed.", reply_markup=back_home())
    else:
        await update.message.reply_text("❌ Listing not found or it doesn't belong to you.")


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 4 — ADMIN COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    target_id, target_name = await resolve_target_user(update, context)
    if not target_id:
        return await update.message.reply_text("Usage: /ban @username or reply to a message")
    try:
        await context.bot.ban_chat_member(chat_id=GROUP_ID, user_id=target_id)
        await update.message.reply_text(f"🔨 {target_name} has been banned!")
        await update_member(target_id, is_banned=True)
    except TelegramError as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    target_id, target_name = await resolve_target_user(update, context)
    if not target_id:
        return await update.message.reply_text("Usage: /mute @username <minutes>")
    minutes = 10
    for arg in (context.args or []):
        if arg.isdigit():
            minutes = int(arg)
            break
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    try:
        await context.bot.restrict_chat_member(
            chat_id=GROUP_ID, user_id=target_id, permissions=MUTED, until_date=until,
        )
        await update.message.reply_text(f"🔇 {target_name} muted for {minutes} minutes!")
    except TelegramError as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    target_id, target_name = await resolve_target_user(update, context)
    if not target_id:
        return await update.message.reply_text("Usage: /warn @username or reply to a message")

    await get_or_create_member(target_id, target_name or "", target_name or "")
    new_count = await add_warning(target_id)

    if new_count >= WARNING_LIMIT:
        try:
            await context.bot.ban_chat_member(chat_id=GROUP_ID, user_id=target_id)
            await update_member(target_id, is_banned=True)
            await update.message.reply_text(f"⚠️ {target_name} reached {new_count} warnings — auto-banned! 🔨")
        except TelegramError as e:
            await update.message.reply_text(f"❌ Auto-ban error: {e}")
    else:
        await update.message.reply_text(f"⚠️ Warning issued to {target_name}! ({new_count}/{WARNING_LIMIT})")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"⚠️ You received a warning! ({new_count}/{WARNING_LIMIT})\n{WARNING_LIMIT} warnings = auto-ban!",
            )
        except TelegramError:
            pass


async def warnings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    target_id, target_name = await resolve_target_user(update, context)
    if not target_id:
        return await update.message.reply_text("Usage: /warnings @username or reply to a message")
    count = await get_warnings(target_id)
    await update.message.reply_text(f"⚠️ {target_name} has {count}/{WARNING_LIMIT} warnings.")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    stats = await get_group_stats()
    await edit_or_reply(
        update,
        f"📊 *Group Stats*\n\n"
        f"👥 Total Members: {stats['total_members']}\n"
        f"📦 Listings Today: {stats['listings_today']}\n"
        f"🆕 New Joins Today: {stats['new_joins_today']}",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb(),
    )


async def addword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    if not context.args:
        return await update.message.reply_text("Usage: /addword <word>")
    word = " ".join(context.args).lower()
    ok   = await add_scam_word(word, update.effective_user.id)
    if ok:
        words = await get_scam_words()
        context.bot_data["scam_words_cache"] = words
        await update.message.reply_text(f"✅ Scam word added: '{word}'")
    else:
        await update.message.reply_text(f"⚠️ Word already exists or error: '{word}'")


async def removeword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    if not context.args:
        return await update.message.reply_text("Usage: /removeword <word>")
    word = " ".join(context.args).lower()
    ok   = await remove_scam_word(word)
    if ok:
        words = await get_scam_words()
        context.bot_data["scam_words_cache"] = words
        await update.message.reply_text(f"✅ Scam word removed: '{word}'")
    else:
        await update.message.reply_text(f"❌ Word not found: '{word}'")


async def announce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    if not context.args:
        return await update.message.reply_text("Usage: /announce <message>")
    message = " ".join(context.args)
    members = await get_all_members()
    await update.message.reply_text(f"📢 Sending to {len(members)} members...")

    sent, failed = 0, 0
    for m in members:
        try:
            await context.bot.send_message(
                chat_id=m["user_id"],
                text=decorate(f"📢 <b>Announcement:</b>\n\n{h(message)}"),
                parse_mode="HTML",
            )
            sent += 1
        except TelegramError:
            failed += 1
        await asyncio.sleep(0.05)

    await update.message.reply_text(f"✅ Done! Delivered: {sent} | Failed: {failed}")


async def sellercard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    target_id, target_name = await resolve_target_user(update, context)
    if not target_id:
        return await update.message.reply_text("Usage: /sellercard @username or reply to a message")
    await post_seller_card(context.bot, target_id, GROUP_ID)


async def admin_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    await update.message.reply_text(
        "⚙️ *Admin Panel*",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 5 — DAILY AUTOMATION
# ─────────────────────────────────────────────────────────────────────────────

async def daily_morning_post(context: ContextTypes.DEFAULT_TYPE):
    await expire_old_listings()
    await cancel_expired_deals()
    sell_count, buy_count = await get_active_listing_counts()
    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=decorate(
                "🌅 <b>Good Morning, AI Tools Buy/Sell Community!</b> ☀️\n\n"
                f"Today's active listings:\n"
                f"🔥 Sell: {sell_count}\n"
                f"🛍️ Buy: {buy_count}\n\n"
                "🚀 Find amazing deals today!"
            ),
            parse_mode="HTML",
        )
    except TelegramError as e:
        logger.error(f"Morning post error: {e}")


async def weekly_leaderboard_post(context: ContextTypes.DEFAULT_TYPE):
    top_trust   = await get_top_by_trust(10)
    top_sellers = await get_top_sellers_by_rating(10)

    lines = ["🏆 <b>Weekly Leaderboard — Top Trusted Sellers!</b> 🏆\n"]
    for i, m in enumerate(top_trust, 1):
        uname = f"@{m['username']}" if m.get("username") else m.get("full_name", "?")
        badge = m.get("badge") or ""
        trust = m.get("trust_count", 0)
        lines.append(f"{i}. {h(uname)} {h(badge)} — 👍 {trust} trust votes")

    lines.append("\n⭐ <b>Top Rated Sellers:</b>\n")
    for i, m in enumerate(top_sellers, 1):
        uname    = f"@{m['username']}" if m.get("username") else m.get("full_name", "?")
        verified = "✅" if m.get("is_verified") else ""
        rating   = m.get("avg_rating", 0)
        lines.append(f"{i}. {h(uname)} {verified} — ⭐ {rating}/5")

    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=decorate("\n".join(lines)),
            parse_mode="HTML",
        )
    except TelegramError as e:
        logger.error(f"Weekly leaderboard error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 6 — VERIFIED SELLER
# ─────────────────────────────────────────────────────────────────────────────

async def verify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    member = await get_or_create_member(user.id, user.username or "", user.full_name or "")
    if member and member.get("is_verified"):
        return await edit_or_reply(
            update, "✅ You are already a verified seller!", reply_markup=back_home()
        )

    uname_str = f"@{user.username}" if user.username else user.full_name
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=decorate(
                    f"🔔 <b>Verification Request!</b>\n\n"
                    f"👤 User: {h(uname_str)}\n"
                    f"🆔 ID: {user.id}"
                ),
                parse_mode="HTML",
                reply_markup=verify_admin_kb(user.id),
            )
        except TelegramError:
            pass

    await edit_or_reply(
        update,
        "✅ Your verification request has been sent to admins! Please wait. 🙏",
        reply_markup=back_home(),
    )


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin = query.from_user

    if admin.id not in ADMIN_IDS and not await is_admin(admin.id, context):
        await query.answer("Admins only!", show_alert=True)
        return

    parts = query.data.split("_")
    if len(parts) < 3:
        return

    action         = parts[1]
    target_user_id = int(parts[2])

    if action == "approve":
        ok = await set_verified(target_user_id, admin.id)
        if ok:
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text="🎉 Congratulations! You are now a *Verified Seller*! ✅",
                    parse_mode="Markdown",
                )
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text="🎊 A new Verified Seller has joined the community! ✅",
                )
            except TelegramError:
                pass
            await query.edit_message_text(f"✅ User {target_user_id} verified!")
        else:
            await query.edit_message_text("❌ Verification failed.")
    elif action == "reject":
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="❌ Your verification request has been rejected. Contact an admin for details.",
            )
        except TelegramError:
            pass
        await query.edit_message_text(f"❌ Verification rejected for user {target_user_id}.")


async def verified_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sellers = await get_verified_sellers()
    if not sellers:
        return await edit_or_reply(update, "✅ No verified sellers yet.", reply_markup=back_home())
    lines = ["✅ *Verified Sellers:*\n"]
    for s in sellers:
        uname  = f"@{s['username']}" if s.get("username") else s.get("full_name", "?")
        badge  = s.get("badge") or ""
        rating = s.get("avg_rating", 0)
        deals  = s.get("total_deals", 0)
        lines.append(f"• {uname} {badge} | ⭐ {rating}/5 | 📦 {deals} deals")
    await edit_or_reply(update, "\n".join(lines), parse_mode="Markdown", reply_markup=back_home())


async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    target_id, target_name = await resolve_target_user(update, context)
    if not target_id:
        return await update.message.reply_text("Usage: /approve @username or reply to a message")
    ok = await set_verified(target_id, update.effective_user.id)
    if ok:
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 You are now a *Verified Seller*! ✅",
                parse_mode="Markdown",
            )
            await context.bot.send_message(chat_id=GROUP_ID, text=decorate(f"🎊 <b>{h(target_name)}</b> is now a Verified Seller! ✅"), parse_mode="HTML")
        except TelegramError:
            pass
        await update.message.reply_text(f"✅ {target_name} verified!")
    else:
        await update.message.reply_text("❌ Verification failed.")


async def reject_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id, context):
        return await update.message.reply_text("❌ Admins only.")
    target_id, target_name = await resolve_target_user(update, context)
    if not target_id:
        return await update.message.reply_text("Usage: /reject @username <reason>")
    reason_args = context.args[1:] if context.args else []
    reason      = " ".join(reason_args) if reason_args else "No reason provided."
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"❌ Verification rejected.\n\n📋 Reason: {reason}",
        )
    except TelegramError:
        pass
    await update.message.reply_text(f"❌ Verification rejected for {target_name}.")


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 7 — RATING & REVIEW
# ─────────────────────────────────────────────────────────────────────────────

async def review_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    if not args or len(args) < 3:
        return await update.message.reply_text(
            "Usage: /review @seller <rating 1-5> <comment>\nExample: /review @john 5 Great seller!"
        )

    seller_username = args[0].lstrip("@")
    try:
        rating = int(args[1])
    except ValueError:
        return await update.message.reply_text("❌ Rating must be 1–5.")
    if not 1 <= rating <= 5:
        return await update.message.reply_text("❌ Rating must be 1–5.")

    comment = " ".join(args[2:])
    seller  = await get_member_by_username(seller_username)
    if not seller:
        return await update.message.reply_text(f"❌ Profile not found for @{seller_username}.")
    seller_id = seller["user_id"]

    if seller_id == user.id:
        return await update.message.reply_text("❌ You cannot review yourself!")

    review, status = await add_review(user.id, seller_id, rating, comment)
    if status == "already_reviewed":
        return await update.message.reply_text("⚠️ You already reviewed this seller.")
    if status == "error" or not review:
        return await update.message.reply_text("❌ Failed to submit review.")

    stars = "⭐" * rating
    reviewer_name = f"@{user.username}" if user.username else user.full_name or f"user#{user.id}"
    await update.message.reply_text(
        decorate(
            f"✅ <b>Review submitted!</b>\n"
            f"{stars} ({rating}/5)\n"
            f"📝 {h(comment)}"
        ),
        parse_mode="HTML",
        reply_markup=back_home(),
    )

    # Notify seller via DM
    try:
        await context.bot.send_message(
            chat_id=seller_id,
            text=decorate(
                f"⭐ <b>New Review!</b>\n\n"
                f"{h(reviewer_name)} ne review diya:\n"
                f"{stars} ({rating}/5)\n"
                f"📝 {h(comment)}"
            ),
            parse_mode="HTML",
        )
    except TelegramError:
        pass

    avg, count = await get_seller_avg_rating(seller_id)
    if avg < LOW_RATING_THRESHOLD and count >= LOW_RATING_MIN_REVIEWS:
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=decorate(
                        f"🚨 <b>Low Rating Alert!</b>\n\n"
                        f"Seller: @{h(seller.get('username', str(seller_id)))}\n"
                        f"Avg Rating: {avg}/5 ({count} reviews)"
                    ),
                    parse_mode="HTML",
                )
            except TelegramError:
                pass


async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if context.args:
        username = context.args[0].lstrip("@")
        member   = await get_member_by_username(username)
        if not member:
            return await edit_or_reply(update, f"❌ Profile not found for @{username}.", reply_markup=back_home())
    else:
        member = await get_or_create_member(user.id, user.username or "", user.full_name or "")

    await _send_profile_card(update, member)


async def _build_seller_card_text(member: dict) -> str:
    """Build the full HTML seller card text used in profile views."""
    uid         = member["user_id"]
    avg, count  = await get_seller_avg_rating(uid)
    reviews     = await get_seller_reviews(uid, 3)
    listings    = await get_user_listings(uid)
    uname       = f"@{member['username']}" if member.get("username") else member.get("full_name", "?")
    verified    = "✅ Yes" if member.get("is_verified") else "❌ No"
    badge       = member.get("badge") or "—"
    trust       = member.get("trust_count", 0)
    total_deals = member.get("total_deals", 0)
    warnings    = member.get("warnings", 0)
    stars       = "⭐" * round(avg) if avg else "—"

    text = decorate(
        f"👤 <b>Seller Profile: {h(uname)}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Verified: {verified}\n"
        f"🏆 Badge: {h(badge)}\n"
        f"⭐ Rating: {avg}/5 ({count} reviews) {stars}\n"
        f"📦 Total Deals: {total_deals}\n"
        f"👍 Trust Votes: {trust}\n"
        f"⚠️ Warnings: {warnings}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if reviews:
        text += "📋 <b>Recent Reviews:</b>\n"
        for r in reviews:
            s = "⭐" * r["rating"]
            text += f"{s} — {h(r.get('comment', '')[:80])}\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if listings:
        text += "🛒 <b>Active Listings:</b>\n"
        for lst in listings[:5]:
            ltype = "🔥 SELL" if lst.get("type") == "sell" else "🛍️ BUY"
            price = f"₹{lst['price']}" if lst.get("price") else "Price on ask"
            text += f"• {ltype} <b>{h(lst.get('tool_name','?'))}</b> — {h(price)}\n"
        if len(listings) > 5:
            text += f"  <i>...and {len(listings)-5} more</i>\n"
    return text


async def _send_profile_card(update: Update, member: dict):
    text = await _build_seller_card_text(member)
    await edit_or_reply(
        update, text,
        parse_mode="HTML",
        reply_markup=seller_card_kb(member["user_id"]),
    )


async def card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/card @username — view any seller's profile card."""
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/card @username</code>",
            parse_mode="HTML",
            reply_markup=back_home(),
        )
        return
    username = context.args[0].lstrip("@")
    member = await get_member_by_username(username)
    if not member:
        await update.message.reply_text(
            f"❌ No member found with username <code>@{h(username)}</code>.",
            parse_mode="HTML",
            reply_markup=back_home(),
        )
        return
    await _send_profile_card(update, member)


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    seller_id = int(query.data.split("_")[1])
    member    = await get_member(seller_id)
    if not member:
        await query.answer("Profile not found!", show_alert=True)
        return
    text = await _build_seller_card_text(member)
    try:
        await query.message.reply_text(
            text, parse_mode="HTML",
            reply_markup=seller_card_kb(seller_id),
        )
    except TelegramError:
        pass


async def topsellers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sellers = await get_top_sellers_by_rating(10)
    if not sellers:
        return await edit_or_reply(update, "⭐ No review data yet.", reply_markup=back_home())
    lines = ["⭐ *Top Sellers by Rating:*\n"]
    for i, s in enumerate(sellers, 1):
        uname    = f"@{s['username']}" if s.get("username") else s.get("full_name", "?")
        verified = "✅" if s.get("is_verified") else ""
        badge    = s.get("badge") or ""
        rating   = s.get("avg_rating", 0)
        deals    = s.get("total_deals", 0)
        lines.append(f"{i}. {uname} {verified} {badge} | ⭐ {rating}/5 | 📦 {deals} deals")
    await edit_or_reply(update, "\n".join(lines), parse_mode="Markdown", reply_markup=back_home())


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 8 — DEAL ESCROW
# ─────────────────────────────────────────────────────────────────────────────

async def deal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rate limit: one deal creation per user per 60 seconds
    uid = update.effective_user.id
    rl  = context.bot_data.setdefault("deal_rl", {})
    now = time.time()
    if now - rl.get(uid, 0) < 60:
        return await update.message.reply_text("⏳ Please wait 60 seconds before creating another deal.")
    rl[uid] = now

    args = context.args
    if not args or len(args) < 3:
        return await update.message.reply_text(
            "Usage: /deal @buyer @seller <amount> [tool]\nExample: /deal @alice @bob 500 ChatGPT"
        )

    buyer_username  = args[0].lstrip("@")
    seller_username = args[1].lstrip("@")
    try:
        amount = float(args[2])
    except ValueError:
        return await update.message.reply_text("❌ Amount must be a number.")
    tool_name = " ".join(args[3:]) if len(args) > 3 else "Tool"

    buyer  = await get_member_by_username(buyer_username)
    seller = await get_member_by_username(seller_username)

    if not buyer:
        return await update.message.reply_text(f"❌ Buyer @{buyer_username} not found.")
    if not seller:
        return await update.message.reply_text(f"❌ Seller @{seller_username} not found.")

    deal = await create_deal(buyer["user_id"], seller["user_id"], amount, tool_name)
    if not deal:
        return await update.message.reply_text("❌ Failed to create deal.")

    deal_id = deal["id"]
    msg = decorate(
        f"🤝 <b>New Deal Proposal!</b>\n\n"
        f"🆔 Deal ID: #{deal_id}\n"
        f"🛒 Tool: {h(tool_name)}\n"
        f"💰 Amount: ₹{amount}\n"
        f"👤 Buyer: @{h(buyer_username)}\n"
        f"🏪 Seller: @{h(seller_username)}\n\n"
        "Both parties must accept for the deal to go active!"
    )

    try:
        await context.bot.send_message(
            chat_id=buyer["user_id"], text=msg, parse_mode="HTML",
            reply_markup=deal_propose_kb(deal_id, buyer["user_id"]),
        )
    except TelegramError:
        pass
    try:
        await context.bot.send_message(
            chat_id=seller["user_id"], text=msg, parse_mode="HTML",
            reply_markup=deal_propose_kb(deal_id, seller["user_id"]),
        )
    except TelegramError:
        pass

    await update.message.reply_text(f"✅ Deal #{deal_id} created! Both parties notified via DM.")

    if "deal_acceptances" not in context.bot_data:
        context.bot_data["deal_acceptances"] = {}
    context.bot_data["deal_acceptances"][deal_id] = set()

    context.job_queue.run_once(
        auto_cancel_deal,
        when=DEAL_TIMEOUT_HOURS * 3600,
        data={"deal_id": deal_id},
        name=f"auto_cancel_deal_{deal_id}",
    )


async def deal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = query.from_user
    data  = query.data
    parts = data.split("_")

    if len(parts) < 4:
        return

    action           = parts[1]
    deal_id          = int(parts[2])
    expected_user_id = int(parts[3])

    if user.id != expected_user_id:
        await query.answer("This deal doesn't belong to you!", show_alert=True)
        return

    deal = await get_deal(deal_id)
    if not deal:
        await query.edit_message_text("❌ Deal not found.")
        return
    if deal["status"] != "pending":
        await query.edit_message_text(f"ℹ️ Deal status: {deal['status']}")
        return

    if action == "decline":
        await update_deal(deal_id, status="cancelled")
        for job in context.job_queue.get_jobs_by_name(f"auto_cancel_deal_{deal_id}"):
            job.schedule_removal()
        await query.edit_message_text(f"❌ Deal #{deal_id} declined.")
        other_id = deal["seller_id"] if user.id == deal["buyer_id"] else deal["buyer_id"]
        try:
            await context.bot.send_message(chat_id=other_id, text=f"❌ Deal #{deal_id} was declined.")
        except TelegramError:
            pass
        return

    if "deal_acceptances" not in context.bot_data:
        context.bot_data["deal_acceptances"] = {}
    acceptances = context.bot_data["deal_acceptances"].setdefault(deal_id, set())
    acceptances.add(user.id)

    await query.edit_message_text(f"✅ You accepted Deal #{deal_id}! Waiting for the other party.")

    if deal["buyer_id"] in acceptances and deal["seller_id"] in acceptances:
        await update_deal(deal_id, status="active")
        context.bot_data["deal_acceptances"].pop(deal_id, None)
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=(
                    f"🤝 *Deal is Now Active!*\n\n"
                    f"🆔 Deal ID: #{deal_id}\n"
                    f"🛒 Tool: {deal['tool_name']}\n"
                    f"💰 Amount: {deal['amount']}\n\n"
                    "Both parties agreed. Good luck! 🚀"
                ),
                parse_mode="Markdown",
            )
        except TelegramError:
            pass
        for uid in [deal["buyer_id"], deal["seller_id"]]:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"✅ Deal #{deal_id} is active!\nUse /dealcomplete {deal_id} once done.",
                )
            except TelegramError:
                pass


async def auto_cancel_deal(context: ContextTypes.DEFAULT_TYPE):
    deal_id = context.job.data["deal_id"]
    deal    = await get_deal(deal_id)
    if deal and deal["status"] == "pending":
        await update_deal(deal_id, status="cancelled")
        for uid in [deal["buyer_id"], deal["seller_id"]]:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"⏰ Deal #{deal_id} auto-cancelled (24h timeout).",
                )
            except TelegramError:
                pass


async def dealcomplete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        return await update.message.reply_text("Usage: /dealcomplete <deal_id>")
    try:
        deal_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ Provide a valid deal ID.")

    deal = await get_deal(deal_id)
    if not deal:
        return await update.message.reply_text("❌ Deal not found.")
    if user.id not in [deal["buyer_id"], deal["seller_id"]]:
        return await update.message.reply_text("❌ This deal doesn't belong to you.")
    if deal["status"] != "active":
        return await update.message.reply_text(f"❌ Deal status is '{deal['status']}'.")

    both_confirmed = await record_deal_confirmation(deal_id, user.id, deal["buyer_id"], deal["seller_id"])

    await update.message.reply_text(
        f"✅ Confirmation recorded for Deal #{deal_id}! Waiting for the other party."
    )

    if both_confirmed:
        from datetime import timezone as tz
        await update_deal(deal_id, status="completed",
                          completed_at=datetime.now(tz.utc).isoformat())
        seller = await get_member(deal["seller_id"])
        new_total = (seller.get("total_deals", 0) if seller else 0) + 1
        await update_member(deal["seller_id"], total_deals=new_total)

        for job in context.job_queue.get_jobs_by_name(f"auto_cancel_deal_{deal_id}"):
            job.schedule_removal()

        seller_username = seller.get("username", "") if seller else ""
        for uid in [deal["buyer_id"], deal["seller_id"]]:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=decorate(
                        f"🎉 <b>Deal #{deal_id} is complete!</b>\n\n"
                        f"🙏 Please leave a review:\n"
                        f"<code>/review @{h(seller_username)} 1-5 your comment</code>"
                    ),
                    parse_mode="HTML",
                )
            except TelegramError:
                pass

        await post_seller_card(context.bot, deal["seller_id"], GROUP_ID)

        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=decorate(
                    f"✅ <b>Deal Completed!</b>\n\n"
                    f"🆔 Deal ID: #{deal_id}\n"
                    f"🛒 Tool: {h(deal['tool_name'])}\n"
                    f"💰 Amount: {deal['amount']}\n\n"
                    "🎊 Congratulations to both parties!"
                ),
                parse_mode="HTML",
            )
        except TelegramError:
            pass


async def mydeals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    deals = await get_user_deals(user.id)
    if not deals:
        return await edit_or_reply(update, "📋 You have no deals yet.", reply_markup=back_home())

    for d in deals:
        role = "Buyer" if d["buyer_id"] == user.id else "Seller"
        text = decorate(
            f"📋 <b>Deal #{d['id']}</b>\n"
            f"🛒 Tool: {h(d['tool_name'])}\n"
            f"💰 Amount: ₹{d['amount']}\n"
            f"👤 Role: {role}\n"
            f"📊 Status: {d['status']}"
        )
        try:
            await update.effective_chat.send_message(
                text,
                parse_mode="HTML",
                reply_markup=deal_actions_kb(d["id"], d["status"]),
            )
        except TelegramError:
            pass


async def deal_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle deal:complete and deal:cancel from mydeals inline buttons."""
    query = update.callback_query
    await query.answer()
    user  = query.from_user
    parts = query.data.split(":")  # deal:complete:123 or deal:cancel:123

    action  = parts[1]
    deal_id = int(parts[2])

    deal = await get_deal(deal_id)
    if not deal:
        await query.edit_message_text("❌ Deal not found.")
        return
    if user.id not in [deal["buyer_id"], deal["seller_id"]]:
        await query.answer("This deal doesn't belong to you!", show_alert=True)
        return

    if action == "complete":
        if deal["status"] != "active":
            await query.edit_message_text(f"❌ Deal is already {deal['status']}.")
            return
        both_confirmed = await record_deal_confirmation(deal_id, user.id, deal["buyer_id"], deal["seller_id"])
        await query.edit_message_text(
            f"✅ Confirmation recorded for Deal #{deal_id}! Waiting for the other party."
        )
        if both_confirmed:
            from datetime import timezone as tz
            await update_deal(deal_id, status="completed",
                              completed_at=datetime.now(tz.utc).isoformat())
            seller    = await get_member(deal["seller_id"])
            new_total = (seller.get("total_deals", 0) if seller else 0) + 1
            await update_member(deal["seller_id"], total_deals=new_total)
            await post_seller_card(context.bot, deal["seller_id"], GROUP_ID)

    elif action == "cancel":
        if deal["status"] in ["completed", "cancelled"]:
            await query.edit_message_text(f"❌ Deal is already {deal['status']}.")
            return
        both_requested = await record_cancel_request(deal_id, user.id, deal["buyer_id"], deal["seller_id"])
        await query.edit_message_text(
            f"⚠️ Cancellation requested for Deal #{deal_id}. Waiting for the other party."
        )
        other_id = deal["seller_id"] if user.id == deal["buyer_id"] else deal["buyer_id"]
        try:
            await context.bot.send_message(
                chat_id=other_id,
                text=f"⚠️ Cancellation requested for Deal #{deal_id}. Tap the deal to agree.",
            )
        except TelegramError:
            pass
        if both_requested:
            await update_deal(deal_id, status="cancelled")
            for uid in [deal["buyer_id"], deal["seller_id"]]:
                try:
                    await context.bot.send_message(chat_id=uid, text=f"✅ Deal #{deal_id} cancelled.")
                except TelegramError:
                    pass


async def canceldeal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        return await update.message.reply_text("Usage: /canceldeal <deal_id>")
    try:
        deal_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ Provide a valid deal ID.")

    deal = await get_deal(deal_id)
    if not deal:
        return await update.message.reply_text("❌ Deal not found.")
    if user.id not in [deal["buyer_id"], deal["seller_id"]]:
        return await update.message.reply_text("❌ This deal doesn't belong to you.")
    if deal["status"] in ["completed", "cancelled"]:
        return await update.message.reply_text(f"❌ Deal is already {deal['status']}.")

    both_requested = await record_cancel_request(deal_id, user.id, deal["buyer_id"], deal["seller_id"])

    await update.message.reply_text(f"⚠️ Cancellation requested for Deal #{deal_id}.")

    other_id = deal["seller_id"] if user.id == deal["buyer_id"] else deal["buyer_id"]
    try:
        await context.bot.send_message(
            chat_id=other_id,
            text=f"⚠️ Cancellation requested for Deal #{deal_id}. Use /canceldeal {deal_id} to agree.",
        )
    except TelegramError:
        pass

    if both_requested:
        await update_deal(deal_id, status="cancelled")
        for job in context.job_queue.get_jobs_by_name(f"auto_cancel_deal_{deal_id}"):
            job.schedule_removal()
        for uid in [deal["buyer_id"], deal["seller_id"]]:
            try:
                await context.bot.send_message(chat_id=uid, text=f"✅ Deal #{deal_id} cancelled.")
            except TelegramError:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# DISPUTE
# ─────────────────────────────────────────────────────────────────────────────

async def dispute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/dispute <deal_id> <reason> — escalate a deal dispute to admins."""
    user = update.effective_user
    if not context.args or len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: <code>/dispute &lt;deal_id&gt; &lt;reason&gt;</code>\n"
            "Example: <code>/dispute 42 Seller sent wrong account</code>",
            parse_mode="HTML",
            reply_markup=back_home(),
        )
    try:
        deal_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ Provide a valid deal ID.")

    reason = " ".join(context.args[1:])
    deal   = await get_deal(deal_id)
    if not deal:
        return await update.message.reply_text("❌ Deal not found.")
    if user.id not in [deal["buyer_id"], deal["seller_id"]]:
        return await update.message.reply_text("❌ This deal doesn't belong to you.")
    if deal["status"] in ["completed", "cancelled", "disputed"]:
        return await update.message.reply_text(f"❌ Deal #{deal_id} is already {deal['status']}.")

    await update_deal(deal_id, status="disputed")

    reporter_name = f"@{user.username}" if user.username else user.full_name or f"user#{user.id}"
    buyer_id  = deal["buyer_id"]
    seller_id = deal["seller_id"]
    buyer_m   = await get_member(buyer_id)
    seller_m  = await get_member(seller_id)
    buyer_tag  = f"@{buyer_m['username']}"  if buyer_m  and buyer_m.get("username")  else f"user#{buyer_id}"
    seller_tag = f"@{seller_m['username']}" if seller_m and seller_m.get("username") else f"user#{seller_id}"

    alert_text = decorate(
        f"🚨 <b>Deal Dispute Raised!</b>\n\n"
        f"🆔 Deal #{deal_id}\n"
        f"🛒 Buyer:  {h(buyer_tag)}\n"
        f"💰 Seller: {h(seller_tag)}\n"
        f"👤 Raised by: {h(reporter_name)}\n\n"
        f"📝 Reason: {h(reason)}\n\n"
        "Deal status set to <b>disputed</b>. Please review."
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="HTML")
        except TelegramError:
            pass

    other_id = seller_id if user.id == buyer_id else buyer_id
    try:
        await context.bot.send_message(
            chat_id=other_id,
            text=decorate(
                f"🚨 <b>Deal #{deal_id} Disputed</b>\n\n"
                f"{h(reporter_name)} ne dispute raise kiya hai.\n"
                f"📝 Reason: {h(reason)}\n\n"
                "Admins ko notify kar diya gaya hai."
            ),
            parse_mode="HTML",
        )
    except TelegramError:
        pass

    await update.message.reply_text(
        decorate(
            f"✅ <b>Dispute raised for Deal #{deal_id}</b>\n\n"
            "Admins ko alert bhej diya gaya hai. Jaldi review hoga."
        ),
        parse_mode="HTML",
        reply_markup=back_home(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 9 — SELLER CARD & TRUST VOTING
# ─────────────────────────────────────────────────────────────────────────────

async def mycard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seller posts their own spotlight card in the group to request trust votes."""
    user = update.effective_user

    # 24-hour cooldown — DB-backed so it survives restarts
    last_post_dt = await get_card_cooldown(user.id)
    if last_post_dt:
        from datetime import timezone as tz
        elapsed   = (datetime.now(tz.utc) - last_post_dt).total_seconds()
        remaining = 24 * 3600 - elapsed
        if remaining > 0:
            hours   = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            return await edit_or_reply(
                update,
                decorate(
                    f"⏳ <b>Cooldown active!</b>\n\n"
                    f"You can post your card again in <b>{hours}h {minutes}m</b>.\n\n"
                    "Only one card post per 24 hours! 🕒"
                ),
                parse_mode="HTML",
                reply_markup=back_home(),
            )

    member = await get_or_create_member(user.id, user.username or "", user.full_name or "")
    avg, count = await get_seller_avg_rating(user.id)
    badge    = member.get("badge") or "—"
    verified = "✅ Yes" if member.get("is_verified") else "❌ No"
    rt       = member.get("avg_response_time") or 0
    deals    = member.get("total_deals") or 0
    trust    = member.get("trust_count") or 0
    username = member.get("username") or user.username or "N/A"
    full_name = member.get("full_name") or username

    text = decorate(
        "🙋 <b>TRUST VOTE REQUEST</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Name: {h(full_name)}\n"
        f"🔗 Username: @{h(username)}\n"
        f"⏱️ Avg Response: {rt} mins\n"
        f"📦 Total Deals: {deals}\n"
        f"⭐ Rating: {avg}/5 ({count} reviews)\n"
        f"✅ Verified: {verified}\n"
        f"🏆 Badge: {h(badge)}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👍 Trust Votes: {trust}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🙏 <b>If you've dealt with me, please give a trust vote!</b>"
    )

    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=trust_profile_kb(user.id),
        )
        await set_card_cooldown(user.id)
        await edit_or_reply(
            update,
            decorate(
                "✅ <b>Your spotlight card has been posted!</b>\n"
                "🙏 People can now give you trust votes.\n\n"
                "⏰ Next post allowed after 24 hours."
            ),
            parse_mode="HTML",
            reply_markup=back_home(),
        )
    except TelegramError as e:
        logger.error(f"mycard post error: {e}")
        await edit_or_reply(update, "❌ Failed to post card. Please try again.", reply_markup=back_home())


async def ranking_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = await get_top_by_trust(10)
    if not top:
        return await edit_or_reply(update, "👍 No trust vote data yet.", reply_markup=back_home())
    lines = ["👑 *Trust Ranking:*\n"]
    for i, m in enumerate(top, 1):
        uname    = f"@{m['username']}" if m.get("username") else m.get("full_name", "?")
        badge    = m.get("badge") or ""
        verified = "✅" if m.get("is_verified") else ""
        trust    = m.get("trust_count", 0)
        lines.append(f"{i}. {uname} {verified} {badge} — 👍 {trust}")
    await edit_or_reply(update, "\n".join(lines), parse_mode="Markdown", reply_markup=back_home())


async def review_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tapped '⭐ Leave Review' on a seller card — show review command."""
    query     = update.callback_query
    await query.answer()
    seller_id = int(query.data.split("_")[2])
    member    = await get_member(seller_id)
    uname     = f"@{member['username']}" if member and member.get("username") else f"user#{seller_id}"
    await query.message.reply_text(
        decorate(
            f"⭐ <b>Leave a Review for {h(uname)}</b>\n\n"
            "Use the command below:\n\n"
            f"<code>/review {h(uname)} 5 Acha seller hai, fast delivery!</code>\n\n"
            "Rating 1–5 de sakte ho. Comment required hai."
        ),
        parse_mode="HTML",
        reply_markup=back_home(),
    )


async def deal_init_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tapped '🤝 Start Deal' on a seller profile — show how to initiate."""
    query     = update.callback_query
    await query.answer()
    seller_id = int(query.data.split("_")[2])
    member    = await get_member(seller_id)
    uname     = f"@{member['username']}" if member and member.get("username") else f"user#{seller_id}"
    await query.message.reply_text(
        decorate(
            f"🤝 <b>Start a Deal with {h(uname)}</b>\n\n"
            "Use the command below — replace the values:\n\n"
            f"<code>/deal @yourUsername {h(uname.lstrip('@'))} amount ToolName</code>\n\n"
            "Example:\n"
            f"<code>/deal @alice {h(uname.lstrip('@'))} 500 ChatGPT Plus</code>\n\n"
            "💡 Both parties will receive a deal proposal to accept."
        ),
        parse_mode="HTML",
        reply_markup=back_home(),
    )


async def trust_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    voter     = query.from_user
    seller_id = int(query.data.split("_")[1])

    result = await add_trust_vote(voter.id, seller_id)
    msgs = {
        "ok":            "✅ Trust vote submitted!",
        "self_vote":     "❌ You cannot vote for yourself!",
        "already_voted": "⚠️ You already voted for this seller!",
        "no_deal":       "❌ You need a completed deal with this seller to vote!",
    }
    await query.answer(msgs.get(result, "❌ An error occurred."), show_alert=True)

    if result == "ok":
        voter_name = f"@{voter.username}" if voter.username else voter.full_name or f"user#{voter.id}"
        seller = await get_member(seller_id)
        new_trust = (seller.get("trust_count") or 0) if seller else "?"
        try:
            await context.bot.send_message(
                chat_id=seller_id,
                text=decorate(
                    f"👍 <b>New Trust Vote!</b>\n\n"
                    f"{h(voter_name)} ne tumhe trust vote diya.\n"
                    f"🏆 Total Trust Votes: <b>{new_trust}</b>"
                ),
                parse_mode="HTML",
            )
        except TelegramError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# HELP
# ─────────────────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_adm = await is_admin(update.effective_user.id, context)
    text = decorate(
        "📖 <b>AI Tools Buy/Sell Bot</b>\n\n"
        "Tap buttons in the main menu to navigate, or use commands:\n\n"
        "🛒 <b>Sell</b> — Create a sell listing\n"
        "🛍️ <b>Buy</b> — Post a buy request\n"
        "🔍 <b>Search</b> — Find active listings\n"
        "📋 <b>My Listings</b> — Manage your listings\n"
        "🔗 <b>Referral Link</b> — Share &amp; earn badges\n"
        "📊 <b>My Stats</b> — Your referral stats\n"
        "👤 <b>My Profile</b> — View your full profile\n"
        "🏆 <b>Leaderboard</b> — Top referrers\n"
        "⭐ <b>Top Sellers</b> — Best rated sellers\n"
        "👑 <b>Trust Ranking</b> — Most trusted sellers\n"
        "✅ <b>Get Verified</b> — Request verified badge\n"
        "🤝 <b>My Deals</b> — Your active deals\n"
        "🏅 <b>Badges</b> — Badge milestones\n\n"
        "Commands:\n"
        "<code>/review @seller 1-5 comment</code>\n"
        "<code>/profile @user</code> — View someone's profile\n"
        "<code>/deal @buyer @seller amount</code> — New deal\n"
        "<code>/dealcomplete id</code> — Confirm deal done\n"
        "<code>/canceldeal id</code> — Cancel a deal\n"
        "<code>/dispute id reason</code> — Raise dispute to admins\n"
        "<code>/delist id</code> — Remove your listing\n"
        "<code>/verified</code> — List verified sellers\n"
    )
    if is_adm:
        text += "\n⚙️ Tap <b>Admin Panel</b> for admin tools."
    await edit_or_reply(update, text, parse_mode="HTML", reply_markup=main_menu(is_adm))


# ─────────────────────────────────────────────────────────────────────────────
# CENTRAL MENU ROUTER
# ─────────────────────────────────────────────────────────────────────────────

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all menu:* callbacks to the right handler."""
    query = update.callback_query
    await query.answer()
    data  = query.data

    try:
        if data == "menu:home":
            is_adm = await is_admin(query.from_user.id, context)
            await edit_or_reply(
                update,
                f"👋 *Welcome back, {query.from_user.first_name}!*\n\nChoose an option 👇",
                parse_mode="Markdown",
                reply_markup=main_menu(is_adm),
            )

        elif data in ("menu:sell", "menu:buy"):
            pass  # handled by ConversationHandler entry points

        elif data == "menu:mylistings":
            await mylistings(update, context)

        elif data == "menu:mylink":
            await mylink(update, context)

        elif data == "menu:mystats":
            await mystats(update, context)

        elif data == "menu:profile":
            context.args = []
            await profile_cmd(update, context)

        elif data == "menu:leaderboard":
            await leaderboard(update, context)

        elif data == "menu:topsellers":
            await topsellers_cmd(update, context)

        elif data == "menu:ranking":
            await ranking_cmd(update, context)

        elif data == "menu:verify":
            await verify_cmd(update, context)

        elif data == "menu:mydeals":
            await mydeals_cmd(update, context)

        elif data == "menu:badges":
            await badges(update, context)

        elif data == "menu:mycard":
            await mycard_cmd(update, context)

        elif data == "menu:help":
            await help_cmd(update, context)

        elif data == "menu:adminpanel":
            if not await is_admin(query.from_user.id, context):
                await query.answer("Admins only!", show_alert=True)
                return
            await edit_or_reply(
                update,
                "⚙️ *Admin Panel*\n\nSelect an action:",
                parse_mode="Markdown",
                reply_markup=admin_panel_kb(),
            )

        # ── Admin Panel actions ───────────────────────────────────────────

        elif data == "adm:stats":
            if not await is_admin(query.from_user.id, context):
                await query.answer("Admins only!", show_alert=True)
                return
            stats = await get_group_stats()
            await edit_or_reply(
                update,
                f"📊 *Group Stats*\n\n"
                f"👥 Total Members: {stats['total_members']}\n"
                f"📦 Listings Today: {stats['listings_today']}\n"
                f"🆕 New Joins Today: {stats['new_joins_today']}",
                parse_mode="Markdown",
                reply_markup=admin_panel_kb(),
            )

        elif data == "adm:scamwords":
            if not await is_admin(query.from_user.id, context):
                await query.answer("Admins only!", show_alert=True)
                return
            words     = context.bot_data.get("scam_words_cache", [])
            word_list = ", ".join(words) if words else "None added yet"
            await edit_or_reply(
                update,
                f"🚫 *Scam Filter Words:*\n`{word_list}`\n\nAdd: `/addword <word>`\nRemove: `/removeword <word>`",
                parse_mode="Markdown",
                reply_markup=admin_panel_kb(),
            )

        elif data == "adm:ban_info":
            await edit_or_reply(update, "🔨 *Ban*\nUsage: `/ban @username` or reply to message.",
                                parse_mode="Markdown", reply_markup=admin_panel_kb())

        elif data == "adm:mute_info":
            await edit_or_reply(update, "🔇 *Mute*\nUsage: `/mute @username <minutes>`\nDefault: 10 minutes.",
                                parse_mode="Markdown", reply_markup=admin_panel_kb())

        elif data == "adm:warn_info":
            await edit_or_reply(update, "⚠️ *Warn*\nUsage: `/warn @username`\nAuto-bans at warning limit.",
                                parse_mode="Markdown", reply_markup=admin_panel_kb())

        elif data == "adm:approve_info":
            await edit_or_reply(update, "✅ *Approve Seller*\nUsage: `/approve @username`",
                                parse_mode="Markdown", reply_markup=admin_panel_kb())

        elif data == "adm:announce_info":
            await edit_or_reply(update, "📢 *Announce*\nUsage: `/announce <message>`\nDMs all members.",
                                parse_mode="Markdown", reply_markup=admin_panel_kb())

        elif data == "adm:badge_info":
            await edit_or_reply(update,
                                "🏅 *Set Badge*\nUsage: `/setbadge <count> <name>`\nExample: `/setbadge 5 Star Seller`",
                                parse_mode="Markdown", reply_markup=admin_panel_kb())

        elif data == "adm:sellercard_info":
            await edit_or_reply(update, "🃏 *Seller Card*\nUsage: `/sellercard @username`",
                                parse_mode="Markdown", reply_markup=admin_panel_kb())

        elif data == "adm:emoji":
            if not await is_admin(query.from_user.id, context):
                await query.answer("Admins only!", show_alert=True)
                return
            context.bot_data["emoji_capture_admin"] = query.from_user.id
            await edit_or_reply(
                update,
                "🎬 <b>Emoji Capture Mode ON</b>\n\n"
                "Send me any message containing custom animated emoji.\n\n"
                "💡 <b>How to get custom emoji:</b>\n"
                "• Use emoji packs from Telegram Premium\n"
                "• Forward a message that has animated emoji\n"
                "• Type custom emoji directly if you have Premium\n\n"
                "I'll automatically detect and save all custom emoji IDs.\n"
                "Send /cancel to exit capture mode.",
                parse_mode="HTML",
                reply_markup=back_home(),
            )

    except Exception as e:
        logger.error(f"menu_router error on '{data}': {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULING SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_jobs(application: Application):
    job_queue = application.job_queue
    ist       = pytz.timezone("Asia/Kolkata")
    now_ist   = datetime.now(ist)

    morning_time = now_ist.replace(hour=9, minute=0, second=0, microsecond=0).timetz()
    job_queue.run_daily(daily_morning_post, time=morning_time)

    sunday_time = now_ist.replace(hour=18, minute=0, second=0, microsecond=0).timetz()
    job_queue.run_daily(weekly_leaderboard_post, time=sunday_time, days=(6,))

    job_queue.run_repeating(refresh_scam_words_job, interval=1800, first=10)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    async def _post_init(app: Application) -> None:
        await emoji_fx.load()

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(_post_init).build()

    # ── Sell ConversationHandler ──────────────────────────────────────────
    sell_conv = ConversationHandler(
        entry_points=[
            CommandHandler("sell", sell_start),
            CallbackQueryHandler(sell_start, pattern=r"^menu:sell$"),
        ],
        states={
            SELL_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_name)],
            SELL_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_price)],
            SELL_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_desc)],
            SELL_PHOTO: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, sell_photo),
                CommandHandler("skip", sell_skip_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", sell_cancel)],
        per_user=True,
        per_chat=False,
        allow_reentry=True,
    )

    # ── Buy ConversationHandler ───────────────────────────────────────────
    buy_conv = ConversationHandler(
        entry_points=[
            CommandHandler("buy", buy_start),
            CallbackQueryHandler(buy_start, pattern=r"^menu:buy$"),
        ],
        states={
            BUY_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_name)],
            BUY_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_budget)],
            BUY_REQ: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buy_req),
                CommandHandler("skip", buy_skip_req),
            ],
        },
        fallbacks=[CommandHandler("cancel", buy_cancel)],
        per_user=True,
        per_chat=False,
        allow_reentry=True,
    )

    # ── Search ConversationHandler (from inline button) ───────────────────
    search_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(search_start_menu, pattern=r"^menu:search$"),
        ],
        states={
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_query_handler)],
        },
        fallbacks=[CommandHandler("cancel", search_cancel)],
        per_user=True,
        per_chat=False,
        allow_reentry=True,
    )

    # ── Register handlers ─────────────────────────────────────────────────

    application.add_handler(ChatMemberHandler(chat_member_updated, ChatMemberHandler.CHAT_MEMBER))

    # Conversations (must be before generic callback handler)
    application.add_handler(sell_conv)
    application.add_handler(buy_conv)
    application.add_handler(search_conv)

    # Callback queries
    application.add_handler(CallbackQueryHandler(captcha_callback,      pattern=r"^captcha_"))
    application.add_handler(CallbackQueryHandler(verify_callback,       pattern=r"^verify_"))
    application.add_handler(CallbackQueryHandler(deal_callback,         pattern=r"^deal_(accept|decline)_"))
    application.add_handler(CallbackQueryHandler(deal_action_callback,  pattern=r"^deal:(complete|cancel):"))
    application.add_handler(CallbackQueryHandler(deal_init_callback,    pattern=r"^deal_init_\d+$"))
    application.add_handler(CallbackQueryHandler(review_prompt_callback, pattern=r"^review_prompt_\d+$"))
    application.add_handler(CallbackQueryHandler(trust_callback,        pattern=r"^trust_"))
    application.add_handler(CallbackQueryHandler(profile_callback,      pattern=r"^profile_"))
    application.add_handler(CallbackQueryHandler(menu_router,           pattern=r"^(menu:|adm:)"))

    # User commands
    application.add_handler(CommandHandler("start",       start))
    application.add_handler(CommandHandler("help",        help_cmd))
    application.add_handler(CommandHandler("mylink",      mylink))
    application.add_handler(CommandHandler("mystats",     mystats))
    application.add_handler(CommandHandler("badges",      badges))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("search",      search_cmd))
    application.add_handler(CommandHandler("mylistings",  mylistings))
    application.add_handler(CommandHandler("delist",      delist_cmd))
    application.add_handler(CommandHandler("verify",      verify_cmd))
    application.add_handler(CommandHandler("verified",    verified_cmd))
    application.add_handler(CommandHandler("review",      review_cmd))
    application.add_handler(CommandHandler("profile",     profile_cmd))
    application.add_handler(CommandHandler("topsellers",  topsellers_cmd))
    application.add_handler(CommandHandler("ranking",     ranking_cmd))
    application.add_handler(CommandHandler("deal",        deal_cmd))
    application.add_handler(CommandHandler("mydeals",     mydeals_cmd))
    application.add_handler(CommandHandler("dealcomplete",dealcomplete_cmd))
    application.add_handler(CommandHandler("canceldeal",  canceldeal_cmd))
    application.add_handler(CommandHandler("dispute",     dispute_cmd))
    application.add_handler(CommandHandler("mycard",      mycard_cmd))
    application.add_handler(CommandHandler("card",        card_cmd))

    # Admin commands
    application.add_handler(CommandHandler("ban",         ban_cmd))
    application.add_handler(CommandHandler("mute",        mute_cmd))
    application.add_handler(CommandHandler("warn",        warn_cmd))
    application.add_handler(CommandHandler("warnings",    warnings_cmd))
    application.add_handler(CommandHandler("stats",       stats_cmd))
    application.add_handler(CommandHandler("addword",     addword_cmd))
    application.add_handler(CommandHandler("removeword",  removeword_cmd))
    application.add_handler(CommandHandler("announce",    announce_cmd))
    application.add_handler(CommandHandler("approve",     approve_cmd))
    application.add_handler(CommandHandler("reject",      reject_cmd))
    application.add_handler(CommandHandler("sellercard",  sellercard_cmd))
    application.add_handler(CommandHandler("adminpanel",  admin_panel_cmd))
    application.add_handler(CommandHandler("setbadge",    setbadge))
    application.add_handler(CommandHandler("editbadge",   editbadge))
    application.add_handler(CommandHandler("removebadge", removebadge))

    # Emoji capture — group=-1 so it fires before ConversationHandlers (group=0)
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.TEXT | filters.FORWARDED),
        emoji_capture_handler,
    ), group=-1)

    # Group message filters
    application.add_handler(MessageHandler(
        filters.Chat(GROUP_ID) & filters.TEXT & ~filters.COMMAND, anti_flood_filter,
    ))
    application.add_handler(MessageHandler(
        filters.Chat(GROUP_ID) & filters.TEXT & ~filters.COMMAND, link_filter,
    ))
    application.add_handler(MessageHandler(
        filters.Chat(GROUP_ID) & filters.TEXT & ~filters.COMMAND, scam_word_filter,
    ))

    setup_jobs(application)

    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
