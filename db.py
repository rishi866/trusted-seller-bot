import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY, DEFAULT_SCAM_WORDS, LISTING_EXPIRY_DAYS, DEAL_TIMEOUT_HOURS

logger = logging.getLogger(__name__)

_supabase: Optional[Client] = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


# ─────────────────────────────────────────────────────────────────────────────
# MEMBERS
# ─────────────────────────────────────────────────────────────────────────────

async def get_member_by_username(username: str) -> Optional[dict]:
    uname = username.lstrip("@").lower()
    def _get():
        res = get_supabase().table("members").select("*").ilike("username", uname).limit(1).execute()
        return res.data[0] if res.data else None
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_member_by_username error: {e}")
        return None


async def get_member(user_id: int) -> Optional[dict]:
    def _get():
        res = get_supabase().table("members").select("*").eq("user_id", user_id).execute()
        return res.data[0] if res.data else None
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_member error: {e}")
        return None


async def create_member(user_id: int, username: str, full_name: str, referred_by: Optional[int] = None) -> Optional[dict]:
    def _create():
        payload = {
            "user_id": user_id,
            "username": username or "",
            "full_name": full_name or "",
            "referred_by": referred_by,
        }
        res = get_supabase().table("members").insert(payload).execute()
        return res.data[0] if res.data else None
    try:
        return await asyncio.to_thread(_create)
    except Exception as e:
        logger.error(f"create_member error: {e}")
        return None


async def get_or_create_member(user_id: int, username: str, full_name: str, referred_by: Optional[int] = None) -> Optional[dict]:
    member = await get_member(user_id)
    if member:
        return member
    return await create_member(user_id, username, full_name, referred_by)


async def update_member(user_id: int, **kwargs):
    def _update():
        get_supabase().table("members").update(kwargs).eq("user_id", user_id).execute()
    try:
        await asyncio.to_thread(_update)
    except Exception as e:
        logger.error(f"update_member error: {e}")


async def get_all_members() -> list:
    def _get():
        res = get_supabase().table("members").select("user_id, username, full_name").execute()
        return res.data or []
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_all_members error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# REFERRALS
# ─────────────────────────────────────────────────────────────────────────────

async def add_referral(referrer_id: int, referred_id: int):
    """Returns new referral count or False on failure/duplicate."""
    def _add():
        supabase = get_supabase()
        # Check duplicate
        existing = supabase.table("referrals").select("id").eq("referred_id", referred_id).execute()
        if existing.data:
            return False
        supabase.table("referrals").insert({"referrer_id": referrer_id, "referred_id": referred_id}).execute()
        # Increment referral_count
        member = supabase.table("members").select("referral_count").eq("user_id", referrer_id).execute()
        if not member.data:
            return False
        new_count = (member.data[0].get("referral_count") or 0) + 1
        supabase.table("members").update({"referral_count": new_count}).eq("user_id", referrer_id).execute()
        return new_count
    try:
        return await asyncio.to_thread(_add)
    except Exception as e:
        logger.error(f"add_referral error: {e}")
        return False


async def get_referral_count(user_id: int) -> int:
    def _get():
        res = get_supabase().table("members").select("referral_count").eq("user_id", user_id).execute()
        return (res.data[0].get("referral_count") or 0) if res.data else 0
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_referral_count error: {e}")
        return 0


async def get_top_referrers(limit: int = 10) -> list:
    def _get():
        res = get_supabase().table("members").select("user_id, username, full_name, referral_count, badge").order("referral_count", desc=True).limit(limit).execute()
        return res.data or []
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_top_referrers error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# BADGES
# ─────────────────────────────────────────────────────────────────────────────

async def get_all_badges() -> list:
    def _get():
        res = get_supabase().table("badge_config").select("*").order("required_count", desc=False).execute()
        return res.data or []
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_all_badges error: {e}")
        return []


async def set_badge_config(required_count: int, badge_name: str, is_admin_level: bool = False) -> bool:
    def _set():
        supabase = get_supabase()
        existing = supabase.table("badge_config").select("id").eq("required_count", required_count).execute()
        if existing.data:
            supabase.table("badge_config").update({"badge_name": badge_name, "is_admin_level": is_admin_level}).eq("required_count", required_count).execute()
        else:
            supabase.table("badge_config").insert({"required_count": required_count, "badge_name": badge_name, "is_admin_level": is_admin_level}).execute()
        return True
    try:
        return await asyncio.to_thread(_set)
    except Exception as e:
        logger.error(f"set_badge_config error: {e}")
        return False


