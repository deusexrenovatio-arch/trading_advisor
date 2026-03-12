from moex_carry.config import AppSettings, DataConfig
from moex_carry.server import create_server_app as create_app


def test_params_specs_api_returns_list(tmp_path):
    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    response = client.get("/api/params/specs")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) > 0

