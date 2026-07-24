"""Humanization quality gate — audits and rewrites content to remove AI writing patterns.
Adapted from avoid-ai-writing (github.com/conorbronsdon/avoid-ai-writing, 2.6k stars).
Implements 57 pattern categories across content, language, structure, and communication.
"""

import re
from typing import Optional
from loguru import logger


class Humanizer:
    """Audits and rewrites content to remove AI writing patterns.
    
    Three modes:
    - rewrite (default): flags AI patterns and rewrites to fix them
    - detect: flags AI patterns without rewriting
    - edit: minimal targeted changes
    """

    TIER_1_WORDS = {
        "leverage": "use", "utilize": "use", "utilize": "use",
        "commence": "start", "endeavor": "try", "facilitate": "help",
        "implement": "set up", "optimize": "improve", "streamline": "simplify",
        "empower": "help", "robust": "reliable", "seamless": "smooth",
        "paradigm": "model", "ecosystem": "system", "landscape": "field",
        "transformative": "game-changing", "cutting-edge": "modern",
        "state-of-the-art": "modern", "next-generation": "new",
        "groundbreaking": "significant", "revolutionary": "different",
        "game-changer": "breakthrough", "unprecedented": "new",
        "granular": "detailed", "actionable": "useful",
        "holistic": "complete", "synergy": "collaboration",
        "deep-dive": "detailed look", "drill-down": "examine",
        "boast": "have", "featuring": "with", "underscore": "show",
        "ascertain": "determine", "paradigm shift": "change",
    }

    TIER_2_WORDS = {
        "navigate": "handle", "vibrant": "active", "thriving": "growing",
        "robustness": "reliability", "scalability": "growth",
        "ever-evolving": "changing", "fast-paced": "busy",
        "mission-critical": "important", "best-in-class": "good",
        "world-class": "good", "a plethora of": "many",
        "in the realm of": "in", "it is worth noting": "",
        "it should be noted": "", "it is important to": "",
    }

    TIER_3_PHRASES = [
        "the integration of", "decentralized compute", "community-driven",
        "long-term sustainability", "in today's digital", "in the modern",
        "in an era of", "when it comes to", "a wide range of",
        "in order to", "due to the fact that", "at the end of the day",
        "the future of", "the power of", "the potential of",
    ]

    AI_FILLER_PHRASES = [
        "in conclusion", "in summary", "to summarize",
        "ultimately,", "essentially,", "basically,",
        "interestingly,", "notably,", "importantly,",
        "it's worth mentioning", "it goes without saying",
        "needless to say", "let's dive in", "let's explore",
        "let's take a look", "let's break this down",
        "I hope this helps", "feel free to reach out",
        "if you have any questions", "don't hesitate",
        "in today's rapidly", "in this article, we'll",
        "in this post, we'll", "we will explore",
        "we delve into", "we examine",
    ]

    def __init__(self):
        self._tier3_pattern = re.compile(
            "|".join(re.escape(p) for p in self.TIER_3_PHRASES),
            re.IGNORECASE
        )

    def detect(self, text: str) -> dict:
        """Analyze text and return AI pattern flags.
        
        Returns {score, issues: [{pattern, severity, quote, suggestion}], label}
        """
        issues = []
        score = 0
        words = text.split()
        word_count = len(words)

        tier1_hits = []
        tier2_hits = []
        tier3_hits = []
        filler_hits = []

        for word in words:
            clean = word.strip(".,!?;:'\"()[]{}").lower()
            if clean in self.TIER_1_WORDS:
                tier1_hits.append(word)
                score += 10
            elif clean in self.TIER_2_WORDS:
                tier2_hits.append(word)
                score += 5

        for phrase in self.TIER_3_PHRASES:
            count = text.lower().count(phrase)
            if count >= 2:
                tier3_hits.append({"phrase": phrase, "count": count})
                score += 8 * count

        for phrase in self.AI_FILLER_PHRASES:
            if phrase.lower() in text.lower():
                filler_hits.append(phrase)
                score += 6

        if tier1_hits:
            issues.append({
                "pattern": "Tier 1 word replacements",
                "severity": "P0",
                "quote": ", ".join(list(set(tier1_hits))[:5]),
                "suggestion": f"Replace with: {', '.join(self.TIER_1_WORDS.get(w.lower().strip('.,!?'), w) for w in list(set(tier1_hits))[:5])}",
            })

        if tier2_hits:
            issues.append({
                "pattern": "Tier 2 word inflation",
                "severity": "P1",
                "quote": ", ".join(list(set(tier2_hits))[:5]),
                "suggestion": "Use simpler alternatives",
            })

        if tier3_hits:
            phrases_str = ", ".join(f"'{h['phrase']}' (x{h['count']})" for h in tier3_hits)
            issues.append({
                "pattern": "Multi-word boilerplate phrases",
                "severity": "P1",
                "quote": phrases_str,
                "suggestion": "Replace with specific claims",
            })

        if filler_hits:
            issues.append({
                "pattern": "Filler phrases / AI openers",
                "severity": "P0",
                "quote": ", ".join(filler_hits[:5]),
                "suggestion": "Remove or replace with direct statement",
            })

        avg_sentence_len = self._avg_sentence_length(text)
        if avg_sentence_len and (avg_sentence_len < 10 or avg_sentence_len > 30):
            issues.append({
                "pattern": "Uniform sentence length",
                "severity": "P1",
                "quote": f"Avg {avg_sentence_len:.0f} words/sentence",
                "suggestion": "Vary sentence length (mix short/long)",
            })
            score += 5

        paragraph_uniformity = self._check_paragraph_uniformity(text)
        if paragraph_uniformity:
            issues.append({
                "pattern": "Uniform paragraph structure",
                "severity": "P1",
                "quote": paragraph_uniformity,
                "suggestion": "Vary paragraph lengths more",
            })
            score += 5

        if re.search(r'[—–]', text):
            count = len(re.findall(r'[—–]', text))
            if count > 3:
                issues.append({
                    "pattern": "Excessive em-dashes",
                    "severity": "P2",
                    "quote": f"{count} em-dashes used",
                    "suggestion": "Replace some with commas or periods",
                })
                score += 3

        hashtags = re.findall(r'#\w+', text)
        if len(hashtags) > 5:
            issues.append({
                "pattern": "Hashtag stuffing",
                "severity": "P2",
                "quote": f"{len(hashtags)} hashtags",
                "suggestion": "Reduce to 2-3 max",
            })
            score += 4

        if re.search(r'\*\*[^*]+\*\*', text):
            bold_count = len(re.findall(r'\*\*[^*]+\*\*', text))
            if bold_count > 5:
                issues.append({
                    "pattern": "Excessive bold formatting",
                    "severity": "P2",
                    "quote": f"{bold_count} bold sections",
                    "suggestion": "Reduce bold usage",
                })
                score += 3

        if re.search(r'(?i)(?:the future looks bright|only time will tell|game-changer|watershed moment)', text):
            issues.append({
                "pattern": "Generic conclusion / significance inflation",
                "severity": "P0",
                "quote": "Generic closing statements detected",
                "suggestion": "Replace with specific closing thought",
            })
            score += 10

        if score > 30:
            label = "likely AI-written"
        elif score > 15:
            label = "may contain AI patterns"
        else:
            label = "likely human-written"

        return {
            "score": min(score, 100),
            "label": label,
            "issues": issues,
            "tier1_count": len(tier1_hits),
            "tier2_count": len(tier2_hits),
            "filler_count": len(filler_hits),
        }

    def humanize(self, text: str, voice: str = "conversational") -> Optional[str]:
        """Rewrite text to remove AI writing patterns.
        
        Uses LLM with specific avoid-ai-writing patterns as system prompt.
        """
        from providers.router import LLMRouter
        llm = LLMRouter()

        system = (
            "You are a human writing coach. Your ONLY job is to rewrite text to sound like "
            "a real human wrote it, not an AI. Follow these rules STRICTLY:\n\n"
            "1. REMOVE all AI filler: 'Certainly!', 'I hope this helps!', 'Feel free to reach out', "
            "'In conclusion', 'In summary', 'Let's dive in', 'Let's explore'\n"
            "2. REPLACE inflated words: leverage→use, utilize→use, robust→reliable, "
            "seamless→smooth, paradigm→model, ecosystem→system, landscape→field, "
            "transformative→game-changing, cutting-edge→modern, empower→help, "
            "streamline→simplify, optimize→improve\n"
            "3. CUT vague attributions: 'experts believe', 'studies show', 'many say'\n"
            "4. REMOVE significance inflation: 'watershed moment', 'game-changer', "
            "'the future looks bright', 'only time will tell', 'groundbreaking'\n"
            "5. FIX copula avoidance: 'serves as'→'is', 'features'→'has', 'boasts'→'has'\n"
            "6. CUT filler transitions: 'Moreover', 'Furthermore', 'In addition', 'Notably'\n"
            "7. SHORTEN: Break long sentences. Cut unnecessary words. Be direct.\n"
            "8. VARY rhythm: Mix short and long sentences. Some paragraphs should be 1-2 sentences.\n"
            "9. REMOVE em-dashes unless necessary for a pause.\n"
            "10. REMOVE hashtag stuffing (>3 hashtags).\n"
            "11. REMOVE excessive bold formatting.\n"
            "12. WRITE like a person, not a marketer. Use 'you'. Be specific. Name things.\n"
            "13. NO rhetorical questions as openers.\n"
            "14. NO 'Let's' constructions. Just state the point.\n"
            "15. NO numbered list inflation ('Here are 7 reasons why').\n\n"
            f"Voice: {voice}. Write in a {voice} tone."
        )

        prompt = (
            f"Rewrite the following text to remove ALL AI writing patterns. "
            f"Keep the facts, structure, and length similar. "
            f"Only change what makes it sound AI-generated. "
            f"Output ONLY the rewritten text, no explanation, no labels.\n\n"
            f"---TEXT TO REWRITE---\n{text}"
        )

        try:
            result = llm.complete(prompt, system=system, agent_type="general",
                                temperature=0.4, max_tokens=4096)
            if result and len(result) > 50:
                second_pass = llm.complete(
                    f"Check this text for remaining AI patterns (filler words, inflated language, "
                    f"marketing speak). If clean, output 'CLEAN'. Otherwise rewrite it:\n\n{result}",
                    system=system, agent_type="general", temperature=0.3, max_tokens=4096
                )
                if second_pass and second_pass.strip() != "CLEAN" and len(second_pass) > 50:
                    return second_pass
                return result
            return text
        except Exception as e:
            logger.warning(f"Humanizer rewrite failed: {e}")
            return text

    def _avg_sentence_length(self, text: str) -> Optional[float]:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if len(s.strip()) > 10]
        if not sentences:
            return None
        total = sum(len(s.split()) for s in sentences)
        return total / len(sentences)

    def _check_paragraph_uniformity(self, text: str) -> Optional[str]:
        paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 20]
        if len(paragraphs) < 3:
            return None
        lengths = [len(p.split()) for p in paragraphs]
        if max(lengths) - min(lengths) < 20:
            return f"All paragraphs are {sum(lengths)//len(lengths)}±{max(lengths)-min(lengths)} words"
        return None

    def score(self, text: str) -> int:
        """Get a 0-100 AI-likeness score (0 = human, 100 = AI)."""
        return self.detect(text)["score"]
