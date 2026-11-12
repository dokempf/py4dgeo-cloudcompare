import io
import json

from py4dgeo_cloudcompare import m3c2_gui
from py4dgeo_cloudcompare.m3c2_protocol import (
    CloudChoice,
    DialogRequest,
    M3C2Configuration,
    M3C2Parameters,
)


def test_gui_protocol_returns_configuration_json(monkeypatch):
    request = DialogRequest(
        clouds=(CloudChoice(10, "one"), CloudChoice(11, "two")),
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=10,
    )
    configuration = M3C2Configuration(
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=10,
        parameters=M3C2Parameters(),
        output_name="result",
    )
    standard_input = io.StringIO(
        json.dumps({"type": "configure", "request": request.to_payload()})
    )
    standard_output = io.StringIO()
    monkeypatch.setattr(m3c2_gui.sys, "stdin", standard_input)
    monkeypatch.setattr(m3c2_gui.sys, "stdout", standard_output)
    monkeypatch.setattr(m3c2_gui, "_show_dialog", lambda received: configuration)

    m3c2_gui.main()

    assert json.loads(standard_output.getvalue()) == {
        "type": "configured",
        "configuration": json.loads(json.dumps(configuration.to_payload())),
    }
