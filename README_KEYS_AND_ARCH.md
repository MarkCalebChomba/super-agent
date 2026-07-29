# Super Agent — Keys, Architecture & Current State

## API Keys & Credentials

### HuggingFace Inference
- **Token**: `hf_***redacted***` (set as HF_TOKEN env var in Railway)
- **Endpoint**: `https://router.huggingface.co/v1/chat/completions`
- **Status**: 402 — monthly free credits depleted
- **Fix**: Add pre-paid credits at https://huggingface.co/settings/billing or subscribe to PRO
- **Notes**: Router endpoint works when credits available. Serverless endpoint (`api-inference.huggingface.co`) has DNS issues from Railway.

### HuggingFace S3 Storage
- **Access Key ID**: `HFAK***redacted***` (set as env var)
- **Secret Access Key**: `d4f1***redacted***` (set as env var)
- **Endpoint**: `https://s3.hf.co/Calebchomba`
- **Namespace**: `Calebchomba`
- **Status**: Not yet integrated — can be used for artifact storage
- **Region**: `us-east-1`
- **Profile name**: `hf`

### NVIDIA API
- **Key 1**: `nvapi-***redacted***` (set as NVIDIA_API_KEY) — regenerated 2026-07-29
- **Key 2**: `nvapi-***redacted***` (set as NVIDIA_API_KEY_2) — regenerated 2026-07-29
- **Endpoint**: `https://integrate.api.nvidia.com/v1`
- **Models** (in order tried):
  1. `deepseek-ai/deepseek-v4-flash` (300s timeout) — fast but returns 503 when overloaded
  2. `nvidia/nemotron-3-super-120b-a12b` (120s timeout) — new, less contention
  3. `nvidia/nemotron-3-ultra-550b-a55b` (120s timeout) — new, powerful
  4. `deepseek-ai/deepseek-v4-pro` (300s timeout) — slower fallback
- **Status**: PRIMARY WORKING PROVIDER — retries on 503 with exponential backoff
- **Circuit breaker**: threshold=100, cooldown=300s
- **Retries**: 5 tries, base backoff 0.5s, only on 429/5xx
- **Serialized**: single `_nvidia_serialize_lock`

### Gemini API
- **Key 1**: `AQ.Ab8***redacted***` (set as GEMINI_API_KEY) — projects/525669420787
- **Key 2**: `AQ.Ab8***redacted***` (set as GEMINI_API_KEY_2) — projects/442125752616
- **Endpoint**: `https://generativelanguage.googleapis.com/v1beta`
- **Models** (in order tried):
  - `gemini-2.5-flash` (10 RPM, up to 1,500 RPD)
  - `gemini-2.5-flash-lite` (15 RPM, up to 1,000 RPD)
  - `gemini-2.5-pro` (5 RPM, up to 100 RPD)
- **Status**: Free tier added as provider #3 (between OpenRouter and NVIDIA)
- **Circuit breaker**: threshold=10, cooldown=60s

### OpenRouter
- **Key 1**: Set in Railway env (`OPENROUTER_API_KEY`)
- **Key 2**: Set in Railway env (`OPENROUTER_API_KEY_2`)
- **Endpoint**: `https://openrouter.ai/api/v1`
- **Free models**: All return 429 (rate limited from Railway IP)
- **Paid models**: All return 402 (no credits)
- **Status**: Not usable without adding credits at https://openrouter.ai/credits

## Railway Deployment
- **URL**: `https://dashboard-production-edec.up.railway.app`
- **Region**: SFO
- **AGENT_COUNT**: 1 (default, down from 12)
- **Single agent**: AffiliateMarketer (North Star: Make money through affiliate marketing commissions)

## Architecture

### Files
```
agent_orchestrator.py   — State machine: PLANNING→EXECUTING→EVALUATING→PASSED→SHIPPING→DONE
evolving_agent.py       — Agent lifecycle (run_loop, run_cycle)
providers/router.py     — LLM router with circuit breakers, exponential backoff
agent_memory.py         — Task queue, experiences, persistence
event_log.py            — Structured JSON-lines event logger
resource_bank.py        — Budget/resource tracking
finance_layer.py        — Finance tracking
dashboard_app.py        — Flask web dashboard + API
tools/stealth_browser.py — Playwright-based browser automation (navigate, login, scrape)
```

