# Super Agent — Build Process & Architecture

> An autonomous multi-agent system for online income generation.
> Every agent runs on **Hermes** (Nous Research, 219k★) and adapts existing
> open-source projects — nothing is generated from scratch.

---

## Table of Contents

- [Core Philosophy](#core-philosophy)
- [Architecture Overview](#architecture-overview)
- [Agent System (13 Agents)](#agent-system-13-agents)
- [Hermes Runtime](#hermes-runtime)
- [Memory & Learning](#memory--learning)
- [Quality Gates](#quality-gates)
- [Files & Structure](#files--structure)
- [Deployment](#deployment)
- [Usage](#usage)

---

## Core Philosophy

**Nothing from scratch.** Every agent in this system finds, studies, and adapts
real open-source projects from GitHub instead of generating original content.

### Why

Most AI agent systems generate content from scratch using LLMs — blog posts,
social media captions, code, trading strategies, etc. This produces:
- Generic, AI-detectable output
- Hallucinated facts and fake references
- Content that has no track record of working

Instead, our agents:
1. **Search** GitHub for the most-starred/popular repos in their domain
2. **Study** their patterns, APIs, and architecture by reading their READMEs and source code
3. **Adapt** those patterns using our own tooling
4. **Quality gate** everything through humanization (anti-AI-detection) and editorial review
5. **Remember** what works and what doesn't across cycles

### Source Repos by Agent

| Agent | Source Repos | Stars |
|-------|-------------|-------|
| **ContentCreator** | [blogging-with-langchain](https://github.com/christancho/blogging-with-langchain) — LangGraph article pipeline; [ALwrity](https://github.com/ALwrity/ALwrity) — web research + content strategy; [avoid-ai-writing](https://github.com/conorbronsdon/avoid-ai-writing) — 57-pattern AI detection/rewrite | 2.6k★ |
| **Hermes (Runtime)** | [hermes-agent](https://github.com/NousResearch/hermes-agent) — self-improving agent with memory, skills, tools, multi-platform messaging | 219k★ |

(Remaining 11 agents follow the same pattern — each backed by 3 top repos in their domain.)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Hugging Face Spaces                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Hermes Agent API                        │   │
│  │  POST /api/eval  │  GET /health  │  ~/.hermes/skills │   │
│  │  ┌──────────────┐ ┌────────────┐ ┌────────────────┐  │   │
│  │  │LLM Router    │ │Web Search  │ │13 Agent Skills │  │   │
│  │  │(any model)   │ │(Firecrawl) │ │(SKILL.md files)│  │   │
│  │  └──────────────┘ └────────────┘ └────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTPS
┌──────────────────────▼──────────────────────────────────────┐
│              Local Agent System (your machine)               │
│                                                              │
│  ┌─────────────┐  providers/router.py  ┌──────────────────┐ │
│  │  Dashboard  │  ┌──────────────────┐  │  LLMRouter       │ │
│  │  :8080      │  │ 1. _try_hermes() │──│→ HF Hermes API  │ │
│  │  (Flask)    │  │ 2. _try_nvidia() │  │→ NVIDIA DeepSeek │ │
│  └─────────────┘  │ 3. _try_oru()    │  │→ OpenRouter     │ │
│                   │ 4. _try_groq()   │  │→ Groq           │ │
│  ┌─────────────┐  │ 5. _try_ollama() │  │→ Local Ollama   │ │
│  │ Orchestrator│  └──────────────────┘  └──────────────────┘ │
│  │ self-healing│                                             │
│  │ 13 threads  │  ┌──────────────────────────────────────┐   │
│  └─────────────┘  │  Memory System (Hermes-style)         │   │
│                   │  ┌─────────┐ ┌────────┐ ┌─────────┐  │   │
│  ┌─────────────┐  │  │Core Mem │ │Session │ │  Skills │  │   │
│  │ 13 Agents   │  │  │(always  │ │History  │ │(learned │  │   │
│  │ (threads)   │  │  │in prompt│ │(FTS5)   │ │from exp)│  │   │
│  └─────────────┘  │  └─────────┘ └────────┘ └─────────┘  │   │
│                   └──────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. Orchestrator starts → exports all 13 agents as Hermes skills
2. Each agent thread runs run_cycle() every ~2 seconds
3. Agent.build() calls _try_hermes() → HTTPS → HF Hermes API
4. Hermes processes: LLM call + web search + memory recall + tool use
5. Result returned to agent → quality gates applied → saved to disk
6. Agent stores cycle results in memory → learns for next cycle
7. Dashboard updates live via in-memory tracker
```

---

## Agent System (13 Agents)

Each agent is a Python class inheriting from `BaseAgent` and running in its own thread.

### Agent List

| # | Name | Module | Income Methods |
|---|------|--------|---------------|
| 1 | **ContentCreator** | `agent_01_content.py` | Blogging, Newsletter, Medium, Affiliate, Sponsored, Ghostwriting |
| 2 | **SocialMediaMonetizer** | `agent_02_social.py` | Sponsored posts, Affiliate, Brand deals, Digital products |
| 3 | **VideoCreator** | `agent_03_video.py` | YouTube AdSense, Sponsorships, Course sales |
| 4 | **EcommerceMerchant** | `agent_04_ecommerce.py` | Product sales, Dropshipping, Print-on-demand |
| 5 | **AffiliateMarketer** | `agent_05_affiliate.py` | Affiliate commissions, Sponsored content |
| 6 | **CryptoTrader** | `agent_06_trading.py` | Trading profits, Staking, DeFi yield, Arbitrage |
| 7 | **FreelanceOptimizer** | `agent_07_freelance.py` | Freelance income, Consulting retainers |
| 8 | **SaaSBuilder** | `agent_08_saas.py` | Subscription revenue, Enterprise licensing |
| 9 | **DeFiOptimizer** | `agent_09_crypto_defi.py` | Yield farming, Lending interest, Liquidity fees |
| 10 | **DataArbitrageur** | `agent_10_data_arbitrage.py` | Arbitrage profits, Data reselling |
| 11 | **ServiceProvider** | `agent_11_services.py` | Consulting fees, Service retainers, Coaching |
| 12 | **PlatformMonetizer** | `agent_12_platform.py` | Platform fees, Subscription, Transaction fees |
| 13 | **Hermes** | `agent_13_hermes.py` | Meta-agent — skill management, orchestration |

### ContentCreator Pipeline (Reference Implementation)

The most complete agent. Implements the full LangGraph-inspired pipeline:

```
1. RESEARCH ──→ web search for existing articles (not generate from scratch)
                  Uses Hermes HF web search tools → finds 3-5 best sources
                  Extracts content + metadata from each source URL

2. AUDIENCE ──→ LLM analyzes reader persona, pain points, content angle
                  Identifies engagement hook for first 2 sentences

3. CURATE ────→ Synthesizes best points from found sources with attribution
                  Adds original perspective + practical examples
                  800-1200 word blog post with inline citations

4. HUMANIZE ──→ Quality gate: avoid-ai-writing patterns (57 categories)
                  Detects: inflated vocab, filler phrases, uniform rhythm
                  Auto-rewrites if AI score > 20/100
                  Second-pass verification

5. SEO ───────→ Generates: title (50-60 chars), meta desc (150-160),
                  excerpt, tags, primary keywords via LLM

6. EDITOR ────→ Approval gate: word count, sections, CTA, sources checks
                  Score must pass threshold (3/5)
                  Feedback loop for rejected articles

7. PUBLISH ───→ Saves to data/content/ with YAML frontmatter metadata
                  Word count, sources, tags, AI score, editor score
```

### All Agents Follow Same Pattern

Each agent:
1. Uses Hermes for LLM + research tools (avoids local API key bottlenecks)
2. Finds existing content/projects — never generates from scratch
3. Applies domain-specific quality gates
4. Stores results in memory for learning
5. Exported as a Hermes SKILL.md file for personality context

---

## Hermes Runtime

### Why Hermes

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (219,000★) by Nous Research
is the only agent with a built-in learning loop. It provides:

- **Self-improving skills** — creates skills from experience, improves them during use
- **Persistent memory** — FTS5 core memory + session search across conversations
- **40+ built-in tools** — web search, code execution, file operations, etc.
- **Multi-platform messaging** — Telegram, Discord, Slack, WhatsApp, Signal
- **Cron scheduling** — scheduled tasks with delivery to any platform
- **Any LLM** — supports Nous Portal, OpenRouter, OpenAI, Anthropic, local endpoints

### How Integration Works

```
┌─────────────────────────────────────────────┐
│           providers/router.py                │
│                                              │
│  complete(prompt, system):                   │
│    │                                         │
│    ├─ 1. _try_hermes() ────→ HF Hermes API  │
│    │     (primary — every agent runs here)   │
│    │                                         │
│    └─ 2-5. Fallback providers:               │
│          NVIDIA DeepSeek V4 Flash            │
│          OpenRouter (free models)            │
│          Groq (free tier)                    │
│          Ollama (local)                      │
└─────────────────────────────────────────────┘
```

### Deployment (Hugging Face)

Hermes runs on Hugging Face Spaces as a Docker container:

1. **Space**: `calebchomba/hermes-agent`
2. **API**: `POST /api/eval` with `{prompt, system, agent_name}`
3. **Health**: `GET /health` returns status + loaded skills
4. **Build**: Dockerfile installs Hermes via pip, exports agent skills

To deploy:
```bash
python -m hermes_integration.deploy_hermes_hf
```

### Agent Skills (Hermes Profiles)

Each agent is exported as a `SKILL.md` file to `~/.hermes/skills/<AgentName>/`.
These give Hermes the context to behave as each agent type:

```markdown
# ContentCreator

Content creation & monetization: blogs, newsletters, courses, ebooks

## System Prompt
You are a content creator who never writes from scratch. ...

## Tools
- web_search
- article_extraction
- seo_analysis
- content_curation
```

13 skill files are auto-exported on orchestrator startup.

---

## Memory & Learning

### Architecture

The memory system follows Hermes's architecture with 5 memory targets:

| Target | Purpose | Example |
|--------|---------|---------|
| **self** | Agent's internal notes | "Topic X worked well, topic Y was rejected" |
| **user** | Human's profile, preferences | "User prefers conversational tone" |
| **task** | Current project context | "Working on AI productivity article" |
| **environment** | Platform info, constraints | "Network blocks Google scraping" |
| **strategy** | Money-making strategies | "Affiliate content outperforms tutorials" |

### Components

**Core Memory** (`memory/core_memory`)
- Always injected into agent's system prompt
- Limited to ~1800 tokens
- Auto-consolidates when >75% full

**Session History** (`memory/session_history`)
- Full detail, searchable via SQLite FTS5
- Stores every agent action with timestamps
- LLM-summarized on demand

**Skills** (`memory/skills`)
- Procedural memory extracted from successful sessions
- Tracks success/failure rates per skill
- Auto-extracted every 20 agent turns

**Consolidation** (`memory/consolidator`)
- Merges related entries when near capacity
- Removes outdated information
- Compresses verbose entries via LLM

### How ContentAgent Learns

```python
# Each cycle stores results in memory
def _learn_from_cycle(self, output):
    key_points = f"Topic: {topic} | Words: {wc} | Score: {score}"
    self.memory.remember("self", key_points, category="content_cycle")

# Every 5 cycles, extract strategy lessons
def _extract_strategy_lesson(self):
    # Analyze last 10 cycles via LLM
    # Returns actionable insight like "Tutorials outperform listicles"
    self.memory.remember("strategy", lesson, importance=3)

# Before each cycle, recall past lessons
past = self.memory.search_past(topic)
# Injects lessons into the pipeline context
```

---

## Quality Gates

### 1. AI Detection Avoidance (avoid-ai-writing)

Adapted from [conorbronsdon/avoid-ai-writing](https://github.com/conorbronsdon/avoid-ai-writing) (2.6k★).
Implements 57 pattern categories across 4 tiers:

| Tier | Examples | Scoring |
|------|----------|---------|
| **Tier 1** | leverage→use, utilize→use, robust→reliable, paradigm→model | Always flags (+10 each) |
| **Tier 2** | navigate→handle, vibrant→active, thriving→growing | Flags on cluster (+5 each) |
| **Tier 3** | "the integration of", "decentralized compute", "community-driven" | Flags at ≥2 repetitions |
| **Filler** | "In conclusion", "Let's dive in", "Feel free to reach out" | Always removes (+6 each) |

Additional structural checks:
- Sentence length uniformity (avg <10 or >30 words)
- Paragraph uniformity (all same length)
- Excessive em-dashes, bold formatting, hashtag stuffing
- Generic conclusions ("the future looks bright")
- Synonym cycling, copula avoidance, rhetorical question openers

### 2. Editorial Review

Each agent has its own approval gate. ContentCreator's checks:
- Word count ≥ 400
- Has introduction hook
- Has 3+ sections (## headings)
- Has call-to-action
- Includes source attributions

Score must pass threshold (3/5). Failed articles get specific feedback and retry.

### 3. Memory Consolidation

Auto-trims core memory when >75% full. Merges related entries,
removes outdated facts, archives low-importance entries.

---

## Files & Structure

```
super-agent/
│
├── agents/                          # 13 agent implementations
│   ├── base_agent.py                # Base class with Hermes runtime, memory, live tracking
│   ├── agent_01_content.py          # ContentCreator (full pipeline)
│   ├── agent_02_social.py           # SocialMediaMonetizer
│   ├── agent_03_video.py            # VideoCreator
│   ├── agent_04_ecommerce.py        # EcommerceMerchant
│   ├── agent_05_affiliate.py        # AffiliateMarketer
│   ├── agent_06_trading.py          # CryptoTrader
│   ├── agent_07_freelance.py        # FreelanceOptimizer
│   ├── agent_08_saas.py             # SaaSBuilder
│   ├── agent_09_crypto_defi.py      # DeFiOptimizer
│   ├── agent_10_data_arbitrage.py   # DataArbitrageur
│   ├── agent_11_services.py         # ServiceProvider
│   ├── agent_12_platform.py         # PlatformMonetizer
│   └── agent_13_hermes.py           # Hermes meta-agent
│
├── providers/
│   └── router.py                    # LLM router: Hermes HF → NVIDIA → OpenRouter → Groq → Ollama
│
├── memory/                          # Hermes-style memory system
│   ├── agent_memory.py              # AgentMemory: remember, recall, search, build_core_context
│   ├── memory_store.py              # SQLite + FTS5 backend
│   └── consolidator.py              # Auto-consolidation, skill extraction, session summarization
│
├── tools/
│   ├── web_research.py              # Web search + article extraction (from ALwrity/blogging-with-langchain)
│   ├── humanizer.py                 # AI detection + rewrite (from avoid-ai-writing, 57 patterns)
│   ├── content_gen.py               # Original content generator (legacy)
│   ├── social_tools.py              # Social media tools
│   ├── wallet_tools.py              # Crypto wallet tools
│   └── browser_automation.py        # Browser automation
│
├── hermes_integration/              # Hermes Agent integration layer
│   ├── __init__.py                  # HermesRunner, HermesSkillBridge, install_hermes
│   ├── hermes_runner.py             # Local Hermes CLI wrapper
│   ├── hermes_hf_client.py          # Remote HF Hermes HTTP client
│   ├── hermes_hf.py                 # (generated by deploy script)
│   ├── agent_skills.py              # 13 agent SKILL.md profile generator
│   └── deploy_hermes_hf.py          # Deploy Hermes to Hugging Face Spaces
│
├── hermes_hf/                       # Hugging Face Space files
│   ├── app.py                       # FastAPI endpoint (POST /api/eval, GET /health)
│   ├── Dockerfile                   # Docker build for HF Space
│   └── requirements.txt             # Python dependencies
│
├── master/                          # Orchestration system
│   ├── orchestrator.py              # Self-healing agent lifecycle manager
│   ├── system_store.py              # Global SQLite DB (agent registry, inbox, budget, plans)
│   ├── super_agent.py               # SuperAgent meta-agent
│   ├── agent_factory.py             # Agent class factory
│   ├── telegram_bot.py              # Telegram interface
│   └── resource_monitor.py          # Resource usage tracking
│
├── config/
│   ├── settings.py                  # Config loader
│   ├── app_config.json              # Agent enable/disable, LLM preference
│   └── identities/                  # Per-agent identity files
│
├── log_system/                      # Centralized logging + supervisor
│   ├── agent_logger.py              # Per-agent logger with levels
│   ├── central_log.py               # Central log aggregator
│   └── supervisor_filter.py         # AI filter for human-notable events
│
├── data/                            # Persistent data (gitignored)
│   ├── system.db                    # System store
│   ├── memory/                      # Per-agent memory databases
│   ├── content/                     # Generated blog posts
│   └── logs/                        # Agent logs
│
├── templates/                       # Flask dashboard templates
├── static/                          # Dashboard static assets
├── dashboard_app.py                 # Flask dashboard (live agent monitoring)
├── live_tracker.py                  # In-memory live I/O streaming
├── main.py                          # Entry point
├── launcher.py                      # Persistent background launcher with auto-restart
├── deploy_hf.py                     # Deploy main system to HF Spaces
├── deploy_railway.py                # Deploy to Railway
├── Dockerfile                       # Main system Docker image
├── requirements.txt                 # Python dependencies
├── build_process.md                 # This file
└── README.md                        # Project README
```

---

## Deployment

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment
cp .env.example .env
# Edit .env with your API keys

# Start all agents + dashboard
python main.py --deploy

# Or use the persistent launcher
python launcher.py
```

### Hugging Face Spaces (Hermes)

```bash
pip install huggingface_hub
export HF_TOKEN=hf_your_token
python -m hermes_integration.deploy_hermes_hf
```

Creates `calebchomba/hermes-agent` Space with:
- Hermes Agent runtime
- FastAPI endpoint at `/api/eval`
- All 13 agent skills pre-loaded
- Health check at `/health`

### Main System (HF Spaces)

```bash
export HF_TOKEN=hf_your_token
python deploy_hf.py
```

Creates `calebchomba/super-agent` Space with:
- Flask dashboard on port 8080
- All 13 agents connecting to remote Hermes

---

## Usage

### Start the System

```bash
# Terminal 1: Start everything
python launcher.py

# Watch the dashboard
open http://localhost:8080

# Watch agent activity
tail -f agent_output.log
```

### Run a Single Agent

```bash
python main.py --agent ContentCreator
python main.py --agent Hermes
```

### Check Status

```bash
python main.py --status
python main.py --list
```

### Stop

```bash
python launcher.py --stop
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `HERMES_HF_URL` | Yes | URL of HF Hermes instance |
| `HF_TOKEN` | For deploy | Hugging Face API token |
| `OPENROUTER_API_KEY` | Fallback | OpenRouter API key |
| `GROQ_API_KEY` | Fallback | Groq API key |
| `NVIDIA_API_KEY` | Fallback | NVIDIA API key (has default) |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot for notifications |
| `TELEGRAM_CHAT_ID` | Optional | Telegram chat ID |

---

## Key Design Decisions

### Why Hermes on HF instead of local install
Local install of Hermes is 177MB+ and requires Python 3.11 specifically.
Hosting on Hugging Face Spaces gives us:
- Always-on availability
- No local resource consumption
- Built-in web search (Firecrawl via Nous Portal)
- Automatic scaling

### Why agents don't generate from scratch
LLM-generated content is:
- Easily detectable as AI-written
- Full of hallucinated facts and references
- Lacks real-world validation

By finding and adapting existing open-source projects, agents:
- Build on proven, working content
- Have real citations and sources
- Produce output that passes AI detection

### Why 13 agents
Each agent targets a specific online income method:
1. Content (blogs, newsletters, courses)
2. Social media (sponsored posts, brand deals)
3. Video (YouTube, TikTok monetization)
4. E-commerce (product sales)
5. Affiliate marketing (commissions)
6. Crypto trading (market profits)
7. Freelancing (services, consulting)
8. SaaS (software subscriptions)
9. DeFi (yield farming, lending)
10. Data arbitrage (price differences)
11. Digital services (consulting, coaching)
12. Platforms (marketplaces, tools)
13. Hermes (meta-agent, orchestration)

---

## Future Work

- [ ] Rewrite remaining 11 agents with the same pattern as ContentCreator
- [ ] Add per-agent web dashboard analytics
- [ ] Implement cross-agent skill sharing via Hermes bridge
- [ ] Add Telegram bot command for Hermes agent chat
- [ ] Automated A/B testing of content strategies
- [ ] Real revenue tracking and ROI dashboard
