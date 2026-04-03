"""Tests for DASH MPD parser."""

from app.services.dash_parser import (
    _parse_duration,
    detect_dash,
    parse_mpd,
)

MPD_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"
     type="static"
     minBufferTime="PT2S"
     mediaPresentationDuration="PT1H30M45.5S">
  <BaseURL>https://cdn.example.com/dash/</BaseURL>
  <Period id="1" duration="PT1H30M45.5S">
    <AdaptationSet id="0" contentType="video" mimeType="video/mp4" codecs="avc1.64001f">
      <SegmentTemplate media="video/$RepresentationID$/$Number$.m4s"
                       initialization="video/$RepresentationID$/init.mp4"
                       timescale="90000"
                       duration="540000"
                       startNumber="1"/>
      <Representation id="1080p" bandwidth="6000000" width="1920" height="1080" frameRate="30000/1001"/>
      <Representation id="720p" bandwidth="3000000" width="1280" height="720" frameRate="30"/>
      <Representation id="480p" bandwidth="1500000" width="854" height="480"/>
      <Representation id="360p" bandwidth="800000" width="640" height="360"/>
    </AdaptationSet>
    <AdaptationSet id="1" contentType="audio" mimeType="audio/mp4" codecs="mp4a.40.2">
      <SegmentTemplate media="audio/$RepresentationID$/$Number$.m4s"
                       initialization="audio/$RepresentationID$/init.mp4"
                       timescale="44100"
                       duration="176400"
                       startNumber="1"/>
      <Representation id="audio_128k" bandwidth="128000"/>
      <Representation id="audio_64k" bandwidth="64000"/>
    </AdaptationSet>
  </Period>
</MPD>
"""

LIVE_MPD = """\
<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="dynamic" minBufferTime="PT4S">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <Representation id="v1" bandwidth="5000000" width="1920" height="1080"/>
    </AdaptationSet>
  </Period>
</MPD>
"""


class TestParseDuration:
    def test_full_duration(self):
        assert _parse_duration("PT1H30M45.5S") == 5445.5

    def test_minutes_seconds(self):
        assert _parse_duration("PT2M30S") == 150.0

    def test_seconds_only(self):
        assert _parse_duration("PT6S") == 6.0

    def test_hours_only(self):
        assert _parse_duration("PT2H") == 7200.0

    def test_empty(self):
        assert _parse_duration("") == 0

    def test_invalid(self):
        assert _parse_duration("not-a-duration") == 0


class TestParseMPD:
    def test_basic_structure(self):
        manifest = parse_mpd(MPD_MANIFEST)
        assert manifest.type == "static"
        assert manifest.min_buffer_time_secs == 2.0
        assert manifest.media_presentation_duration_secs == 5445.5
        assert len(manifest.periods) == 1

    def test_base_url(self):
        manifest = parse_mpd(MPD_MANIFEST)
        assert manifest.base_url == "https://cdn.example.com/dash/"

    def test_adaptation_sets(self):
        manifest = parse_mpd(MPD_MANIFEST)
        period = manifest.periods[0]
        assert len(period.adaptation_sets) == 2

        video = period.adaptation_sets[0]
        assert video.content_type == "video"
        assert video.mime_type == "video/mp4"

        audio = period.adaptation_sets[1]
        assert audio.content_type == "audio"

    def test_video_representations(self):
        manifest = parse_mpd(MPD_MANIFEST)
        video_reps = manifest.video_representations
        assert len(video_reps) == 4

        # Sorted by bandwidth descending
        assert video_reps[0].bandwidth == 6000000
        assert video_reps[0].resolution == "1920x1080"
        assert video_reps[0].id == "1080p"

        assert video_reps[-1].bandwidth == 800000
        assert video_reps[-1].resolution == "640x360"

    def test_frame_rate_fraction(self):
        manifest = parse_mpd(MPD_MANIFEST)
        reps = manifest.video_representations
        top = reps[0]
        assert top.frame_rate is not None
        assert abs(top.frame_rate - 29.97) < 0.01

    def test_frame_rate_integer(self):
        manifest = parse_mpd(MPD_MANIFEST)
        reps = manifest.video_representations
        assert reps[1].frame_rate == 30.0

    def test_segment_template(self):
        manifest = parse_mpd(MPD_MANIFEST)
        video_adapt = manifest.periods[0].adaptation_sets[0]
        tmpl = video_adapt.segment_template
        assert tmpl is not None
        assert tmpl.timescale == 90000
        assert tmpl.duration == 540000
        assert tmpl.segment_duration_secs == 6.0
        assert "$RepresentationID$" in tmpl.media
        assert tmpl.start_number == 1

    def test_audio_segment_template(self):
        manifest = parse_mpd(MPD_MANIFEST)
        audio_adapt = manifest.periods[0].adaptation_sets[1]
        tmpl = audio_adapt.segment_template
        assert tmpl is not None
        assert tmpl.timescale == 44100
        assert abs(tmpl.segment_duration_secs - 4.0) < 0.01

    def test_codecs_inheritance(self):
        manifest = parse_mpd(MPD_MANIFEST)
        video_reps = manifest.video_representations
        # Codecs inherited from AdaptationSet
        assert video_reps[0].codecs == "avc1.64001f"

    def test_live_mpd(self):
        manifest = parse_mpd(LIVE_MPD)
        assert manifest.type == "dynamic"
        assert manifest.min_buffer_time_secs == 4.0

    def test_content_type_inferred_from_mime(self):
        manifest = parse_mpd(LIVE_MPD)
        adapt = manifest.periods[0].adaptation_sets[0]
        assert adapt.content_type == "video"


class TestDetection:
    def test_detect_by_content_type(self):
        assert detect_dash("foo", "application/dash+xml")
        assert not detect_dash("foo", "text/html")

    def test_detect_by_url(self):
        assert detect_dash("https://cdn.example.com/manifest.mpd", "")
        assert not detect_dash("https://cdn.example.com/index.m3u8", "")
