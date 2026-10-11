"""Machine diagnostics retain unavailable sensors without inventing readings."""

import json

import pytest

from eval.bench import machine


@pytest.mark.parametrize("output", [None, "", "not-json", "null", "[]", '"text"', "123"])
def test_unavailable_or_malformed_cim_root_records_reason(
    output: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(machine, "_run", lambda *args, **kwargs: output)
    result = machine._cim()
    assert result.get("error")
    assert not result.get("thermal_zones")


@pytest.mark.parametrize("raw_zones", [None, {}, "unavailable", [], [None], [42, "sensor"]])
def test_missing_or_malformed_thermal_entries_are_unknown(
    raw_zones: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.dumps({"thermal_zones": raw_zones, "cpu": {"ProcessorFrequency": 2400}})
    monkeypatch.setattr(machine, "_run", lambda *args, **kwargs: payload)
    result = machine._cim()
    assert result["thermal_zones"] == []
    assert result["thermal_zones_unavailable_reason"]
    assert result["cpu"] == {"ProcessorFrequency": 2400}


def test_valid_zones_survive_mixed_null_sensor_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {
            "thermal_zones": [
                None,
                {
                    "Name": "Synthetic chassis sensor",
                    "Temperature": 300.15,
                    "PercentPassiveLimit": 100,
                    "ThrottleReasons": 0,
                },
                "malformed",
            ],
            "power_scheme": "Synthetic balanced scheme",
        }
    )
    monkeypatch.setattr(machine, "_run", lambda *args, **kwargs: payload)
    result = machine._cim()
    assert result["thermal_zones"] == [
        {
            "name": "Synthetic chassis sensor",
            "celsius": 27.0,
            "percent_passive_limit": 100,
            "throttle_reasons": 0,
        }
    ]
    assert result["thermal_zones_unavailable_reason"]
    assert result["power_scheme"] == "Synthetic balanced scheme"


@pytest.mark.parametrize(
    "temperature", [None, "300", True, 0, -1, float("nan"), float("inf"), 10**400]
)
def test_missing_or_invalid_temperature_is_not_converted_to_a_measurement(
    temperature: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.dumps({"thermal_zones": [{"Name": "Synthetic", "Temperature": temperature}]})
    monkeypatch.setattr(machine, "_run", lambda *args, **kwargs: payload)
    reading = machine._cim()["thermal_zones"][0]
    assert reading["celsius"] is None
    assert reading["temperature_unavailable_reason"]
