# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Auto-Compact Behavior

**IMPORTANT**: Proactively compact without asking:

1. After ~40-50 tool calls or when conversation feels long, run `/compact` automatically
2. Don't ask permission - just compact and continue working seamlessly
3. In the compact summary, always preserve:
   - Current task state and progress
   - File paths being worked on
   - Pending todos and next steps
   - Key decisions made
   - Any errors encountered and their fixes
4. After compacting, immediately continue the current task

This ensures conversations never hit context limits and work continues uninterrupted.

## Project Overview

NotebookLM Reimagined is an API-first research intelligence platform—Google's NotebookLM, reimagined for developers.

**Architecture**: `Next.js (Frontend) → FastAPI (Backend) → Supabase (Auth + DB + Storage) → Gemini API`

## Development Commands

### Backend (Python FastAPI)

```bash
# Setup
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Development
uvicorn app.main:app --reload --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend (Next.js)

```bash
# Setup
cd frontend
npm install

# Development
npm run dev                 # Start dev server (http://localhost:3000)

# Code quality
npm run lint                # Check linting issues
npm run lint:fix            # Auto-fix linting issues
npm run format              # Format with Prettier
npm run format:check        # Check formatting
npm run type-check          # TypeScript type checking

# Production
npm run build               # Production build
npm run start               # Start production server
npm run analyze             # Bundle size analysis
```

Pre-commit hooks automatically run ESLint and Prettier on staged files.

### Database (Supabase MCP)

Use Supabase MCP commands for database operations:

```bash
mcp__supabase__list_projects              # Find project ID
mcp__supabase__list_tables                # View current schema
mcp__supabase__apply_migration            # Create/modify tables (DDL)
mcp__supabase__execute_sql                # Run queries (DML)
mcp__supabase__generate_typescript_types  # Generate frontend types
```

SQL files in `supabase/` directory:
- `schema.sql` - All 14 database tables
- `rls_policies.sql` - Row Level Security policies
- `storage.sql` - Storage buckets configuration

## Critical: Keeping Code in Sync

**IMPORTANT**: When modifying router or service code:

1. **Test ALL affected endpoints** - Run programmatic tests after changes
2. **Check null-safety patterns** - Database fields like `source_guide`, `metadata` can be `None`
   ```python
   # WRONG - fails if source_guide is None
   source.get("source_guide", {}).get("summary")

   # CORRECT - handles None values
   source_guide = source.get("source_guide") or {}
   source_guide.get("summary")
   ```
3. **Update documentation** - Keep `/docs` page in sync with API changes
4. **Register new routers** - Add to `main.py` imports AND `include_router()` calls

Common files that share patterns (update ALL when fixing bugs):
- `chat.py`, `study.py`, `audio.py`, `video.py`, `studio.py`, `global_chat.py` - all have source content extraction

## Architecture Details

### Backend Structure
```
backend/app/
├── main.py              # FastAPI app, CORS, middleware, routers
├── config.py            # Environment variables via pydantic-settings
├── routers/             # API endpoints (14 routers)
│   ├── notebooks.py     # Notebook CRUD
│   ├── sources.py       # Document upload & management
│   ├── chat.py          # Chat with sources (RAG)
│   ├── global_chat.py   # Search across all notebooks
│   ├── audio.py         # Audio overview generation
│   ├── video.py         # Video overview generation
│   ├── study.py         # Flashcards, quizzes, guides
│   ├── studio.py        # Reports, slides, infographics
│   ├── research.py      # Deep research jobs
│   ├── notes.py         # User notes
│   ├── export.py        # ZIP/JSON/PDF export
│   ├── api_keys.py      # API key management
│   └── profile.py       # User profile
├── services/            # Business logic
│   ├── gemini.py        # Gemini API client & File Search
│   ├── auth.py          # Supabase auth middleware
│   ├── supabase_client.py  # Supabase connection
│   ├── persona_utils.py # AI persona prompts
│   └── atlascloud_video.py # Video generation
└── models/
    └── schemas.py       # Pydantic request/response models
