"""Aspect-aware OpenAI Images API ``size`` selection (txt2img / ``generate``)."""

from boardfactory.providers.openai_img import _generation_size_for_target


def test_generation_size_portrait_like_centerpiece():
    assert _generation_size_for_target((520, 720)) == "1024x1536"


def test_generation_size_square_tile():
    assert _generation_size_for_target((128, 128)) == "1024x1024"


def test_generation_size_landscape_tile():
    assert _generation_size_for_target((720, 520)) == "1536x1024"


def test_generation_size_invalid_falls_back_square():
    assert _generation_size_for_target((0, 720)) == "1024x1024"
    assert _generation_size_for_target((520, 0)) == "1024x1024"
