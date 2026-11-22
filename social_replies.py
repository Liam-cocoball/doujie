"""Short spoken reactions to follows and fan club arrivals."""
import random

from host_dialogue import beat


_LINES = {
    "follow": (
        ("关注收了，眼光过关。", "smirk", "nod"),
        ("这手指有主见，我欣赏。", "smirk", "point"),
        ("关注键你管，麦克风我管。", "deadpan", "look"),
        ("哟，被我这张嘴圈住了？", "skeptical", "lean"),
        ("关注了还想看甜妹？你这手点偏了。", "grumpy", "shrug"),
        ("敢把我放进关注列表，有胆。", "skeptical", "nod"),
        ("你点得倒快，我还没开始摆架子呢。", "smirk", "wave"),
        ("行，下回迷路，顺着关注摸回来。", "deadpan", "point"),
    ),
    "fans_club_join": (
        ("团员证收好，免怼券可没发。", "smirk", "point"),
        ("新团员，前排有座，麦归我。", "deadpan", "wave"),
        ("这就入团了？面试官都没来得及摆谱。", "skeptical", "lean"),
        ("团规就一条，我翻白眼的时候别抢镜。", "grumpy", "look"),
        ("进团就想当团宠？那位子我坐着呢。", "smirk", "shrug"),
        ("入团申请我批了，夸我的稿子自己写。", "deadpan", "nod"),
        ("哟，团里又来了个敢接我话茬的。", "skeptical", "wave"),
        ("团牌挂稳了，我嘴上可没刹车。", "smirk", "lean"),
    ),
}


def social_beat(task, history, active=None):
    if task.get("segments"):
        return task["segments"][0]  # Several notifications can share one queued cue.
    options = _LINES[task["source"]]
    heard = [row.get("text") for row in (*history, active)
             if row and row.get("roomId") == task["roomId"] and row.get("source") == task["source"]]
    unused = [line for line in options if line[0] not in heard]
    choices = unused or [line for line in options if line[0] not in heard[-5:]]
    return beat(*random.choice(choices))
