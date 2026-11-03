import pytest

from bot.data_api import extract_positions_page, position_condition_id, position_current_value


def test_extract_positions_page_v2_envelope() -> None:
    payload = {
        "data": [{"slug": "one"}],
        "pagination": {"next_cursor": "abc"},
    }
    rows, cursor = extract_positions_page(payload)
    assert len(rows) == 1
    assert cursor == "abc"


def test_extract_positions_page_rejects_missing_data() -> None:
    with pytest.raises(ValueError, match="missing data/positions"):
        extract_positions_page({"unexpected": []})


def test_position_field_helpers_read_v2_and_v1_keys() -> None:
    row = {
        "condition_id": "0xcond",
        "token_id": "123",
        "current_size": 4.5,
        "current_value": 9.0,
    }
    assert position_condition_id(row) == "0xcond"
    assert position_current_value(row) == pytest.approx(9.0)

    legacy = {"conditionId": "0xlegacy", "size": 2.0, "currentValue": 3.0}
    assert position_condition_id(legacy) == "0xlegacy"
    assert position_current_value(legacy) == pytest.approx(3.0)
