"""
Tests for scripts/connect-tracker.py.

The tool talks to a real Traccar over HTTP and a real container over docker, and
neither belongs in a unit test. So the split is deliberate: everything that
decides *what to tell the operator* is a pure function, and that is what is
tested here. A wrong decision is worse than a crash -- the operator acts on it
with a vehicle and a phone, on site.

The case that matters most is `test_stale_unknown_device_is_ignored`. Without the
time window, the diagnosis reads a log tail containing some other tracker's
"I don't know this device" warning from last week and instructs the operator to
rename this device to a stranger's IMEI, which then silently breaks that other
vehicle. The window is not a nicety.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import re
import sys

import pytest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "connect-tracker.py"
spec = importlib.util.spec_from_file_location("connect_tracker", MODULE_PATH)
ct = importlib.util.module_from_spec(spec)
sys.modules["connect_tracker"] = ct
spec.loader.exec_module(ct)


# ---------------------------------------------------------------------------
# The SMS sequence
# ---------------------------------------------------------------------------

def commands(**kwargs) -> list[str]:
    defaults = dict(apn="internet", server="203.0.113.10", port=5013)
    defaults.update(kwargs)
    return [command for command, _ in ct.sms_sequence(**defaults)]


def test_sms_uses_the_documented_numeric_syntax():
    """The ST-906L manual's own command set, verbatim in shape."""
    got = commands()
    assert got[0] == "8030000 internet"
    assert got[1] == "8040000 203.0.113.10 5013"
    assert got[2] == "8050000 20"
    assert got[3] == "8090000 300"
    assert "7100000" in got
    assert got[-1] == "RCONF"


def test_sms_never_emits_the_withdrawn_comma_syntax():
    """Regression guard, and the reason this file exists.

    An earlier revision of docs/TRACKER-SETUP.md recommended `apn,name#` and
    `server,0,host,port,0#` as an equivalent SinoTrack syntax. They are not in
    this model's manual; they belong to other tracker families. The unit's only
    configuration channel is SMS, so sending a command it does not understand is
    not a free experiment. If this assertion ever fails, someone has put the
    comma form back somewhere.
    """
    for command in commands():
        assert not command.startswith("apn,"), command
        assert not command.startswith("server,"), command
        assert not command.endswith("#"), command
        assert not command.startswith("mode,"), command


def test_apn_is_first_because_nothing_else_can_be_observed_without_a_data_session():
    assert commands()[0].startswith("8030000")


def test_server_comes_before_the_intervals():
    got = commands()
    assert got.index("8040000 203.0.113.10 5013") < got.index("8050000 20")


def test_seconds_are_seconds():
    got = commands(acc_interval=30, parked_interval=600)
    assert "8050000 30" in got
    assert "8090000 600" in got


@pytest.mark.parametrize("seconds", [0, 1, 9])
def test_an_interval_below_ten_seconds_is_refused(seconds):
    """0 closes GPRS entirely and reads on the server as dead hardware."""
    with pytest.raises(ValueError, match="at least 10 seconds"):
        ct.sms_sequence("internet", "203.0.113.10", 5013, acc_interval=seconds)
    with pytest.raises(ValueError, match="at least 10 seconds"):
        ct.sms_sequence("internet", "203.0.113.10", 5013, parked_interval=seconds)


def test_ten_seconds_is_allowed_because_the_manual_says_it_is_the_floor():
    ct.sms_sequence("internet", "203.0.113.10", 5013, acc_interval=10, parked_interval=10)


def test_the_password_is_substituted_not_hardcoded():
    got = [c for c, _ in ct.sms_sequence("internet", "203.0.113.10", 5013, password="1234")]
    # three-digit verb + four-digit password, so 803 + 1234
    assert "8031234 internet" in got
    assert "8041234 203.0.113.10 5013" in got
    assert "8051234 20" in got
    assert "7101234" in got
    assert not any("0000" in c for c in got), got
    # RCONF is a bare verb: it takes no password argument on any firmware.