### State Machine Flow
1. **PLANNING**: `_plan_tasks()` → LLM generates 3-5 tasks via tool-calling schema
2. **EXECUTING**: `_execute_task()` → LLM generates output + optional browser actions
3. **EVALUATING**: `_evaluate_output()` → Critic scores output (0-10), verdict: passed/needs_revision/failed
4. **REVISION LOOP**: Up to `max_revisions` (3) revisions if needs_revision
5. **SHIPPING**: `_ship_output()` → Writes artifact to `artifacts/<agent>/<task_id>/<timestamp>.md`
6. **DONE/FAILED/DEAD_LETTER**: Terminal states

### LLM Provider Path — Tier-Driven
```
complete() / complete_structured():
  Order depends on tier:

  cheap (Gemini-first):
    1. Gemini 2.5 Flash → free, fast, 10 RPM
    2. Gemini 2.5 Flash-Lite → free, 15 RPM
    3. Gemini 2.5 Pro → free, 5 RPM
    4. OpenRouter → 429/402
    5. HF Inference → 402 (no credits)
    6. NVIDIA → last resort

  powerful (NVIDIA-first):
    1. NVIDIA DeepSeek V4 Flash → 503 overloaded (retries 5x)
    2. NVIDIA Nemotron-3 Super 120B → new, less contention
    3. NVIDIA Nemotron-3 Ultra 550B → new, powerful
    4. NVIDIA DeepSeek V4 Pro → cold start 120s
    5. OpenRouter → 429/402
    6. HF Inference → 402 (no credits)
    7. Gemini → last resort
```

### Tier Assignments
| Call Site | Tier | Why |
|-----------|------|-----|
| `_plan_tasks()` | powerful | Task planning = decision-making |
| `_execute_task()` | powerful | Content creation = decision-making |
| `_evaluate_output()` | powerful | Scoring/critique = decision-making |
| `_build_revision_prompt()` | powerful | Revision instructions = decision-making |
| `AgentBrowser` (browser-use) | cheap | Data extraction, form-filling, summaries |

### Current Working State
- DeepSeek V4 Flash works on NVIDIA but gets 503 (ResourceExhausted) from other instances
- Backoff: 5 retries, base 0.5s (0.5, 1, 2, 4, 8s)
- Circuit breakers: HF opens after 5 failures (60s cooldown), OR opens after 3 (120s), NV opens after 100
- Tool-calling schemas for planning/evaluation: PLAN_SCHEMA, CRITIC_SCHEMA, REVISION_SCHEMA
- Plain-text JSON fallback when tool-calling fails
- Task status normalized to lowercase (fix for PENDING/pending mismatch)
- Browser automation: basic navigate/scrape/login_google/login_platform via StealthBrowser

### Browser Automation (Current)
- `_execute_browser_actions()` in agent_orchestrator.py
- LLM outputs `BROWSER: navigate | url`, `BROWSER: scrape | url`, `BROWSER: login_google | email | pass`
- Uses Playwright via `tools/stealth_browser.py`
- Single global browser instance (shared across agents to save RAM)
- Anti-detection via random viewports, user agents, stealth plugin

## Known Issues
1. DeepSeek V4 Flash gets 503 on NVIDIA when many instances hit it
2. HF credits depleted — need $5-10 pre-paid credits for reliable access
3. Browser automation is basic (navigate/scrape only) — no real form-filling for sign-ups
4. No credentials provided for platform sign-ups (need Gmail, Fiverr, etc. accounts)
5. OpenRouter needs credits for paid models
6. Tasks pass/fail based on text quality — no real-world validation of sign-ups

## Next Steps
1. Integrate browser-use/web-ui for robust browser automation
2. Add HF credits for reliable DeepSeek V4 Flash access
3. Wire browser automation into task execution for real sign-ups
4. Add email/OTP handling for account creation workflows
