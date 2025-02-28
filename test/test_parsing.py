import json
import logging
import os
from pathlib import Path

import pytest

from shortener.app import app
from shortener.shortng import (ErrMsg, _is_editable_password, logger, _parse_link,
                               _parse_request, _parse_state, RequestSource, CLIO_URL)

FILENAME = "test-filename"
TITLE = "This is a test title"
PASSWORD = "myTestPassword"
# this is not a valid neuroglancer link, but it's enough for testing parsing
LINK = "http://neuroglancer.janelia.org"

# for testing:
HEMIBRAIN_DOMAIN = "https://neuroglancer-demo.appspot.com/"

WEB_HEADERS = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0',
    }

API_HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0',
    }

SLACK_HEADERS = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'User-Agent': 'Slackbot',
    }


@pytest.fixture(autouse=True)
def setup_logger():
    logger.setLevel(logging.WARNING)


@pytest.fixture(autouse=True)
def setup_credentials():
    with open(os.environ['GOOGLE_APPLICATION_CREDENTIALS'], 'r') as f:
        os.environ['GOOGLE_APPLICATION_CREDENTIALS_CONTENTS'] = f.read()


@pytest.fixture
def hemibrain_data():
    test_dir_base = os.path.dirname(__file__)

    hemibrain_link = open(
        Path(test_dir_base) / "default-hemibrain-url.txt",
        'rt',
        encoding='utf-8'
    ).read()

    hemibrain_json = json.loads(
        open(
            Path(test_dir_base) / "default-hemibrain-url.json",
            'rt',
            encoding='utf-8'
        ).read()
    )
    return hemibrain_link, hemibrain_json


def test_parse_web():
    with app.test_request_context(
        "/shortng",
        headers=WEB_HEADERS,
        data={
            "filename": FILENAME,
            "title": TITLE,
            "password": PASSWORD,
            "text": LINK,
            "client": "web",
        },
    ):
        filename, title, password, link, source = _parse_request()
        assert filename == f"{FILENAME}.json"
        assert title == TITLE
        assert password == PASSWORD
        assert link == LINK
        assert source is RequestSource.WEB


def test_parse_web_no_link():
    with app.test_request_context(
        "/shortng",
        headers=WEB_HEADERS,
        data={
            "filename": FILENAME,
            "title": TITLE,
            "password": PASSWORD,
            "client": "web",
        },
    ):
        with pytest.raises(ErrMsg):
            _parse_request()


def test_parse_web_no_filename_title_pwd():
    with app.test_request_context(
        "/shortng",
        headers=WEB_HEADERS,
        data={
            "text": LINK,
            "client": "web",
        },
    ):
        filename, title, password, link, source = _parse_request()
        assert filename.endswith(".json")
        assert title is None
        assert password == ""
        assert link == LINK
        assert source is RequestSource.WEB


def test_parse_slack():
    with app.test_request_context(
        "/shortng",
        headers=SLACK_HEADERS,
        data={
            "text": f"{FILENAME} {LINK}",
        },
    ):
        filename, title, password, link, source = _parse_request()
        assert filename == f"{FILENAME}.json"
        assert title is None
        assert password == ""
        assert link == LINK
        assert source is RequestSource.SLACK


def test_parse_slack_no_link():
    with app.test_request_context(
        "/shortng",
        headers=SLACK_HEADERS,
        data={
            "text": "",
        },
    ):
        with pytest.raises(ErrMsg):
            _parse_request()


def test_parse_slack_no_filename():
    with app.test_request_context(
        "/shortng",
        headers=SLACK_HEADERS,
        data={
            "text": f"{LINK}",
        },
    ):
        filename, title, password, link, source = _parse_request()
        assert filename.endswith(".json")
        assert title is None
        assert password == ""
        assert link == LINK
        assert source is RequestSource.SLACK


def test_parse_api_text():
    with app.test_request_context(
        "/shortng",
        headers=WEB_HEADERS,
        data={
            "filename": FILENAME,
            "title": TITLE,
            "password": PASSWORD,
            "text": LINK,
        },
    ):
        filename, title, password, link, source = _parse_request()
        assert filename == f"{FILENAME}.json"
        assert title == TITLE
        assert password == PASSWORD
        assert link == LINK
        assert source is RequestSource.API_PLAIN


def test_parse_api_text_no_filename_title_pwd():
    with app.test_request_context(
        "/shortng",
        headers=WEB_HEADERS,
        data={
            "text": LINK,
        },
    ):
        filename, title, password, link, source = _parse_request()
        assert filename.endswith(".json")
        assert title is None
        assert password == ""
        assert link == LINK
        assert source is RequestSource.API_PLAIN


