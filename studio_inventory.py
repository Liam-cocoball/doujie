"""Answer questions about the fixed 3-D set from the same catalogue as the renderer."""
import json
import re
from pathlib import Path


CATALOGUE = Path(__file__).resolve().parent / "web" / "assets" / "studio-inventory.json"
ITEMS = {item["id"]: item for item in json.loads(CATALOGUE.read_text(encoding="utf-8"))["items"]}
FEATURED = {ITEMS[key]["viewerSide"]: key for key in ("phone", "monitor")}


def _fold(text):
    return "".join(text.casefold().split())


ALIASES = {key: tuple(sorted({_fold(alias) for alias in [item["name"], *item["aliases"]]}, key=len, reverse=True))
           for key, item in ITEMS.items()}
_ITEM_NOUN = "(?:" + "|".join(re.escape(alias) for aliases in ALIASES.values() for alias in aliases) + ")"
_OTHER_BAG = re.compile(r"表情包|显眼包|受气包|钱包|书包|包(?:子|邮|含|括|袱|容|装|场|月|工|养|庇|揽|办|浆|吃|住|饺子|馄饨|粽子|车|机|餐|年|夜宵)|面包|红包|荷包|快递包裹|外包")
_BAG_NAME = r"(?:(?:lv|路易威登|louisvuitton)(?:老花)?(?:小包|包包|手提包|包)?|(?:老花|小|手提)?包包?)"
_SET_BAG = re.compile(r"(?:你|豆姐|主播|桌子?上|桌面|直播间|镜头里|[左右](?:边|侧)|[这那](?:个|只|款))"
                      r"(?:的|那|这|只|个|款|小|桌子?上|桌面|摆的|摆着|放的|放着|有|还|是|是不是|以前|之前|原来|[左右][侧边])*" + _BAG_NAME
                      + r"|^" + _BAG_NAME + r"(?:呢|在哪|去哪|怎么不见|还在|不见|放哪|多少钱|啥价|没了|没摆|还摆|$)")
_QUESTION = re.compile(r"什么|啥|哪|几|谁|怎么|多少|真[假货的]|假的|[?？吗呢]|有没|是不是|介绍|看看|看一下|给我看|讲讲|说说")
_SET = re.compile(r"豆姐|主播|[你您]|桌(?:上|面|前|边|子上)|直播间|演播室|镜头|画面|屏幕[左右]|这[台只部款个套件条双]|那[台只部款个套件条双]")
_VISIBLE = re.compile(r"桌(?:上|面|前|旁|边|子上)|镜头(?:里|前|中)|画面(?:里|上|中|[左右])|屏幕(?:上|[左右])|直播间(?:的|里)")
_POINT = r"(?:你|您|豆姐|主播)(?:自己)?(?:的|用的|背的|拿的|摆的|穿的|戴的|围的|那个|这个|那|这)?[台只个条件部双款]?|[这那][台只个条件部双款]?"
_POINTED_ITEM = re.compile(r"(?:" + _POINT + ")" + _ITEM_NOUN)
_PLACE = r"(?:桌子?上|桌面|桌前|直播间|画面|镜头|屏幕)"
_PLACED_ITEM = re.compile(_PLACE + r"(?:两[侧边]|左右两[侧边])?[里的上中前侧左右边摆放着有这那个件台只部小]*" + _ITEM_NOUN
                          + "|" + _ITEM_NOUN + r"(?:摆|放|搁)?在(?:你|你的)?" + _PLACE)
_SIDE_OBJECT = re.compile(r"(?:手边|边|侧|面|方)(?:的)?(?:[那这][个件台只款]|摆|放|发[亮光]|闪|是(?:啥|什么)|什么|啥)|[那这][个件台只].{0,4}(?:在|是)(?:左|右)")
_SIDE_ITEM = re.compile(r"(?:手边|边|侧)(?:的|是)?[那这]?(?:个|只|台|部|小)?" + _ITEM_NOUN)
_OWN = re.compile(r"[我他她](?:家|朋友|同事|老婆|对象|妈妈?|爸爸?|妹|哥)?的?(?:新买的?|刚买的?|自己的?)?" + _ITEM_NOUN)
_SCENE_ASIDE = re.compile(r"给(?:你|豆姐|主播)(?:送|买)|[我他她](?:最近|刚刚?|昨天|今天|想|朋友|同事|妈妈|爸爸)*"
                          r"(?:用|拿|买|借|换|丢|修|弄坏|摔坏|收到|送)(?:过|了|的|台|部|个|只|款|一|这|那)*" + _ITEM_NOUN)
