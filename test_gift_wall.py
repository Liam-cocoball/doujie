import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from server import Scheduler, validate
from studio_store import StudioStore


class GiftWallTest(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "booth.sqlite3"
        self.start = datetime.now(timezone.utc)
        self.open()

    def open(self):
        self.studio = Scheduler(data_path=self.path)
        self.studio.dialogue.configure("", None)
        self.addCleanup(self.studio.close)

    def gift(self, n, nick, gift="玫瑰", count=1, *, room="A", combo=None, age=None):
        data = {"giftName": gift, "displayCount": count}
        if combo is not None:
            data["comboId"] = combo
        return {"roomId": room, "eventId": str(n), "type": "gift", "actor": {"nickname": nick, "userId": nick},
                "capturedAt": (self.start + timedelta(seconds=n if age is None else age)).isoformat(), "data": data}

    def send(self, *rows):
        self.studio.ingest(validate(list(rows)))

    def state(self):
        return self.studio.state(stage=True)

    def test_unspecialized_gifts_use_the_same_effect_and_keep_their_own_acknowledgements(self):
        gifts = [("阿梨", "新来的星星", 2), ("团子", "天鹅之梦", 3), ("小林", "嘉年华", 4)]
        self.send(*(self.gift(i, who, gift, count) for i, (who, gift, count) in enumerate(gifts, 1)))
        state = self.studio.state()
        self.assertEqual([(fx["nickname"], fx["giftName"], fx["count"], fx["effect"]) for fx in state["giftEffects"]],
                         [(*gift, "generic") for gift in gifts])
        self.assertEqual([(row["nickname"], row["giftName"], row["count"]) for row in state["giftWall"]],
                         gifts[::-1])
        cues = state["queue"] + ([state["active"]] if state["active"] else [])
        by_gift = {cue["giftName"]: cue for cue in cues}
        for who, gift, count in gifts:
            cue = by_gift[gift]
            self.assertEqual((cue["effect"], cue["giftFx"]), ("generic", "generic"))
            opener = cue["segments"][0]["text"]
            self.assertIn(who, opener)
            self.assertIn(f"{count}份{gift}", opener)
            self.assertRegex(opener, r"谢谢|谢了|谢啦")

    def test_three_recent_entries_keep_distinct_senders_and_one_cumulative_combo(self):
        self.assertEqual(self.state()["giftWall"], [])
        one = self.gift(1, "团子", combo="原始分组")
        self.send(one, one, self.gift(2, "团子", count=3, combo="原始分组"), self.gift(3, "小林", "跑车"))
        self.send(self.gift(4, "团子", count=5, combo="原始分组"), self.gift(5, "阿梨", "棒棒糖"))
        self.send(self.gift(6, "团子", count=3, combo="原始分组", age=2))
        state = self.state()
        wall = state["giftWall"]
        self.assertEqual([(r["nickname"], r["giftName"], r["count"]) for r in wall],
                         [("阿梨", "棒棒糖", 1), ("团子", "玫瑰", 5), ("小林", "跑车", 1)])
        for entry in wall:
            self.assertEqual(set(entry), {"eventId", "nickname", "giftName", "count"})
        self.assertNotIn("原始分组", json.dumps(state, ensure_ascii=False))
        self.assertEqual(len(state["giftEffects"]), 5)
        self.studio.close()
        self.open()
        self.assertEqual(self.state()["giftWall"], wall)
        self.assertEqual(self.state()["giftEffects"], [])
        self.send(self.gift(7, "团子", count=5, combo="原始分组"))
        self.assertEqual(self.state()["giftWall"], wall)
        self.assertEqual(self.state()["giftEffects"], [])
        self.send(self.gift(8, "团子", count=7, combo="原始分组"))
        self.assertEqual(self.state()["giftWall"][0]["count"], 7)
        self.assertEqual(len(self.state()["giftWall"]), 3)

    def test_rooms_manual_mode_and_stop_keep_wall_separate_from_speech_and_effects(self):
        self.studio.control({"action": "auto", "enabled": False})
        self.send(self.gift(1, "小林"), self.gift(2, "小林"))
        self.assertEqual(len(self.state()["giftWall"]), 2)
        self.assertEqual(len(self.state()["giftEffects"]), 2)
        self.assertIsNone(self.state()["active"])
        self.send({"roomId": "B", "eventId": "intro", "type": "comment", "data": {"content": "你好"}})
        self.assertEqual(self.state()["giftWall"], [])
        self.assertEqual(self.state()["giftEffects"], [])
        self.studio.control({"action": "stop"})
        self.send(self.gift(3, "", room="B"))
        self.assertEqual(self.state()["giftWall"][0]["nickname"], "")
        self.assertEqual(self.state()["giftEffects"], [])
        self.send({"roomId": "A", "eventId": "back", "type": "room_join"})
        self.assertEqual([r["eventId"] for r in self.state()["giftWall"]], ["2", "1"])

    def test_first_upgrade_can_recover_gifts_buried_under_old_comments(self):
        self.studio.close()
        store = StudioStore(self.path)
        try:
            with store.db:
                for n in range(1, 85):
                    row = {"roomId": "A", "eventId": str(n), "type": "gift" if n < 4 else "comment",
                           "capturedAt": n * 1000, "nickname": "小鱼"}
                    if n < 4:
                        row.update(giftName="玫瑰", displayCount=n)
                    else:
                        row["content"] = "你好"
                    store.insert_event(row)
        finally:
            store.db.close()
        self.open()
        self.assertEqual(self.state()["giftWall"], [{"nickname": "小鱼", "count": 3, "giftName": "玫瑰", "eventId": "3"}])
        self.assertEqual(self.state()["giftEffects"], [])
