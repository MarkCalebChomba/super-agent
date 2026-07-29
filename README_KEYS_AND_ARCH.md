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
- **Key 1**: `nvapi-***redacted***` (set as NVIDIA_API_KEY)
- **Key 2**: `nvapi-***redacted***` (set as NVIDIA_API_KEY_2, may be truncated)
- **Endpoint**: `https://integrate.api.nvidia.com/v1`
- **DeepSeek V4 Flash**: `deepseek-ai/deepseek-v4-flash` — works but returns 503 (ResourceExhausted) when overloaded by other instances
- **DeepSeek V4 Pro**: `deepseek-ai/deepseek-v4-pro` — works but ~120s cold start
- **Status**: PRIMARY WORKING PROVIDER — retries on 503 with exponential backoff
- **Circuit breaker**: Set to 100 failures (effectively always tries)

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

### LLM Provider Path
```
complete() / complete_structured():
  1. HF Inference (router.huggingface.co) → 402 (no credits)
  2. HF serverless fallback (api-inference.huggingface.co) → DNS failure
  3. OpenRouter (4 models) → 429 (free) / 402 (paid, no credits)
  4. NVIDIA DeepSeek V4 Flash → 503 overloaded (retries 5x with backoff)
  5. NVIDIA DeepSeek V4 Pro → cold start 120s
```

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