_TROUBLE = re.compile(r"退货|寄修|开不了机|死机|断网|连不上|怎么(?:修|截屏|截图|换壁纸)|发(?:不出|不了)|"
                      r"(?:手机|电脑).{0,12}(?:看|进|刷).{0,8}(?:直播|视频).{0,6}(?:卡|黑屏|没声|闪退)")
_PRICE = re.compile(r"多少钱|多少米|啥价|价[格钱签]|贵不贵|多贵|贵吗|便宜|几块|花了|花多少|值[几多]|"
                    r"几[万千]|[卖买]多少|[\d一二两三四五六七八九十]+[千万元块]")
_AUTH = re.compile(r"真假|真(?:的|是?假)|正版|[真假]货|正品|高仿|鉴定|真伪|仿的|假的|山寨|冒牌|小票|真皮")
_ORIGIN = re.compile(r"同款|怎么买|链接|在哪买|哪[里儿家]买|哪买|谁(?:送|买|给)|买的|赞助|代言|专柜|渠道|从哪|网上买")
_SPEC = re.compile(r"内存|容量|芯片|处理器|配置|尺寸|多大|多重|几斤|几寸|多少(?:寸|g|gb|t)|装得下|能装|哪一?代|几代|哪款|哪一款|型号|"
                   r"什么款|款式|系列|材质|材料|[限绝]版|配色名|什么做的|几个摄像头|什么皮|啥皮")
_FOLLOW = re.compile(r"(?:(?:哦|噢|喔|嗯|好|那|这|它|个|只|台|件|请问|所以|到底|看起来|又|还|是|有|的)[，,、]?)*"
                     r"(?:多少钱|多少米|啥价|几块钱?|贵不贵|贵吗|真的假的|真是假|真假|真货?|假货?|正品|正版|什么牌子?|啥牌子?|什么色|什么颜色|啥颜?色|"
                     r"(?:在|是从|从)?哪[家里儿]?买|谁(?:送|买)|多大|多重|多贵|几斤|几寸|什么材质|什么型号|哪一?款|(?:另|另外)一[侧边个只台]|"
                     r"(?:放)?在哪[儿里边]?|有链接|链接|能装多少|什么做的|好看吗|怎么[摆放折]|[摆放]成什么样|"
                     r"(?:背面|后盖|标志|标识|键盘|内屏|屏幕)(?:上|的)?(?:朝哪(?:[边面里]|个方向)?|向哪边|对着谁|在哪|是啥|是什么|呢))"
                     r"[的了呢吗么呀啊吧嘛呗哇哦?？!！，。～~]*")
_DIRECTION = re.compile(r"(左|右)(?:手边|边|面|侧|手旁|手侧|手|方|前方|后方)")
_HOST_VIEW = re.compile(r"(?:你|您|豆姐|主播)(?:自己的?|的)?(?:这边|那边|角度|视角|方向|位置)?(?:来看|看去|看过去|看)?[，,、]?$")
_WEARING = re.compile(r"穿搭|打扮|穿(?:的|着|了|啥|什么|的是)|[一这那]身|衣服|服装|配饰|搭配|穿戴")
_OVERVIEW = re.compile(r"桌(?:面|子?上|前)(?:都有|还有|摆着|摆了|放着|放了|有|的)*(?:什么|啥|几样|哪些|摆件|宝贝)|(?:有什么|有哪些|摆了什么).{0,4}(?:摆件|模型|道具)|"
                       r"(?:摆件|模型|道具|家当|藏品)(?:都|还)?(?:有哪些|有什么|有啥|哪几|几[样个]|是(?:什么|啥))|(?:这|那)[个件些两俩]*模型(?:是|都)?(?:什么|啥)")
