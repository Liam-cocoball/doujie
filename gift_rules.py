"""Gift catalogue, combo counters and ready-to-play performances for 豆姐."""
from collections import OrderedDict


# Unit prices are the windring-island catalogue values, in diamonds.
GIFTS = (
    {"id": "heart", "name": "小心心", "price": 1, "show": "嘴硬比心"},
    {"id": "rose", "name": "玫瑰", "price": 1, "show": "花瓣特写"},
    {"id": "beer", "name": "大啤酒", "price": 2, "show": "开罐审题"},
    {"id": "lollipop", "name": "棒棒糖", "price": 9, "show": "糖衣锐评"},
    {"id": "duck", "name": "加油鸭", "price": 15, "show": "小鸭抢麦"},
    {"id": "glowstick", "name": "荧光棒", "price": 99, "show": "灯光打拍"},
    {"id": "cannon", "name": "礼花筒", "price": 199, "show": "彩带抢话"},
    {"id": "fireworks", "name": "浪漫花火", "price": 599, "show": "烟花返场"},
    {"id": "car", "name": "跑车", "price": 1200, "show": "车灯过场"},
)

_BY_NAME = {gift["name"]: gift for gift in GIFTS}
_SINGLE_UNITS = {
    "heart": "颗", "rose": "朵", "beer": "杯", "lollipop": "根", "duck": "只",
    "glowstick": "根", "cannon": "个", "fireworks": "场", "car": "辆",
}
_MAX_NAMED_VIEWERS = 3
_OTHER_PRICES = {
    "抖音": 1, "天鹅羽翼": 1, "你最好看": 2, "给到夯": 9, "心疼": 9, "服了": 9,
    "天鹅之梦": 50, "Thuglife": 99, "步步生莲": 99, "捏捏小脸": 99, "亲吻": 99,
    "龙抬头": 99, "趣玩泡泡": 99, "黄桃罐头": 99, "爱的纸鹤": 99, "荧光律动": 99,
    "多喝热水": 126, "比心": 199, "真爱誓言": 199, "为你爆灯": 199, "为你举牌": 199,
    "蝶·连理枝": 280, "大圣兔兔": 299, "比心兔兔": 299, "不行不行": 299,
    "天鹅梦起": 366, "花开烂漫": 466, "热气球": 520, "天鹅启航": 599, "爱情树下": 599,
    "PK宝箱": 600, "七十二变": 699, "日出相伴": 726, "为你披甲": 1888, "浪漫恋人": 1999,
    "直升机": 2999, "瑶池仙梦": 5200, "广寒仙缘": 5200, "定海神针": 8999, "抖音1号": 10001,
    "九九归真": 11000, "大闹天宫": 15000, "嘉年华": 30000,
}

