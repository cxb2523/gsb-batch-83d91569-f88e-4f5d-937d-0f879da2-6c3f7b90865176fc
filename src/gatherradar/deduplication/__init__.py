"""Conservative, in-memory event identity and review."""
from .models import CandidateContext, DuplicateDecision, MatchKind, CanonicalizationResult
from .matcher import match_pair
from .service import canonicalize

__all__ = ["CandidateContext", "DuplicateDecision", "MatchKind", "CanonicalizationResult",
           "match_pair", "canonicalize"]