def test_apn_credentials_only_when_given():
    assert "8030000 internet" in [c for c, _ in ct.sms_sequence("internet", "1.1.1.1", 5013)]
    withcred = [c for c, _ in ct.sms_sequence(
        "internet", "1.1.1.1", 5013, apn_user="user", apn_password="pw")]
    assert "8030000 internet user pw" in withcred


@pytest.mark.parametrize("apn,server,port", [("", "1.1.1.1", 5013), ("apn", "", 5013), ("apn", "1.1.1.1", 0), ("apn", "1.1.1.1", 70000)])
def test_incomplete_or_impossible_input_is_refused(apn, server, port):
    with pytest.raises(ValueError):
        ct.sms_sequence(apn, server, port)


def test_every_command_the_script_sends_is_documented_in_tracker_setup():
    """Keeps the code and the operator-facing document from drifting apart.

    The commands are firmware-specific and a wrong one is not recoverable without
    the unit in hand, so the document and the tool have to agree. This test fails
    the moment one of them is edited alone.
    """
    doc = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "TRACKER-SETUP.md").read_text(encoding="utf-8")
    for command in commands():
        if command == "RCONF":
            stem = "RCONF"
        else:
            stem = command.split()[0][:4]  # the 8-digit code, password stripped
        assert stem in doc, f"{stem!r} (from {command!r}) is not documented in docs/TRACKER-SETUP.md"


def setup_doc():
    return (pathlib.Path(__file__).resolve().parents[2] / "docs" / "TRACKER-SETUP.md").read_text(encoding="utf-8")


COMMA_FORMS = ("server,0,", "apn,your_carrier_apn#", "mode,1#")


def test_the_document_never_gives_the_comma_syntax_as_something_to_send():
    """The withdrawn commands may be *named* -- explaining why they were removed is
    the point -- but they must never appear where an operator would copy them.

    Two places qualify: a fenced code block, which is where a command you are
    meant to send lives, and a table row, which is how the documented set is
    presented. Both are checked.
    """
    doc = setup_doc()
    for block in re.findall(r"```.*?```", doc, re.S):
        for form in COMMA_FORMS:
            assert form not in block, f"{form!r} is given as a command in a code block"
    for line in doc.splitlines():
        if line.strip().startswith("|"):
            for form in COMMA_FORMS:
                assert form not in line, f"{form!r} is given as a command in a table row"
    # ...and the documented set IS presented the same way, or the checks above
    # would pass vacuously on an empty document.
    rows = [line for line in doc.splitlines() if line.strip().startswith("|")]
    assert any("8040000" in row for row in rows), "the documented server command is missing"


def test_the_document_says_why_the_comma_syntax_went_away():
    doc = setup_doc()
    assert "not in the ST-906L manual" in doc
    assert "RCONF" in doc
    assert "database.registerUnknown" in doc or "auto-register" in doc.lower()


# ---------------------------------------------------------------------------
# The device record
# ---------------------------------------------------------------------------

def test_device_payload_uses_uniqueid_for_the_imei():
    payload = ct.device_payload("AB123CD", "4210209006")
    assert payload["uniqueId"] == "4210209006"
    assert payload["name"] == "AB123CD"
    assert payload["disabled"] is False


def test_device_payload_sends_the_category_as_a_top_level_field():
    """Traccar's category is a TOP-LEVEL field, and `attributes.deviceType` is not
    it.

    Measured on this stack rather than remembered (14 Oct 2026), on two devices
    created through the API and read straight back:

        POST {"attributes": {"deviceType": "truck"}}           -> category: null
        POST {"category": "truck", "attributes": {...}}        -> category: "truck"

    The tool sent only the attributes form, so `--category` was a no-op and every
    device it registered had a null category -- which is the exact condition
    docs/TRACKER-SETUP.md warns about, where Traccar's derived speed and distance
    are quietly wrong. A test that asserted only the attributes form is what let
    that through, so this one asserts both.
    """
    payload = ct.device_payload("AB123CD", "4210209006")
    assert payload["category"] == "truck"
    assert payload["attributes"]["deviceType"] == "truck"
    assert "type" not in payload


