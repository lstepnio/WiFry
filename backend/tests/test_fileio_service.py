"""Service-level tests for supported file sharing flows."""

import pytest

from app.services import fileio


@pytest.fixture(autouse=True)
def reset_upload_history():
    fileio._upload_history.clear()
    yield
    fileio._upload_history.clear()


@pytest.mark.anyio
async def test_upload_file_mock_records_history(tmp_path):
    sample = tmp_path / "capture.pcap"
    sample.write_bytes(b"pcap-bytes")

    result = await fileio.upload_file(str(sample), expires="15m")
    history = fileio.get_history()

    assert result["success"] is True
    assert result["filename"] == "capture.pcap"
    assert result["link"].startswith("https://file.io/")
    assert history[0]["filename"] == "capture.pcap"


@pytest.mark.anyio
async def test_upload_bundle_mock_records_file_count(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first")
    second.write_text("second")

    result = await fileio.upload_bundle(
        [str(first), str(second)],
        bundle_name="support-bundle.zip",
        expires="1h",
    )

    assert result["success"] is True
    assert result["filename"] == "support-bundle.zip"
    assert result["files_bundled"] == 2
    assert fileio.get_history()[0]["files_bundled"] == 2
