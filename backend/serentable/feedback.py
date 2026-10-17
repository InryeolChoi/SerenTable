"""Work #8 feedback API (feedback-contract.md). Owned by its ticket; T0 only registers it."""

from fastapi import APIRouter

router = APIRouter()


def run_feedback_jobs():
    """Create the single unanswered-feedback reminder per member (T2 implements)."""