def test_a_non_default_category_reaches_both_fields():
    payload = ct.device_payload("AB123CD", "4210209006", category="car")
    assert payload["category"] == "car"
    assert payload["attributes"]["deviceType"] == "car"


@pytest.mark.parametrize("name,imei", [("", "123"), ("AB123CD", ""), ("  ", "123"), ("AB123CD", "   ")])
def test_device_payload_requires_both_identifier_and_name(name, imei):
    with pytest.raises(ValueError):
        ct.device_payload(name, imei)


# ---------------------------------------------------------------------------
# The three stages
# ---------------------------------------------------------------------------

def test_a_brand_new_record_is_only_registered():
    assert ct.stage({"id": 1, "name": "AB123CD"}, []) == "registered"


def test_a_fresh_lastupdate_is_connected_even_while_status_says_offline():
    """The heartbeat case, straight from the research.

    H02 units send HTBT keep-alives that do not move Traccar's online flag, so
    status stays `offline` while the server is very much hearing from the device.
    Treating status as the signal would report a working tracker as dead.
    """
    device = {"id": 1, "status": "offline", "lastUpdate": "2026-10-13T21:00:00.000+00:00"}
    assert ct.stage(device, []) == "connected"


def test_a_stored_position_is_the_only_thing_that_counts_as_positioned():
    assert ct.stage({"id": 1, "positionId": 900}, []) == "positioned"
    assert ct.stage({"id": 1}, [{"id": 900}]) == "positioned"


def test_no_device_at_all_is_registered_not_an_error():
    assert ct.stage(None, None) == "registered"


# ---------------------------------------------------------------------------
# Log windowing
# ---------------------------------------------------------------------------

NOW = dt.datetime(2026, 10, 13, 21, 0, 0)


def test_window_keeps_only_lines_after_the_cutoff():
    text = (
        "2026-10-13 20:00:00 INFO: old news\n"
        "2026-10-13 21:00:01 INFO: current\n"
    )
    assert ct.lines_since(text, NOW) == ["2026-10-13 21:00:01 INFO: current"]


def test_window_keeps_unstamped_lines_because_they_are_the_interesting_ones():
    text = "Traceback (most recent call last):\n  File \"x\", line 1\n2026-10-13 20:00:00 INFO: old\n"
    kept = ct.lines_since(text, NOW)
    assert "Traceback (most recent call last):" in kept
    assert '  File "x", line 1' in kept
    assert "old" not in " ".join(kept)


def test_window_survives_a_malformed_timestamp():
    kept = ct.lines_since("2026-13-99 99:99:99 INFO: nonsense\n", NOW)
    assert kept == ["2026-13-99 99:99:99 INFO: nonsense"]


def test_no_cutoff_keeps_everything_non_empty():
    assert len(ct.lines_since("a\n\nb\n", None)) == 2


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------

REAL_UNKNOWN_DEVICE_LOG = (
    "2021-02-09 16:06:26 INFO: [44d4b800: gt06 < 5.35.166.137] "
    "HEX: 78781101086528204001555280330001007306230d0a\n"
    "2021-02-09 16:06:26 WARN: Unknown device - 865282040015552 (5.35.166.137)\n"
)


def test_unknown_device_is_detected_with_the_identifier_the_server_read():
    """The real log shape, from a Traccar forum transcript."""
    fixed = REAL_UNKNOWN_DEVICE_LOG.replace("2021-02-09", "2026-10-13")
    result = ct.diagnose(fixed, "4210209006", since=dt.datetime(2026, 10, 13, 15, 0, 0))
    assert result["kind"] == "unknown_device"
    assert result["seen_identifiers"] == ["865282040015552"]


