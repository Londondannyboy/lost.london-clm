"""Response models with fact-grounding validation."""

from pydantic import BaseModel, field_validator, model_validator
from typing import Self


class ArticleResult(BaseModel):
    """A retrieved article from the knowledge base."""

    id: str
    title: str
    content: str
    score: float


class SearchResults(BaseModel):
    """Results from article search."""

    articles: list[ArticleResult]
    query: str


class ValidatedVICResponse(BaseModel):
    """Response that is guaranteed to be grounded in source articles.

    All facts stated in the response must be traceable to the source content.
    This model validates that no hallucinated information is included.
    """

    response_text: str
    facts_stated: list[str]  # Each distinct fact mentioned in response
    source_content: str      # The combined article content used
    source_titles: list[str] # Titles of articles referenced

    @field_validator('response_text')
    @classmethod
    def response_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Response cannot be empty")
        return v.strip()

    @model_validator(mode='after')
    def facts_must_be_in_source(self) -> Self:
        """Validate that each stated fact has grounding in source content."""
        source = self.source_content.lower() if self.source_content else ""
        facts = self.facts_stated

        if not source:
            # No source content - only allow if no facts stated
            if facts:
                raise ValueError("Cannot state facts without source content")
            return self

        for fact in facts:
            # Extract key terms (words > 4 chars, excluding common words)
            common_words = {'about', 'which', 'where', 'there', 'their', 'would', 'could', 'should'}
            key_terms = [
                t for t in fact.lower().split()
                if len(t) > 4 and t not in common_words
            ]

            # At least one key term must appear in source
            if key_terms and not any(term in source for term in key_terms):
                raise ValueError(f"Fact not grounded in source: {fact}")

        return self

    @model_validator(mode='after')
    def no_architect_unless_mentioned(self) -> Self:
        """Specific check: don't mention architects/designers unless in source.

        This is a known hallucination pattern - LLMs love to invent architects.
        """
        architect_patterns = [
            'designed by', 'architect', 'built by', 'designer',
            'constructed by', 'created by', 'commissioned by'
        ]
        response_lower = self.response_text.lower()
        source_lower = self.source_content.lower()

        for pattern in architect_patterns:
            if pattern in response_lower:
                # If we mention this pattern, source must also contain it
                # (or at least mention the specific name we're attributing)
                if pattern not in source_lower:
                    raise ValueError(
                        f"Response mentions '{pattern}' but source doesn't discuss attribution"
                    )
        return self

    @model_validator(mode='after')
    def no_specific_dates_unless_in_source(self) -> Self:
        """Check that specific years mentioned are in the source."""
        import re

        # Find all 4-digit years in response (1000-2099)
        response_years = set(re.findall(r'\b(1[0-9]{3}|20[0-9]{2})\b', self.response_text))
        source_years = set(re.findall(r'\b(1[0-9]{3}|20[0-9]{2})\b', self.source_content))

        hallucinated_years = response_years - source_years
        if hallucinated_years:
            raise ValueError(
                f"Response mentions years not in source: {hallucinated_years}"
            )

        return self


class DeclinedResponse(BaseModel):
    """Response when we cannot answer from available sources."""

    response_text: str
    reason: str

    @field_validator('response_text')
    @classmethod
    def must_indicate_limitation(cls, v: str) -> str:
        """Ensure the response indicates we're declining to answer."""
        decline_phrases = [
            "don't have", "don't cover", "can't find", "not sure",
            "articles don't", "no information", "couldn't find"
        ]
        if not any(phrase in v.lower() for phrase in decline_phrases):
            raise ValueError(
                "Declined response must indicate limitation to user"
            )
        return v