_SINGLE_UNNAMED = re.compile(r"[那这][个件台只](?:模型|摆件|道具)(?:是|叫|在)?(?:什么|啥|哪)")
_TASTE = re.compile(r"(?:你|您|豆姐|主播).{0,5}(?:喜欢|最爱).{0,6}(?:贵|奢侈)|(?:贵重|奢侈).{0,6}(?:你|豆姐).{0,3}(?:喜欢|最爱)")
_UNLISTED = re.compile(r"手表|腕表|项链|手链|耳环|眼镜|帽子|戒指|耳机|平板|鼠标|音箱|音响|香水|口红|杯子|水杯|时钟|高跟鞋|运动鞋|皮靴")
_TEMP_GIFTS = re.compile(r"玫瑰|加油鸭|棒棒糖|荧光棒|啤酒|跑车|礼花筒|浪漫花火|小心心")
_WALL_CLUE = re.compile(r"(?:身后|背后|后面|背景墙|上方|头顶).{0,12}(?:送礼|礼物|昵称|名字)|"
                        r"(?:身后|背后|后面|上方)(?:的|那块|那面|这块|这面|大|发光的)*(?:屏|墙|牌|板)")
_COMPUTER = re.compile(r"笔记本|电脑|键盘")
_DEVICE_OWNER = re.compile(r"[我他她](?:家|们|自己)?的?(?:那[台个张]|这[台个张])?(?:桌[子面上]|笔记本|电脑|键盘|苹果标)")
_DEVICE_IN_VIEW = re.compile(r"桌[上面]|桌子上|画面|镜头|直播间|[这那它](?:个|台|部)?(?:看着|看起来|(?:真的?)?是)|像.{0,5}(?:电脑|笔记本)")
_APPLE_MARK = re.compile(r"(?:苹果|apple)(?:的)?(?:logo|标志?|标识|图标)")


def _mentions(text):
    return [key for key, aliases in ALIASES.items() if any(alias in text for alias in aliases)]


_SHORT_DETAIL = re.compile(
    r"(?:的|是|有|在|什么|啥|哪一?|多少|几|有没有)*(?:牌子|牌|品牌|颜色|色|型号|款|代|材质|价格|尺寸|g|gb|寸|克|块钱|链接)"
    r"|(?:背面|后盖|包身|身上|正面|内屏|屏幕|键盘)(?:上|的)?(?:是|有|写的|写着|印着|朝|对着)(?:什么|啥|哪|谁)(?:标志?|logo|字母|[边面])?"
)
_COLOR_PREFIX = re.compile(r"^(?:莓红|银白|炭灰|米白|暖棕|焦糖|黄铜|红|黑|灰|白|棕|银)(?:色的?|的)?")
_ASK_COLOR = re.compile(r"颜色|什么色|啥色")
_ASK_LOCATION = re.compile(r"位置|(?:放|摆|搁)?在哪(?![家里儿]?买)|放在什么地方|摆在什么地方")
_ASK_SCREEN = re.compile(r"(?:屏幕|内屏|屏).{0,4}(?:朝|向|对着|呢|哪边|哪面)")
_ASK_POSE = re.compile(r"(?:怎么|咋)[摆放折]|[摆放]成什么样|摆法|摆放姿势")


def _short_item_question(text, ids):
    """A bare '手机什么牌子' points to a prop. A story containing the same noun does not."""
    compact = _COLOR_PREFIX.sub("", text.strip("?!？！。～~"))
    for key in ids:
        for alias in ALIASES[key]:
            if compact.startswith(alias):
                tail = compact[len(alias):]
                if not tail or _FOLLOW.fullmatch(tail) or _SHORT_DETAIL.fullmatch(tail.rstrip("的呀啊呢吗")):
                    return True
    return False


