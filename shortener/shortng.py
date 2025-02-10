import enum
import os
import logging
import datetime
import tempfile
import json
import urllib
from textwrap import dedent

from google.cloud import storage
from flask import Response, request, current_app, jsonify

logger = logging.getLogger(__name__)

SHORTNG_BUCKET = 'flyem-user-links'  # Owned by FlyEM-Private
SHORTENER_URL = "https://shortng-bmcp5imp6q-uc.a.run.app/shortener.html"
CLIO_URL = "https://clio-ng.janelia.org/"

class RequestSource(enum.Enum):
    WEB = "web"
    SLACK = "slack"
    API_PLAIN = "api_plain"
    API_JSON = "api_json"

# expiration range on link editing; use one week
EDIT_EXPIRATION = datetime.timedelta(days=7)
# if we need effectively no expiration, use this:
# EDIT_EXPIRATION = datetime.timedelta.max

# this holds the Google Cloud Storage client, once created
_client = None

class ErrMsg(RuntimeError):
    def __init__(self, msg, source):
        self.msg = msg
        self.source = source

    def response(self):
        if self.source in [RequestSource.SLACK, RequestSource.API_JSON]:
            return jsonify({"text": self.msg, "response_type": "ephemeral"})
        return Response(self.msg, 400)


def shortener():
    return current_app.send_static_file('shortener.html')


def shortng():
    try:
        return _shortng()
    except ErrMsg as ex:
        return ex.response()
    except Exception as ex:
        logger.error(ex)
        raise


def _shortng():
    """
    Handle a request to shorten a neuroglancer link,
    which might have come from one of three sources:

    - Our web UI
    - Our Slack bot (/shortng)
    - A generic http request

    In the case of the web UI, the filename, title, and
    link text are specified in separate html form elements.

    In the case of the Slack bot, the filename and link are
    provided together, in the 'text' form element, and separated with a space.

    In the case of a generic request (mostly for testing),
    the link is in the body payload.

    If no filename is provided, we construct a filename using a timestamp.
    """
    filename, title, link, source = _parse_request()

    # check if it's a shortened link:
    if link.startswith(CLIO_URL) and link.endswith('.json'):
        url_base = CLIO_URL
        state = _get_short_link_state(link, source)
    else:
        # it's a neuroglancer link or json state
        url_base, state = _parse_state(link, source)

    if title:
        state['title'] = title

    if not _is_editable(filename):
        msg = (
            "This link is too old to be edited. Please create a new link instead."
        )
        raise ErrMsg(msg, source)

    bucket_path = _upload_state(state, filename)
    url = f'{url_base}#!gs://{bucket_path}'
    logger.info(f"Completed {url}")

    match source:
        case RequestSource.SLACK:
            return jsonify({"text": url, "response_type": "ephemeral"})
        case RequestSource.WEB:
            return _web_response(url, bucket_path)
        case RequestSource.API_PLAIN | RequestSource.API_JSON:
            return Response(url, 200)

def _get_client():
    global _client
    if _client is None:
        _client = _initialize_google_cloud_client()
    return _client

def _initialize_google_cloud_client():
    # HACK:
    # I store the *contents* of the credentials in the environment
    # via the CloudRun settings, but the google API wants a filepath,
    # not a JSON string.
    # So I write the JSON text into a file before uploading.
    _fd, creds_path = tempfile.mkstemp('.json')
    with open(creds_path, 'w') as f:
        f.write(os.environ['GOOGLE_APPLICATION_CREDENTIALS_CONTENTS'])
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path

    return storage.Client.from_service_account_json(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])


def _parse_web_request():
    title = request.form.get('title', None)
    filename = request.form.get('filename', None)
    link = (request.form.get('text', None))
    if link is not None:
        link = link.strip()
    return filename, title, link


def _parse_slack_request():
    title = None
    text_data = request.form.get('text', None)

    # remove Slack "code" formatting in the /shortng command input
    text_data.replace('`', '').strip()

    if text_data == "":
        msg = (
            "No link provided. Use one of the following formats:\n"
            f"```/shortng my-filename {CLIO_URL}...```\n\n"
            f"```/shortng {CLIO_URL}...```\n\n"
            "Alternatively, try the web interface:\n"
            f"{SHORTENER_URL}")
        raise ErrMsg(msg, RequestSource.SLACK)

    name_and_link = text_data.split(' ')
    if len(name_and_link) == 0:
        raise ErrMsg("Error: No link provided", RequestSource.SLACK)

    # Stuart gets the link from the original, unsplit data for some reason
    if len(name_and_link) == 1:
        filename = None
        link = text_data
    else:
        filename = name_and_link[0]
        link = text_data[len(filename):].strip()

    return filename, title, link


def _parse_api_request(source):
    if request.headers.get('Content-Type') == 'application/json':
        data = json.loads(request.data)
    else:
        data = request.form
    title = data.get('title', None)
    filename = data.get('filename', None)

    # we don't care if title or filename are empty, but we need a link
    link = data.get('text', None)
    if link is not None:
        link = link.strip()
    if not link:
        raise ErrMsg("No link was provided!", source)

    return filename, title, link


