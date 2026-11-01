"""The scripted evaluation (``eval/assistant_eval.py``): parsing, timing, percentiles and validation.

Everything here runs offline. The NDJSON fixtures in ``fixtures/streams/`` are
recorded from the real service code (``ASSISTANT_FAKE=1``), so they have the
event shapes ``POST /chat`` sends; the live run itself is not tested here.
PyYAML is not pinned in ``assistant/requirements*.txt``, so the one test that
loads the question file skips without it.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
STREAMS = Path(__file__).parent / "fixtures" / "streams"
PT = ZoneInfo("America/Los_Angeles")


def _load():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("assistant_eval", ROOT / "eval" / "assistant_eval.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["assistant_eval"] = module
    spec.loader.exec_module(module)
    return module


ev = _load()


def stream(name: str) -> str:
    return (STREAMS / f"{name}.ndjson").read_text(encoding="utf-8")


def timed(name: str, first: float = 1.0, step: float = 0.5) -> list[tuple[float, dict]]:
    """The fixture's events with made-up arrival times: ``first`` for event 0, then ``step`` apart."""
    events, bad = ev.parse_ndjson(stream(name))
    assert bad == 0
    return [(first + i * step, e) for i, e in enumerate(events)]


def summary(name: str, **kw) -> dict:
    return ev.summarize(timed(name, **kw))


# --- parsing and summarising -----------------------------------------------------


def test_parse_ndjson_skips_blank_lines_and_counts_malformed():
    events, bad = ev.parse_ndjson('{"type":"form"}\n\n{not json}\n[1,2]\n{"type":"done"}\n')
    assert [e["type"] for e in events] == ["form", "done"]
    assert bad == 2  # the broken line and the non-object line


def test_summarize_answered_route():
    s = summary("route_ok", first=1.25, step=0.5)
    assert s["outcome"] == "options"
    assert s["kinds"][0] == "options" and s["kinds"][-1] == "done"
    assert s["first_options_s"] == 1.25
    assert s["done_s"] == pytest.approx(1.25 + 0.5 * (len(s["kinds"]) - 1))
    assert s["agencies"] == ["Caltrain", "VTA"]
    assert s["replaced"] is False
    assert s["text"].startswith("Option 1 leaves")
    assert set(s["server_latency_ms"]) >= {"extract", "routing", "context", "explain", "total"}


def test_final_text_is_the_replace_text_when_one_came():
    events, _ = ev.parse_ndjson(stream("route_replaced"))
    texts = "".join(e["delta"] for e in events if e["type"] == "text")
    replace = next(e["text"] for e in events if e["type"] == "replace")
    assert texts and texts != replace
    assert ev.final_text(events) == replace
    s = summary("route_replaced")
    assert s["replaced"] is True and s["text"] == replace


def test_summarize_follow_up_has_no_options_or_done_time():
    s = summary("follow_up")
    assert s["outcome"] == "follow_up"
    assert s["first_options_s"] is None and s["done_s"] is None
    assert s["end_s"] == 1.0


def test_summarize_options_event_without_options_is_no_routes():
    s = summary("no_routes")
    assert s["outcome"] == "no_routes"
    assert s["first_options_s"] == 1.0  # the event did arrive; the checks decide whether that is acceptable
    assert s["agencies"] == []


def test_summarize_empty_stream():
    s = ev.summarize([])
    assert s["outcome"] == "empty" and s["first_options_s"] is None and s["text"] == ""


# --- validation against the options ----------------------------------------------


def test_options_round_trip_and_service_text_validates():
    for name in ("route_ok", "route_replaced"):
        s = summary(name)
        options = ev.options_from_json(s["options"])
        assert len(options) == 2
        assert options[0].legs[1].agency == "Caltrain"
        assert ev.validate_text(s["text"], options)["status"] == "pass", name


def test_validate_unsupported_time_fails():
    options = ev.options_from_json(summary("route_ok")["options"])
    v = ev.validate_text("Take the next train, it leaves at 3:17 AM.", options)
    assert v["status"] == "fail" and v["claims"]