def _recent_subject(task, history):
    viewer = task.get("audience") or task.get("name")
    if not viewer:
        return None
    for row in reversed(list(history)[-8:]):
        if row.get("roomId") != task.get("roomId") or row.get("source") not in ("comment", "topic"):
            continue
        if (row.get("audience") or row.get("name")) != viewer:
            continue
        if row.get("at") and task.get("_stamp") and task["_stamp"] - row["at"] / 1000 > 300:
            return None
        if row.get("focusItem"):
            return row["focusItem"] if row["focusItem"] in ITEMS else None
        # Older archives carry spoken text. Use the name actually said on air, never the viewer's guess.
        spoken = _fold(row.get("text", ""))
        named = [key for key, item in ITEMS.items() if _fold(item["name"]) in spoken]
        # A previous model may have gone off-topic. Require the original question to point at the set.
        return named[0] if len(named) == 1 and room_reply(row, []) else None
    return None


def _side(text):
    match = _DIRECTION.search(text)
    if not match:
        return None
    left = match[1] == "左"
    # “你桌子左边” normally describes the screen. Explicit reference to the host's body flips it.
    if _HOST_VIEW.search(text[:match.start()]):
        left = not left
    return "left" if left else "right"


def _paired():
    return "，".join(f'画面{side}边是{ITEMS[FEATURED[key]]["name"]}' for side, key in (("左", "left"), ("右", "right"))) + "。"


def _where(key, brief=False):
    item = ITEMS[key]
    location = item["location"].replace("观众看过去，", "你画面里的")
    if brief:
        location = location.replace("你画面里的桌面", "画面").split("，")[0]
    return f'{item["name"]}在{location}'


def _color(key):
    item = ITEMS[key]
    if item["category"] == "outfit":
        return item["name"].partition("色")[0] + "色"
    visible = {"phone": "后盖是银白色", "microphone": "麦头是深色",
               "monitor": "深色屏，绿色波形", "lamp": "黄铜色灯架，暖色灯罩", "desk": "暖棕色"}
    return visible.get(key, "颜色从镜头里看不准")


def _requested_details(key, text):
    details = []
    if _ASK_LOCATION.search(text):
        details.append(_where(key, brief=True))
    if _ASK_COLOR.search(text):
        details.append(_color(key))
    if key == "phone":
        if _ASK_POSE.search(text):
            details.append("下半部平放，上半部掀起")
        if _ASK_SCREEN.search(text):
            details.append("内屏朝我")
        if re.search(r"标志|标识|logo|苹果标|什么标|啥标", text):
            details.append("后盖的苹果标朝镜头")
    return details


def _phone_display(text, reply):
    """Answer the particular visible detail the viewer pointed to."""
    phone = ITEMS["phone"]
    name = phone["name"]
    if "键盘" in text:
        return reply(f'{name}下半部平放在桌上，那也是内屏。', "掀起来的半边朝我，桌上没给它配实体键盘。", "phone",
                     short="平放的是内屏，没配实体键盘。")
    if _COMPUTER.search(text):
        return reply(f'桌上那台是我的{name}折叠手机。', "上半部沿水平铰链掀起来，换个姿势就被你升成电脑了？", "phone",
                     short=f'是折起来的{name}手机。')
    if _APPLE_MARK.search(text) or re.search(r"后盖|背面|标志|标识|(?:什么|啥)(?:标|logo)", text):
        return reply(f'看{name}的银白后盖，{phone["brand"]}标志就朝着镜头。', "我特意把这一面摆给你看，总算看见了？", "phone",
                     short=f'银白后盖上的{phone["brand"]}标志朝你。')
    if _ASK_SCREEN.search(text):
        return reply(f'{name}的内屏朝我。你看见的是银白后盖上的{phone["brand"]}标志。', "弹幕归我看，排场归你看。", "phone",
                     short="内屏朝我，背标朝你。")
    if _ASK_POSE.search(text):
        return reply(f'{name}下半部平放在桌上，上半部沿铰链掀起。', "内屏朝我，苹果标朝你，好东西哪能白摆？", "phone",
                     short="下半部平放，上半部掀起，内屏朝我。")
    return None


