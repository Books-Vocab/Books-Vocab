"""`ops/podcast_preview_backfill.py` 的純函式契約。

這支工具改動的是**已發布、已被裝置同步過**的 series，所以它的正確性標準不是
「S3 上的位元組對不對」，而是「已安裝的客戶端會不會看到這個改動」。

2026-08-06 之前它兩件事都沒做：不 bump `updatedAt`、不動 `index.json`。理由是
preview 欄位住在 episode 陣列裡，而 series-list 會把 episodes 剝掉，所以「catalog
不受影響」。那個推論在 iOS 開始**用 catalog 指紋做快取**的那天失效——清單上沒有
任何差異 = 客戶端永遠不會重抓 detail = 回填的 preview 永遠到不了裝置，而那正是
這支工具存在的全部理由。

這裡釘住的就是那條訊號鏈。
"""

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "podcast_preview_backfill.py"


def _load():
    spec = importlib.util.spec_from_file_location("podcast_preview_backfill", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


def _meta(updated="2026-04-14T03:07:11+00:00", episodes=2):
    return {
        "id": "s1",
        "title": "S1",
        "createdAt": "2026-01-01T00:00:00+00:00",
        "updatedAt": updated,
        "episodes": [
            {"episodeNumber": n, "title": f"ep{n}", "previewAvailable": False}
            for n in range(1, episodes + 1)
        ],
    }


class TestPatchPreviewMeta:
    def test_sets_preview_fields_on_episode_one_only(self):
        out = mod.patch_preview_meta(_meta(), duration_sec=180, stamp="NEW")
        assert out["episodes"][0]["previewAvailable"] is True
        assert out["episodes"][0]["previewDurationSec"] == 180
        assert out["episodes"][1]["previewAvailable"] is False

    def test_bumps_updated_at(self):
        """沒有這個 bump，回填的 preview 對已安裝的裝置永遠不存在。"""
        out = mod.patch_preview_meta(_meta(updated="OLD"), duration_sec=180, stamp="NEW")
        assert out["updatedAt"] == "NEW"

    def test_preserves_everything_else_verbatim(self):
        src = _meta()
        out = mod.patch_preview_meta(src, duration_sec=180, stamp="NEW")
        assert out["createdAt"] == src["createdAt"]
        assert out["id"] == src["id"]
        assert out["title"] == src["title"]
        assert len(out["episodes"]) == len(src["episodes"])

    def test_does_not_mutate_the_input(self):
        src = _meta(updated="OLD")
        mod.patch_preview_meta(src, duration_sec=180, stamp="NEW")
        assert src["updatedAt"] == "OLD"
        assert src["episodes"][0]["previewAvailable"] is False

    def test_raises_when_episode_one_is_absent(self):
        src = _meta()
        src["episodes"] = [{"episodeNumber": 2, "title": "ep2"}]
        with pytest.raises(ValueError, match="no episode 1"):
            mod.patch_preview_meta(src, duration_sec=180, stamp="NEW")


class TestPatchIndexStamp:
    def test_patches_only_the_target_entry(self):
        index = [
            {"id": "other", "updatedAt": "KEEP", "episodeCount": 3},
            {"id": "s1", "updatedAt": "OLD", "episodeCount": 2},
        ]
        out, changed = mod.patch_index_stamp(index, series_id="s1", stamp="NEW")
        assert changed is True
        assert out[1]["updatedAt"] == "NEW"
        assert out[0] == {"id": "other", "updatedAt": "KEEP", "episodeCount": 3}

    def test_leaves_other_fields_of_the_target_alone(self):
        index = [{"id": "s1", "updatedAt": "OLD", "coverImageURL": "/c", "episodeCount": 2}]
        out, _ = mod.patch_index_stamp(index, series_id="s1", stamp="NEW")
        assert out[0]["coverImageURL"] == "/c"
        assert out[0]["episodeCount"] == 2

    def test_does_not_mutate_the_input(self):
        index = [{"id": "s1", "updatedAt": "OLD"}]
        mod.patch_index_stamp(index, series_id="s1", stamp="NEW")
        assert index[0]["updatedAt"] == "OLD"

    def test_reports_missing_entry_rather_than_inventing_one(self):
        """metadata 有、index 沒有 = 真的不一致。憑殘缺資料補一筆會讓 catalog
        多出一個沒人驗過的 series，比誠實回報 False 危險得多。"""
        index = [{"id": "other", "updatedAt": "KEEP"}]
        out, changed = mod.patch_index_stamp(index, series_id="s1", stamp="NEW")
        assert changed is False
        assert out == index

    def test_tolerates_non_dict_entries(self):
        index = ["garbage", {"id": "s1", "updatedAt": "OLD"}]
        out, changed = mod.patch_index_stamp(index, series_id="s1", stamp="NEW")
        assert changed is True
        assert out[0] == "garbage"


class TestUtcStamp:
    def test_shape_matches_what_the_publisher_writes(self):
        stamp = mod.utc_stamp()
        # 2026-08-06T05:12:33+00:00 — 秒精度、帶 UTC offset，與 index.json 現有值同形。
        assert stamp.endswith("+00:00")
        assert "T" in stamp
        assert "." not in stamp, "小數秒會讓指紋比對多一個無謂的變異來源"


class TestIndexNeedsStamp:
    """`already` 短路的判準。少了這一條，舊版工具回填過的整批 series 永遠拿不到
    index bump —— 而那正是這支工具服務的全部人口。"""

    def test_stale_index_entry_is_reported(self):
        meta = _meta(updated="NEW")
        index = [{"id": "s1", "updatedAt": "OLD"}]
        assert mod.index_needs_stamp(index, series_id="s1", meta=meta) is True

    def test_matching_stamp_is_not_reported(self):
        meta = _meta(updated="SAME")
        index = [{"id": "s1", "updatedAt": "SAME"}]
        assert mod.index_needs_stamp(index, series_id="s1", meta=meta) is False

    def test_absent_entry_is_not_a_repairable_state(self):
        """憑殘缺資料補一筆 catalog entry，比留著陳舊時戳危險。"""
        meta = _meta(updated="NEW")
        assert mod.index_needs_stamp([{"id": "other"}], series_id="s1", meta=meta) is False

    def test_malformed_index_is_not_a_repairable_state(self):
        meta = _meta(updated="NEW")
        assert mod.index_needs_stamp(None, series_id="s1", meta=meta) is False
        assert mod.index_needs_stamp({"not": "a list"}, series_id="s1", meta=meta) is False

    def test_metadata_without_a_stamp_cannot_drive_a_repair(self):
        meta = _meta()
        del meta["updatedAt"]
        assert mod.index_needs_stamp([{"id": "s1", "updatedAt": "OLD"}], series_id="s1", meta=meta) is False
