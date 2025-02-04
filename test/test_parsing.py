import json
import logging
import unittest

from shortener.app import app
from shortener.shortng import ErrMsg, logger, _parse_request, RequestSource

FILENAME = "test-filename"
TITLE = "This is a test title"
# this is not a valid neuroglancer link, but it's enough for testing parsing
LINK = "http://neuroglancer.janelia.org"
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

class ParsingTestCase(unittest.TestCase):
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
                "text": LINK,
                "client": "web",
            },
            ):
            filename, title, link, source = _parse_request()
            self.assertTrue(filename == f"{FILENAME}.json")
            self.assertTrue(title == TITLE)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.WEB)

    def test_parse_web_no_link(self):
        with app.test_request_context("/shortng",
            headers=WEB_HEADERS,
            data={
                "filename": FILENAME,
                "title": TITLE,
                "client": "web",
            },
            ):
            self.assertRaises(ErrMsg, _parse_request)

    def test_parse_web_no_filename_title(self):
        with app.test_request_context("/shortng",
            headers=WEB_HEADERS,
            data={
                "text": LINK,
                "client": "web",
            },
            ):
            filename, title, link, source = _parse_request()
            self.assertTrue(filename.endswith(".json"))
            self.assertIs(title, None)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.WEB)

    def test_parse_slack(self):
        with app.test_request_context("/shortng",
            headers=SLACK_HEADERS,
            data={
                "text": f"{FILENAME} {LINK}",
            },
            ):
            filename, title, link, source = _parse_request()
            self.assertTrue(filename == f"{FILENAME}.json")
            self.assertIs(title, None)
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
            filename, title, link, source = _parse_request()
            self.assertTrue(filename.endswith(".json"))
            self.assertIs(title, None)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.SLACK)

    def test_parse_api_text(self):
        with app.test_request_context("/shortng",
            headers=WEB_HEADERS,
            data={
                "filename": FILENAME,
                "title": TITLE,
                "text": LINK,
            },
            ):
            filename, title, link, source = _parse_request()
            self.assertTrue(filename == f"{FILENAME}.json")
            self.assertTrue(title == TITLE)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.API_PLAIN)

    def test_parse_api_text_no_filename_title(self):
        with app.test_request_context("/shortng",
            headers=WEB_HEADERS,
            data={
                "text": LINK,
            },
            ):
            filename, title, link, source = _parse_request()
            self.assertTrue(filename.endswith(".json"))
            self.assertIs(title, None)
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
                "text": LINK,
            }),
            ):
            filename, title, link, source = _parse_request()
            self.assertTrue(filename == f"{FILENAME}.json")
            self.assertTrue(title == TITLE)
            self.assertTrue(link == LINK)
            self.assertIs(source, RequestSource.API_JSON)

    def test_parse_api_json_no_filename_title(self):
        with app.test_request_context("/shortng",
            headers=API_HEADERS,
            data=json.dumps({
                "text": LINK,
            }),
            ):
            filename, title, link, source = _parse_request()
            self.assertTrue(filename.endswith(".json"))
            self.assertIs(title, None)
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


if __name__ == '__main__':
    unittest.main()