def _parse_request():
    """
    Extract basic fields from the request and make
    minor tweaks to them if needed (e.g. remove spaces).

    Returns:
        (filename, title, link, request source)
    """

    if "Slackbot" in request.headers.get('User-Agent'):
        source = RequestSource.SLACK
    elif request.form.get('client') == 'web':
        source = RequestSource.WEB
    elif request.headers.get('Content-Type') == 'application/json':
        source = RequestSource.API_JSON
    else:
        source = RequestSource.API_PLAIN
    logger.info(f"source: {source}")

    match source:
        case RequestSource.WEB:
            filename, title, link = _parse_web_request()
        case RequestSource.SLACK:
            filename, title, link = _parse_slack_request()
        case RequestSource.API_PLAIN | RequestSource.API_JSON:
            filename, title, link = _parse_api_request(source)
        case _:
            filename, title, link = None, None, None

    if link is None:
        raise ErrMsg("No link was provided!", source)

    return _process_filename(filename), title, link, source


def _process_filename(filename):
    """
    common filename processing steps
    """
    # default datetime filename
    if not filename:
        filename = datetime.datetime.now().strftime('%Y-%m-%d.%H%M%S.%f')

    if not filename.endswith('.json'):
        filename += '.json'

    # remove spaces from filename
    filename = filename.replace(' ', '_')

    return filename

def _parse_state(link, source):
    """
    Extract the neuroglancer state JSON data from the given link.
    Raise ErrMsg if something went wrong.
    """

    # we allow JSON to be provided directly in the link
    if link.startswith('{'):
        try:
            state = json.loads(link)
            return CLIO_URL, state
        except ValueError as ex:
            msg = (
                "It appears that JSON was provided instead of "
                f"a link, but I couldn't parse the JSON:\n{link}"
            )
            raise ErrMsg(msg, source) from ex


    # otherwise, we expect a link copied from neuroglancer
    try:
        url_base, encoded_json = link.split('#!')
        encoded_json = urllib.parse.unquote(encoded_json)
        state = json.loads(encoded_json)
    except ValueError as ex:
        if source is RequestSource.SLACK:
            link = f"```{link}```"
        msg = f"Could not parse link:\n\n{link}"
        logger.error(msg)
        raise ErrMsg(msg, source) from ex

    if not (url_base.startswith('http://') or url_base.startswith('https://')):
        msg = "Error: Filename must not contain spaces, and links must start with http or https"
        logger.error(msg)
        raise ErrMsg(msg, source)

    return url_base, state

def _get_short_link_state(link, source):
    blob_name = link.removeprefix(f"{CLIO_URL}#!gs://flyem-user-links/")
    bucket = _get_client().get_bucket(SHORTNG_BUCKET)
    blob = bucket.get_blob(blob_name)
    if blob is None or not blob.exists():
        msg = f"Could not find a link with the name {blob_name}"
        logger.error(msg)
        raise ErrMsg(msg, source)
    return json.loads(blob.download_as_bytes())


def _blob_name(filename):
    """
    Build a blob name for the given filename.
    """
    return f"short/{filename}"


def _is_editable(filename):
    """
    Determine whether the given filename is still editable.
    """

    bucket = _get_client().get_bucket(SHORTNG_BUCKET)
    blob = bucket.get_blob(_blob_name(filename))
    if blob is None or not blob.exists():
        # doesn't exist = OK to create
        return True

    created_time = blob.time_created
    return created_time + EDIT_EXPIRATION > datetime.datetime.now(datetime.timezone.utc)


def _upload_state(state, filename):
    """
    Upload the given JSON state to a file in our (hard-coded) google storage bucket.
    """

    state_string = json.dumps(state, indent=2)
    _upload_to_bucket(_blob_name(filename), state_string, SHORTNG_BUCKET)

    bucket_path = f'{SHORTNG_BUCKET}/{_blob_name(filename)}'
    return bucket_path


def _upload_to_bucket(blob_name, blob_contents, bucket_name):
    """
    Upload a blob of data to the specified google storage bucket.
    """
    bucket = _get_client().get_bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.cache_control = 'public, no-store'
    blob.upload_from_string(blob_contents, content_type='application/json')
    return blob.public_url


def _web_response(url, bucket_path):
    """
    Return a little HTML page to display the shortened URL,
    along with some convenient links.
    """
    download_url = f"https://storage.googleapis.com/{bucket_path}"

    # FIXME: The proper way to do this is with a jinja template.

    script = """
        <script type="text/javascript">
        function copy_to_clipboard(text) {
            try {
                navigator.clipboard.writeText(text);
            }
            catch (err) {
                console.error("Couldn't write to clipboard:", err)
            }
        }
        </script>
        """

    style = """
        <style>
            *{font-family: Verdana;}
            a {
                text-decoration: none
            }
        </style>
        """

    page = dedent(f"""\
        <!doctype html>
        <html>
        <head>
        <title>Shortened link</title>
        {style}
        {script}
        </head>
        <body>
        <h3>
            <a href={url}>{url}</a>
        </h3>
        <h4>
            <a href="" onclick="copy_to_clipboard('{url}'); return false;">[copy link]</a>
            <a href={download_url}>[view json]</a>
            <a href=shortener.html>[start over]</a>
        </h4>
        </body>
        </html>""")
    return Response(page, 200, mimetype='text/html')