def test_validate_unsupported_duration_fails():
    options = ev.options_from_json(summary("route_ok")["options"])
    assert ev.validate_text("The trip is only 33 minutes.", options)["status"] == "fail"


def test_validate_source_cited_figure_is_unverifiable_not_fail():
    # The digest (not in the stream) carries alert headers and event starts; a figure next to
    # such wording cannot be checked here, and the service already checked it against the digest.
    options = ev.options_from_json(summary("route_ok")["options"])
    v = ev.validate_text("Caltrain posted a delay alert until 11:45 PM.", options)
    assert v["status"] == "unverifiable" and v["claims"]
    v = ev.validate_text("The Sharks game starts at 7:30 PM.", options)
    assert v["status"] == "unverifiable"


def test_validate_one_bad_sentence_fails_even_beside_an_unverifiable_one():
    options = ev.options_from_json(summary("route_ok")["options"])
    text = "There is a delay alert until 11:45 PM. Your train leaves at 3:17 AM."
    assert ev.validate_text(text, options)["status"] == "fail"


def test_validate_empty_text_fails():
    options = ev.options_from_json(summary("route_ok")["options"])
    assert ev.validate_text("   ", options)["status"] == "fail"


# --- percentiles and the latency gate ----------------------------------------------


def test_percentile_linear_interpolation():
    assert ev.percentile([1, 2, 3, 4], 50) == 2.5
    assert ev.percentile([4, 1, 3, 2], 100) == 4
    assert ev.percentile([1, 2, 3, 4, 5], 95) == pytest.approx(4.8)
    assert ev.percentile([7.0], 95) == 7.0
    assert ev.percentile([], 50) is None


def _rows(first, done):
    return [{"first_options_s": f, "done_s": d} for f, d in zip(first, done)]


def test_aggregate_meets_targets_at_the_boundary():
    agg = ev.aggregate(_rows([2.0, 2.0, 2.0], [4.0, 4.0, 4.0]))
    assert agg["first_options"]["p50"] == 2.0 and agg["done"]["p50"] == 4.0
    assert agg["ok"] is True


def test_aggregate_reports_each_miss():
    agg = ev.aggregate(_rows([1.0, 1.0, 1.0, 1.0, 9.0], [2.0, 2.0, 2.0, 2.0, 2.0]))
    assert agg["first_options"]["ok"]["p50"] is True
    assert agg["first_options"]["ok"]["p95"] is False  # p95 = 1 + 0.8 * 8 = 7.4
    assert agg["done"]["ok"] == {"p50": True, "p95": True}
    assert agg["ok"] is False


def test_aggregate_ignores_missing_times_and_fails_with_no_samples():
    agg = ev.aggregate(_rows([1.0, None], [2.0, None]))
    assert agg["first_options"]["n"] == 1 and agg["done"]["n"] == 1
    empty = ev.aggregate(_rows([None], [None]))
    assert empty["ok"] is False and empty["first_options"]["p50"] is None


# --- per-question checks -------------------------------------------------------------


def route_q(**kw) -> dict:
    return {"id": "t", "message": "x", "kind": "route", "expect_agencies": ["Caltrain"], **kw}


def failed(checks: dict) -> set[str]:
    return {name for name, c in checks.items() if not c["ok"]}


def test_route_question_passes_with_expected_agency():
    checks = ev.check_question(route_q(), summary("route_ok"))
    assert failed(checks) == set()
    assert ev.question_ok(checks) is True


def test_route_question_fails_when_agency_missing():
    checks = ev.check_question(route_q(expect_agencies=["BART"]), summary("route_ok"))
    assert failed(checks) == {"agencies"}
    assert ev.question_ok(checks) is False


def test_route_question_fails_when_no_options():
    checks = ev.check_question(route_q(), summary("no_routes"))
    assert "options" in failed(checks)


