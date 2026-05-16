"""Pydantic models for the on-disk proposal manifest."""

from .manifest import (
    AnimationCandidate,
    AnimationParams,
    ProposalManifest,
)

__all__ = ["AnimationCandidate", "AnimationParams", "ProposalManifest"]
