from moex_carry.decision_log import validate_decision_log, validate_decision_view


def test_decision_log_requires_fields():
    errors = validate_decision_log({})
    assert "schema_version" in errors
    assert "decision_id" in errors
    assert "input_snapshots" in errors


def test_decision_view_requires_fields():
    errors = validate_decision_view({})
    assert "decision_view_id" in errors
    assert "decision_id" in errors
    assert "links" in errors