# Each pair is a setup and its payoff, played on two poses. {gift} includes the
# actual item and any combo count.
_BEATS = {
    "heart": ("skeptical", "heart", "smirk", "lean", (
        ("{gift}，手倒挺快。", "我手指头刚弯一下，你连孩子名都想好了？少臭美。"),
        ("{gift}举那么高干吗？", "哟，还朝我眨眼。眼皮抽筋就歇会儿，别赖我头上。"),
        ("{gift}，放我手里。", "你那半边心先别比了，手都举酸了我也不跟你拼图。"))),
    "rose": ("skeptical", "look", "smirk", "point", (
        ("{gift}给我，刺留着。", "你跟着凑什么？我桌上缺个花瓶，谁跟你招亲了？"),
        ("{gift}往左搁。", "谁给它拔的刺？自作主张。怎么不顺手给我这张嘴也磨磨边？"),
        ("{gift}借我挡下脸。", "你看，镜头还是追我。这花白抢半天戏。"))),
    "beer": ("grumpy", "hold", "smirk", "shrug", (
        ("{gift}谁晃过了？", "一拉环，泡沫全喷我麦上。你那边敢笑出声试试？"),
        ("{gift}，拉环给我。", "等我喝多了说句好听的？我这还没开罐，你倒先醉了。"),
        ("{gift}先别碰杯。", "隔着屏幕也敢跟我干杯，你拿什么碰，手机壳啊？"))),
    "lollipop": ("skeptical", "hold", "deadpan", "lean", (
        ("{gift}还敢往我嘴边递？", "糖纸都没剥，就学人家献殷勤。手收回去，重新排练。"),
        ("{gift}，想堵我的嘴？", "这糖真倒霉，出厂头一天就摊上这么个烂活。"),
        ("{gift}，谁挑的口味？", "我先替你尝。酸了算你的，甜了算我会挑。"))),
    "duck": ("grumpy", "look", "deadpan", "point", (
        ("{gift}，你也来抢麦？", "嘎一声算试音，嘎两声就想当主播？导播，把它的椅子撤了。"),
        ("{gift}上来就抢麦啊。", "这桌上就数你嗓门大。来，鸭老师，把刚才那句翻译成人话。"),
        ("{gift}，站好给个侧脸。", "导播，把镜头往我这边挪。它的正面留到鸭子专场。"))),
    "glowstick": ("grumpy", "wave", "skeptical", "point", (
        ("{gift}压低点，照谁呢？", "离我脸远点。你那点小心思倒值得照照，藏都没藏好。"),
        ("{gift}挥得挺忙啊。", "给你三秒当指挥。行了，下岗。整首歌就你抢半拍。"),
        ("{gift}，灯光师借我用下。", "往脸上补光就行了，你给我鼻孔办什么灯展？"))),
    "cannon": ("surprised", "look", "grumpy", "shrug", (
        ("{gift}这声谁放的？", "我准你开幕了吗？彩带落我水杯里了，过来，一根一根捞。"),
        ("{gift}响完了吧？", "就为宣布你进屋了？门铃坏了，还是嘴落家了？"),
        ("{gift}，这彩带归谁扫？", "刚才拍手那位，手都空出来了，扫帚也替你备好了。"))),
    "fireworks": ("skeptical", "look", "smirk", "lean", (
        ("{gift}闪完没有？", "全场抬头看烟花，就你盯着我。抓了个现行，你装什么路人？"),
        ("{gift}还挺会挑时候。", "镜头切回来。它炸三秒就消气，我可没那么好打发。"),
        ("{gift}，抬头看两眼。", "刚才许愿要我温柔点的那位，瞧见没，愿望当场炸了。"))),
    "car": ("grumpy", "look", "deadpan", "point", (
        ("{gift}靠边停。", "驾照掏出来。谁教你开着远光进我直播间的？还挺神气。"),
        ("{gift}还敢按喇叭？", "熄火。这儿就我能吵，发动机有意见让它发弹幕。"),
        ("{gift}，车钥匙留下。", "副驾给谁留的？腾出来，我出门连脾气都得单占一座。"))),
    "generic_low": ("skeptical", "nod", "smirk", "lean", (
        ("{gift}放这儿。", "瞅什么？给了你一眼，还想把我这眼神打包带走？"),
        ("{gift}，往左挪点。", "你那嘴角收一收。我叫你摆东西，没叫你脑补婚礼。"),
        ("{gift}，我验个货。", "礼物过关了。送礼的还在门口凹造型，我可不验那部分。"))),
    "generic_mid": ("grumpy", "hold", "smirk", "shrug", (
        ("{gift}占着正中间呢。", "给我让个镜头。刚学会进场就会抢戏，你这课上得挺快啊。"),
        ("{gift}，我听见了。", "谁还在那儿咳嗽等我点名？就你，连装个路人都抢拍。"),
        ("{gift}给个特写。", "拿到镜头了吧？说你送的东西呢，别自己对屏幕抛媚眼。"))),
    "generic_high": ("skeptical", "look", "deadpan", "point", (
        ("{gift}还带这么大排场？", "红毯卷起来。进我的门还想走压轴？你把台本拿反了吧。"),
        ("{gift}把我名牌挡了。", "想听我喊老板？玉皇大帝来了，也得等我把这句话说完。"),
        ("{gift}，阵仗倒是够了。", "导播，给它单独腾个位。我的主位谁坐谁交房租。"))),
}


