"""SillyTavern compat layer — all ST naming converges here (per D5).

Public surface:

* :mod:`card_front`      — ST-style regex -> HTML front rendering.
* :mod:`card_migration`  — tavern card -> 8-resource project migration.
* :mod:`preset_extract`  — preset 文风/jailbreak -> PromptFragment.

Per decision D5, this package is one
of the two sanctioned places where SillyTavern is named (the other is
``docs/compat_tavern_card.md``). Code outside ``app/compat/tavern_card/``
must use the project's own terms (角色卡兼容 / 卡导入 / 预设片段).
"""

from __future__ import annotations
