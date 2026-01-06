# VIC CLM - Claude Code Notes

## Project Overview
Custom Language Model (CLM) backend for Lost London voice assistant (VIC).
- **Frontend**: `/Users/dankeegan/lost.london-app` (Next.js, deployed to lost.london)
- **CLM Backend**: This repo, deployed to `https://vic-clm.vercel.app`
- **Voice**: Hume EVI integration

## Current Status (Jan 6, 2026)

### What Happened - The Outage
1. **Jan 5, 2026**: Made changes to switch from Groq to Google Gemini to fix rate limiting
2. **The Problem**: Added `google-generativeai` package (200MB+) which exceeded Vercel's 250MB serverless limit
3. **Result**: Deployment failed silently, app broke with "UnboundLocalError" messages
4. **Fix**: Rolled back to Dec 27 stable version (`fa549cf`)

### What Was Rolled Back
~2300 lines of code from Jan 5th including:
- Pydantic AI content validation/moderation
- Validation encouragement prompts
- Human-in-the-loop interest validation
- Smart Zep-powered returning user greetings
- Query tracking improvements
- Content filtering for affirmations

### What Still Works (Dec 27 version)
- **Zep integration** - Full conversation memory, user graphs, entity search
- **Groq LLM** - Using llama-3.3-70b-versatile (fast, reliable)
- **Pydantic AI agent** - Structured responses with validation
- **Article search** - pgvector + hybrid search
- **Name spacing** - Doesn't say user's name every turn
- **Affirmation handling** - "yes/sure" uses last suggestion
- **Safe topic fallbacks** - When search fails

### Frontend Features (Unaffected)
The frontend (lost.london-app) was NOT rolled back:
- Dashboard with transcripts
- Recent topics/conversations
- User query history
- Interest validation UI
- All UI improvements intact

## Architecture

```
User Voice → Hume EVI → vic-clm.vercel.app/chat/completions → Response
                              ↓
                    ┌─────────┴─────────┐
                    │                   │
              Groq LLM          pgvector search
           (llama-3.3-70b)      (Neon database)
                    │                   │
                    └─────────┬─────────┘
                              ↓
                         Zep Memory
                    (user conversation history)
```

## Key Files
| File | Purpose |
|------|---------|
| `api/index.py` | FastAPI + `/chat/completions` endpoint |
| `api/agent.py` | Pydantic AI agent with Vic persona |
| `api/tools.py` | Article search + Zep memory integration |
| `api/database.py` | Neon pgvector queries |
| `api/agent_config.py` | Agent configuration, system prompts |

## Environment Variables (Vercel)
- `DATABASE_URL` - Neon PostgreSQL
- `VOYAGE_API_KEY` - Embeddings
- `GROQ_API_KEY` - LLM (llama-3.3-70b)
- `ZEP_API_KEY` - Conversation memory
- `CLM_AUTH_TOKEN` - Hume authentication

## Lessons Learned

### 1. Package Size Matters on Vercel
- Vercel serverless has 250MB limit
- `google-generativeai` SDK is huge (~200MB with dependencies)
- Use REST APIs via `httpx` instead of full SDKs when possible

### 2. Test Deployments
- Vercel can fail silently in production
- Always check `vercel ls` for deployment status
- Test the actual production endpoint after deploying

### 3. Keep Rollback Points
- The Dec 27 commit was a clean, stable state
- Tag important stable versions for easy rollback

## Reintroduced Features (Jan 6, 2026)

### Smart Returning User Greetings
Added back the smart greeting system without heavy dependencies:

**How it works:**
1. Tracks `last_interaction_time` and `current_topic` per session
2. If user returns after 5+ minutes gap, offers to continue their topic
3. Looks up user's actual query history from `user_queries` table (ground truth)
4. Falls back gracefully for new users

**Greeting variations:**
- **Returning user with topic**: "Welcome back {name}. Shall we pick up where we left off with {topic}?"
- **Known user with history**: "Hello again {name}. I remember you were interested in {topic}."
- **New user with name**: "Ah, hello {name}. I'm Vic, and I've collected over 370 stories..."
- **Anonymous user**: "Ah, hello there. I'm Vic, the voice of Vic Keegan..."

**Key insight**: Uses actual `user_queries` database table for topics, NOT Zep inference (which sometimes hallucinated topics like "London Bridge" from Thames associations).

**Bug fix (Jan 6)**: SQL query was failing silently - PostgreSQL doesn't allow `ORDER BY` columns not in `SELECT` when using `DISTINCT`. Fixed by using `GROUP BY` with `MAX(created_at)` in a subquery.

### Session Context Tracking
Added to `SessionContext` dataclass:
- `current_topic: str` - What they're currently discussing
- `last_interaction_time: float` - For returning user detection
- `greeted_this_session: bool` - Prevent double greetings
- `user_emotion: str` - From Hume emotion tags (for future use)

### Helper Functions Added
- `check_returning_user(session_id)` - Returns (is_returning, last_topic)
- `update_interaction_time(session_id)` - Call after each response
- `mark_greeted_this_session(session_id)` - Prevent greeting loops
- `set_current_topic(session_id, topic)` - Track discussion topic
- `extract_emotion_from_message(content)` - Parse Hume emotion tags

### Content Validation & Moderation (Jan 6)

Added `api/validation.py` with fast rule-based content moderation (no LLM needed):

**How it works:**
1. Check for banned words (slurs, explicit content) → Immediate block
2. Check suspicious patterns (profanity, sexual, violent) → Block with warning
3. Check off-topic patterns (crypto, politics, personal) → Redirect to London history

**Categories:**
| Category | Example | Response |
|----------|---------|----------|
| `offensive` | Slurs, hate speech | "I can't engage with that kind of language..." |
| `inappropriate` | Profanity, sexual | "That's not quite the sort of topic I cover..." |
| `off_topic` | Bitcoin, politics | "That's outside my area of expertise..." |
| `spam` | Diet pills, forex | Blocked |
| `safe` | London history | Normal response |

**Integration:**
- `validate_user_input()` called at start of `generate_response_with_enrichment()`
- If invalid, returns warning message immediately (no LLM cost)
- Validated content stored to Zep; invalid content is not stored

**Key files:**
- `api/validation.py` - All validation rules and patterns
- `api/agent.py:1184` - Validation check integration

## TODO - Still to Reintroduce

1. [x] ~~Content validation~~ - Done (fast rule-based)
2. [ ] Human-in-the-loop validation (frontend already has UI)

## Commands

```bash
# Local development
source .venv/bin/activate
source .env.local && uvicorn api.index:app --port 8000

# Deploy
vercel --prod

# Check deployments
vercel ls

# Test endpoint
curl -s -X POST https://vic-clm.vercel.app/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer vic-clm-hume-secret-2024' \
  -d '{"messages":[{"role":"user","content":"thorney island"}]}'
```

---
*Last updated: Jan 6, 2026*
