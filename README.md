# AI Tools Buy/Sell — Telegram Group Bot

A fully-featured Telegram group bot for an "AI Tools Buy/Sell" community with verification, referrals, listings, admin moderation, deal escrow, ratings, and trust voting. All user-facing messages are in **Hinglish** (Hindi + English mix).

---

## Features

1. **Verification & Security** — Math captcha for new members, link filter, scam word filter, anti-flood mute
2. **Referral System** — Referral links, badge milestones, leaderboard
3. **Buy/Sell Listings** — Conversation-based listing creation, search, manage
4. **Admin Commands** — Ban, mute, warn, announce, approve/reject verified sellers
5. **Daily Automation** — 9 AM morning post, Sunday leaderboard (APScheduler via PTB JobQueue)
6. **Verified Seller** — Request/approve/reject verified seller badge
7. **Rating & Review** — Star ratings, avg calculation, low-rating alerts to admins
8. **Deal Escrow** — Create deals, both-party accept, dual confirmation complete, auto-cancel
9. **Seller Card & Trust Voting** — Spotlight cards, trust votes (require completed deal)

---

## Environment Variables

Create a `.env` file in the project root:

```env
BOT_TOKEN=your_telegram_bot_token
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_or_service_key
GROUP_ID=-1001234567890
ADMIN_IDS=123456789,987654321
```

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Supabase anon or service role key |
| `GROUP_ID` | Telegram group/supergroup ID (negative number) |
| `ADMIN_IDS` | Comma-separated Telegram user IDs of bot admins |

---

## Supabase Database Setup

Run the following SQL in your Supabase SQL editor:

```sql
-- Members
CREATE TABLE members (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT UNIQUE NOT NULL,
  username TEXT DEFAULT '',
  full_name TEXT DEFAULT '',
  joined_at TIMESTAMPTZ DEFAULT NOW(),
  referred_by BIGINT,
  referral_count INTEGER DEFAULT 0,
  warnings INTEGER DEFAULT 0,
  is_banned BOOLEAN DEFAULT FALSE,
  badge TEXT,
  avg_rating FLOAT DEFAULT 0,
  is_verified BOOLEAN DEFAULT FALSE,
  verified_at TIMESTAMPTZ,
  verified_by BIGINT,
  trust_count INTEGER DEFAULT 0,
  avg_response_time INTEGER DEFAULT 0,
  total_deals INTEGER DEFAULT 0
);

-- Listings
CREATE TABLE listings (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  username TEXT DEFAULT '',
  type TEXT NOT NULL CHECK (type IN ('buy','sell')),
  tool_name TEXT NOT NULL,
  price TEXT,
  description TEXT,
  file_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ,
  is_active BOOLEAN DEFAULT TRUE
);

-- Referrals
CREATE TABLE referrals (
  id BIGSERIAL PRIMARY KEY,
  referrer_id BIGINT NOT NULL,
  referred_id BIGINT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scam words
CREATE TABLE scam_words (
  id BIGSERIAL PRIMARY KEY,
  word TEXT UNIQUE NOT NULL,
  added_by BIGINT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Badge config
CREATE TABLE badge_config (
  id BIGSERIAL PRIMARY KEY,
  required_count INTEGER UNIQUE NOT NULL,
  badge_name TEXT NOT NULL,
  is_admin_level BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Reviews
CREATE TABLE reviews (
  id BIGSERIAL PRIMARY KEY,
  reviewer_id BIGINT NOT NULL,
  seller_id BIGINT NOT NULL,
  rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment TEXT,
  deal_id BIGINT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Deals
CREATE TABLE deals (
  id BIGSERIAL PRIMARY KEY,
  buyer_id BIGINT NOT NULL,
  seller_id BIGINT NOT NULL,
  amount FLOAT NOT NULL,
  tool_name TEXT DEFAULT '',
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending','active','completed','cancelled')),
  buyer_confirmed BOOLEAN DEFAULT FALSE,
  seller_confirmed BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  listing_id BIGINT
);

-- Trust votes
CREATE TABLE trust_votes (
  id BIGSERIAL PRIMARY KEY,
  voter_id BIGINT NOT NULL,
  seller_id BIGINT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(voter_id, seller_id)
);
```

