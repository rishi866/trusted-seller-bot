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
