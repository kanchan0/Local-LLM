import time

from app.storage import TemporaryFileStore


def test_file_store_enforces_owner_and_cleanup(tmp_path):
    store = TemporaryFileStore(tmp_path, retention_seconds=1)
    record = store.create(1, "sample.txt", ".txt", b"hello")
    assert store.get_owned(record.file_id, 1) is record
    assert store.get_owned(record.file_id, 2) is None

    token = store.attach_output(record, "sample_corrected.docx", b"docx")
    assert store.get_download(token, 1) is record
    assert store.get_download(token, 2) is None

    time.sleep(1.1)
    assert store.cleanup() == 1
    assert store.get_download(token, 1) is None
