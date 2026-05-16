"""Tests for in-process job runner helpers."""

from __future__ import annotations

from jobs.runner import Job, JobProgressSink


def test_job_progress_sink_emit_records_structured_dict_detail():
    j = Job(id="jid", label="L", operation="token.design_explore", target="slug")
    sink = JobProgressSink(j, runner=None)
    sink.emit("candidate_ready", {"index": 2, "path": "/tmp/candidate_2.png"})
    ev = j.events[-1]
    assert ev["step"] == "candidate_ready"
    assert ev["detail"]["index"] == 2
    assert "candidate_2.png" in ev["detail"]["path"]


def test_job_progress_sink_emit_string_detail_has_step_only_or_detail_key():
    j = Job(id="jid2", label="L", operation="noop", target=None)
    sink = JobProgressSink(j, runner=None)
    sink.emit("derive_prompts", "hello")
    assert j.events[-1] == {"step": "derive_prompts", "detail": "hello"}

    sink.emit("tick")
    assert j.events[-1] == {"step": "tick"}
