# Task Definitions

## Phase 1 Tasks (AffiliateMarketer)

### Task 1: Research Profitable Niches
- **Description**: Research 5 profitable affiliate marketing niches with high commission rates
- **Success Criteria**: List of 5 niches with commission rates, competition level, and revenue potential
- **Action Type**: research
- **Tags**: research, analysis, affiliate

### Task 2: Join Affiliate Programs
- **Description**: Sign up for 3 affiliate programs in the chosen niche
- **Success Criteria**: Account created on each platform, affiliate links generated
- **Action Type**: signup (requires human approval)
- **Tags**: outreach, affiliate, signup

### Task 3: Create Content
- **Description**: Write 3 blog posts optimized for SEO with affiliate links
- **Success Criteria**: 3 published blog posts with affiliate links, each 1000+ words
- **Action Type**: content
- **Tags**: content, blog, seo

### Task 4: Set Up Tracking
- **Description**: Create tracking system for affiliate conversions
- **Success Criteria**: Tracking spreadsheet or database with conversion metrics
- **Action Type**: code
- **Tags**: code, tracking, analytics

### Task 5: Outreach to Partners
- **Description**: Contact 5 potential partners for cross-promotion
- **Success Criteria**: 5 personalized outreach emails sent
- **Action Type**: outreach
- **Tags**: outreach, partnerships

## Task Schema
```json
{
  "id": "task_1",
  "description": "Research profitable niches",
  "success_criteria": "List of 5 niches with commission rates",
  "tags": ["research", "analysis"],
  "action_type": "research",
  "state": "pending",
  "status": "pending",
  "attempts": 0,
  "revisions": 0
}
```

## Task States
- `pending` — not started
- `executing` — in progress
- `evaluating` — critic reviewing
- `passed` — approved by critic
- `awaiting_approval` — needs human approval
- `shipping` — writing artifact
- `done` — completed successfully
- `failed` — failed after revisions
- `dead_letter` — permanently failed

## Revision Rules
- Max 3 revisions per task
- Each revision must address specific critic feedback
- After 3 revisions, task moves to failed/dead_letter
- Frustration counter tracks repeated failures
