# Phase 1: Get One Agent Working

## Goal
AffiliateMarketer agent completes one full cycle using free OpenRouter models. Dashboard shows real progress.

## Success Criteria
1. LLM call succeeds (at least one provider works)
2. Agent plans 3-5 tasks
3. Agent executes at least one task
4. Agent evaluates output (critic scores it)
5. At least one task passes and ships as artifact
6. Dashboard shows chat history with real LLM interactions
7. Human tasks tab shows any pending approvals

## Steps

### Step 1: Deploy Updated Router
- Push new `providers/router.py` with free model stack
- Set `OPENROUTER_API_KEY` in Railway to new paid key
- Verify deploy succeeds

### Step 2: Start Agent and Watch Logs
- Start AffiliateMarketer via dashboard
- Watch Railway logs for:
  - `OpenRouter SUCCESS` — LLM call worked
  - `planning_complete` — tasks were planned
  - `executing_complete` — task was executed
  - `evaluating_complete` — critic evaluated output
  - `cycle_complete` — full cycle completed

### Step 3: Fix Issues
- If OpenRouter 429 → wait and retry (20 RPM cap)
- If Gemini censorship blocks output → skip to next model
- If MiMo v2.5 needed → use it (paid, last resort)

### Step 4: Verify Dashboard
- Chat history shows LLM interactions
- Tasks show progress (pending → executing → completed)
- Artifacts appear in artifacts/ directory
- Human tasks tab works

## Expected Timeline
- Step 1: 2 minutes (deploy)
- Step 2: 5 minutes (agent runs)
- Step 3: varies (fix issues)
- Step 4: 2 minutes (verify)

## Risk: All Providers Fail
If OpenRouter free models don't work:
1. Check model names are correct on OpenRouter
2. Try Google Gemini as primary (censored but works)
3. Use MiMo v2.5 as primary (paid, $0.50/M input tokens)
