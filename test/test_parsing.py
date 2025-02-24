import json
import logging
import os
import unittest

from shortener.app import app
from shortener.shortng import (ErrMsg, _is_editable_password, logger,
                               _parse_request, _parse_state, RequestSource, CLIO_URL)

FILENAME = "test-filename"
TITLE = "This is a test title"
PASSWORD = "myTestPassword"
# this is not a valid neuroglancer link, but it's enough for testing parsing
LINK = "http://neuroglancer.janelia.org"

# for testing:
HEMIBRAIN_URL = "https://neuroglancer-demo.appspot.com/"

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

class RequestParsingTestCase(unittest.TestCase):
    """
    testing request parsing only--no link will be created; as such,
    the values can be simple:
    - the endpoint doesn't matter
    - the method (POST, etc) doesn't matter
    - LINK is not a valid neuroglancer state
    """
    def setUp(self):
        logger.setLevel(logging.WARNING)

    def test_parse_web(self):
        with app.test_request_context("/shortng",
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
            self.assertTrue(filename == f"{FILENAME}.json")
            self.assertTrue(title == TITLE)
            self.assertTrue(password == PASSWORD)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.WEB)

    def test_parse_web_no_link(self):
        with app.test_request_context("/shortng",
            headers=WEB_HEADERS,
            data={
                "filename": FILENAME,
                "title": TITLE,
                "password": PASSWORD,
                "client": "web",
            },
            ):
            self.assertRaises(ErrMsg, _parse_request)

    def test_parse_web_no_filename_title_pwd(self):
        with app.test_request_context("/shortng",
            headers=WEB_HEADERS,
            data={
                "text": LINK,
                "client": "web",
            },
            ):
            filename, title, password, link, source = _parse_request()
            self.assertTrue(filename.endswith(".json"))
            self.assertIs(title, None)
            self.assertIs(password, None)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.WEB)

    def test_parse_slack(self):
        with app.test_request_context("/shortng",
            headers=SLACK_HEADERS,
            data={
                "text": f"{FILENAME} {LINK}",
            },
            ):
            filename, title, password, link, source = _parse_request()
            self.assertTrue(filename == f"{FILENAME}.json")
            self.assertIs(title, None)
            self.assertIs(password, None)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.SLACK)

    def test_parse_slack_no_link(self):
        with app.test_request_context("/shortng",
            headers=SLACK_HEADERS,
            data={
                "text": "",
            },
            ):
            self.assertRaises(ErrMsg, _parse_request)

    def test_parse_slack_no_filename(self):
        with app.test_request_context("/shortng",
            headers=SLACK_HEADERS,
            data={
                "text": f"{LINK}",
            },
            ):
            filename, title, password, link, source = _parse_request()
            self.assertTrue(filename.endswith(".json"))
            self.assertIs(title, None)
            self.assertIs(password, None)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.SLACK)

    def test_parse_api_text(self):
        with app.test_request_context("/shortng",
            headers=WEB_HEADERS,
            data={
                "filename": FILENAME,
                "title": TITLE,
                "password": PASSWORD,
                "text": LINK,
            },
            ):
            filename, title, password, link, source = _parse_request()
            self.assertTrue(filename == f"{FILENAME}.json")
            self.assertTrue(title == TITLE)
            self.assertTrue(password == PASSWORD)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.API_PLAIN)

    def test_parse_api_text_no_filename_title_pwd(self):
        with app.test_request_context("/shortng",
            headers=WEB_HEADERS,
            data={
                "text": LINK,
            },
            ):
            filename, title, password, link, source = _parse_request()
            self.assertTrue(filename.endswith(".json"))
            self.assertIs(title, None)
            self.assertIs(password, None)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.API_PLAIN)

    def test_parse_api_text_no_link(self):
        with app.test_request_context("/shortng",
            headers=WEB_HEADERS,
            data={
                "filename": FILENAME,
                "title": TITLE,
            },
            ):
            self.assertRaises(ErrMsg, _parse_request)

    def test_parse_api_json(self):
        with app.test_request_context("/shortng",
            headers=API_HEADERS,
            data=json.dumps({
                "filename": FILENAME,
                "title": TITLE,
                "password": PASSWORD,
                "text": LINK,
            }),
            ):
            filename, title, password, link, source = _parse_request()
            self.assertTrue(filename == f"{FILENAME}.json")
            self.assertTrue(title == TITLE)
            self.assertTrue(password == PASSWORD)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.API_JSON)

    def test_parse_api_json_no_filename_title(self):
        with app.test_request_context("/shortng",
            headers=API_HEADERS,
            data=json.dumps({
                "text": LINK,
            }),
            ):
            filename, title, password, link, source = _parse_request()
            self.assertTrue(filename.endswith(".json"))
            self.assertIs(title, None)
            self.assertIs(password, None)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.API_JSON)

    def test_parse_api_json_no_link(self):
        with app.test_request_context("/shortng",
            headers=API_HEADERS,
            data=json.dumps({
                "filename": FILENAME,
                "title": TITLE,
            }),
            ):
            self.assertRaises(ErrMsg, _parse_request)

