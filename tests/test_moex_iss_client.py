import responses

from moex_carry.data.moex_iss import MoexIssClient


def test_parse_table():
    payload = {"securities": {"columns": ["SECID", "SHORTNAME"], "data": [["SBER", "Sberbank"]]}}
    client = MoexIssClient("https://iss.moex.com")
    parsed = client._parse_table(payload, "securities")
    assert parsed[0]["SECID"] == "SBER"


@responses.activate
def test_get_securities():
    payload = {"securities": {"columns": ["SECID"], "data": [["SBER"]]}}
    responses.add(
        responses.GET,
        "https://iss.moex.com/iss/engines/stock/markets/shares/securities.json",
        json=payload,
        status=200,
    )
    client = MoexIssClient("https://iss.moex.com")
    data = client.get_securities("stock", "shares")
    assert data[0]["SECID"] == "SBER"
