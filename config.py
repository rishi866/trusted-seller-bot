import os
from dotenv import load_dotenv
import pytz

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
GROUP_INVITE_LINK = os.getenv("GROUP_INVITE_LINK", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

import logging as _logging
_log = _logging.getLogger(__name__)
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN env var is required")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY env vars are required")
# GROUP_ID is now optional — 0 means "all groups mode"
if not GROUP_ID:
    _log.info("GROUP_ID not set — running in all-groups mode")
if not ADMIN_IDS:
    _log.warning("ADMIN_IDS is empty — no hardcoded admins set")

# Alias for clarity: SUPERADMIN_IDS can manage any group
SUPERADMIN_IDS = ADMIN_IDS

IST = pytz.timezone("Asia/Kolkata")

CAPTCHA_TIMEOUT = 120       # seconds
FLOOD_MSG_COUNT = 5
FLOOD_TIME_WINDOW = 10      # seconds
FLOOD_MUTE_DURATION = 600   # seconds (10 min)
LISTING_EXPIRY_DAYS = 7
DEAL_TIMEOUT_HOURS = 24
WARNING_LIMIT = 3
LOW_RATING_THRESHOLD = 2.0
LOW_RATING_MIN_REVIEWS = 5

DEFAULT_SCAM_WORDS = [
    "free mein do", "guaranteed", "double money", "investment", "giveaway"
]
