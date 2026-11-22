"""Short gift invitations for the room or for the end of an audience reply."""
import random
import re

from gift_rules import GIFTS
from host_dialogue import beat


_INVITES = {
    "玫瑰来一朵，刺我自己有。": ("smirk", "point"),
    "小心心抛一颗，我接得稳。": ("smirk", "lean"),
    "谁送只加油鸭？让它上麦嘎一声。": ("skeptical", "look"),
    "递根棒棒糖，我看看谁比我嘴甜。": ("skeptical", "lean"),
    "想送荧光棒的，亮一根我看看。": ("smirk", "wave"),
    "谁递杯大啤酒？杯子给我，麦也归我。": ("deadpan", "point"),
    "谁送朵玫瑰？我看看是谁先脸红。": ("smirk", "look"),
    "给个小心心，我这臭脾气也配个甜的。": ("grumpy", "heart"),
    "来只加油鸭，我倒要看看谁的嘴更硬。": ("skeptical", "shrug"),
    "来根棒棒糖，看看能不能治我这张嘴。": ("deadpan", "shrug"),
    "谁递根荧光棒？我拿它给这场戏打光。": ("smirk", "wave"),
    "大啤酒来一杯，这段吐槽可真费嗓子。": ("grumpy", "nod"),
}
_GIFT_NAMES = tuple(gift["name"] for gift in GIFTS)
_GIFT_TALK = re.compile(r"礼物|送礼|收礼|刷礼|打赏|上票|刷票|灯牌|嘉年华|礼花|"
                        r"(?:刷|送)(?:一波|一组|一发|点东西)|(?:给我|给主播)刷(?:个|点|一)")


def mentions_gifts(text):
    return bool(text and (any(name in text for name in _GIFT_NAMES) or _GIFT_TALK.search(text)))


def _pick_invite(options, recent_lines):
    last_used = {line: -1 for line in options}
    for index, text in enumerate(recent_lines):
        for line in options:
            if line in text:
                last_used[line] = index
    oldest = min(last_used.values())
    return random.choice([line for line in options if last_used[line] == oldest])


def make_gift_invite(recent_lines):
    """Address the room in one spoken beat, using the same history as reply endings."""
    invite = _pick_invite(_INVITES, recent_lines)
    expression, gesture = _INVITES[invite]
    return beat(invite, expression, gesture)


def append_gift_invite(segments, recent_lines, *, max_chars=162):
    """Keep the original reply and poses. Recent aired lines are ordered oldest first."""
    if not segments or any(mentions_gifts(part.get("text", "")) for part in segments):
        return segments
    ending = segments[-1].get("text") or ""
    if not ending.strip():
        return segments
    separator = "" if ending.rstrip().endswith(tuple("。！？!?….”’」』")) else "。"
    options = [line for line in _INVITES if len(ending + separator + line) <= max_chars]
    if not options:
        return segments

    invite = _pick_invite(options, recent_lines)
    return [*segments[:-1], {**segments[-1], "text": ending + separator + invite}]
