import datetime
import enum
import functools
import hashlib
import json
import logging
import os
import urllib
import tempfile
from textwrap import dedent

from google.cloud import storage
from flask import Response, request, jsonify, render_template

logger = logging.getLogger(__name__)

SHORTNG_BUCKET = 'flyem-user-links'  # Both buckets owned by FlyEM-Private
SHORTNG_PASSWORD_BUCKET = 'flyem-user-links-private'

BUCKET_LINK_SEPARATOR = "#!gs://"

SHORTENER_URL = "https://shortng-bmcp5imp6q-uc.a.run.app/shortener.html"
CLIO_URL = "https://clio-ng.janelia.org/"

# password hashing parameters
SALT_WIDTH = 16
DKLEN_WIDTH = 32


class RequestSource(enum.Enum):
    WEB = "web"
    SLACK = "slack"
    API_PLAIN = "api_plain"
    API_JSON = "api_json"


# expiration range on link editing; use one week
EDIT_EXPIRATION = datetime.timedelta(days=7)
# if we need effectively no expiration, use this:
# EDIT_EXPIRATION = datetime.timedelta.max


class ErrMsg(RuntimeError):
    def __init__(self, msg, source):
        self.msg = msg
        self.source = source

    def response(self):
        if self.source in [RequestSource.SLACK, RequestSource.API_JSON]:
            json_response = jsonify({"text": self.msg, "response_type": "ephemeral"})
            json_response.status_code = 400
            return json_response
        return Response(self.msg, 400)


def shortener():
    filename = request.args.get('filename', "")
    title = request.args.get('title', "")
    text = request.args.get('text', "")
    return render_template('shortener.html', filename=filename, title=title, text=text)


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
    filename, title, password, link, source = _parse_request()

    url_base, state = _parse_state(link, source)

    # check if the link has already been shortened; if it has, check if
    #   it's editable (i.e. password is correct and it's not too old)
    has_password_file = _file_exists(SHORTNG_PASSWORD_BUCKET, _password_filename(filename))
    _raise_if_not_editable(filename, has_password_file, password, source)

    if title:
        state['title'] = title

    # the actual work
    bucket_path = _upload_state(state, filename)
    url = f'{url_base}#!gs://{bucket_path}'
    logger.info(f"Completed {url}")

    # if password was provided and password file doesn't exist, store it; we store
    #    in individual files per link to avoid race conditions
    if password and not has_password_file:
        salt = _new_salt()
        hashed_password = _hash_password(password, salt)
        _store_hashed_password_salt(_password_filename(filename), hashed_password, salt)
        logger.info(f"Stored password for {_password_filename(filename)}")

    # and finally the response to the user
    match source:
        case RequestSource.SLACK:
            return jsonify({"text": url, "response_type": "ephemeral"})
        case RequestSource.WEB:
            return _web_response(url, bucket_path)
        case RequestSource.API_JSON:
            return jsonify({"link": url})
        case RequestSource.API_PLAIN:
            return Response(url, 200)


@functools.cache
def _get_client():
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
    password = request.form.get('password', "")
    link = (request.form.get('text', None))
    if link is not None:
        link = link.strip()
    return filename, title, password, link


def _parse_slack_request(source):
    text_data = request.form.get('text', None)

    # remove Slack "code" formatting in the /shortng command input
    text_data = text_data.strip(" `")

    if text_data == "":
        msg = (
            "No link provided. Use one of the following formats:\n"
            f"```/shortng my-filename {CLIO_URL}...```\n\n"
            f"```/shortng {CLIO_URL}...```\n\n"
            "Alternatively, try the web interface:\n"
            f"{SHORTENER_URL}")
        raise ErrMsg(msg, source)

    name_and_link = text_data.split(' ')
    if len(name_and_link) == 0:
        raise ErrMsg("Error: No link provided", source)

    if len(name_and_link) == 1:
        filename = None
        link = text_data
    else:
        filename = name_and_link[0]
        link = text_data[len(filename):].strip()

    # our Slackbot does not support titles or passwords at this time
    title = None
    password = ""

    return filename, title, password, link