async def remove_badge_config(required_count: int) -> bool:
    def _remove():
        get_supabase().table("badge_config").delete().eq("required_count", required_count).execute()
        return True
    try:
        return await asyncio.to_thread(_remove)
    except Exception as e:
        logger.error(f"remove_badge_config error: {e}")
        return False


async def get_badge_for_count(count: int) -> Optional[dict]:
    """Returns the highest badge the user has earned."""
    def _get():
        res = get_supabase().table("badge_config").select("*").lte("required_count", count).order("required_count", desc=True).limit(1).execute()
        return res.data[0] if res.data else None
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_badge_for_count error: {e}")
        return None


async def get_next_badge(count: int) -> Optional[dict]:
    """Returns the next badge milestone above the current count."""
    def _get():
        res = get_supabase().table("badge_config").select("*").gt("required_count", count).order("required_count", desc=False).limit(1).execute()
        return res.data[0] if res.data else None
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_next_badge error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# LISTINGS
# ─────────────────────────────────────────────────────────────────────────────

async def create_listing(user_id: int, username: str, type_: str, tool_name: str, price: str, description: str, file_id: Optional[str] = None) -> Optional[dict]:
    def _create():
        from datetime import timezone as tz
        now = datetime.now(tz.utc)
        expires_at = (now + timedelta(days=LISTING_EXPIRY_DAYS)).isoformat()
        payload = {
            "user_id": user_id,
            "username": username or "",
            "type": type_,
            "tool_name": tool_name,
            "price": price,
            "description": description,
            "file_id": file_id,
            "expires_at": expires_at,
            "is_active": True,
        }
        res = get_supabase().table("listings").insert(payload).execute()
        return res.data[0] if res.data else None
    try:
        return await asyncio.to_thread(_create)
    except Exception as e:
        logger.error(f"create_listing error: {e}")
        return None


async def search_listings(keyword: str) -> list:
    def _search():
        from datetime import datetime, timezone as tz
        now_iso = datetime.now(tz.utc).isoformat()
        res = (
            get_supabase().table("listings")
            .select("*")
            .eq("is_active", True)
            .gt("expires_at", now_iso)
            .ilike("tool_name", f"%{keyword}%")
            .execute()
        )
        return res.data or []
    try:
        return await asyncio.to_thread(_search)
    except Exception as e:
        logger.error(f"search_listings error: {e}")
        return []


async def get_user_listings(user_id: int) -> list:
    def _get():
        res = get_supabase().table("listings").select("*").eq("user_id", user_id).eq("is_active", True).execute()
        return res.data or []
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_user_listings error: {e}")
        return []


async def delist_listing(listing_id: int, user_id: int) -> bool:
    def _delist():
        res = get_supabase().table("listings").select("id").eq("id", listing_id).eq("user_id", user_id).eq("is_active", True).execute()
        if not res.data:
            return False
        get_supabase().table("listings").update({"is_active": False}).eq("id", listing_id).execute()
        return True
    try:
        return await asyncio.to_thread(_delist)
    except Exception as e:
        logger.error(f"delist_listing error: {e}")
        return False


async def expire_old_listings():
    def _expire():
        from datetime import timezone as tz
        now = datetime.now(tz.utc).isoformat()
        get_supabase().table("listings").update({"is_active": False}).eq("is_active", True).lt("expires_at", now).execute()
    try:
        await asyncio.to_thread(_expire)
    except Exception as e:
        logger.error(f"expire_old_listings error: {e}")