_STINGS = {
    "phone": ("银白后盖上的苹果标冲着镜头，我显摆还挑背光的角度？",
              "银白后盖给你看，内屏朝我，免得你偷瞄我看哪条弹幕。"),
    "scarf": ("红成这样还带着流苏，你总算舍得从弹幕上抬眼了。",
              "把流苏理好我才开麦，免得你光盯着线头忘了听。"),
    "coat": ("这身黑色长袖压得住场，尤其压得住乱点评的。",),
    "skirt": ("你若连裙摆的褶子都敢数，那得给这张桌子查查视力。",),
    "socks": ("能猜中袜口的颜色算你有眼力，再往下编就露馅了。",),
    "shoes": ("圆头鞋面擦得发亮，可惜桌子不肯给它让镜头。",),
    "microphone": ("深色麦头配金属环，我一开口，你那点嘀咕能盖过我？",),
    "monitor": ("绿线是声音的波形，我一开麦，它可比你反应快。",),
    "mixer": ("那排滑杆调的是声音，你的意见哪根也管不着。",),
    "lamp": ("黄铜灯架托着暖色灯罩，这盏灯比你先找到我的好角度。",),
    "window": ("楼里的灯都亮了，你要赏月，眼神可得从我这儿挪开。",),
    "gift_wall": ("你看最近三笔，谁送了什么、送了多少，都在上面。",),
    "desk": ("暖棕木纹配金属桌沿，比起敲桌子，我更爱敲打嘴硬的。",),
}


