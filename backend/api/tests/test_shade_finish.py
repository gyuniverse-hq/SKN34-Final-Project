"""A shade carries an optional eyeshadow finish; it is left out of the JSON when empty."""

import pytest
from pydantic import ValidationError

from app.schemas.catalog import Shade


def test_finish_is_sent_when_reviewed():
    shade = Shade(id="A000000174309-085", name="위티", hex="#D8C2B6", finish="glitter")
    assert shade.model_dump(mode="json")["finish"] == "glitter"


def test_finish_is_omitted_when_empty():
    shade = Shade(id="01", name="Red", hex="#AA2233")
    assert "finish" not in shade.model_dump(mode="json")


@pytest.mark.parametrize("finish", ["satin", "metallic"])
def test_finishes_beyond_the_current_lid_renderer_are_accepted(finish):
    assert Shade(id="01", name="Red", hex="#AA2233", finish=finish).finish == finish


def test_non_finish_codes_are_rejected():
    with pytest.raises(ValidationError):
        Shade(id="01", name="Case", hex="#AA2233", finish="accessory")
