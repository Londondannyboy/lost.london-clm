"""
VIC Agent Dependencies - Runtime context for Pydantic AI agents.

This dataclass is passed to all agent tools and allows them to access
session context, user information, and conversation history.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VICAgentDeps:
    """Runtime dependencies for the VIC agent.

    Attributes:
        user_id: Unique identifier for the user (from Neon Auth)
        session_id: Current conversation session ID
        user_name: User's first name for personalization
        conversation_history: Recent messages for context
        enrichment_mode: True when running background enrichment (slower path)
        prior_entities: Entities from previous turns (for context)
        prior_topics: Topics discussed in previous turns
    """
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    user_name: Optional[str] = None
    conversation_history: list[dict] = field(default_factory=list)
    enrichment_mode: bool = False
    prior_entities: list[str] = field(default_factory=list)
    prior_topics: list[str] = field(default_factory=list)

    def has_context(self) -> bool:
        """Check if we have prior context from previous turns."""
        return bool(self.prior_entities or self.prior_topics)

    def add_entity(self, entity: str) -> None:
        """Add an entity to the context (deduped)."""
        if entity and entity not in self.prior_entities:
            self.prior_entities.append(entity)

    def add_topic(self, topic: str) -> None:
        """Add a topic to the context (deduped)."""
        if topic and topic not in self.prior_topics:
            self.prior_topics.append(topic)