def room_reply(task, history, *, brief=False):
    """Resolve a question about this set, or return None so ordinary banter takes its normal route."""
    def reply(line, sting="", focus=None, *, short=None):
        if brief:
            line, sting = short or line, ""
        rows = [{"text": line, "expression": "smirk", "gesture": "look", "pauseMs": 75 if sting else 0}]
        if sting:
            rows.append({"text": sting, "expression": "skeptical", "gesture": "point", "pauseMs": 0})
        if focus in ITEMS:
            for row in rows:
                row["focusItem"] = focus
        return rows

    text = _fold(task.get("prompt") or "").strip(" ，,。")
    if not text or task.get("source") not in ("comment", "topic"):
        return None
    is_set = bool(_SET.search(text))
    if _OWN.search(text) or _DEVICE_OWNER.search(text) or _SCENE_ASIDE.search(text) or _TROUBLE.search(text):
        if not re.search(r"(?:你桌|豆姐的桌|镜头里|画面上)", text):
            return None

    ids = _mentions(text)
    if _SET_BAG.search(_OTHER_BAG.sub("", text)):
        return reply("桌上的包已经撤了。", "右边现在是波形小监视器，那条绿线才是今天的值班员。")
    if ("gift_wall" in ids or _WALL_CLUE.search(text)) and not _OWN.search(text):
        return reply("礼物墙在我身后上方。", "最近三笔是谁送的、什么礼物、多少份，看这里就行。",
                     "gift_wall", short="我身后，上面记着最近三笔礼物。")
    pointed = _POINTED_ITEM.search(text) or _PLACED_ITEM.search(text) or _short_item_question(text, ids)
    if not ids and (is_set or _QUESTION.search(text)):
        for clue, item_id in ((r"(?:你|主播|豆姐)的?(?:脖子|颈)(?:上|那|间)|脖子上[那这]条", "scarf"),
                              (r"(?:你|主播|豆姐)的?脚上(?:穿|那|是)", "shoes"),
                              (r"绿色(?:的)?波形|绿线.{0,6}(?:动|跳)|跳动.{0,3}(?:小)?屏", "monitor"),
                              (r"左后(?:方|面).{0,6}(?:亮|发光|灯)", "lamp")):
            if re.search(clue, text):
                ids = [item_id]
                pointed = True
                break
    # A desk reference can describe another item's location.
    if "desk" in ids and len(ids) > 1:
        ids.remove("desk")
    side = _side(text)
    question = _QUESTION.search(text)
    follow = _FOLLOW.fullmatch(text)
    pointed_side = bool(side and _SIDE_OBJECT.search(text))
    if not ids or ids == ["desk"]:
        if _COMPUTER.search(text) and (pointed_side or _DEVICE_IN_VIEW.search(text)):
            ids = [FEATURED[side] if side else "phone"]
            pointed = True
        elif _APPLE_MARK.search(text) and re.search(r"哪|朝|对着|位置|后盖|背面", text):
            ids = ["phone"]
            pointed = True
    garments = [key for key, item in ITEMS.items() if item["category"] == "outfit"]
    mentioned_garments = [key for key in ids if key in garments]
    if pointed and len(mentioned_garments) == 1 and re.search(r"什么牌|啥牌|品牌|牌子|(?:是|印着|印了|有)(?:lv|路易威登)", text):
        item = ITEMS[mentioned_garments[0]]
        return reply(f'我这件是{item["name"]}。', "镜头里看得见颜色，看不见牌子。别替我往衣服上缝标。",
                     mentioned_garments[0], short="衣服上看不见牌子。")
    if not ids and _TASTE.search(text):
        return reply("喜欢贵的，还得挑我看得上眼的。", "你替我操心价钱，是打算排队结账？")
    if _TEMP_GIFTS.search(text) and re.search(r"常驻|摆件|一直摆|一直放|桌上的礼物", text) and question and not any(k != "desk" for k in ids):
        return reply("礼物有自己的出场时间。", "谢幕就该下场，你还想给它办个常住证？")
    if not ids and (_VISIBLE.search(text) or re.search(r"你[的这那戴穿]", text)) and _UNLISTED.search(text) and question:
        unlisted = _UNLISTED.search(text)[0]
        return reply(f"我可没说镜头里有{unlisted}。", "给个位置，别拿你自己脑补的来考我。")
    if not ids and _WEARING.search(text) and re.search(r"(?:你|您|豆姐|主播)(?:今天|现在|的|今日)?(?:这身|那身|穿|的穿搭|的衣服|的服装|衣服|打扮|怎么搭配)|^(?:这身|这套)(?:衣服|穿搭|搭配)", text):
        hidden = "、".join(ITEMS[key]["name"] for key in ("skirt", "socks", "shoes"))
        return reply(f'上镜的是{ITEMS["scarf"]["name"]}配{ITEMS["coat"]["name"]}。',
                      f'{hidden}都在桌后，别说你看全了。')
    directions = {match[1] for match in _DIRECTION.finditer(text)}
    both_sides = len(directions) == 2 or re.search(r"左右(?:两[边侧]|[边侧]|分别)|两[侧边]", text)
    unselected = not ids or ids == ["desk"]
    if unselected and not side and _SINGLE_UNNAMED.search(text):
        prior = _recent_subject(task, history)
        if not prior:
            return reply("你指的是哪一件？给我个位置。", "报左还是右就行，你那根手指可没伸进镜头。", short="你指哪件，左边还是右边？")
        ids, pointed, unselected = [prior], True, False
    overview = (_OVERVIEW.search(text) and not side
                and (_VISIBLE.search(text) or re.search(r"摆件|道具|家当|藏品|[这那][个些两件]*模型", text)))
    asking_both = both_sides and question and (pointed_side or _VISIBLE.search(text))
    if (unselected and (overview or asking_both)) or (set(FEATURED.values()).issubset(ids) and pointed):
        if _PRICE.search(text):
            return reply(_paired(), "两件我都肯给你看，小票可没挂在桌沿上。", short="这两件，我都没报过价。")
        if _ASK_COLOR.search(text) and (both_sides or re.search(r"分别|各自|各是|各在|都是", text)):
            phone, monitor = FEATURED["left"], FEATURED["right"]
            return reply(f'左边的{ITEMS[phone]["name"]}，{_color(phone)}。',
                         f'右边的{ITEMS[monitor]["name"]}，{_color(monitor)}。',
                         short=f'左边手机{_color(phone)}，右边{_color(monitor)}。')
        if "直播间" in text and re.search(r"模型|布景|道具", text):
            return reply(_paired(), f'脖子上是{ITEMS["scarf"]["name"]}，身后是礼物墙和{ITEMS["window"]["name"]}。')
        if re.search(r"都有什么|还有什么|还有啥|都有哪些|有哪些设备", text):
            return reply(_paired(), f'正中是{ITEMS["mixer"]["name"]}，左边伸过来的是我的麦。')
        return reply(_paired(), "我就是故意分开放。你看完这边，还得回头看那边。")
    if follow and not ids and not side:
        prior = _recent_subject(task, history)
        if not prior:
            return None
        if "另一" in text or "另外一" in text:
            opposite = next((key for key in FEATURED.values() if key != prior), None)
            if prior not in FEATURED.values() or opposite is None:
                return None
            ids = [opposite]
        else:
            ids = [prior]
        pointed = True
    if pointed_side and (not ids or ids == ["desk"]):
        ids = [FEATURED[side]]
    if not ids or not (pointed or pointed_side or side and _SIDE_ITEM.search(text)):
        return None
    key = ids[0]
    item = ITEMS[key]
    if len(ids) > 1:
        if len(ids) == 2:
            return reply(_where(ids[0]) + "。", _where(ids[1]) + "。",
                         short="，".join(_where(k, brief=True) for k in ids) + "。")
        positions = [_where(k, brief=True) for k in ids[:4]]
        lead = "先给你指四件，" if len(ids) > 4 else ""
        return reply(lead + "，".join(positions[:2]) + "。", "，".join(positions[2:]) + "。",
                     short="，".join(positions) + "。")
    if re.search(r"[，,、；;]|以及|还有|分别|和|还想|顺便", text) or len(_QUESTION.findall(text.rstrip("?？"))) >= 2:
        details = _requested_details(key, text)
        if len(details) > 1:
            return reply(details[0] + "。", "，".join(details[1:]) + "。", key,
                         short="，".join(details) + "。")
    if item.get("brand") and re.search(r"什么牌|啥牌|品牌|牌子", text):
        return reply(f'{item["brand"]}的{item["name"]}，{item["location"]}。', "名字给你报清了，这回眼神跟上。", key,
                     short=f'{item["brand"]}的。')
    if _PRICE.search(text):
        return reply(f'你问{item["name"]}？我可没报过价。', "看个直播还兼职给我做账？算盘先收了。", key,
                     short="这件我可没报过价。")
    if key == "phone" and _COMPUTER.search(text):
        return _phone_display(text, reply)
    if _AUTH.search(text):
        return reply(f'{item["name"]}是我直播间里的模型。', "隔着屏幕还想让我给你开鉴定书？眼力可以，业务别越界。", key,
                     short="直播间里的模型，隔屏可鉴不了真。")
    if _ORIGIN.search(text):
        return reply(f'问我的{item["name"]}？小票我可没摆出来。', "眼光可以借，购物车别推到我台上。", key,
                     short="小票没摆，我没说过在哪买。")
    if _SPEC.search(text):
        if key == "phone" and re.search(r"型号|哪款|哪一款|什么款", text):
            return reply(f'型号是{item["name"]}。{item["location"]}。', "展开给你认了，这回别念错。", key,
                         short=f'型号是{item["name"]}。')
        return reply(f'镜头里能认出{item["name"]}，这我敢说。', "再细的规格瞧不见，别指望我张嘴替它编说明书。", key,
                     short="这规格从镜头里瞧不出来。")
    if key == "phone":
        detail = _phone_display(text, reply)
        if detail:
            return detail
    if brief and _ASK_COLOR.search(text):
        return reply(_color(key) + "。", focus=key)
    options = _STINGS.get(key, (item["appearance"] + "。",))
    recently_said = "".join(r.get("text", "") for r in list(history)[-3:])
    sting = next((line for line in options if line not in recently_said), options[0])
    return reply(_where(key) + "。", sting, key, short=_where(key, brief=True) + "。")
