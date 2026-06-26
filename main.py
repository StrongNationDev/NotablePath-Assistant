import html
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Update,
    constants,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))

IMAGES_DIR = Path(__file__).resolve().parent / "images"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing from .env")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

(QUESTION_CONTINUE, QUESTION_SUBJECT, QUESTION_TYPE, QUESTION_COVERAGE,
 QUESTION_PREVIOUS, QUESTION_GOAL, QUESTION_CONTACT, QUESTION_CONTACT_VALUE,
 QUESTION_FULLNAME, QUESTION_LINKS, QUESTION_ADDITIONAL, CONFIRM) = range(12)


def _safe(text: str) -> str:
    """Safely escape HTML entities."""
    return html.escape(text or "")


def build_main_menu(has_help: bool = True) -> ReplyKeyboardMarkup:
    """Build main menu with reply buttons."""
    keys = [
        ["📜 View Commands", "🛎️ Our Services"],
        ["🧠 Assessment", "🏠 About Us"],
    ]
    if has_help:
        keys.append(["❓ Help"])
    keys.append([KeyboardButton("📲 Share Contact", request_contact=True),
                 KeyboardButton("📍 Share Location", request_location=True)])
    return ReplyKeyboardMarkup(keys, resize_keyboard=True, one_time_keyboard=False)


def build_service_menu() -> InlineKeyboardMarkup:
    """Service menu with inline buttons."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Book A Session", url="http://notablepath.online/order")],
        [InlineKeyboardButton("🌐 Check Other Services", url="https://notablepath.online/other-services")],
        [InlineKeyboardButton("⬅️ Back", callback_data="SERVICE_BACK")],
    ])


def build_about_menu() -> ReplyKeyboardMarkup:
    """About menu with reply button."""
    return ReplyKeyboardMarkup([["⬅️ Back"]], resize_keyboard=True, one_time_keyboard=True)


def build_help_menu() -> ReplyKeyboardMarkup:
    """Help menu with reply buttons."""
    return ReplyKeyboardMarkup([["⬅️ Back"], ["✅ Assessment"]], resize_keyboard=True, one_time_keyboard=True)


def build_preview_actions() -> InlineKeyboardMarkup:
    """Preview actions with inline buttons (Submit/Edit)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Submit", callback_data="SUBMIT_ASSESSMENT"),
        InlineKeyboardButton("✏️ Edit", callback_data="EDIT_ASSESSMENT"),
    ]])


def build_question_keyboard(options: list[str]) -> ReplyKeyboardMarkup:
    """Build question keyboard with reply buttons."""
    keys = [[opt] for opt in options]
    keys.append(["⬅️ Back"])
    return ReplyKeyboardMarkup(keys, resize_keyboard=True, one_time_keyboard=True)


def is_back_text(message_text: str | None) -> bool:
    return bool(message_text and message_text.strip() == "⬅️ Back")


async def reset_to_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("assessment", None)
    await send_welcome(update, context)
    return ConversationHandler.END


async def notify_admin_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE, source_text: str | None) -> None:
    """Notify admin group of new user joining."""
    user = update.effective_user
    if not user:
        logger.warning("No effective_user in update")
        return

    username = f"@{_safe(user.username)}" if user.username else _safe(user.full_name)
    full_name = _safe(user.full_name)
    user_id = user.id
    location = "Not provided"
    phone = "Not provided"
    source_text = _safe(source_text) if source_text else "direct"

    admin_message = (
        f"<b>📣 New NotablePath Visitor</b>\n\n"
        f"<b>👤 Username:</b> {username}\n"
        f"<b>📝 Full Name:</b> {full_name}\n"
        f"<b>🆔 User ID:</b> <code>{user_id}</code>\n"
        f"<b>🔗 Source:</b> <code>{source_text}</code>\n"
        f"📍 <b>Location:</b> {location}\n"
        f"📱 <b>Phone:</b> {phone}\n"
        f"🔍 <b>Profile:</b> https://t.me/{_safe(user.username) if user.username else 'not_available'}"
    )

    try:
        profile = await context.bot.get_user_profile_photos(user.id, limit=1)
        if profile.total_count > 0:
            photo_id = profile.photos[0][0].file_id
            await context.bot.send_photo(
                chat_id=ADMIN_GROUP_ID,
                photo=photo_id,
                caption=admin_message,
                parse_mode=constants.ParseMode.HTML,
            )
            logger.info("Sent admin notification with profile photo for user %s", user_id)
        else:
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=admin_message,
                parse_mode=constants.ParseMode.HTML,
            )
            logger.info("Sent admin notification (no photo) for user %s", user_id)
    except Exception as exc:
        logger.exception("Failed to notify admin: %s", exc)


