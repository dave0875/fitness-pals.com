import uuid
from unittest.mock import MagicMock, patch

from app.services.influx import get_influx_client_for_user
from app.utils.security import encrypt_token
from app.models import DataSource


def test_get_influx_client_for_user():
    fake_db = MagicMock()
    user_id = uuid.uuid4()
    ds = DataSource(
        user_id=user_id,
        influx_url="http://localhost:8086",
        influx_org="test",
        influx_bucket="bucket",
        token_encrypted=encrypt_token("token"),
    )
    fake_db.query.return_value.filter.return_value.first.return_value = ds
    with patch("app.services.influx.InfluxDBClient") as client_cls:
        client = get_influx_client_for_user(fake_db, user_id)
        client_cls.assert_called_once()
