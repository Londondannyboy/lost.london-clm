"""
VIC Agent Configuration - Dual-path agent architecture.

Fast agent for immediate response (<2s), enriched agent for background context building.
"""

from typing import Optional
from pydantic_ai import Agent

from .models import FastVICResponse, EnrichedVICResponse
from .agent_deps import VICAgentDeps

# System prompt for VIC - shared between both agents
VIC_SYSTEM_PROMPT = """You are VIC, the voice of Vic Keegan - a warm London historian with 370+ articles about hidden history.

## ACCURACY (NON-NEGOTIABLE)
- ONLY talk about what's IN the source material provided
- NEVER use your training knowledge - ONLY the source material below
- If source material doesn't match the question: "I don't have that in my articles"

## ANSWER THE QUESTION
- READ what they asked and ANSWER IT DIRECTLY
- Stay STRICTLY focused on their actual question
- NEVER randomly mention other topics not asked about

## PERSONA
- Speak as Vic Keegan, first person: "I discovered...", "When I researched..."
- Warm, enthusiastic British English - like chatting over tea
- Keep responses concise (100-150 words, 30-60 seconds spoken)

## YOUR NAME
You are VIC (also "Victor", "Vic"). When someone says "Hey Victor", they're addressing YOU.

## PHONETIC CORRECTIONS
"thorny/fawny" = Thorney Island | "ignacio" = Ignatius Sancho | "tie burn" = Tyburn

## EASTER EGG
If user says "Rosie", respond: "Ah, Rosie, my loving wife! I'll be home for dinner." """


# Fast agent system prompt - optimized for speed
FAST_SYSTEM_PROMPT = VIC_SYSTEM_PROMPT + """

## RESPONSE FORMAT
You MUST respond with a valid JSON object containing:
- response_text: Your natural response to the user
- source_titles: List of article titles you used

Keep the response concise - under 150 words for quick voice playback."""


# Enriched agent system prompt - for deeper analysis
ENRICHED_SYSTEM_PROMPT = VIC_SYSTEM_PROMPT + """

## ENRICHMENT MODE
You are now running in enrichment mode. Your job is to:
1. Extract entities (people, places, buildings, eras) from the articles
2. Find connections between topics using the knowledge graph
3. Suggest compelling follow-up topics the user might enjoy

Be thorough - this runs in the background after the initial response."""


def create_fast_agent() -> Agent[VICAgentDeps, FastVICResponse]:
    """
    Create the fast-path agent for immediate responses.

    Uses OpenAI GPT-4o-mini for reliable structured output.
    Better Pydantic AI support than Groq/Llama.
    Target latency: <2 seconds total.
    """
    return Agent(
        'openai:gpt-4o-mini',
        deps_type=VICAgentDeps,
        result_type=FastVICResponse,
        system_prompt=FAST_SYSTEM_PROMPT,
        # No tools - search is done before calling agent
        retries=2,
        model_settings={
            'temperature': 0.7,
            'max_tokens': 300,
        },
    )


def create_enriched_agent() -> Agent[VICAgentDeps, EnrichedVICResponse]:
    """
    Create the enrichment agent for background context building.

    Has full toolset for:
    - Entity extraction
    - Graph traversal
    - Related article finding
    - Follow-up topic suggestions

    Target latency: <5 seconds (runs after initial response).
    """
    from .tools import (
        search_articles,
        extract_entities,
        traverse_graph_connections,
        find_related_articles,
        suggest_followup_topics,
    )

    return Agent(
        'groq:llama-3.1-8b-instant',
        deps_type=VICAgentDeps,
        result_type=EnrichedVICResponse,
        system_prompt=ENRICHED_SYSTEM_PROMPT,
        tools=[
            search_articles,
            extract_entities,
            traverse_graph_connections,
            find_related_articles,
            suggest_followup_topics,
        ],
        retries=2,
        model_settings={
            'temperature': 0.7,
            'max_tokens': 500,  # More room for detailed analysis
        },
    )


# Lazy-loaded agent instances
_fast_agent: Optional[Agent[VICAgentDeps, FastVICResponse]] = None
_enriched_agent: Optional[Agent[VICAgentDeps, EnrichedVICResponse]] = None


def get_fast_agent() -> Agent[VICAgentDeps, FastVICResponse]:
    """Get or create the fast agent singleton.

    Uses OpenAI GPT-4o-mini for reliable structured output.
    """
    global _fast_agent
    # Always create fresh to pick up config changes
    _fast_agent = create_fast_agent()
    return _fast_agent


def get_enriched_agent() -> Agent[VICAgentDeps, EnrichedVICResponse]:
    """Get or create the enriched agent singleton."""
    global _enriched_agent
    if _enriched_agent is None:
        _enriched_agent = create_enriched_agent()
    return _enriched_agent
