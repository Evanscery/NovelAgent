"""Provider encoders — RequestSpec <-> concrete provider wire formats.

The seam is :class:`~app.runtime.providers.base.RequestEncoder`
(a Protocol); :class:`~app.runtime.providers.openai_chat.OpenAIChatEncoder`
is the one concrete encoding today. New providers implement the Protocol
here without touching runners or the prompt builder.
"""

from app.runtime.providers.base import RequestEncoder
from app.runtime.providers.openai_chat import OpenAIChatEncoder

__all__ = [
    "OpenAIChatEncoder",
    "RequestEncoder",
]
