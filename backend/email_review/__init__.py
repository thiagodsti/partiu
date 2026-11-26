"""
Email review feature package: booking emails the sync could not read.

Layering (routes -> service -> repository -> database):
  routes.py      - FastAPI router; only HTTP concerns
  dto.py         - request/response models at the HTTP boundary
  detect.py      - pure functions: the hints and excerpt shown for an email
  repository.py  - EmailReviewRepository: `email_candidates`, ignored senders
  service.py     - EmailReviewService: what qualifies, LLM drafts, importing

``sync/pipeline._process_emails`` calls ``consider_for_review`` for every email
that produced nothing.
"""

from .service import consider_for_review, email_review_service

__all__ = ["consider_for_review", "email_review_service"]