def test_stale_unknown_device_is_ignored():
    """The dangerous case. Acting on a stale warning renames this device to a
    stranger's IMEI and silently breaks that other vehicle."""
    result = ct.diagnose(REAL_UNKNOWN_DEVICE_LOG, "4210209006", since=NOW)
    assert result["kind"] == "no_traffic"
    assert result["seen_identifiers"] == []


def test_protocol_traffic_with_no_unknown_warning_means_it_reached_the_server():
    text = ("2026-10-13 21:00:05 INFO: [44d4b800: h02 < 1.2.3.4] "
            "TEXT: *HQ,4210209006,V1,210005,A,4546.1370,N,00911.4000,E,000.80,000,131026,FFFFF9FF,310,260,0,0,6#\n")
    result = ct.diagnose(text, "4210209006", since=NOW)
    assert result["kind"] == "reached_server"
    assert result["our_lines"] == 1


def test_our_identifier_alone_is_enough_to_call_it_reached():
    text = "2026-10-13 21:00:05 INFO: login 4210209006 from 1.2.3.4\n"
    assert ct.diagnose(text, "4210209006", since=NOW)["kind"] == "reached_server"


def test_nothing_in_the_window_is_no_traffic():
    text = "2026-10-13 21:00:05 INFO: [Main] started\n"
    result = ct.diagnose(text, "4210209006", since=NOW)
    assert result["kind"] == "no_traffic"
    assert result["traffic_lines"] == 0


def test_someone_elses_traffic_is_not_reported_as_ours():
    """Traffic in the log that names no identifier we can act on is context, not
    evidence. Calling it `reached_server` would tell the operator their tracker is
    fine while they are looking at another vehicle's packets."""
    text = "2026-10-13 21:00:05 INFO: [44d4b800: h02 < 10.0.0.9] TEXT: *HQ,9999999999,V1,210005,A...#\n"
    result = ct.diagnose(text, "4210209006", since=NOW)
    assert result["kind"] == "no_traffic"
    assert result["traffic_lines"] == 1


def test_an_empty_log_is_no_traffic_not_a_crash():
    assert ct.diagnose("", "4210209006", since=NOW)["kind"] == "no_traffic"


def test_heartbeats_alone_are_flagged_rather_than_read_as_success():
    text = "2026-10-13 21:00:05 INFO: [x: h02 < 1.2.3.4] TEXT: *HQ,4210209006,HTBT#\n"
    result = ct.diagnose(text, "4210209006", since=NOW)
    assert result["kind"] == "reached_server"
    assert result["heartbeat_only"] is True


# ---------------------------------------------------------------------------
# Advice
# ---------------------------------------------------------------------------

def test_unknown_device_advice_carries_the_one_command_fix():
    result = {"kind": "unknown_device", "seen_identifiers": ["865282040015552"]}
    text = "\n".join(ct.advice(result, "4210209006", "vps.example.com", 5013))
    assert "--adopt-seen-id 865282040015552" in text
    assert "auto-register" in text


# ---------------------------------------------------------------------------
# Settings read back from the server, so the advice is not a guess
# ---------------------------------------------------------------------------
#
# The symptom is identical either way -- "Unknown device" in the log -- and the
# two causes need opposite fixes. Measured on this stack: with the allow-list set
# to `^42102` a matching unit was refused, and the tool told the operator that
# "Traccar does not auto-register unknown devices", which was simply false.

RENDERED_OFF = (
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    "<properties>\n"
    "    <entry key='database.registerUnknown'>false</entry>\n"
    "</properties>\n"
)

RENDERED_ON_WITH_ALLOWLIST = (
    "<properties>\n"
    "    <entry key='database.registerUnknown'>true</entry>\n"
    "    <entry key='database.registerUnknown.defaultCategory'>truck</entry>\n"
    "    <entry key='database.registerUnknown.regex'>42102.*</entry>\n"
    "</properties>\n"
)


