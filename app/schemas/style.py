"""Series Style Bible — one visual style for the whole book.

Generated once from the book (genre/era/mood, spoiler-safe) and applied
identically to every character portrait (and later chapter covers) so the
whole cast looks like one coherent illustrated series that fits the book.
Maps directly onto the Ideogram-4 style_description fields (PLAN Appendix A.2).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Phrase = Annotated[str, StringConstraints(max_length=160, strip_whitespace=True)]
Hex = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class StyleBible(BaseModel):
    genre: Phrase = "general fiction"
    art_style: Phrase = "painterly illustration"
    aesthetics: Phrase = "cohesive, character-focused"
    lighting: Phrase = "soft even light"
    medium: Phrase = "digital illustration"
    color_palette: list[Hex] = Field(
        default_factory=lambda: ["#1A2238", "#9DAAF2", "#F4DB7D", "#E0E0E0"],
        min_length=3,
        max_length=8,
    )
    # Neutral portrait backdrop that fits the book's world (no plot/scene).
    background: Phrase = "plain neutral studio backdrop, soft vignette"
    # Several distinct book-fitting backdrops so each character gets a different
    # (but consistent-world) background instead of all sharing one.
    background_variants: list[Phrase] = Field(default_factory=list, max_length=6)
    # Casting/wardrobe context so portraits fit the book and avoid the model's
    # default bias (e.g. Z-Image defaults to Asian faces / undressed subjects).
    setting: Phrase = "contemporary"
    casting: Phrase = "predominantly European features, varied and natural"
    wardrobe: Phrase = "ordinary everyday clothing appropriate to the setting"
    # Several distinct outfits fitting the setting so characters don't all wear
    # the same thing (used when the text gives no clothing for a character).
    wardrobe_variants: list[Phrase] = Field(default_factory=list, max_length=6)