def test_route_question_fails_on_bad_text_but_not_on_unverifiable_text():
    s = summary("route_ok")
    bad = {**s, "text": "It leaves at 3:17 AM."}
    assert "text_times" in failed(ev.check_question(route_q(), bad))
    src = {**s, "text": "There is a delay alert until 11:45 PM."}
    checks = ev.check_question(route_q(), src)
    assert "text_times" not in failed(checks)
    assert checks["text_times"]["status"] == "unverifiable"


def _with_stops(s: dict, to_stop: str) -> dict:
    s = copy.deepcopy(s)
    for o in s["options"]:
        transit = [leg for leg in o["legs"] if leg["mode"] == "TRANSIT"]
        transit[-1]["to_stop"] = to_stop
    s["dest_stops"] = ev.destination_stops(s["options"])
    return s


def test_destination_stop_must_match_and_avoid_the_known_wrong_stop():
    q = route_q(dest_stop_contains=["12th st", "city center"], dest_stop_excludes=["west oakland"])
    good = _with_stops(summary("route_ok"), "12th St. / Oakland City Center")
    assert failed(ev.check_question(q, good)) == set()
    west = _with_stops(summary("route_ok"), "West Oakland")
    assert failed(ev.check_question(q, west)) == {"dest_stop"}


def test_destination_stops_use_the_last_transit_leg_of_each_option():
    s = summary("route_ok")
    assert ev.destination_stops(s["options"]) == ["San Jose Diridon", "San Jose Diridon"]


def test_refusal_question_accepts_follow_up_and_form_only():
    q = {"id": "r", "message": "x", "kind": "refuse"}
    assert ev.question_ok(ev.check_question(q, summary("follow_up"))) is True
    form = ev.summarize([(0.4, {"type": "form"})])
    assert ev.question_ok(ev.check_question(q, form)) is True
    assert ev.question_ok(ev.check_question(q, summary("route_ok"))) is False
    assert ev.question_ok(ev.check_question(q, summary("no_routes"))) is False  # an options event is not a scope message


def test_depart_offset_checks_a_relative_time():
    s = summary("route_ok")
    first_depart = datetime.fromisoformat(s["options"][0]["depart"])
    q = route_q(depart_offset_min=[25, 120])
    requested = first_depart - timedelta(minutes=31)
    assert failed(ev.check_question(q, s, requested_at=requested)) == set()
    assert failed(ev.check_question(q, s, requested_at=first_depart - timedelta(minutes=5))) == {"depart_offset"}
    assert failed(ev.check_question(q, s, requested_at=first_depart - timedelta(minutes=300))) == {"depart_offset"}


def test_stream_without_done_fails_a_route_question():
    events = [(t, e) for t, e in timed("route_ok") if e["type"] != "done"]
    checks = ev.check_question(route_q(), ev.summarize(events))
    assert "done" in failed(checks)


# --- the question file ----------------------------------------------------------------


def test_question_file_is_within_the_rate_limit_and_covers_the_required_cases():
    pytest.importorskip("yaml")
    warmup, questions = ev.load_questions(ROOT / "eval" / "assistant_questions.yaml")
    assert warmup
    assert 1 + len(questions) <= ev.RATE_LIMIT_PER_HOUR
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    assert {q["kind"] for q in questions} == {"route", "refuse"}
    expected = {a for q in questions for a in q.get("expect_agencies", [])}
    assert expected == {"BART", "VTA", "Caltrain"}
    assert any(q.get("dest_stop_excludes") for q in questions)  # the 12th St check
    assert any(q.get("depart_offset_min") for q in questions)  # the relative time
    assert sum(q["kind"] == "refuse" for q in questions) >= 2  # out of area and nonsense
    assert all(len(q["message"]) <= 500 for q in questions)


# --- the whole run, against a mock transport ----------------------------------------------


QUESTIONS = """\
warmup: {message: "from Berkeley to SFO"}
questions:
  - {id: a, message: "from Mountain View to SAP Center", kind: route, expect_agencies: [Caltrain]}
  - {id: b, message: "hello there", kind: refuse}
"""


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://assistant.test")