async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message to user."""
    user = update.effective_user
    if not user:
        return

    username = f"@{_safe(user.username)}" if user.username else _safe(user.full_name)
    welcome_text = (
        f"<b>🎉 Hey {username}, Welcome!</b>\n\n"
        "<i>You're with NotablePath Assessment Assistant.</i> This assessment helps us understand your situation and identify the most relevant next steps based on Wikipedia standards and best practices.\n\n"
        "⏱️ <b>The assessment takes approximately 3 minutes.</b>\n"
        "<b>⚠️ Important:</b>\n\n"
        "• We do not bypass Wikipedia policies.\n"
        "• We do not guarantee Wikipedia publication (however we can assure you based on how strong your sources are).\n"
        "• We are not affiliated with Wikipedia.\n\n"
        "<i>Press any of the buttons below to proceed.</i>"
    )

    if update.message:
        await update.message.reply_text(
            welcome_text,
            parse_mode=constants.ParseMode.HTML,
            reply_markup=build_main_menu(has_help=False),
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            welcome_text,
            parse_mode=constants.ParseMode.HTML,
            reply_markup=build_main_menu(has_help=False),
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    source_text = " ".join(context.args) if context.args else None
    context.user_data["start_source"] = source_text
    await send_welcome(update, context)
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        _clear_follow_up_jobs(context, chat_id)
        _schedule_follow_up_job(context, chat_id, "start_no_button", timedelta(minutes=45))

    logger.info("User %s started bot (source=%s)", update.effective_user.id if update.effective_user else None, source_text)
    try:
        await notify_admin_new_user(update, context, source_text)
    except Exception as exc:
        logger.exception("notify_admin_new_user failed: %s", exc)


async def allcommands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /allcommands."""
    message = (
        "<b>📘 NotablePath Bot Commands</b>\n\n"
        "<b>/start</b> - Start the assessment\n"
        "<b>/help</b> - Learn how the assistant works\n"
        "<b>/assessment</b> - Begin Wikipedia readiness assessment\n"
        "<b>/services</b> - View NotablePath services\n"
        "<b>/about</b> - About NotablePath\n"
        "<b>/contact</b> - Contact a consultant"
    )
    if update.message:
        await update.message.reply_text(message, parse_mode=constants.ParseMode.HTML)
    elif update.callback_query:
        await update.callback_query.message.reply_text(message, parse_mode=constants.ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    user = update.effective_user
    username = f"@{_safe(user.username)}" if user and user.username else _safe(user.full_name if user else "Guest")
    help_text = (
        f"<b>Welcome {username}, to the NotablePath Assessment Assistant.</b>\n\n"
        "<i>This assistant helps individuals, founders, companies, authors, artists, organizations, and public figures understand Wikipedia readiness and editorial requirements.</i>\n\n"
        "<b>📋 What you can do:</b>\n\n"
        "• Assess Wikipedia readiness\n"
        "• Review source coverage\n"
        "• Request article guidance\n"
        "• Help with draft improvement\n"
        "• Page Creation & Editing\n"
        "• Request a consultation\n\n"
        "If you're representing a public figure, founder, company, or organization, we can help evaluate source coverage, article readiness, and editorial considerations."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode=constants.ParseMode.HTML, reply_markup=build_help_menu())
    elif update.callback_query:
        await update.callback_query.message.reply_text(help_text, parse_mode=constants.ParseMode.HTML, reply_markup=build_help_menu())


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /about command."""
    about_text = (
        "<b>ℹ️ About NotablePath</b>\n\n"
        "<b>NotablePath</b> is an independent consultation service focusing on Wikipedia research, source analysis and editorial guidance.\n\n"
        "We are not affiliated with the Wikimedia Foundation and do not promise guaranteed approvals. Our goal is to help you make informed, professional choices.\n\n"
        "<b>👨‍💼 Founder & Wikipedia Research Consultant</b>\n"
        "The founder provides expert guidance on source strength, article structure and Wikipedia readiness without claiming any official editorial influence."
    )
    if update.message:
        await update.message.reply_text(about_text, parse_mode=constants.ParseMode.HTML, reply_markup=build_about_menu())
    elif update.callback_query:
        await update.callback_query.message.reply_text(about_text, parse_mode=constants.ParseMode.HTML, reply_markup=build_about_menu())


async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /services command."""
    if update.message:
        message = await update.message.reply_text("🎨 Preparing our service showcase...")
    else:
        message = await update.callback_query.message.reply_text("🎨 Preparing our service showcase...")

    service_messages = []
    for image_name in ("Service.png", "Services.png"):
        image_path = IMAGES_DIR / image_name
        if image_path.exists():
            try:
                with open(image_path, "rb") as photo:
                    sent_photo = await context.bot.send_photo(chat_id=message.chat_id, photo=photo)
                    service_messages.append(sent_photo.message_id)
                    logger.info("Sent image %s", image_name)
            except Exception as exc:
                logger.warning("Failed to send image %s: %s", image_name, exc)

    service_text = (
        "<b>🛎️ NotablePath Services</b>\n\n"
        "Discover our primary support options and connect with our specialist.\n\n"
        "✓ Consultations tailored to Wikipedia readiness\n"
        "✓ Source evaluation and draft review\n"
        "✓ Notability and article strategy support"
    )
    service_message = await context.bot.send_message(
        chat_id=message.chat_id,
        text=service_text,
        parse_mode=constants.ParseMode.HTML,
        reply_markup=build_service_menu(),
    )
    service_messages.append(service_message.message_id)
    context.user_data["service_messages"] = service_messages


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show main menu."""
    if update.message:
        await update.message.reply_text(
            "Back to the main assistant menu.",
            reply_markup=build_main_menu(has_help=True),
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            "Back to the main assistant menu.",
            reply_markup=build_main_menu(has_help=True),
        )


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route callback queries from reply/inline buttons."""
    query = update.callback_query
    if not query or not query.data:
        logger.warning("No callback query data")
        return

    data = query.data
    await query.answer()

    if data == "VIEW_COMMANDS":
        await allcommands(update, context)
    elif data == "OUR_SERVICES":
        await services_command(update, context)
    elif data == "SERVICE_BACK":
        deleted_ids = context.user_data.pop("service_messages", [])
        for msg_id in deleted_ids:
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=msg_id)
            except Exception:
                pass
        await show_main_menu(update, context)
    elif data == "ABOUT_US":
        await about_command(update, context)
    elif data == "HELP_MENU":
        await help_command(update, context)
    elif data == "MAIN_MENU":
        await show_main_menu(update, context)
    elif data in {"CONTINUE_ASSESSMENT", "RESUME_ASSESSMENT", "CONTINUE_REVIEW"}:
        chat_id = query.message.chat_id if query.message else None
        if chat_id:
            _clear_follow_up_jobs(context, chat_id)
        await assessment_start(update, context)
    elif data in {"PROFESSIONAL_REPORT", "REQUEST_REPORT", "REQUEST_ASSESSMENT"}:
        chat_id = query.message.chat_id if query.message else None
        if chat_id:
            _clear_follow_up_jobs(context, chat_id)
        await query.message.reply_text(
            render_professional_report_text(),
            parse_mode=constants.ParseMode.HTML,
            reply_markup=build_professional_report_markup(),
        )
    else:
        logger.debug("Unhandled callback data: %s", data)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route text messages from main menu."""
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id and not context.chat_data.get("assessment_started", False):
        _clear_follow_up_jobs(context, chat_id)

    text = update.message.text.strip()

    if text == "📜 View Commands":
        await allcommands(update, context)
    elif text == "🛎️ Our Services":
        await services_command(update, context)
    elif text == "🧠 Assessment":
        await assessment_start(update, context)
    elif text == "🏠 About Us":
        await about_command(update, context)
    elif text == "❓ Help":
        await help_command(update, context)
    elif text == "⬅️ Back":
        await show_main_menu(update, context)


async def assessment_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start assessment flow."""
    text = (
        "<b>🧠 Assessment Flow</b>\n\n"
        "What you'll receive:\n\n"
        "✓ Initial readiness review\n"
        "✓ Source coverage evaluation\n"
        "✓ Professional guidance\n"
        "✓ Consultation recommendation if needed\n\n"
        "<b>Are you ready to continue?</b>"
    )
    kb = ReplyKeyboardMarkup([["Continue"]], resize_keyboard=True, one_time_keyboard=True)
    if update.message:
        await update.message.reply_text(text, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
    context.user_data["assessment"] = {}
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        _clear_follow_up_jobs(context, chat_id)
        chat_data = context.application.chat_data.setdefault(chat_id, {})
        chat_data["assessment_started"] = True
        chat_data["assessment_completed"] = False
        _schedule_follow_up_job(context, chat_id, "assessment_incomplete_12h", timedelta(hours=12))
        _schedule_follow_up_job(context, chat_id, "assessment_incomplete_60h", timedelta(hours=60))
        _schedule_follow_up_job(context, chat_id, "assessment_incomplete_7d", timedelta(days=7))
        _schedule_follow_up_job(context, chat_id, "assessment_incomplete_21d", timedelta(days=21))
    return QUESTION_CONTINUE


async def q_continue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Continue button."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    if update.message and update.message.text and "Continue" not in update.message.text:
        return QUESTION_CONTINUE

    await update.message.reply_text(f"✅ Starting assessment...\n\n")
    await update.message.reply_text(
        "<b>Question 1</b>\n\nWhat best describes your situation?",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=build_question_keyboard([
            "I want guidance for a new Wiki page",
            "I have a rejected draft",
            "I have an existing article to edit",
            "Help with source analysis",
            "Create wiki page for me",
            "I am not sure",
        ]),
    )
    return QUESTION_SUBJECT


async def q1_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 1 response."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    choice = update.message.text.strip()
    context.user_data["assessment"]["request"] = choice
    await update.message.reply_text(f"✅ Selected: {choice}")

    await update.message.reply_text(
        "<b>Question 2</b>\n\nWho is the subject?",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=build_question_keyboard([
            "Founder (CEO)",
            "Author",
            "Artist",
            "Public Figure",
            "Company",
            "Other",
        ]),
    )
    return QUESTION_TYPE


async def q2_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 2 response."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    choice = update.message.text.strip()
    context.user_data["assessment"]["subject"] = choice
    await update.message.reply_text(f"✅ Selected: {choice}")

    await update.message.reply_text(
        "<b>Question 3</b>\n\nDo you currently have independent media coverage that talks about the subject name?",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=build_question_keyboard([
            "Yes, Major Coverage",
            "Well, Some Coverage",
            "No, at all",
            "I Don't think So",
        ]),
    )
    return QUESTION_COVERAGE


async def q3_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 3 response."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    choice = update.message.text.strip()
    context.user_data["assessment"]["coverage"] = choice
    await update.message.reply_text(f"✅ Selected: {choice}")

    await update.message.reply_text(
        "<b>Question 4</b>\n\nHave you previously submitted a Wikipedia draft?",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=build_question_keyboard(["Yes", "No"]),
    )
    return QUESTION_PREVIOUS


async def q4_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 4 response."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    choice = update.message.text.strip()
    context.user_data["assessment"]["wiki_status"] = choice
    await update.message.reply_text(f"✅ Selected: {choice}")

    await update.message.reply_text(
        "<b>Question 5</b>\n\nWhat is your main goal?\n\n<i>Please write your main goal in a single message.</i>",
        parse_mode=constants.ParseMode.HTML,
    )
    return QUESTION_GOAL


async def q5_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 5 response (free text)."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    text = update.message.text.strip()
    context.user_data["assessment"]["goal"] = text
    await update.message.reply_text(f"✅ Received goal: {text}")

    await update.message.reply_text(
        "<b>Question 6</b>\n\nWhich means did you prefer our Admin contact through?",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=build_question_keyboard(["Telegram", "Email"]),
    )
    return QUESTION_CONTACT


async def q6_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 6 response (contact type)."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    choice = update.message.text.strip()
    context.user_data["assessment"]["contact_type"] = choice
    user = update.effective_user

    if choice.lower() == "telegram":
        if user and user.username:
            context.user_data["assessment"]["contact_value"] = f"@{user.username}"
            await update.message.reply_text(f"✅ Selected: {choice} (will contact via @{user.username})")
            await update.message.reply_text(
                "<b>Question 7</b>\n\nWhat is your full name?",
                parse_mode=constants.ParseMode.HTML,
            )
            return QUESTION_FULLNAME
        await update.message.reply_text(
            "<b>Question 6a</b>\n\nPlease send your Telegram username so admin can contact you.",
            parse_mode=constants.ParseMode.HTML,
        )
        return QUESTION_CONTACT_VALUE

    if choice.lower() == "email":
        await update.message.reply_text(
            "<b>Question 6a</b>\n\nPlease send the email address you want admin to use.",
            parse_mode=constants.ParseMode.HTML,
        )
        return QUESTION_CONTACT_VALUE

    await update.message.reply_text(
        f"✅ Selected: {choice}\n\nPlease send the contact method details.",
    )
    return QUESTION_CONTACT_VALUE


async def q6_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 6a response (contact value)."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    value = update.message.text.strip()
    context.user_data["assessment"]["contact_value"] = value
    await update.message.reply_text(f"✅ Contact details saved: {value}")

    await update.message.reply_text(
        "<b>Question 7</b>\n\nWhat is your full name?",
        parse_mode=constants.ParseMode.HTML,
    )
    return QUESTION_FULLNAME


async def q7_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 7 response (full name)."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    text = update.message.text.strip()
    context.user_data["assessment"]["full_name"] = text
    await update.message.reply_text(f"✅ Received name: {text}")

    await update.message.reply_text(
        "<b>Question 8</b>\n\nGive us useful Link, Name, or any means to make research on your subject.\n\n<i>You can send multiple links in one message.</i>",
        parse_mode=constants.ParseMode.HTML,
    )
    return QUESTION_LINKS


async def q8_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 8 response (research links)."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    text = update.message.text.strip()
    context.user_data["assessment"]["research_links"] = text
    await update.message.reply_text(f"✅ Received research references.")

    await update.message.reply_text(
        "<b>📝 Additional Message</b>\n\nPlease send any extra context or notes for our team.",
        parse_mode=constants.ParseMode.HTML,
    )
    return QUESTION_ADDITIONAL


async def q9_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Question 9 response (additional message)."""
    if update.message and is_back_text(update.message.text):
        return await reset_to_welcome(update, context)

    text = update.message.text.strip()
    context.user_data["assessment"]["additional_message"] = text
    await update.message.reply_text(f"✅ Received additional message.")

    await send_preview(update, context)
    return CONFIRM


async def send_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send preview of assessment for confirmation."""
    user = update.effective_user
    assessment = context.user_data.get("assessment", {})
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    preview_text = (
        "<b>📋 Recheck the details you are about to submit to us:</b>\n\n"
        f"<b>👤 Name:</b> {_safe(assessment.get('full_name', 'Not provided'))}\n"
        f"<b>📌 Request:</b> {_safe(assessment.get('request', 'Not provided'))}\n"
        f"<b>🏢 Subject:</b> {_safe(assessment.get('subject', 'Not provided'))}\n"
        f"<b>📰 Coverage:</b> {_safe(assessment.get('coverage', 'Not provided'))}\n"
        f"<b>🎯 Goal:</b> {_safe(assessment.get('goal', 'Not provided'))}\n"
        f"<b>📧 Contact:</b> {_safe(assessment.get('contact_type', 'Not provided'))}\n"
        f"<b>✉️ Contact Details:</b> {_safe(assessment.get('contact_value', 'Not provided'))}\n"
        f"<b>🔗 Useful URLs:</b> {_safe(assessment.get('research_links', 'Not provided'))}\n"
        f"<b>📖 Previously submitted a Wikipedia draft:</b> {_safe(assessment.get('wiki_status', 'Not provided'))}\n"
        f"<b>📅 Time:</b> {timestamp}\n"
        f"<b>💬 Additional Message:</b> {_safe(assessment.get('additional_message', 'Not provided'))}\n"
    )

    await update.message.reply_text(preview_text, parse_mode=constants.ParseMode.HTML, reply_markup=build_preview_actions())


async def save_assessment(assessment: dict, user, source: str | None) -> bool:
    """Save assessment to Supabase."""
    if not supabase:
        logger.warning("Supabase client not configured. Skipping save.")
        return False

    record = {
        "telegram_id": user.id,
        "username": user.username,
        "full_name": assessment.get("full_name"),
        "request_type": assessment.get("request"),
        "subject": assessment.get("subject"),
        "goal": assessment.get("goal"),
        "wiki_status": assessment.get("wiki_status"),
        "contact_type": assessment.get("contact_type", "telegram"),
        "contact_value": assessment.get("contact_value", user.username if user.username else str(user.id)),
        "lead_status": "new",
        "consultant_notes": assessment.get("additional_message"),
        "source": source or "telegram",
    }
    try:
        result = supabase.table("assessments").insert(record).execute()
        if result.error:
            logger.error("Supabase insert error: %s", result.error)
            return False
        logger.info("Saved assessment for user %s", user.id)
        return True
    except Exception as exc:
        logger.exception("Failed to save assessment to Supabase: %s", exc)
        return False


def compute_lead_score(assessment: dict) -> tuple[int, str]:
    """Compute a simple internal lead score and priority."""
    score = 0
    coverage = assessment.get("coverage", "").lower()
    wiki_status = assessment.get("wiki_status", "").lower()
    subject = assessment.get("subject", "").lower()
    goal = assessment.get("goal", "")

    if "major" in coverage:
        score += 40
    elif "well" in coverage:
        score += 30
    elif "no" in coverage or "don'" in coverage:
        score += 10

    if "yes" in wiki_status:
        score += 25
    else:
        score += 5

    if "founder" in subject or "company" in subject or "public" in subject:
        score += 20
    elif "author" in subject or "artist" in subject:
        score += 15
    else:
        score += 10

    score += min(len(goal) // 15, 15)
    score = max(0, min(100, score))

    priority = "Low"
    if score >= 70:
        priority = "High"
    elif score >= 40:
        priority = "Medium"

    return score, priority


async def notify_admin_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Notify admin group of new submission."""
    user = update.effective_user
    assessment = context.user_data.get("assessment", {})
    if not user or not assessment:
        return

    timestamp = datetime.now(timezone.utc).strftime("%d %b %Y")
    score, priority = compute_lead_score(assessment)
    username_text = f"@{_safe(user.username)}" if user.username else "Not available"
    admin_text = (
        "<b>🚨 NEW NOTABLEPATH LEAD</b>\n\n"
        f"<b>Lead Score:</b> {score}\n"
        f"<b>Priority:</b> {priority}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"<b>👤 Name:</b> {_safe(assessment.get('full_name', 'N/A'))}\n"
        f"<b>🆔 Telegram:</b> {username_text}\n"
        f"<b>🏢 Subject:</b> {_safe(assessment.get('subject', 'N/A'))}\n"
        f"<b>📰 Coverage:</b> {_safe(assessment.get('coverage', 'N/A'))}\n"
        f"<b>📄 Draft:</b> {_safe(assessment.get('wiki_status', 'N/A'))}\n"
        f"<b>🎯 Goal:</b> {_safe(assessment.get('goal', 'N/A'))}\n"
        f"<b>� Contact:</b> {_safe(assessment.get('contact_type', 'N/A'))}\n"
        f"<b>✉️ Contact Details:</b> {_safe(assessment.get('contact_value', 'N/A'))}\n"
        f"<b>�🔗 Sources:</b> {_safe(assessment.get('research_links', 'N/A'))}\n"
        f"<b>📝 Additional Notes:</b> {_safe(assessment.get('additional_message', 'N/A'))}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"Submitted: {timestamp}\n\n"
        "When you start getting 10–20 leads per week, this matters."
    )

    try:
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=admin_text, parse_mode=constants.ParseMode.HTML, disable_web_page_preview=True)
        logger.info("Sent admin submission notification for user %s", user.id)
    except Exception as exc:
        logger.exception("Failed to send admin submission notification: %s", exc)


def _assessment_result_type(assessment: dict) -> int:
    coverage = assessment.get("coverage", "").lower()
    request = assessment.get("request", "").lower()
    wiki_status = assessment.get("wiki_status", "").lower()

    if any(keyword in request for keyword in ["rejected draft", "existing article", "deleted", "deletion", "delete"]):
        return 4
    if "yes" in wiki_status:
        return 4
    if "major" in coverage:
        return 1
    if "well" in coverage:
        return 2
    if "no" in coverage or "don'" in coverage or "dont" in coverage:
        return 3
    return 2


def render_assessment_overview(assessment: dict) -> str:
    subject = _safe(assessment.get("subject", "Not provided"))
    coverage = assessment.get("coverage", "Not provided")
    existing_draft = _safe(assessment.get("wiki_status", "Not provided"))
    goal = _safe(assessment.get("goal", "Not provided"))

    result_type = _assessment_result_type(assessment)

    if result_type == 1:
        return (
            "<b>📊 Wikipedia Readiness Overview</b>\n\n"
            "Thank you for completing the NotablePath Assessment.\n\n"
            "Based on the information provided, your responses show several positive indicators that may support further Wikipedia evaluation.\n\n"
            "━━━━━━━━━━━━━━\n\n"
            f"<b>📂 Subject Type</b>\n{subject}\n\n"
            "<b>📰 Source Coverage</b>\nStrong independent coverage identified\n\n"
            f"<b>📄 Existing Draft</b>\n{existing_draft}\n\n"
            f"<b>🎯 Main Goal</b>\n{goal}\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "🟢 <b>Preliminary Readiness</b>\n"
            "Positive Indicators Identified\n\n"
            "Your assessment suggests that your topic may have elements commonly associated with Wikipedia readiness.\n"
            "However, readiness depends on deeper review of source quality, independence, coverage depth, and alignment with Wikipedia standards.\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "✅ <b>Strength Indicators</b>\n\n"
            "• Independent sources appear available\n"
            "• External coverage may support notability evaluation\n"
            "• Existing information may provide a foundation for review\n"
            "• Topic appears suitable for further analysis\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "⚠ <b>Important Note</b>\n\n"
            "This overview is based only on your submitted information and does not represent a final Wikipedia evaluation.\n"
            "A detailed review of available sources and editorial considerations is recommended.\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "Recommended Next Step:\n"
            "Continue with a Professional Wikipedia Readiness Report for a deeper evaluation of your sources, risks, and preparation strategy."
        )

    if result_type == 3:
        return (
            "<b>📊 Wikipedia Readiness Overview</b>\n\n"
            "Thank you for completing the NotablePath Assessment.\n\n"
            "Based on the information provided, the current indicators suggest that additional preparation may be needed before moving forward with Wikipedia-related efforts.\n\n"
            "━━━━━━━━━━━━━━\n\n"
            f"<b>📂 Subject Type</b>\n{subject}\n\n"
            "<b>📰 Source Coverage</b>\nLimited independent coverage identified\n\n"
            f"<b>📄 Existing Draft</b>\n{existing_draft}\n\n"
            f"<b>🎯 Main Goal</b>\n{goal}\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "🔴 <b>Preliminary Readiness</b>\n"
            "Additional Preparation Recommended\n\n"
            "Wikipedia requires significant independent coverage from reliable sources.\n"
            "Current information may need further research and evaluation before determining whether Wikipedia standards can be met.\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "✅ <b>Areas To Improve</b>\n\n"
            "• Development of stronger independent source coverage\n"
            "• Evaluation of available references\n"
            "• Review of notability requirements\n"
            "• Improvement of documentation quality\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "Important:\n"
            "A limited readiness result does not automatically mean a topic cannot be considered in the future.\n"
            "The correct next step is understanding what evidence exists and what gaps need attention.\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "Recommended Next Step:\n"
            "A Professional Wikipedia Readiness Report can help identify opportunities, challenges, and recommended actions."
        )

    if result_type == 4:
        return (
            "<b>📊 Wikipedia Article Review Overview</b>\n\n"
            "Thank you for completing the NotablePath Assessment.\n\n"
            "Your request appears focused on understanding an existing Wikipedia article situation.\n\n"
            "━━━━━━━━━━━━━━\n\n"
            f"<b>📂 Subject Type</b>\n{subject}\n\n"
            f"<b>📰 Source Coverage</b>\n{coverage}\n\n"
            f"<b>📄 Article Status</b>\n{existing_draft}\n\n"
            f"<b>🎯 Main Goal</b>\n{goal}\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "🔵 <b>Review Category</b>\n"
            "Article History & Compliance Review Recommended\n\n"
            "When Wikipedia articles are deleted or challenged, common factors may include:\n"
            "• Insufficient independent sources\n"
            "• Notability concerns\n"
            "• Promotional wording\n"
            "• Citation problems\n"
            "• Policy compliance issues\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "<b>Next Review Areas:</b>\n\n"
            "• Previous article structure\n"
            "• Available sources\n"
            "• Deletion concerns\n"
            "• Editorial issues\n"
            "• Improvement possibilities\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "This overview is based on submitted information only.\n"
            "A deeper review of the article history and available sources is recommended.\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "Recommended Next Step:\n"
            "Request a Professional Wikipedia Readiness Report for a detailed analysis."
        )

    return (
        "<b>📊 Wikipedia Readiness Overview</b>\n\n"
        "Thank you for completing the NotablePath Assessment.\n\n"
        "Based on your responses, your topic shows some indicators that require a closer evaluation before determining the best approach.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"<b>📂 Subject Type</b>\n{subject}\n\n"
        f"<b>📰 Source Coverage</b>\n{coverage}\n\n"
        f"<b>📄 Existing Draft</b>\n{existing_draft}\n\n"
        f"<b>🎯 Main Goal</b>\n{goal}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🟡 <b>Preliminary Readiness</b>\n"
        "Requires Further Review\n\n"
        "Your answers suggest that there may be relevant information available, but important factors such as source independence, publication quality, and Wikipedia standards require additional analysis.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>Areas Requiring Review</b>\n\n"
        "• Strength and independence of available sources\n"
        "• Depth of third-party coverage\n"
        "• Reliability of publications\n"
        "• Current article/draft quality\n"
        "• Alignment with Wikipedia expectations\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "This assessment provides an initial overview only.\n\n"
        "A professional review is recommended to identify strengths, risks, and possible next steps.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "Recommended Next Step:\n"
        "Request a Professional Wikipedia Readiness Report for a detailed evaluation."
    )


def _clear_follow_up_jobs(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Cancel any pending follow-up jobs for this chat."""
    chat_data = context.application.chat_data.get(chat_id, {})
    jobs = chat_data.pop("follow_up_jobs", []) if isinstance(chat_data, dict) else []
    for job in jobs:
        try:
            job.schedule_removal()
        except Exception:
            pass


def _schedule_follow_up_job(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stage: str, delay: timedelta) -> None:
    """Schedule a follow-up reminder job for the chat."""
    if not hasattr(context, "application") or not context.application:
        return

    job = context.application.job_queue.run_once(
        _send_follow_up_message,
        delay,
        chat_id=chat_id,
        data={"stage": stage},
    )
    chat_data = context.application.chat_data.setdefault(chat_id, {})
    chat_data.setdefault("follow_up_jobs", []).append(job)


async def _send_follow_up_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a scheduled follow-up reminder based on the stage."""
    job = context.job
    if not job or not job.chat_id:
        return

    chat_id = job.chat_id
    stage = job.data.get("stage") if isinstance(job.data, dict) else None
    chat_data = context.application.chat_data.get(chat_id, {})

    if chat_data.get("assessment_completed"):
        return

    if stage == "start_no_button" and chat_data.get("assessment_started"):
        return

    button = None
    if stage == "start_no_button":
        text = (
            "👋 Just a quick reminder from NotablePath.\n\n"
            "Your Wikipedia Readiness Assessment is still available whenever you're ready.\n\n"
            "The assessment takes approximately 3 minutes and can help identify:\n\n"
            "✓ Source strength\n"
            "✓ Potential notability challenges\n"
            "✓ Next recommended steps\n\n"
            "We're here whenever you're ready to continue."
        )
        button = InlineKeyboardMarkup([[InlineKeyboardButton("▶ Continue Assessment", callback_data="CONTINUE_ASSESSMENT")]])
    elif stage == "assessment_incomplete_12h":
        text = (
            "📋 It looks like your Wikipedia Readiness Assessment was not completed.\n\n"
            "Many Wikipedia-related issues are easier to identify before significant time or resources are invested.\n\n"
            "Complete your assessment to receive your preliminary readiness overview.\n\n"
            "Estimated remaining time:\n"
            "Less than 2 minutes."
        )
        button = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Resume Assessment", callback_data="RESUME_ASSESSMENT")]])
    elif stage == "assessment_incomplete_60h":
        text = (
            "📚 Did you know?\n\n"
            "One of the most common reasons Wikipedia submissions fail is insufficient independent source coverage.\n\n"
            "A readiness review can often identify these issues before submission.\n\n"
            "Your assessment is still available whenever you're ready."
        )
        button = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Continue Review", callback_data="CONTINUE_REVIEW")]])
    elif stage == "assessment_incomplete_7d":
        text = (
            "📰 Wikipedia readiness often depends on factors such as:\n\n"
            "• Independent media coverage\n"
            "• Reliable sources\n"
            "• Subject notability\n"
            "• Editorial standards\n\n"
            "If your situation has changed recently, you can continue your assessment at any time.\n\n"
            "We're happy to help evaluate your situation."
        )
        button = InlineKeyboardMarkup([[InlineKeyboardButton("📊 Resume Assessment", callback_data="RESUME_ASSESSMENT")]])
    elif stage == "assessment_incomplete_21d":
        text = (
            "👋 This will be our final reminder regarding your incomplete assessment.\n\n"
            "If you still need guidance regarding Wikipedia readiness, source evaluation, or article improvement, NotablePath is available whenever you choose to continue.\n\n"
            "Thank you for your interest."
        )
        button = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Continue Assessment", callback_data="CONTINUE_ASSESSMENT")]])
    elif stage == "completed_24h":
        text = (
            "📊 Thank you for completing your NotablePath Assessment.\n\n"
            "Our preliminary review identified areas that may benefit from deeper analysis.\n\n"
            "A Professional Wikipedia Readiness Report can provide:\n\n"
            "✓ Source evaluation\n"
            "✓ Notability review\n"
            "✓ Risk assessment\n"
            "✓ Recommendations\n\n"
            "Would you like to learn more?"
        )
        button = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Professional Report", callback_data="PROFESSIONAL_REPORT")]])
    elif stage == "completed_3d":
        text = (
            "📚 Professional Wikipedia assessments often uncover issues that are difficult to identify through automated reviews alone.\n\n"
            "A detailed report can help clarify:\n\n"
            "• Source strength\n"
            "• Readiness level\n"
            "• Editorial risks\n"
            "• Recommended next steps\n\n"
            "If you'd like a deeper review, we're available to help."
        )
        button = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Request Report", callback_data="REQUEST_REPORT")]])
    elif stage == "completed_7d":
        text = (
            "🎯 Many successful Wikipedia projects begin with understanding the strengths and weaknesses of available sources.\n\n"
            "If you're still considering a detailed review, you can request a Professional Wikipedia Readiness Report at any time."
        )
        button = InlineKeyboardMarkup([[InlineKeyboardButton("💼 Request Assessment", callback_data="REQUEST_ASSESSMENT")]])
    else:
        return

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=constants.ParseMode.HTML,
            reply_markup=button,
        )
    except Exception as exc:
        logger.warning("Failed to send follow-up reminder: %s", exc)


def render_professional_report_text() -> str:
    return (
        "<b>🔍 Professional Wikipedia Readiness Report</b>\n\n"
        "If you would like a deeper review, <b>NotablePath</b> offers a Professional Wikipedia Readiness Report.\n\n"
        "Included:\n"
        "✓ Source Evaluation\n"
        "✓ Notability Review\n"
        "✓ Risk Assessment\n"
        "✓ Editorial Considerations\n"
        "✓ Recommendations\n"
        "✓ Suggested Next Steps\n\n"
        "This report is prepared manually after reviewing your submitted information and available independent sources.\n\n"
        "<b>Price:</b> $Negotiable\n\n"
        "<b>Because every Wikipedia situation is different, pricing depends on complexity.\n\n"
    )


def build_professional_report_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Request Professional Report",
            url="https://t.me/Enochs_world?text=Hello%2C%0A%0A%22I%20completed%20the%20NotablePath%20Assessment%20and%20would%20like%20to%20request%20a%20Professional%20Wikipedia%20Readiness%20Report.%0A%0APlease%20provide%20the%20next%20steps%20and%20payment%20method.%22"
        )]
    ])


async def confirm_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle submission confirmation (inline button)."""
    query = update.callback_query
    await query.answer()

    if query.data == "SUBMIT_ASSESSMENT":
        assessment = context.user_data.get("assessment", {})
        user = update.effective_user
        source_text = context.user_data.get("start_source", "telegram")

        saved = await save_assessment(assessment, user, source_text)
        if saved:
            await query.message.reply_text("✅ Your details were submitted successfully. Our team will review them soon.")
        else:
            # await query.message.reply_text("⚠️ Your submission was recorded, but there was an issue saving to the database. Please try again.")
            await query.message.reply_text("✅ Your details were submitted successfully. Check the message below to see your result.")

        try:
            await notify_admin_submission(update, context)
        except Exception as exc:
            logger.warning("Failed to notify admin: %s", exc)

        chat_id = query.message.chat_id if query.message else None
        if chat_id:
            _clear_follow_up_jobs(context, chat_id)
            chat_data = context.application.chat_data.setdefault(chat_id, {})
            chat_data["assessment_completed"] = True
            _schedule_follow_up_job(context, chat_id, "completed_24h", timedelta(hours=24))
            _schedule_follow_up_job(context, chat_id, "completed_3d", timedelta(days=3))
            _schedule_follow_up_job(context, chat_id, "completed_7d", timedelta(days=7))

        await query.message.reply_text(render_assessment_overview(assessment), parse_mode=constants.ParseMode.HTML)

        report_text = render_professional_report_text()
        await query.message.reply_text(report_text, parse_mode=constants.ParseMode.HTML,
            reply_markup=build_professional_report_markup()
        )

        context.user_data.pop("assessment", None)
        return ConversationHandler.END

    if query.data == "EDIT_ASSESSMENT":
        await query.message.reply_text(
            "Please, because you need to edit something, you will start the assessment process again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Start Process Again", callback_data="RESTART_ASSESSMENT")]]),
        )
        return ConversationHandler.END

    return ConversationHandler.END


