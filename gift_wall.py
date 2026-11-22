"""Three recent gift entries for a studio wall, independent of the spoken queue."""
from gift_rules import gift_merge_key


def place_gift(entries, row, captured, delta):
    name = row.get("giftName", "").strip() or "礼物"
    viewer = row.get("_viewer") or row.get("nickname")
    combo = row.get("_combo") or None
    count = row.get("displayCount", 1)
    entry = {"eventId": row["eventId"], "nickname": row.get("nickname", ""), "giftName": name, "count": count,
             "_viewer": viewer, "_combo": combo, "_captured": captured, "_archiveId": row["archiveId"],
             "_counted": "displayCount" in row}
    if delta < count:
        # A rising counter is one send. Two separate single roses remain two sends.
        for old in entries:
            if (old["_viewer"] == viewer and old["_combo"] == combo and
                    gift_merge_key(old["giftName"]) == gift_merge_key(name)):
                entries.remove(old)
                break
    entries.append(entry)
    entries.sort(key=lambda item: (item["_captured"], item["_archiveId"]), reverse=True)
    del entries[3:]