class StateParsingTestCase(unittest.TestCase):
    """
    testing state parsing only--no link will be created
    """
    def setUp(self):
        logger.setLevel(logging.WARNING)
        test_dir_base = os.path.dirname(__file__)
        self.hemibrain_link = open(os.path.join(test_dir_base, "default-hemibrain-url.txt"), 'rt').read()
        self.hemibrain_json = json.loads(open(os.path.join(test_dir_base, "default-hemibrain-url.json"), 'rt').read())

    def test_parse_link(self):
        url, state = _parse_state(self.hemibrain_link)
        self.assertEqual(url, HEMIBRAIN_URL)
        self.assertEqual(state, self.hemibrain_json)

    def test_parse_link_invalid(self):
        # there are lots of ways this can fail; just try one
        self.assertRaises(ErrMsg, _parse_state, "https://not a valid link/jsonstuff")

    def test_parse_json(self):
        url, state = _parse_state(json.dumps(self.hemibrain_json))
        self.assertEqual(url, CLIO_URL)
        self.assertEqual(state, self.hemibrain_json)

    def test_parse_json_invalid(self):
        self.assertRaises(ErrMsg, _parse_state, "{'this isn't really': 'json', ][ 123}")

    def test_parse_short_link(self):
        url_base, state = _parse_state("https://clio-ng.janelia.org/#!gs://flyem-user-links/short/djo-test-hemibrain.json")
        self.assertEqual(url_base, "https://clio-ng.janelia.org/")
        self.assertEqual(state, self.hemibrain_json)

    def test_parse_short_link_other_neuroglancer(self):
        # check we can parse short links from other neuroglancer instances
        url_base, state = _parse_state("https://neuroglancer-demo.appspot.com/#!gs://flyem-user-links/short/djo-test-hemibrain.json")
        self.assertEqual(url_base, "https://neuroglancer-demo.appspot.com/")
        self.assertEqual(state, self.hemibrain_json)

    def test_parse_short_link_invalid(self):
        self.assertRaises(ErrMsg, _parse_state, "https://clio-ng.janelia.org/#!gs://flyem-user-links/short/no-such-link-exists")

class RequestPasswordChecking(unittest.TestCase):
    """
    testing password checking only--no link will be created

    if we end up with a few more password-related tests, they should
    probably be moved to a separate file instead of here with the parsing
    """
    def setUp(self):
        logger.setLevel(logging.WARNING)

    def test_check_password(self):
        # this is a known stored password
        self.assertTrue(_is_editable_password("djo-test-pwd", "pwd-pwd"))
        self.assertFalse(_is_editable_password("djo-test-pwd", "wrong-pwd"))


if __name__ == '__main__':
    unittest.main()