async def cancel_assessment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel assessment."""
    if update.message:
        await update.message.reply_text("Assessment canceled. You can start again with /assessment.")
    context.user_data.pop("assessment", None)
    return ConversationHandler.END


def main() -> None:
    """Main bot entry point."""
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    assessment_handler = ConversationHandler(
        entry_points=[
            CommandHandler("assessment", assessment_start),
            MessageHandler(filters.Regex("^🧠 Assessment$"), assessment_start),
            CallbackQueryHandler(assessment_start, pattern="^RESTART_ASSESSMENT$"),
        ],
        states={
            QUESTION_CONTINUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, q_continue)],
            QUESTION_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, q1_handler)],
            QUESTION_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, q2_handler)],
            QUESTION_COVERAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, q3_handler)],
            QUESTION_PREVIOUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, q4_handler)],
            QUESTION_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, q5_handler)],
            QUESTION_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, q6_handler)],
            QUESTION_CONTACT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, q6_value_handler)],
            QUESTION_FULLNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, q7_handler)],
            QUESTION_LINKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, q8_handler)],
            QUESTION_ADDITIONAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, q9_handler)],
            CONFIRM: [CallbackQueryHandler(confirm_submission, pattern="^(SUBMIT_ASSESSMENT|EDIT_ASSESSMENT)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_assessment)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("allcommands", allcommands))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("services", services_command))
    app.add_handler(assessment_handler)
    app.add_handler(CallbackQueryHandler(button_router, pattern="^(SERVICE_BACK|ABOUT_US|HELP_MENU|MAIN_MENU|VIEW_COMMANDS|OUR_SERVICES|CONTINUE_ASSESSMENT|RESUME_ASSESSMENT|CONTINUE_REVIEW|PROFESSIONAL_REPORT|REQUEST_REPORT|REQUEST_ASSESSMENT)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Starting NotablePath bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