def test_the_settings_are_read_from_the_rendered_xml():
    got = ct.parse_server_settings(RENDERED_ON_WITH_ALLOWLIST)
    assert got == {"register_unknown": True, "regex": "42102.*", "category": "truck"}


def test_an_unreadable_or_empty_config_is_unknown_not_off():
    """Unknown must not collapse into "off": that is the confident wrong answer."""
    assert ct.parse_server_settings("") is None
    assert ct.parse_server_settings("not xml at all") is None


def test_a_config_without_the_key_concludes_nothing():
    assert ct.parse_server_settings("<properties></properties>\n") is None


def test_the_allow_list_is_evaluated_the_way_java_does():
    """Traccar uses String.matches, so the WHOLE identifier must match.

    This is the difference between `42102.*` working and `^42102` silently
    accepting nothing, and it was measured against the live server rather than
    read off a wiki.
    """
    assert ct.matches_identifier("42102.*", "421020999002") is True
    assert ct.matches_identifier("^42102", "421020999002") is False
    assert ct.matches_identifier("42102", "421020999002") is False
    assert ct.matches_identifier("42102.*", "990000000000781") is False


def test_an_unevaluable_pattern_says_so_rather_than_reassuring():
    assert ct.matches_identifier("", "421020999002") is None
    assert ct.matches_identifier("42102.*", "") is None
    assert ct.matches_identifier("[", "421020999002") is None


def test_the_advice_names_the_allow_list_when_it_is_what_refused_the_device():
    text = "\n".join(ct.unknown_device_advice(
        "990000000000781", "990000000000780",
        {"register_unknown": True, "regex": "42102.*", "category": "truck"}))
    assert "42102.*" in text
    assert "990000000000781" in text
    assert "does not" in text
    assert "TRACCAR_REGISTER_UNKNOWN_REGEX" in text
    # and NOT the default-off explanation, which would be wrong here
    assert "does not auto-register" not in text


def test_a_matching_identifier_pointed_at_the_allow_list_is_called_out():
    """If it matched and was still refused, the allow-list is not the cause, and
    sending the operator off to widen it would waste another round trip."""
    text = "\n".join(ct.unknown_device_advice(
        "421020999002", "421020999001",
        {"register_unknown": True, "regex": "42102.*", "category": "truck"}))
    assert "DOES match" in text
    assert "TRACCAR_REGISTER_UNKNOWN_REGEX" not in text


def test_with_auto_registration_off_the_default_explanation_stands():
    text = "\n".join(ct.unknown_device_advice(
        "990000000000781", "42", {"register_unknown": False, "regex": "", "category": ""}))
    assert "does not auto-register" in text


def test_an_unreadable_config_falls_back_to_the_default_wording():
    text = "\n".join(ct.unknown_device_advice("990000000000781", "42", None))
    assert "does not auto-register" in text


def test_advice_passes_the_settings_through_the_top_level_function():
    result = {"kind": "unknown_device", "seen_identifiers": ["990000000000781"]}
    text = "\n".join(ct.advice(
        result, "990000000000780", "vps.example.com", 5013,
        server_settings={"register_unknown": True, "regex": "42102.*", "category": "truck"}))
    assert "TRACCAR_REGISTER_UNKNOWN_REGEX" in text


def test_no_traffic_advice_names_the_outside_in_test_and_the_sim():
    text = "\n".join(ct.advice({"kind": "no_traffic"}, "4210209006", "vps.example.com", 5013))
    assert "traccar.org/port-check" in text
    assert "RCONF" in text
    assert "APN" in text
    assert "vps.example.com:5013" in text


def test_reached_server_advice_points_at_the_fix_flag_and_the_sim():
    text = "\n".join(ct.advice({"kind": "reached_server"}, "4210209006", "vps.example.com", 5013))
    assert "`A`" in text and "`V`" in text
    assert "*HQ" in text