def _name(value):
    return "".join((value or "").split()) or "礼物"


def gift_merge_key(gift_name):
    name = _name(gift_name)
    gift = _BY_NAME.get(name)
    return gift["id"] if gift else "other:" + name


def gift_script(gift_name, count=1, names=(), *, variant=0):
    """Build a fresh script. Receivers may omit names for anonymous gifts."""
    name = _name(gift_name)
    gift = _BY_NAME.get(name)
    price = gift["price"] if gift else _OTHER_PRICES.get(name, 1)
    tier = 1 if price < 50 else 2 if price < 500 else 3
    effect = gift["id"] if gift else "generic"
    script_id = gift["id"] if gift else ("generic_low", "generic_mid", "generic_high")[tier - 1]
    count = max(1, count)
    if isinstance(names, str):
        names = [names]
    viewers = list(dict.fromkeys(person.strip() for person in names if person and person.strip()))
    who = "、".join(person[:24] for person in viewers[:_MAX_NAMED_VIEWERS]) or "送礼的朋友"
    if len(viewers) > _MAX_NAMED_VIEWERS:
        who += f"等{len(viewers)}位"
    item = (f"{count}份" if count > 1 else "一" + _SINGLE_UNITS.get(script_id, "份")) + name[:20]
    first_mood, first_move, last_mood, last_move, scripts = _BEATS[script_id]
    variant %= len(scripts)
    opening, closing = scripts[variant]
    thanks = (f"谢谢{who}，", f"{who}，谢了！", f"谢啦，{who}！")[variant]
    if len(viewers) > 1:
        item = "你们的" + item
    segments = [
        {"text": thanks + opening.format(gift=item), "expression": first_mood, "gesture": first_move},
        {"text": closing, "expression": last_mood, "gesture": last_move},
    ]
    return {
        "giftId": script_id, "giftFx": effect, "effect": effect, "giftName": name, "giftPrice": price,
        "giftTier": tier, "giftCount": count, "giftViewers": viewers, "giftVariant": variant, "segments": segments,
    }


def can_merge_gift(current, incoming):
    """Only combine gifts whose donors can all be thanked in the same short opener."""
    first, second = current["giftViewers"], incoming["giftViewers"]
    return (gift_merge_key(current["giftName"]) == gift_merge_key(incoming["giftName"]) and
            bool(first) == bool(second) and len(set(first).union(second)) <= _MAX_NAMED_VIEWERS)


def merge_gift(current, incoming):
    """Combine compatible pending acknowledgements without dropping a donor."""
    if not can_merge_gift(current, incoming):
        raise ValueError("cannot combine these gifts into one acknowledgement")
    return gift_script(current["giftName"], current["giftCount"] + incoming["giftCount"],
                       [*current["giftViewers"], *incoming["giftViewers"]], variant=current.get("giftVariant", 0))


def live_gift_variant(task, history):
    """Pick the least recently heard performance. Archived text also covers older studios."""
    scripts = _BEATS[task["giftId"]][-1]
    order = list(range(len(scripts)))
    openings = [setup.format(gift=task["giftName"][:20]) for setup, _ in scripts]
    for row in history:
        if row.get("source") != "gift":
            continue
        text = row.get("text", "")
        for index, (_, ending) in enumerate(scripts):
            # Names and combo counts precede the gift. A shared tier can also reuse its ending.
            if openings[index] in text or text.endswith(ending):
                order.remove(index)
                order.append(index)
                break
    return order[0]


def _previous_topic(history):
    for row in reversed(list(history)[-4:]):
        source = row.get("source")
        if source == "gift":
            break  # A second gift gets its own joke instead of dragging back an old comment.
        if source in ("comment", "manual", "topic") and (row.get("prompt") or row.get("text")):
            return row
    return {}


