from unittest.mock import patch

import pytest
from flask import session

from app import app, get_new_token, get_valid_token, process_file


@pytest.fixture
def client():
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_requests_post():
    with patch("app.requests.post") as mock_post:
        yield mock_post


@pytest.fixture
def mock_requests_get():
    with patch("app.requests.get") as mock_get:
        yield mock_get


@pytest.fixture
def mock_get_valid_token():
    with patch("app.get_valid_token") as mock_token:
        yield mock_token


def test_home_route(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"<title>DOOPT LO map</title>" in response.data


def test_get_new_token_success(mock_requests_post):
    mock_requests_post.return_value.status_code = 200
    mock_requests_post.return_value.json.return_value = {"accessToken": "fake-token"}

    with app.test_request_context():
        token = get_new_token()

        assert token == "fake-token"
        assert session["token"] == "fake-token"
        assert "token_time" in session


def test_get_new_token_failure(mock_requests_post):
    mock_requests_post.return_value.status_code = 400
    token = get_new_token()
    assert token is None


def test_get_valid_token_success(mock_requests_post):
    mock_requests_post.return_value.status_code = 200
    mock_requests_post.return_value.json.return_value = {"accessToken": "fake-token"}

    with app.test_request_context():
        token = get_valid_token()

        assert token == "fake-token"
        assert session["token"] == "fake-token"


def test_get_valid_token_failure(mock_requests_post):
    mock_requests_post.return_value.status_code = 400
    mock_requests_post.return_value.json.return_value = {"error": "Invalid credentials"}

    with app.test_request_context():
        token = get_valid_token()
        assert token is None
        assert "token" not in session


def test_get_data_route_invalid_type(client):
    response = client.get("/api/getDataTable?type=invalid_type")
    assert response.status_code == 400
    assert b"Invalid type parameter" in response.data


def test_process_file_gpx(mock_requests_get):
    mock_requests_get.return_value.status_code = 200
    mock_requests_get.return_value.content = (
        b"<gpx><trk><trkseg><trkpt lon='12.34' lat='56.78'></trkpt></trkseg></trk></gpx>"
    )

    result = process_file("fake_url", {"name": "test"})

    assert result is not None
    assert result["features"]
