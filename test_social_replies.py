from unittest import TestCase
from unittest.mock import patch

from server import CROWD_GAP, Scheduler, validate
from social_replies import social_beat


class SocialRepliesTest(TestCase):
    def test_recent_lines_are_scoped_to_room_and_event_type(self):
        task = {"source": "follow", "roomId": "A"}
        with patch("social_replies.random.choice", side_effect=lambda options: options[0]):
            first = social_beat(task, [])["text"]
            other_room = {**task, "roomId": "B", "text": first}
            other_kind = {**task, "source": "comment", "text": first}
            self.assertEqual(social_beat(task, [other_room, other_kind])["text"], first)
            self.assertNotEqual(social_beat(task, [], {**task, "text": first})["text"], first)

    def test_each_kind_rotates_on_air_but_a_merged_notification_keeps_its_line(self):
        studio = Scheduler()
        self.addCleanup(studio.close)

        def ingest(kind, number):
            studio.ingest(validate({"roomId": "A", "eventId": f"{kind}-{number}", "type": kind,
                                    "actor": {"nickname": f"观众{number}"}, "data": {}}))

        def current():
            with studio.cv:
                self.assertTrue(studio.cv.wait_for(lambda: studio.active is not None, 2))
                return studio.state(stage=True)["active"]

        def finish(cue):
            for phase in ("start", "segment", "complete"):
                self.assertTrue(studio.playback({"id": cue["id"], "player": "test-stage",
                                                 "phase": phase, "index": 0}))

        with patch.dict(CROWD_GAP, follow=0, fans_club_join=0):
            for kind in ("follow", "fans_club_join"):
                ingest(kind, 0)
                first = current()
                ingest(kind, 1)
                queued = studio.state()["queue"][0]
                ingest(kind, 2)
                self.assertEqual(studio.state()["queue"], [queued])
                finish(first)
                second = current()
                self.assertEqual((second["id"], second["text"]), (queued["id"], queued["text"]))
                self.assertNotEqual(first["text"], second["text"])
                finish(second)
                heard = [first["text"], second["text"]]
                for i in range(3, 15):
                    ingest(kind, i)
                    cue = current()
                    self.assertEqual(len(cue["segments"]), 1)
                    self.assertNotIn(cue["text"], heard[-5:])
                    heard.append(cue["text"])
                    finish(cue)
                self.assertEqual(len(set(heard[:8])), 8)
