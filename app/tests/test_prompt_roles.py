"""Tests for pipeline prompt role phrases (generation hierarchy)."""

from __future__ import annotations

from boardfactory.prompt_roles import (
    centerpiece_role_phrase,
    compose_prompt,
    panel_role_phrase,
    space_role_phrase,
)


def test_space_standard_vs_event_differ():
    s = space_role_phrase("standard")
    e = space_role_phrase("event")
    assert s != e
    assert "track space" in s.lower() or "track" in s.lower()
    assert "event" in e.lower()
    assert space_role_phrase(None) == s
    assert space_role_phrase("standard") == s


def test_compose_order():
    out = compose_prompt("Mood. ", "Role phrase ", "user stuff")
    assert out == "Mood. Role phrase user stuff"


def test_panel_and_centerpiece_non_empty():
    assert len(panel_role_phrase()) > 40
    assert "panel" in panel_role_phrase().lower()
    assert "centerpiece" in centerpiece_role_phrase().lower() or "hero" in centerpiece_role_phrase().lower()