def test_advice_reports_an_unexpected_sms_reply():
    text = "\n".join(ct.advice({"kind": "no_traffic"}, "1", "s", 5013, sms_reply="ERROR"))
    assert "ERROR" in text
    assert ct.SMS_OK_REPLY in text


# ---------------------------------------------------------------------------
# The compose port-mapping guard (docs/UNIMPLEMENTED.md 7.8)
# ---------------------------------------------------------------------------

def patch_docker(monkeypatch, ports_json: str, code: int = 0):
    monkeypatch.setattr(ct, "run", lambda cmd, timeout=20: (code, ports_json))


def test_the_real_mapping_is_accepted(monkeypatch):
    patch_docker(monkeypatch, '{"5013/tcp":[{"HostIp":"0.0.0.0","HostPort":"5013"}]}')
    result = ct.check_port_mapping("traccar-1", 5013)
    assert result["ok"] is True
    assert result["host_port"] == 5013
    assert result["container_port"] == 5013


def test_a_custom_host_port_onto_the_right_container_port_is_fine(monkeypatch):
    patch_docker(monkeypatch, '{"5013/tcp":[{"HostIp":"0.0.0.0","HostPort":"15013"}]}')
    result = ct.check_port_mapping("traccar-1", 15013)
    assert result["ok"] is True
    assert result["host_port"] == 15013


def test_the_watch_port_mistake_is_caught(monkeypatch):
    """`${H02_PORT}:${H02_PORT}` with H02_PORT=5093 -- the shipped bug. Traccar's
    watch listener is at 5093, so the stack comes up healthy and decodes nothing."""
    patch_docker(monkeypatch, '{"5093/tcp":[{"HostIp":"0.0.0.0","HostPort":"5093"}]}')
    result = ct.check_port_mapping("traccar-1", 5093)
    assert result["ok"] is False
    assert "5013" in result["detail"]


def test_nothing_published_on_h02_is_caught(monkeypatch):
    patch_docker(monkeypatch, '{}')
    result = ct.check_port_mapping("traccar-1", 5013)
    assert result["ok"] is False
    assert "5013" in result["detail"]


def test_a_host_port_that_disagrees_with_h02_port_is_caught(monkeypatch):
    patch_docker(monkeypatch, '{"5013/tcp":[{"HostIp":"0.0.0.0","HostPort":"5099"}]}')
    result = ct.check_port_mapping("traccar-1", 5013)
    assert result["ok"] is False
    assert "5099" in result["detail"]


def test_no_container_is_unknown_not_a_failure(monkeypatch):
    """Docker is not installed on a technician's laptop. That is not a fault in
    the deployment and must not be reported as one."""
    result = ct.check_port_mapping("", 5013)
    assert result["ok"] is None


def test_unparseable_docker_output_is_unknown_not_a_failure(monkeypatch):
    patch_docker(monkeypatch, "not json")
    assert ct.check_port_mapping("traccar-1", 5013)["ok"] is None


# ---------------------------------------------------------------------------
# Which container is "the" Traccar container
# ---------------------------------------------------------------------------
#
# Choosing by "first name docker prints" is wrong as soon as two stacks run on one
# machine, and it happened here: a second compose project held the H02 port this
# one was configured for. The result is not a harmless wrong answer -- it is a
# port-mapping FAULT reported against a healthy stack, which sends the operator to
# edit a correct compose file.

def two_stacks():
    return [("gpstracer-new-traccar-1", 5013), ("gpstracer-dev-traccar-1", 5093)]


def test_real_inspect_output_yields_the_published_port():
    ports = {"5013/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5093"}],
             "8092/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8092"}]}
    assert ct.published_h02_port(ports) == 5093


def test_an_exposed_but_unpublished_port_is_not_a_mapping():
    """`expose:` without `ports:` gives an empty list. That is precisely the silent
    failure the precondition exists for, so it must not read as a mapping."""
    assert ct.published_h02_port({"5013/tcp": []}) is None