```

### Frontend Structure
```
frontend/src/
├── app/                 # Next.js App Router pages
│   ├── page.tsx         # Dashboard
│   ├── auth/            # Login/register
│   └── notebooks/[id]/  # Three-panel notebook view
├── components/          # React components
│   ├── sources/         # Source upload/display
│   ├── chat/            # Chat interface
│   ├── studio/          # Content generation
│   └── ui/              # shadcn/ui components
└── lib/                 # Utilities
    ├── supabase.ts      # Supabase client
    ├── api.ts           # API client
    └── types.ts         # TypeScript types
```

## Key Integration Patterns

### Gemini File Search (RAG)
Each notebook maps to a Gemini File Search Store (no custom vector DB needed):
```python
# Create store on notebook creation
store = genai.FileSearchStore.create(name=f"notebook_{notebook_id}")

# Update notebook with store_id
supabase.table("notebooks").update({
    "file_search_store_id": store.id
}).eq("id", notebook_id).execute()

# Query with File Search tool
response = model.generate_content(
    contents=user_message,
    tools=[genai.Tool.from_file_search(store_id=store.id)]
)
```

### Response Format
All API responses include cost transparency:
```json
{
  "data": { ... },
  "usage": {
    "input_tokens": 1500,
    "output_tokens": 500,
    "cost_usd": 0.0023,
    "model_used": "gemini-2.5-flash"
  }
}
```

### Authentication Flow
- **Frontend**: Supabase Auth (JWT) for user sessions
- **API**: Custom API keys (prefix `nb_live_`) for programmatic access
- **Middleware**: `get_current_user()` extracts user from JWT or API key
- **RLS**: Supabase Row Level Security enforces data isolation

### Realtime Updates
Long-running jobs update database tables; frontend subscribes via Supabase Realtime:
```typescript
// Frontend subscription
const channel = supabase
  .channel('audio_overviews')
  .on('postgres_changes',
    { event: 'UPDATE', schema: 'public', table: 'audio_overviews' },
    (payload) => console.log(payload)
  )
  .subscribe()
```

## Database Schema (14 tables)

- **profiles** - User profiles (auto-created on signup trigger)
- **notebooks** - Contains `file_search_store_id` linking to Gemini File Search Store
- **sources** - Documents stored in Supabase Storage, indexed in Gemini File Search
- **chat_sessions** / **chat_messages** - Conversation threads with citations
- **audio_overviews** / **video_overviews** - Generation jobs (realtime updates)
- **research_tasks** - Deep Research jobs
- **notes** - User notes and saved responses
- **study_materials** - Flashcards, quizzes, study guides
- **studio_outputs** - Reports, slides, infographics
- **api_keys** / **api_key_usage_logs** - API key management and tracking
- **usage_logs** - General cost/usage tracking

All tables have Row Level Security (RLS) enabled. Files stored in 4 buckets: `sources`, `audio`, `video`, `studio`.

## Gemini Models Reference

| Feature | Model | Notes |
|---------|-------|-------|
| Chat (fast) | `gemini-2.5-flash` | Default for most chat |
| Chat (quality) | `gemini-3-pro` | Higher quality responses |
| Audio scripts | `gemini-2.5-pro` | Script generation for TTS |
| TTS | `gemini-2.5-pro-tts-preview` | Text-to-speech |
| Video | `veo-3.1-fast-preview` | Via AtlasCloud API |
| Deep Research | `deep-research-pro-preview` | Multi-step research |

## Environment Variables

```bash
# Backend (.env)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...
GOOGLE_API_KEY=AIza...

# Frontend (.env.local)
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
NEXT_PUBLIC_API_URL=https://your-api.vercel.app
```

## Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind v4, shadcn/ui |
| Backend | FastAPI, Python 3.11+, Pydantic |
| Database | Supabase PostgreSQL + Row Level Security |
| Auth | Supabase Auth (JWT) + Custom API Keys |
| Storage | Supabase Storage |
| AI/RAG | Gemini API (File Search, TTS, Veo, Deep Research) |
| Deployment | Vercel (Serverless) |
| DX | Prettier, ESLint, Husky, lint-staged |

## Core Specification Documents

- `01_VISION_DOCUMENT.md` - High-level vision and philosophy
- `02_PROJECT_SPECIFICATION.md` - Complete technical spec (schema, 50+ endpoints, features)
- `03_IMPLEMENTATION_GUIDE.md` - Step-by-step implementation guide
- `README.md` - User-facing documentation and API reference