### Recommended indexes for performance

```sql
CREATE INDEX idx_members_user_id ON members(user_id);
CREATE INDEX idx_listings_user_id ON listings(user_id);
CREATE INDEX idx_listings_active ON listings(is_active);
CREATE INDEX idx_listings_type ON listings(type);
CREATE INDEX idx_referrals_referrer ON referrals(referrer_id);
CREATE INDEX idx_referrals_referred ON referrals(referred_id);
CREATE INDEX idx_reviews_seller ON reviews(seller_id);
CREATE INDEX idx_deals_buyer ON deals(buyer_id);
CREATE INDEX idx_deals_seller ON deals(seller_id);
CREATE INDEX idx_trust_votes_seller ON trust_votes(seller_id);
```

---

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill env
cp .env.example .env

# Run
python bot.py
```

---

## Railway Deployment

1. Push this project to a GitHub repository
2. Go to [Railway](https://railway.app) → New Project → Deploy from GitHub
3. Select your repository
4. Add environment variables in Railway dashboard:
   - `BOT_TOKEN`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `GROUP_ID`
   - `ADMIN_IDS`
5. Railway will auto-detect `railway.toml` and use `python bot.py` as start command
6. Deploy!

---

## Bot Commands Reference

### User Commands
| Command | Description |
|---|---|
| `/start` | Start the bot / register |
| `/sell` | Create a sell listing (conversation) |
| `/buy` | Create a buy request (conversation) |
| `/search <keyword>` | Search active listings |
| `/mylistings` | View your active listings |
| `/delist <id>` | Deactivate a listing |
| `/mylink` | Get your referral link |
| `/mystats` | View referral stats and badge |
| `/badges` | View all badge milestones |
| `/leaderboard` | Top 10 referrers |
| `/profile` | View your profile |
| `/profile @username` | View another user's profile |
| `/review @seller <1-5> <comment>` | Leave a review for a seller |
| `/topsellers` | Top sellers by avg rating |
| `/ranking` | Trust vote ranking |
| `/verify` | Request verified seller status |
| `/verified` | List all verified sellers |
| `/deal @buyer @seller <amount> [tool]` | Create a deal |
| `/mydeals` | List your deals |
| `/dealcomplete <id>` | Confirm deal completion |
| `/canceldeal <id>` | Request deal cancellation |
| `/help` | Show all commands |

### Admin Commands
| Command | Description |
|---|---|
| `/ban @user` | Ban user from group |
| `/mute @user <minutes>` | Mute user for N minutes |
| `/warn @user` | Issue warning (auto-ban at limit) |
| `/warnings @user` | Show warning count |
| `/stats` | Group statistics |
| `/addword <word>` | Add scam filter word |
| `/removeword <word>` | Remove scam filter word |
| `/announce <message>` | DM all members |
| `/approve @user` | Approve verified seller |
| `/reject @user <reason>` | Reject verification with reason |
| `/sellercard @user` | Post seller spotlight card |
| `/setbadge <count> <name> [admin]` | Create/update badge milestone |
| `/editbadge <count> <name>` | Edit existing badge name |
| `/removebadge <count>` | Remove a badge milestone |

---

## Bot Setup in BotFather

1. Message @BotFather → `/newbot`
2. Set bot name and username
3. Enable group privacy off: `/setprivacy` → Disable (so bot can read group messages)
4. Add the bot to your group as **Administrator** with these permissions:
   - Delete messages
   - Ban users
   - Restrict members
   - Pin messages (optional)

---

## Architecture Notes

- All Supabase calls are wrapped with `asyncio.to_thread()` for async compatibility
- Scam word list is cached in `bot_data` and refreshed every 30 minutes
- Captcha state, deal confirmations, and flood tracking are stored in `bot_data` (in-memory)
- ConversationHandlers use `per_user=True, per_chat=False` so conversations work in DMs
- Scheduled jobs use PTB's built-in JobQueue (backed by APScheduler)