def _parse_api_request(source):
    if request.headers.get('Content-Type') == 'application/json':
        data = json.loads(request.data)
    else:
        data = request.form
    title = data.get('title', None)
    filename = data.get('filename', None)
    password = data.get('password', "")

    # we don't care if title or filename are empty, but we need a link
    link = data.get('text', None)
    if link is not None:
        link = link.strip()
    if not link:
        raise ErrMsg("No link was provided!", source)

    return filename, title, password, link


def _parse_request():
    """
    Extract basic fields from the request and make
    minor tweaks to them if needed (e.g. remove spaces).

    Returns:
        (filename, title, password, link, request source)
    """

    if "Slackbot" in request.headers.get('User-Agent'):
        source = RequestSource.SLACK
    elif request.form.get('client') == 'web':
        source = RequestSource.WEB
    elif request.headers.get('Content-Type') == 'application/json':
        source = RequestSource.API_JSON
    else:
        source = RequestSource.API_PLAIN
    logger.info(f"Request source: {source}")

    match source:
        case RequestSource.WEB:
            filename, title, password, link = _parse_web_request()
        case RequestSource.SLACK:
            filename, title, password, link = _parse_slack_request(source)
        case RequestSource.API_PLAIN | RequestSource.API_JSON:
            filename, title, password, link = _parse_api_request(source)
        case _:
            filename, title, password, link = None, None, None, None

    if link is None:
        raise ErrMsg("No link was provided!", source)

    return _process_filename(filename), title, password, link, source


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
    Extract the neuroglancer state JSON data from the given link. Returns
    the URL base and the state JSON. Raise ErrMsg if something went wrong.
    """

    # the link could be to a previously shortened link
    if BUCKET_LINK_SEPARATOR in link:
        url_base, bucket_name, blob_name = _parse_link(link)
        data = _download_state_public(bucket_name, blob_name)
        if data is None:
            msg = f"Could not retrieve json state from bucket {bucket_name}, blob {blob_name}"
            logger.error(msg)
            raise ErrMsg(msg, source)
        return url_base, data

    # or we allow JSON to be provided directly in the link variable
    if link.startswith('{'):
        try:
            state = json.loads(link)
            # we default to the clio URL even though it could be some other neuroglancer
            return CLIO_URL, state
        except ValueError as ex:
            msg = (
                f"It appears that JSON was provided instead of a link, but I couldn't parse the JSON:\n{link}"
            )
            raise ErrMsg(msg, source) from ex

    # otherwise, we expect a link copied from neuroglancer
    try:
        url_base, encoded_json = link.split('#!')
        encoded_json = urllib.parse.unquote(encoded_json)
        state = json.loads(encoded_json)
    except ValueError as ex:
        msg = f"Could not parse link:\n\n{link}"
        logger.error(msg)
        raise ErrMsg(msg, source) from ex

    if not (url_base.startswith('http://') or url_base.startswith('https://')):
        msg = "Error: Filename must not contain spaces, and links must start with http or https"
        logger.error(msg)
        raise ErrMsg(msg, source)

    return url_base, state


def _parse_link(link):
    """
    split the link into the base url, the bucket name, and the blog name,
    regardless of which neuroglancer instance or bucket it's in
    """
    url_base, blob_name = link.split(BUCKET_LINK_SEPARATOR)
    bucket_name, blob_name = blob_name.split('/', 1)
    return url_base, bucket_name, blob_name


def _blob_name(filename):
    return f"short/{filename}"


def _password_filename(filename):
    return filename.removesuffix('.json')


def _file_exists(bucket_name, filename):
    """
    Determine whether a file exists for the given filename.
    """
    bucket = _get_client().get_bucket(bucket_name)
    blob = bucket.get_blob(_blob_name(filename))
    return blob is not None and blob.exists()


def _get_stored_hashed_password(filename, source):
    bucket = _get_client().get_bucket(SHORTNG_PASSWORD_BUCKET)
    blob_name = _blob_name(filename)
    blob = bucket.get_blob(blob_name)
    if blob is None or not blob.exists():
        msg = f"Could not retrieve password file with the name {blob_name} in {SHORTNG_PASSWORD_BUCKET}"
        logger.error(msg)
        raise ErrMsg(msg, source)
    data = blob.download_as_bytes()
    return data[:DKLEN_WIDTH], data[DKLEN_WIDTH:]


def _store_hashed_password_salt(password_filename, hashed_password, salt):
    """
    Store the given password (hashed) and salt in the password bucket.
    """
    data = hashed_password + salt
    blob_name = _blob_name(password_filename)
    _upload_to_bucket(blob_name, data, SHORTNG_PASSWORD_BUCKET)


def _is_editable_password(password_filename, password, source):
    """
    Determine whether the given filename is still editable based on password.
    """

    # this check is currently redundant, but leaving it in for safety
    if not _file_exists(SHORTNG_PASSWORD_BUCKET, password_filename):
        return True

    stored_hashed_password, stored_salt = _get_stored_hashed_password(password_filename, source)
    hashed_input_password = _hash_password(password, stored_salt)
    return stored_hashed_password == hashed_input_password


def _raise_if_not_editable(filename, has_password_file, password, source):
    """
    Raise an error if the given filename is not editable due to password
    or age restrictions.
    """
    if _file_exists(SHORTNG_BUCKET, filename):
        if has_password_file:
            # check pwd
            if not _is_editable_password(_password_filename(filename), password, source):
                msg = (
                    f"A password is required to overwite the link with filename {filename}. The provided password is missing or incorrect."
                )
                raise ErrMsg(msg, source)
        else:
            # no password; check time
            if not _is_editable_age(filename):
                msg = (
                    f"This link was last saved more than {EDIT_EXPIRATION} ago and cannot be resaved. Please create a new link instead, "
                    f"or contact the site admin to reset the editing period. Note that links with passwords can "
                    f"be edited indefinitely."
                )
                raise ErrMsg(msg, source)


def _is_editable_age(filename):
    """
    Determine whether the given filename is still editable based on last edit time.
    """

    bucket = _get_client().get_bucket(SHORTNG_BUCKET)
    blob = bucket.get_blob(_blob_name(filename))
    if blob is None or not blob.exists():
        # doesn't exist = OK to edit/create
        return True

    created_time = blob.time_created
    return created_time + EDIT_EXPIRATION > datetime.datetime.now(datetime.timezone.utc)


def _new_salt():
    return os.urandom(SALT_WIDTH)


def _hash_password(password, salt):
    """
    Hash the given password, and return the salt and hashed password.
    """
    hashed_password = hashlib.scrypt(bytes(password, encoding='utf-8'), salt=salt, n=16384, r=8, p=1, dklen=DKLEN_WIDTH)
    return hashed_password


def _download_state_public(bucket_name, blob_name):
    """
    download the given JSON state from a google bucket via a public URL
    """
    url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
    try:
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read())
    except Exception as e:
        logger.error(f"Error downloading json state from {url}: {e}")
        return None


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
    along with some convenient buttons.
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
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #f0f2f5;
                margin: 0;
                padding: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
            }
            .container {
                background-color: #ffffff;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                max-width: 500px;
                width: 100%;
                text-align: center;
            }
            h3, h4 {
                color: #333;
                margin: 10px 0;
            }
            button, .button {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 10px 20px;
                margin: 5px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
                font-weight: normal;
                text-decoration:none;
            }
            button:hover, .button:hover {
                background-color: #0056b3;
            }
        </style>
        """

    page = dedent(f"""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Shortened link</title>
            {style}
            {script}
        </head>
        <body>
            <div class="container">
                <h3>Your shortened link:</h3>
                <p><a href="{url}">{url}</a></p>
                <h4>
                    <button onclick="copy_to_clipboard('{url}'); return false;">Copy Link</button>
                    <a class="button" href="{download_url}">View JSON</a>
                    <a class="button" href="shortener.html">Start Over</a>
                </h4>
            </div>
        </body>
        </html>
        """)
    return Response(page, 200, mimetype='text/html')
