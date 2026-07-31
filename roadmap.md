# Super Agent — Project Roadmap

## Vision
Autonomous multi-agent system that makes money online across 12+ income verticals. Self-modifying — SuperAgent creates, edits, and stops agents autonomously.

## Current State (v1 — Broken)
- All LLM providers exhausted (NVIDIA 429, Gemini 429, OpenRouter 429/402, HF 402)
- Single agent mode (AffiliateMarketer) — 12 agent types registered but only 1 active
- Dashboard works, agent state machine works, but no LLM calls succeed
- Browser automation exists but untested with real sign-ups

## Provider Stack (New)
| Priority | Provider | Models | Cost | Status |
|----------|----------|--------|------|--------|
| 1st | OpenRouter | Nemotron 3 Ultra, Gemma 4 31B, Laguna, Ling, etc. | FREE | Active, 20 RPM cap |
| 2nd | Google Gemini | Gemini 2.5 Flash, Gemini 2.5 Pro | FREE (censored) | Fallback only |
| 3rd | MiMo v2.5 | mimo/mimo-v2.5 | PAID | Last resort only |

## Phases

### Phase 1: Get One Agent Working (Current)
- [x] Provider router rewritten for free models
- [ ] Deploy and verify LLM calls succeed
- [ ] AffiliateMarketer completes one full cycle
- [ ] Dashboard shows chat history and task progress

### Phase 2: Browser Automation
- [ ] Playwright sign-up flows for affiliate platforms
- [ ] Account creation with email/OTP handling
- [ ] Platform-specific workflows (Fiverr, Upwork, ClickBank, etc.)

### Phase 3: Multi-Agent Expansion
- [ ] ContentCreator agent
- [ ] FreelanceOptimizer agent
- [ ] CryptoTrader agent
- [ ] SocialMediaMonetizer agent

### Phase 4: Real Revenue
- [ ] Affiliate link generation and tracking
- [ ] Content publishing to platforms
- [ ] Payment verification via blockchain
- [ ] Revenue dashboard with real metrics

### Phase 5: Self-Modification
- [ ] SuperAgent creates/edits sub-agents
- [ ] Platform-specific agent spawning
- [ ] Instruction evolution from outcomes
- [ ] Resource auto-provisioning

## Key Decisions
1. **Free models first** — prove concept before spending money
2. **OpenRouter primary** — new paid key with higher limit, but only free models used
3. **20 RPM cap** — respect rate limits, no wasted calls
4. **Google as fallback only** — heavily censored, avoid when possible
5. **MiMo v2.5 paid** — only when free models fail and task is critical

## Deployment
- **Platform**: Railway (SFO region)
- **URL**: https://dashboard-production-edec.up.railway.app
- **Stack**: Python + Flask + Playwright + SQLite
- **Config**: Docker, gunicorn gthread workers
