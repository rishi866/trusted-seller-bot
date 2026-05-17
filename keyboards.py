from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PRIMARY = "primary"
SUCCESS = "success"
DANGER  = "danger"


def _stagger(i: int) -> str:
    return (SUCCESS, PRIMARY, DANGER)[i % 3]


def _btn(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    style: str | None = None,
) -> InlineKeyboardButton:
    kwargs: dict = {}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    if style is not None:
        kwargs["style"] = style
    return InlineKeyboardButton(text, **kwargs)


# ── Main Menu ─────────────────────────────────────────────────────────────────

def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn("🛒 Sell",  callback_data="menu:sell",  style=SUCCESS),
            _btn("🛍️ Buy",   callback_data="menu:buy",   style=SUCCESS),
        ],
        [
            _btn("🔍 Search",      callback_data="menu:search",     style=PRIMARY),
            _btn("📋 My Listings", callback_data="menu:mylistings", style=PRIMARY),
        ],
        [
            _btn("🔗 Referral Link", callback_data="menu:mylink",  style=SUCCESS),
            _btn("📊 My Stats",      callback_data="menu:mystats", style=PRIMARY),
        ],
        [
            _btn("👤 My Profile",  callback_data="menu:profile",     style=PRIMARY),
            _btn("🏆 Leaderboard", callback_data="menu:leaderboard", style=SUCCESS),
        ],
        [
            _btn("⭐ Top Sellers",  callback_data="menu:topsellers", style=PRIMARY),
            _btn("👑 Trust Ranking", callback_data="menu:ranking",   style=SUCCESS),
        ],
        [
            _btn("✅ Get Verified", callback_data="menu:verify",   style=SUCCESS),
            _btn("🤝 My Deals",     callback_data="menu:mydeals",  style=PRIMARY),
        ],
        [
            _btn("🏅 Badges", callback_data="menu:badges", style=PRIMARY),
            _btn("❓ Help",   callback_data="menu:help",   style=PRIMARY),
        ],
        [
            _btn("🃏 Post My Card", callback_data="menu:mycard", style=SUCCESS),
        ],
    ]
    if is_admin:
        rows.append([_btn("⚙️ Admin Panel", callback_data="menu:adminpanel", style=DANGER)])
    return InlineKeyboardMarkup(rows)


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("🏠 Main Menu", callback_data="menu:home", style=PRIMARY)],
    ])


# ── Seller Card / Trust ───────────────────────────────────────────────────────

def trust_profile_kb(seller_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("👍 Trust", callback_data=f"trust_{seller_id}", style=SUCCESS),
            _btn("👤 Profile", callback_data=f"profile_{seller_id}", style=PRIMARY),
        ]
    ])


# ── Verification ──────────────────────────────────────────────────────────────

def verify_admin_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("✅ Approve", callback_data=f"verify_approve_{user_id}", style=SUCCESS),
            _btn("❌ Reject",  callback_data=f"verify_reject_{user_id}",  style=DANGER),
        ]
    ])


# ── Deal Proposal ─────────────────────────────────────────────────────────────

def deal_propose_kb(deal_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("✅ Accept",  callback_data=f"deal_accept_{deal_id}_{user_id}",  style=SUCCESS),
            _btn("❌ Decline", callback_data=f"deal_decline_{deal_id}_{user_id}", style=DANGER),
        ]
    ])


def deal_actions_kb(deal_id: int, status: str) -> InlineKeyboardMarkup:
    rows = []
    if status == "active":
        rows.append([
            _btn(f"✅ Complete #{deal_id}", callback_data=f"deal:complete:{deal_id}", style=SUCCESS),
        ])
        rows.append([
            _btn(f"❌ Cancel #{deal_id}", callback_data=f"deal:cancel:{deal_id}", style=DANGER),
        ])
    rows.append([_btn("🏠 Main Menu", callback_data="menu:home", style=PRIMARY)])
    return InlineKeyboardMarkup(rows)


# ── Admin Panel ───────────────────────────────────────────────────────────────

def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("📊 Group Stats",  callback_data="adm:stats",        style=PRIMARY),
            _btn("🚫 Scam Words",   callback_data="adm:scamwords",    style=DANGER),
        ],
        [
            _btn("🔨 Ban",          callback_data="adm:ban_info",     style=DANGER),
            _btn("🔇 Mute",         callback_data="adm:mute_info",    style=DANGER),
        ],
        [
            _btn("⚠️ Warn",         callback_data="adm:warn_info",    style=DANGER),
            _btn("✅ Approve",       callback_data="adm:approve_info", style=SUCCESS),
        ],
        [
            _btn("📢 Announce",     callback_data="adm:announce_info", style=PRIMARY),
            _btn("🏅 Set Badge",    callback_data="adm:badge_info",    style=PRIMARY),
        ],
        [
            _btn("🃏 Seller Card",  callback_data="adm:sellercard_info", style=SUCCESS),
            _btn("🎬 Emoji Capture", callback_data="adm:emoji",          style=PRIMARY),
        ],
        [_btn("🏠 Main Menu", callback_data="menu:home", style=PRIMARY)],
    ])