def test_a_missing_port_key_is_not_a_mapping():
    assert ct.published_h02_port({"8092/tcp": [{"HostPort": "8092"}]}) is None
    assert ct.published_h02_port({}) is None
    assert ct.published_h02_port(None) is None


@pytest.mark.parametrize("entry", ["nonsense", {}, {"HostPort": ""}, {"HostPort": "eight"}, []])
def test_malformed_inspect_output_degrades_to_unknown(entry):
    assert ct.published_h02_port({"5013/tcp": [entry]}) is None


def test_the_container_publishing_the_expected_port_wins():
    """Both stacks are healthy; only one is the one H02_PORT points at."""
    assert ct.choose_container(two_stacks(), 5093) == "gpstracer-dev-traccar-1"
    assert ct.choose_container(two_stacks(), 5013) == "gpstracer-new-traccar-1"


def test_the_expected_port_wins_even_when_it_is_listed_last():
    candidates = [("a", 5013), ("b", None), ("c", 5093)]
    assert ct.choose_container(candidates, 5093) == "c"


def test_without_an_expected_port_the_first_publisher_is_used():
    assert ct.choose_container(two_stacks(), 0) == "gpstracer-new-traccar-1"


def test_an_expected_port_nobody_publishes_falls_back_to_a_publisher():
    """Better a real mismatch than a port-mapping FAULT against a stack that
    publishes nothing at all -- the mismatch is then reported as a mismatch."""
    assert ct.choose_container(two_stacks(), 6001) == "gpstracer-new-traccar-1"


def test_a_stack_with_nothing_published_is_still_chosen_last_resort():
    """So the operator gets a truthful "nothing is published to 5013/tcp" rather
    than "no container found", which reads as a docker problem."""
    assert ct.choose_container([("lonely", None)], 5093) == "lonely"


def test_no_candidates_is_an_empty_string():
    assert ct.choose_container([], 5093) == ""


def test_discovery_picks_the_stack_that_publishes_the_configured_port(monkeypatch):
    """End of the chain: docker listing + per-container inspect, wired together."""
    ports = {
        "gpstracer-new-traccar-1": '{"5013/tcp":[{"HostIp":"0.0.0.0","HostPort":"5013"}]}',
        "gpstracer-dev-traccar-1": '{"5013/tcp":[{"HostIp":"127.0.0.1","HostPort":"5093"}]}',
    }

    def fake_run(cmd, timeout=20):
        if cmd[:2] == ["docker", "ps"]:
            return 0, "gpstracer-new-traccar-1\ngpstracer-dev-traccar-1\n"
        if cmd[:2] == ["docker", "inspect"]:
            return 0, ports.get(cmd[2], "{}")
        return 127, ""

    monkeypatch.setattr(ct, "run", fake_run)
    assert ct.find_traccar_container("", 5093) == "gpstracer-dev-traccar-1"
    assert ct.find_traccar_container("", 5013) == "gpstracer-new-traccar-1"


def test_an_explicit_container_is_never_second_guessed(monkeypatch):
    monkeypatch.setattr(ct, "run", lambda cmd, timeout=20: (0, "other\n"))
    assert ct.find_traccar_container("chosen-by-hand", 5093) == "chosen-by-hand"


def test_discovery_without_docker_reports_nothing(monkeypatch):
    monkeypatch.setattr(ct, "run", lambda cmd, timeout=20: (127, "docker: not found"))
    assert ct.find_traccar_container("", 5093) == ""


# ---------------------------------------------------------------------------
# The provisioning record
# ---------------------------------------------------------------------------

def test_record_row_carries_the_facts_and_no_secret():
    row = ct.provisioning_record("4210209006", "AB123CD", "internet", "vps.example.com", 5013,
                                 when=dt.datetime(2026, 10, 13))
    assert "4210209006" in row
    assert "AB123CD" in row
    assert "2026-10-13" in row
    assert "vps.example.com:5013" in row
    # the SMS password and any API credential must never reach the record
    assert "0000" not in row.replace("4210209006", "")