def _gift_callback(gift_id, topic, default):
    if any(word in topic for word in ("好累", "失业", "被裁", "去世", "生病", "撑不住", "失眠")):
        return "最烦隔着屏幕劝人大度的。嘴皮子一碰，倒显得你出了多少力。"
    if any(word in topic for word in ("第二个家", "公司是我家", "公司就是家")):
        return {
            "duck": "鸭老师先替我去那第二个家看看。哪间是你的主卧？哦，折叠床在打印机后面。",
            "rose": "这花留着。哪天老板真分房了，拿去给你剪彩，省得他又拿嘴送套房。",
            "car": "第二个家连车都有了。老板分你的是停车位，还是扫车库那把拖把？",
        }.get(gift_id, "东西都到我桌上了。你老板分的房呢，也卡在发货页面了？")
    if any(word in topic for word in ("工资", "欠薪", "加班", "调休", "涨薪", "奖金")):
        return {
            "car": "钥匙给我，我去接加班费。人都下班了，钱还堵在老板嘴里呢？",
            "rose": "花都有到货日期。工资没动静，老板是拿嘴当付款码了？",
            "duck": "人家鸭子好歹当场嘎了两声。老板答应的那笔钱，连个屁都没听见。",
        }.get(gift_id, "礼物都到账了。回头问问你老板，发钱那颗键是有电还是扎手？")
    if any(word in topic for word in ("开会", "这场会", "会议", "周会", "例会")):
        return "我这场秀都演到收礼了。你们那破会还没结论？椅子上有胶啊？"
    if any(word in topic for word in ("录取", "考上", "夺冠", "拿到offer", "上岸")):
        return "谁非要把人家的本事说成运气？来，你把自己那张奖状也亮一亮。"
    return default


def contextual_gift(task, history, refine=None):
    """Keep the immediate opener playable while optionally rewriting only the second beat."""
    segments = [segment.copy() for segment in task["segments"]]
    if len(segments) < 2:
        return segments
    row = _previous_topic(history)
    topic = row.get("prompt") or row.get("text") or ""
    closing = _gift_callback(task["giftId"], topic, segments[-1]["text"])
    def just_heard(line):
        words = "".join(c for c in line.casefold() if c.isalnum())
        return bool(words) and any("".join(c for c in row.get("text", "").casefold() if c.isalnum()).endswith(words)
                                   for row in history if row.get("source") == "gift")
    if closing != segments[-1]["text"] and just_heard(closing):
        closing = segments[-1]["text"]
    if refine is not None:
        try:
            candidate = refine(row, closing)
            if isinstance(candidate, str) and candidate.strip() and not just_heard(candidate):
                closing = candidate.strip()[:95]
        except Exception:
            # A failed rewrite must leave the authored performance ready to air.
            pass
    segments[-1]["text"] = closing
    return segments


class GiftCombos:
    """Count increments from captured cumulative display counts after event-ID dedup.

    A collector may explicitly identify its combo. Otherwise a newer lower counter,
    a separate one-off gift, or a ten-second gap begins a new combo. Older snapshots
    never rewind its state.
    Call under the scheduler lock.
    """

    def __init__(self, window=10, max_keys=4096):
        self.window = window
        self.max_keys = max_keys
        self._counts = OrderedDict()

    def increment(self, room, viewer, gift_name, display_count, captured_at, combo_id=None):
        if display_count is None or (not viewer and not combo_id):
            # Anonymous rows can't reliably be attributed to the same sender.
            return display_count or 1
        key = (room, viewer, gift_merge_key(gift_name), combo_id)
        current = display_count
        previous = self._counts.get(key)
        delta = current
        if previous is not None:
            last_time, last_count = previous
            # A duplicate timestamp with a larger counter is a legitimate update
            # from collectors with coarse time resolution.
            if captured_at < last_time or (captured_at == last_time and current <= last_count):
                return 0
            if combo_id or captured_at - last_time < self.window:
                if current == last_count:
                    # The default collector supplies independent event IDs for
                    # separate one-off sends. Its timestamps disambiguate singles.
                    if combo_id or current != 1:
                        return 0
                elif current > last_count:
                    delta = current - last_count
                elif combo_id:
                    return 0
                # A newer lower counter without a combo ID starts the next streak.
        self._counts[key] = (captured_at, current)
        self._counts.move_to_end(key)
        if len(self._counts) > self.max_keys:
            self._counts.popitem(last=False)
        return delta
