from __future__ import annotations

import re


def split_narration_sentences(text: str) -> list[str]:
    narration = text.strip()
    if not narration:
        raise ValueError("narration must not be empty")
    # Latin/Korean marks need following whitespace; fullwidth CJK marks end a
    # sentence on their own, so a following space is optional there.
    parts = re.split(r"(?<=[.?!])\s+(?=\S)|(?<=[。！？])\s*(?=\S)", narration)
    return [part for part in parts if part]