def test_parse_api_text_no_link():
    with app.test_request_context(
        "/shortng",
        headers=WEB_HEADERS,
        data={
            "filename": FILENAME,
            "title": TITLE,
        },
    ):
        with pytest.raises(ErrMsg):
            _parse_request()


def test_parse_api_json():
    with app.test_request_context(
        "/shortng",
        headers=API_HEADERS,
        data=json.dumps({
            "filename": FILENAME,
            "title": TITLE,
            "password": PASSWORD,
            "text": LINK,
        }),
    ):
        filename, title, password, link, source = _parse_request()
        assert filename == f"{FILENAME}.json"
        assert title == TITLE
        assert password == PASSWORD
        assert link == LINK
        assert source is RequestSource.API_JSON


def test_parse_api_json_no_filename_title():
    with app.test_request_context(
        "/shortng",
        headers=API_HEADERS,
        data=json.dumps({
            "text": LINK,
        }),
    ):
        filename, title, password, link, source = _parse_request()
        assert filename.endswith(".json")
        assert title is None
        assert password == ""
        assert link == LINK
        assert source is RequestSource.API_JSON


def test_parse_api_json_no_link():
    with app.test_request_context(
        "/shortng",
        headers=API_HEADERS,
        data=json.dumps({
            "filename": FILENAME,
            "title": TITLE,
        }),
    ):
        with pytest.raises(ErrMsg):
            _parse_request()


def test_parse_link(hemibrain_data):
    hemibrain_link, hemibrain_json = hemibrain_data
    domain, state = _parse_state(hemibrain_link, RequestSource.WEB)
    assert domain == HEMIBRAIN_DOMAIN
    assert state == hemibrain_json


def test_parse_link_invalid():
    # there are lots of ways this can fail; just try one
    with pytest.raises(ErrMsg):
        _parse_state("https://not a valid link/jsonstuff", RequestSource.WEB)


def test_parse_json(hemibrain_data):
    _, hemibrain_json = hemibrain_data
    url, state = _parse_state(json.dumps(hemibrain_json), RequestSource.API_JSON)
    assert url == CLIO_URL
    assert state == hemibrain_json


def test_parse_json_invalid():
    with pytest.raises(ErrMsg):
        _parse_state("{'this isn't really': 'json', ][ 123}", RequestSource.API_JSON)


def test_parse_short_link(hemibrain_data):
    _, hemibrain_json = hemibrain_data
    url_base, state = _parse_state("https://clio-ng.janelia.org/#!gs://flyem-user-links/short/djo-test-hemibrain.json", RequestSource.WEB)
    assert url_base == "https://clio-ng.janelia.org/"
    assert state == hemibrain_json


def test_parse_short_link_other_neuroglancer(hemibrain_data):
    # check we can parse short links from other neuroglancer instances
    _, hemibrain_json = hemibrain_data
    url_base, state = _parse_state("https://neuroglancer-demo.appspot.com/#!gs://flyem-user-links/short/djo-test-hemibrain.json", RequestSource.WEB)
    assert url_base == "https://neuroglancer-demo.appspot.com/"
    assert state == hemibrain_json


def test_parse_short_link_invalid():
    with pytest.raises(ErrMsg):
        _parse_state("https://clio-ng.janelia.org/#!gs://flyem-user-links/short/no-such-link-exists", RequestSource.WEB)


def test_parse_short_link_main_bucket():
    # test we are not sensitive to the bucket name (this test and next one)
    url_base, bucket_name, blob_name = _parse_link("https://clio-ng.janelia.org/#!gs://flyem-user-links/short/djo-test-hemibrain.json")
    assert url_base == "https://clio-ng.janelia.org/"
    assert bucket_name == "flyem-user-links"
    assert blob_name == "short/djo-test-hemibrain.json"


def test_parse_short_link_other_bucket():
    url_base, bucket_name, blob_name = _parse_link("https://neuroglancer-demo.appspot.com/#!gs://flyem-views/hemibrain/v1.2/base.json")
    assert url_base == "https://neuroglancer-demo.appspot.com/"
    assert bucket_name == "flyem-views"
    assert blob_name == "hemibrain/v1.2/base.json"


def test_check_password():
    # this is a known stored password
    assert _is_editable_password("djo-test-pwd", "pwd-pwd", RequestSource.WEB)
    assert not _is_editable_password("djo-test-pwd", "wrong-pwd", RequestSource.WEB)
