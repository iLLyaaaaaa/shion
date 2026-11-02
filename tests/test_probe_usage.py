"""Isolated checks for the aggregate-only feasibility probe."""
from datetime import date
import io
import json

from tools import probe_usage as probe


def record(mid="reply-a", request="request-a", **extra):
    return {"type": "assistant", "timestamp": "2026-11-01T18:30:00Z",
            "requestId": request, "message": {"id": mid,
                "model": "claude-sonnet-4-5-20250929",
                "usage": dict(zip(probe.TOKENS, (1, 2, 3, 4))),
                "content": "PRIVATE_CONVERSATION"}, **extra}


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_cross_file_dedup_and_no_private_output(tmp_path):
    row = record(entrypoint="cli", cwd="PRIVATE_DIRECTORY", project="PRIVATE_PROJECT")
    write_rows(tmp_path / "PRIVATE_FILENAME.jsonl", [row, row])
    write_rows(tmp_path / "nested" / "copy.jsonl", [row, record(mid="reply-b")])
    result = probe.scan(tmp_path, date(2026, 11, 2))
    day = str(probe.local_date(row["timestamp"]))
    assert result["file_count"] == 2
    assert result["assistant_usage_lines"] == result["before_dedup"] == 4
    assert result["after_dedup"] == 2
    assert result["last_7_days"][day] == dict(zip(probe.TOKENS, (2, 4, 6, 8)))
    assert len(result["last_7_days"]) == 7
    assert result["client_fields"] == {"entrypoint": {"cli": 3}}
    assert "PRIVATE" not in json.dumps(result)
    assert "reply-a" not in json.dumps(result)


def test_malformed_oversized_and_invalid_rows(tmp_path):
    good = record()
    bad_count = record(mid="bad-count")
    bad_count["message"]["usage"]["input_tokens"] = True
    bad_id = record(mid=["invalid"])
    no_id = record(mid=None, request=None)
    bad_date = record(mid="bad-date", timestamp="not-a-date")
    write_rows(tmp_path / "sample.jsonl", [good, bad_count, bad_id, no_id, bad_date,
                                         record(type="user")])
    with (tmp_path / "sample.jsonl").open("ab") as stream:
        stream.write(b'{"usage":broken}\n')
        stream.write(b'X' * (probe.MAX_LINE + 20) + b'\n')
        stream.write(json.dumps(record(mid="second")).encode() + b'\n')
        stream.write(b'{"usage":')  # An actively appended, truncated tail.
    result = probe.scan(tmp_path)
    assert result["assistant_usage_lines"] == 6
    assert result["before_dedup"] == result["after_dedup"] == 2
    assert list(probe.bounded_lines(io.BytesIO(b'x' * (probe.MAX_LINE + 1)))) == [None]


def test_private_metadata_values_are_bucketed(tmp_path):
    row = record(entrypoint="PRIVATE_PROJECT", source={"text": "PRIVATE_CONVERSATION"})
    row["message"]["model"] = "PRIVATE_PROJECT"
    write_rows(tmp_path / "rows.jsonl", [row])
    result = probe.scan(tmp_path)
    assert result["models"] == ["<other-model>"]
    assert result["client_fields"] == {"entrypoint": {"<other>": 1}, "source": {"<other>": 1}}
    assert "PRIVATE" not in json.dumps(result)


def test_missing_root_and_replaced_transcript(tmp_path):
    assert probe.scan(tmp_path / "missing")["file_count"] == 0
    path = tmp_path / "rows.jsonl"
    write_rows(path, [record(), record(mid="second")])
    assert probe.scan(tmp_path)["after_dedup"] == 2
    write_rows(path, [record()])
    assert probe.scan(tmp_path)["after_dedup"] == 1


def test_cli_only_writes_fixed_report_and_keeps_input_bytes(tmp_path, monkeypatch, capsys):
    config = tmp_path / "isolated-config"
    source = config / "projects" / "rows.jsonl"
    write_rows(source, [record()])
    before = source.read_bytes()
    output = tmp_path / "build" / "probe-usage.txt"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    monkeypatch.setattr(probe, "OUTPUT", output)
    assert probe.main() == 0
    assert source.read_bytes() == before
    assert json.loads(output.read_text())["after_dedup"] == 1
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == [
        "build/probe-usage.txt", "isolated-config/projects/rows.jsonl"]
    assert capsys.readouterr() == ("", "")


def test_date_conversion_uses_host_timezone():
    stamp = "2026-11-01T18:30:00+00:00"
    from datetime import datetime
    assert probe.local_date(stamp) == datetime.fromisoformat(stamp).astimezone().date()
    assert probe.local_date("2026-11-01T18:30:00") is None
