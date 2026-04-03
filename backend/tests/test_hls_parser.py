"""Tests for HLS M3U8 parser."""

from app.services.hls_parser import (
    detect_hls,
    detect_segment,
    is_master_playlist,
    parse_master,
    parse_media,
)

MASTER_PLAYLIST = """\
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080,CODECS="avc1.64001f,mp4a.40.2",FRAME-RATE=29.97
1080p/playlist.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1280x720,CODECS="avc1.640020,mp4a.40.2"
720p/playlist.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=854x480,CODECS="avc1.42c01e,mp4a.40.2"
480p/playlist.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
360p/playlist.m3u8
"""

MEDIA_PLAYLIST = """\
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:100
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXTINF:5.005,
segment100.ts
#EXTINF:5.005,
segment101.ts
#EXTINF:4.838,Title Here
segment102.ts
#EXT-X-DISCONTINUITY
#EXTINF:6.006,
segment103.ts
#EXT-X-ENDLIST
"""


class TestMasterPlaylist:
    def test_detect_master(self):
        assert is_master_playlist(MASTER_PLAYLIST)
        assert not is_master_playlist(MEDIA_PLAYLIST)

    def test_parse_variants(self):
        result = parse_master(MASTER_PLAYLIST)
        assert len(result.variants) == 4
        assert result.version == 3

    def test_variants_sorted_by_bandwidth(self):
        result = parse_master(MASTER_PLAYLIST)
        bandwidths = [v.bandwidth for v in result.variants]
        assert bandwidths == sorted(bandwidths, reverse=True)

    def test_variant_details(self):
        result = parse_master(MASTER_PLAYLIST)
        top = result.variants[0]
        assert top.bandwidth == 6000000
        assert top.resolution == "1920x1080"
        assert "avc1" in top.codecs
        assert top.frame_rate == 29.97
        assert top.uri == "1080p/playlist.m3u8"

    def test_variant_without_optional_attrs(self):
        result = parse_master(MASTER_PLAYLIST)
        low = result.variants[-1]  # 360p
        assert low.bandwidth == 800000
        assert low.resolution == "640x360"
        assert low.codecs == ""
        assert low.frame_rate is None

    def test_base_url_resolution(self):
        result = parse_master(
            MASTER_PLAYLIST,
            base_url="https://cdn.example.com/live/",
        )
        assert result.variants[0].uri == "https://cdn.example.com/live/1080p/playlist.m3u8"


class TestMediaPlaylist:
    def test_parse_segments(self):
        result = parse_media(MEDIA_PLAYLIST)
        assert len(result.segments) == 4
        assert result.target_duration == 6
        assert result.media_sequence == 100
        assert result.is_endlist
        assert result.playlist_type == "VOD"

    def test_segment_sequence(self):
        result = parse_media(MEDIA_PLAYLIST)
        sequences = [s.sequence for s in result.segments]
        assert sequences == [100, 101, 102, 103]

    def test_segment_duration(self):
        result = parse_media(MEDIA_PLAYLIST)
        assert result.segments[0].duration == 5.005
        assert result.segments[3].duration == 6.006

    def test_total_duration(self):
        result = parse_media(MEDIA_PLAYLIST)
        assert abs(result.total_duration - (5.005 + 5.005 + 4.838 + 6.006)) < 0.001

    def test_discontinuity(self):
        result = parse_media(MEDIA_PLAYLIST)
        assert not result.segments[2].discontinuity
        assert result.segments[3].discontinuity

    def test_encryption(self):
        result = parse_media(MEDIA_PLAYLIST)
        assert result.segments[0].key_method == "AES-128"
        assert result.segments[0].key_uri == "key.bin"

    def test_segment_title(self):
        result = parse_media(MEDIA_PLAYLIST)
        assert result.segments[2].title == "Title Here"

    def test_base_url_resolution(self):
        result = parse_media(
            MEDIA_PLAYLIST,
            base_url="https://cdn.example.com/1080p/",
        )
        assert result.segments[0].uri == "https://cdn.example.com/1080p/segment100.ts"


class TestDetection:
    def test_detect_hls_by_content_type(self):
        assert detect_hls("foo", "application/vnd.apple.mpegurl")
        assert detect_hls("foo", "application/x-mpegURL")
        assert not detect_hls("foo", "text/html")

    def test_detect_hls_by_url(self):
        assert detect_hls("https://cdn.example.com/live/index.m3u8", "")
        assert detect_hls("https://cdn.example.com/live/index.m3u8?token=abc", "")
        assert not detect_hls("https://cdn.example.com/video.mp4", "")

    def test_detect_segment_by_url(self):
        assert detect_segment("https://cdn.example.com/seg001.ts", "")
        assert detect_segment("https://cdn.example.com/chunk_001.m4s", "")
        assert not detect_segment("https://cdn.example.com/index.m3u8", "")

    def test_detect_segment_by_content_type(self):
        assert detect_segment("foo", "video/mp2t")
        assert detect_segment("foo", "video/mp4")