async def get_active_listing_counts() -> tuple:
    def _get():
        supabase = get_supabase()
        sell = supabase.table("listings").select("id", count="exact").eq("is_active", True).eq("type", "sell").execute()
        buy = supabase.table("listings").select("id", count="exact").eq("is_active", True).eq("type", "buy").execute()
        return (sell.count or 0, buy.count or 0)
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_active_listing_counts error: {e}")
        return (0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# SCAM WORDS
# ─────────────────────────────────────────────────────────────────────────────

async def get_scam_words() -> list:
    def _get():
        res = get_supabase().table("scam_words").select("word").execute()
        return [row["word"] for row in res.data] if res.data else []
    try:
        words = await asyncio.to_thread(_get)
        return words if words else DEFAULT_SCAM_WORDS
    except Exception as e:
        logger.error(f"get_scam_words error: {e}")
        return DEFAULT_SCAM_WORDS


async def add_scam_word(word: str, added_by: int) -> bool:
    def _add():
        supabase = get_supabase()
        existing = supabase.table("scam_words").select("id").eq("word", word.lower()).execute()
        if existing.data:
            return False
        supabase.table("scam_words").insert({"word": word.lower(), "added_by": added_by}).execute()
        return True
    try:
        return await asyncio.to_thread(_add)
    except Exception as e:
        logger.error(f"add_scam_word error: {e}")
        return False


async def remove_scam_word(word: str) -> bool:
    def _remove():
        res = get_supabase().table("scam_words").select("id").eq("word", word.lower()).execute()
        if not res.data:
            return False
        get_supabase().table("scam_words").delete().eq("word", word.lower()).execute()
        return True
    try:
        return await asyncio.to_thread(_remove)
    except Exception as e:
        logger.error(f"remove_scam_word error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# WARNINGS
# ─────────────────────────────────────────────────────────────────────────────

async def add_warning(user_id: int) -> int:
    def _add():
        supabase = get_supabase()
        member = supabase.table("members").select("warnings").eq("user_id", user_id).execute()
        if not member.data:
            return 0
        new_count = (member.data[0].get("warnings") or 0) + 1
        supabase.table("members").update({"warnings": new_count}).eq("user_id", user_id).execute()
        return new_count
    try:
        return await asyncio.to_thread(_add)
    except Exception as e:
        logger.error(f"add_warning error: {e}")
        return 0


async def get_warnings(user_id: int) -> int:
    def _get():
        res = get_supabase().table("members").select("warnings").eq("user_id", user_id).execute()
        return (res.data[0].get("warnings") or 0) if res.data else 0
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_warnings error: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS
# ─────────────────────────────────────────────────────────────────────────────

async def add_review(reviewer_id: int, seller_id: int, rating: int, comment: str, deal_id: Optional[int] = None) -> tuple:
    def _add():
        supabase = get_supabase()
        # Check already reviewed
        existing = supabase.table("reviews").select("id").eq("reviewer_id", reviewer_id).eq("seller_id", seller_id).execute()
        if existing.data:
            return (None, "already_reviewed")
        # Verify a completed deal exists between the two parties
        d1 = supabase.table("deals").select("id").eq("status", "completed").eq("buyer_id", reviewer_id).eq("seller_id", seller_id).limit(1).execute()
        d2 = supabase.table("deals").select("id").eq("status", "completed").eq("buyer_id", seller_id).eq("seller_id", reviewer_id).limit(1).execute()
        if not d1.data and not d2.data:
            return (None, "no_deal")
        payload = {
            "reviewer_id": reviewer_id,
            "seller_id": seller_id,
            "rating": rating,
            "comment": comment,
            "deal_id": deal_id,
        }
        res = supabase.table("reviews").insert(payload).execute()
        if not res.data:
            return (None, "error")
        review = res.data[0]
        # Recalculate avg
        all_reviews = supabase.table("reviews").select("rating").eq("seller_id", seller_id).execute()
        if all_reviews.data:
            ratings = [r["rating"] for r in all_reviews.data]
            avg = sum(ratings) / len(ratings)
            supabase.table("members").update({"avg_rating": round(avg, 2)}).eq("user_id", seller_id).execute()
        return (review, "ok")
    try:
        return await asyncio.to_thread(_add)
    except Exception as e:
        logger.error(f"add_review error: {e}")
        return (None, "error")


async def get_seller_reviews(seller_id: int, limit: int = 3) -> list:
    def _get():
        res = get_supabase().table("reviews").select("*").eq("seller_id", seller_id).order("created_at", desc=True).limit(limit).execute()
        return res.data or []
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_seller_reviews error: {e}")
        return []


async def get_seller_avg_rating(seller_id: int) -> tuple:
    def _get():
        res = get_supabase().table("reviews").select("rating").eq("seller_id", seller_id).execute()
        if not res.data:
            return (0.0, 0)
        ratings = [r["rating"] for r in res.data]
        avg = sum(ratings) / len(ratings)
        return (round(avg, 2), len(ratings))
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_seller_avg_rating error: {e}")
        return (0.0, 0)


async def get_top_sellers_by_rating(limit: int = 10) -> list:
    def _get():
        res = get_supabase().table("members").select("user_id, username, full_name, avg_rating, total_deals, badge, is_verified").order("avg_rating", desc=True).limit(limit).execute()
        return res.data or []
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_top_sellers_by_rating error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# DEALS
# ─────────────────────────────────────────────────────────────────────────────

async def create_deal(buyer_id: int, seller_id: int, amount: float, tool_name: str, listing_id: Optional[int] = None) -> Optional[dict]:
    def _create():
        payload = {
            "buyer_id": buyer_id,
            "seller_id": seller_id,
            "amount": amount,
            "tool_name": tool_name,
            "listing_id": listing_id,
            "status": "pending",
            "buyer_confirmed": False,
            "seller_confirmed": False,
        }
        res = get_supabase().table("deals").insert(payload).execute()
        return res.data[0] if res.data else None
    try:
        return await asyncio.to_thread(_create)
    except Exception as e:
        logger.error(f"create_deal error: {e}")
        return None


async def get_deal(deal_id: int) -> Optional[dict]:
    def _get():
        res = get_supabase().table("deals").select("*").eq("id", deal_id).execute()
        return res.data[0] if res.data else None
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_deal error: {e}")
        return None


async def update_deal(deal_id: int, **kwargs) -> bool:
    def _update():
        get_supabase().table("deals").update(kwargs).eq("id", deal_id).execute()
        return True
    try:
        return await asyncio.to_thread(_update)
    except Exception as e:
        logger.error(f"update_deal error: {e}")
        return False


async def get_user_deals(user_id: int) -> list:
    def _get():
        supabase = get_supabase()
        as_buyer = supabase.table("deals").select("*").eq("buyer_id", user_id).execute().data or []
        as_seller = supabase.table("deals").select("*").eq("seller_id", user_id).execute().data or []
        combined = {d["id"]: d for d in as_buyer + as_seller}
        return list(combined.values())
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_user_deals error: {e}")
        return []


async def cancel_expired_deals():
    def _cancel():
        from datetime import timezone as tz
        cutoff = (datetime.now(tz.utc) - timedelta(hours=DEAL_TIMEOUT_HOURS)).isoformat()
        get_supabase().table("deals").update({"status": "cancelled"}).eq("status", "pending").lt("created_at", cutoff).execute()
    try:
        await asyncio.to_thread(_cancel)
    except Exception as e:
        logger.error(f"cancel_expired_deals error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TRUST VOTES
# ─────────────────────────────────────────────────────────────────────────────

async def add_trust_vote(voter_id: int, seller_id: int) -> str:
    def _vote():
        if voter_id == seller_id:
            return "self_vote"
        supabase = get_supabase()
        # Check for existing vote
        existing = supabase.table("trust_votes").select("id").eq("voter_id", voter_id).eq("seller_id", seller_id).execute()
        if existing.data:
            return "already_voted"
        # Verify completed deal exists (voter was buyer OR seller in a deal with the seller)
        d1 = supabase.table("deals").select("id").eq("status", "completed") \
                     .eq("buyer_id", voter_id).eq("seller_id", seller_id).limit(1).execute()
        d2 = supabase.table("deals").select("id").eq("status", "completed") \
                     .eq("buyer_id", seller_id).eq("seller_id", voter_id).limit(1).execute()
        if not d1.data and not d2.data:
            return "no_deal"
        try:
            supabase.table("trust_votes").insert({"voter_id": voter_id, "seller_id": seller_id}).execute()
        except Exception:
            return "already_voted"
        # Increment trust_count
        member = supabase.table("members").select("trust_count").eq("user_id", seller_id).execute()
        if member.data:
            new_count = (member.data[0].get("trust_count") or 0) + 1
            supabase.table("members").update({"trust_count": new_count}).eq("user_id", seller_id).execute()
        return "ok"
    try:
        return await asyncio.to_thread(_vote)
    except Exception as e:
        logger.error(f"add_trust_vote error: {e}")
        return "error"


async def get_top_by_trust(limit: int = 10) -> list:
    def _get():
        res = get_supabase().table("members").select("user_id, username, full_name, trust_count, avg_rating, badge, is_verified").order("trust_count", desc=True).limit(limit).execute()
        return res.data or []
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_top_by_trust error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# STATS
# ─────────────────────────────────────────────────────────────────────────────

async def get_group_stats() -> dict:
    def _get():
        from datetime import timezone as tz
        supabase = get_supabase()
        today_start = datetime.now(tz.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        total_members = supabase.table("members").select("id", count="exact").execute().count or 0
        listings_today = supabase.table("listings").select("id", count="exact").gte("created_at", today_start).execute().count or 0
        new_joins_today = supabase.table("members").select("id", count="exact").gte("joined_at", today_start).execute().count or 0
        return {
            "total_members": total_members,
            "listings_today": listings_today,
            "new_joins_today": new_joins_today,
        }
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_group_stats error: {e}")
        return {"total_members": 0, "listings_today": 0, "new_joins_today": 0}


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

async def set_verified(user_id: int, admin_id: int) -> bool:
    def _set():
        from datetime import timezone as tz
        get_supabase().table("members").update({
            "is_verified": True,
            "verified_at": datetime.now(tz.utc).isoformat(),
            "verified_by": admin_id,
        }).eq("user_id", user_id).execute()
        return True
    try:
        return await asyncio.to_thread(_set)
    except Exception as e:
        logger.error(f"set_verified error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM EMOJIS
# ─────────────────────────────────────────────────────────────────────────────

async def get_custom_emojis() -> list:
    def _get():
        res = get_supabase().table("custom_emojis").select("*").execute()
        return res.data or []
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_custom_emojis error: {e}")
        return []


async def save_custom_emoji(fallback: str, custom_id: str, keyword: str = "") -> bool:
    def _save():
        get_supabase().table("custom_emojis").upsert(
            {"fallback": fallback, "custom_id": custom_id, "keyword": keyword or ""},
            on_conflict="fallback",
        ).execute()
        return True
    try:
        return await asyncio.to_thread(_save)
    except Exception as e:
        logger.error(f"save_custom_emoji error: {e}")
        return False


async def delete_custom_emoji(fallback: str) -> bool:
    def _del():
        get_supabase().table("custom_emojis").delete().eq("fallback", fallback).execute()
        return True
    try:
        return await asyncio.to_thread(_del)
    except Exception as e:
        logger.error(f"delete_custom_emoji error: {e}")
        return False


async def get_card_cooldown(user_id: int) -> Optional[datetime]:
    """Return the last card post time for rate-limiting mycard."""
    def _get():
        res = get_supabase().table("members").select("card_last_posted").eq("user_id", user_id).execute()
        if not res.data:
            return None
        val = res.data[0].get("card_last_posted")
        if not val:
            return None
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_card_cooldown error: {e}")
        return None


async def set_card_cooldown(user_id: int) -> None:
    """Record that the user just posted their card."""
    from datetime import timezone as tz
    now = datetime.now(tz.utc).isoformat()
    await update_member(user_id, card_last_posted=now)


async def record_deal_confirmation(deal_id: int, user_id: int, buyer_id: int, seller_id: int) -> bool:
    """Persist deal completion confirmation. Returns True when BOTH parties confirmed."""
    def _record():
        supabase = get_supabase()
        if user_id == buyer_id:
            supabase.table("deals").update({"buyer_confirmed": True}).eq("id", deal_id).execute()
        elif user_id == seller_id:
            supabase.table("deals").update({"seller_confirmed": True}).eq("id", deal_id).execute()
        deal = supabase.table("deals").select("buyer_confirmed, seller_confirmed").eq("id", deal_id).execute()
        if not deal.data:
            return False
        d = deal.data[0]
        return bool(d.get("buyer_confirmed")) and bool(d.get("seller_confirmed"))
    try:
        return await asyncio.to_thread(_record)
    except Exception as e:
        logger.error(f"record_deal_confirmation error: {e}")
        return False


async def record_cancel_request(deal_id: int, user_id: int, buyer_id: int, seller_id: int) -> bool:
    """Persist cancel request. Returns True when BOTH parties requested."""
    def _record():
        supabase = get_supabase()
        if user_id == buyer_id:
            supabase.table("deals").update({"buyer_cancel_requested": True}).eq("id", deal_id).execute()
        elif user_id == seller_id:
            supabase.table("deals").update({"seller_cancel_requested": True}).eq("id", deal_id).execute()
        deal = supabase.table("deals").select("buyer_cancel_requested, seller_cancel_requested").eq("id", deal_id).execute()
        if not deal.data:
            return False
        d = deal.data[0]
        return bool(d.get("buyer_cancel_requested")) and bool(d.get("seller_cancel_requested"))
    try:
        return await asyncio.to_thread(_record)
    except Exception as e:
        logger.error(f"record_cancel_request error: {e}")
        return False


async def get_verified_sellers() -> list:
    def _get():
        res = get_supabase().table("members").select("user_id, username, full_name, avg_rating, total_deals, badge").eq("is_verified", True).execute()
        return res.data or []
    try:
        return await asyncio.to_thread(_get)
    except Exception as e:
        logger.error(f"get_verified_sellers error: {e}")
        return []