def _serve(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)["message"]
    name = "follow_up" if "hello" in body else "route_ok"
    return httpx.Response(200, content=stream(name).encode(), headers={"content-type": "application/x-ndjson"})


def test_run_passes_and_writes_json(tmp_path):
    pytest.importorskip("yaml")
    qfile = tmp_path / "q.yaml"
    qfile.write_text(QUESTIONS)
    out = tmp_path / "out" / "result.json"
    sent: list[str] = []

    def handler(request):
        sent.append(json.loads(request.content)["message"])
        return _serve(request)

    code = ev.run("https://assistant.test", qfile, out, client=_client(handler), latency_gate=False)
    assert code == 0
    assert sent[0] == "from Berkeley to SFO"  # the discarded warm-up goes first
    assert len(sent) == 3
    result = json.loads(out.read_text())
    assert [r["id"] for r in result["questions"]] == ["a", "b"]  # the warm-up is not in the results
    assert result["ok"] is True and result["requests"] == 3
    assert result["questions"][0]["checks"]["agencies"]["ok"] is True
    assert "text" in result["questions"][0] and "options" not in result["questions"][0]  # compact record


def test_run_exits_nonzero_when_a_check_fails(tmp_path):
    pytest.importorskip("yaml")
    qfile = tmp_path / "q.yaml"
    qfile.write_text(QUESTIONS.replace("[Caltrain]", "[BART]"))
    code = ev.run("https://assistant.test", qfile, tmp_path / "r.json", client=_client(_serve), latency_gate=False)
    assert code == 1


def test_run_stops_on_rate_limit_and_fails(tmp_path):
    pytest.importorskip("yaml")
    qfile = tmp_path / "q.yaml"
    qfile.write_text(QUESTIONS)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, json={"error": "rate_limited"}, headers={"Retry-After": "120"})

    out = tmp_path / "r.json"
    code = ev.run("https://assistant.test", qfile, out, client=_client(handler), latency_gate=False)
    assert code == 1 and len(calls) == 1  # no further requests once limited
    assert json.loads(out.read_text())["rate_limited"] is True


def test_run_refuses_to_exceed_the_rate_limit_before_sending(tmp_path):
    pytest.importorskip("yaml")
    qfile = tmp_path / "q.yaml"
    many = "\n".join(f'  - {{id: q{i}, message: "hello {i}", kind: refuse}}' for i in range(10))
    qfile.write_text('warmup: {message: "hi"}\nquestions:\n' + many + "\n")
    calls = []

    def handler(request):
        calls.append(1)
        return _serve(request)

    code = ev.run("https://assistant.test", qfile, tmp_path / "r.json", client=_client(handler))
    assert code == 2 and calls == []


# --- sleep detection ----------------------------------------------------------------------------------


class _Stub:
    """A client whose stream yields the route_ok lines; ``tick`` advances the fake clocks per line."""

    def __init__(self, tick):
        self.tick = tick

    def stream(self, method, url, json):
        stub = self

        class _Response:
            status_code = 200
            headers: dict = {}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def iter_lines(self):
                for line in stream("route_ok").splitlines():
                    stub.tick()
                    yield line

        return _Response()


def test_ask_flags_a_sample_the_computer_slept_through():
    mono, wall = [0.0], [1000.0]
    awake = _Stub(lambda: (mono.__setitem__(0, mono[0] + 0.1), wall.__setitem__(0, wall[0] + 0.1)))
    r = ev.ask(awake, "x", clock=lambda: mono[0], wall=lambda: wall[0])
    assert r["suspect_sleep"] is False and r["outcome"] == "options"

    def nap():
        mono[0] += 0.1
        wall[0] += 0.1 + (900.0 if wall[0] < 1100 else 0.0)  # the wall clock keeps running while the timing clock stops

    mono, wall = [0.0], [1000.0]
    r = ev.ask(_Stub(nap), "x", clock=lambda: mono[0], wall=lambda: wall[0])
    assert r["suspect_sleep"] is True and r["suspended_s"] > 100
