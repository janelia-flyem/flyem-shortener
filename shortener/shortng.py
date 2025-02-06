import os
import logging
import datetime
import tempfile
import json
import urllib

from google.cloud import storage
from flask import Response, request, current_app, jsonify

logger = logging.getLogger(__name__)

SHORTNG_BUCKET = 'flyem-user-links'  # Owned by FlyEM-Private
SHORTENER_URL = "https://shortng-bmcp5imp6q-uc.a.run.app/shortener.html"


class ErrMsg(RuntimeError):
    def __init__(self, msg, from_slack):
        self.msg = msg
        self.from_slack = from_slack

    def response(self):
        if self.from_slack:
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
    filename, title, link, from_slack, from_web = _parse_request()
    url_base, state = _parse_state(link, from_slack)
    if title:
        state['title'] = title

    bucket_path = _upload_state(state, filename)
    url = f'{url_base}#!gs://{bucket_path}'
    logger.info(f"Completed {url}")

    if from_slack:
        return jsonify({"text": url, "response_type": "ephemeral"})
    elif from_web:
        return _web_response(url, bucket_path)
    else:
        return Response(url, 200)


def _parse_request():
    """
    Extract basic fields from the request and make
    minor tweaks to them if needed (e.g. remove spaces).

    Returns:
        (filename, title, link, from_slack, from_web)
        where from_slack means the Slackbot sent the request
        and from_web means the web UI sent the request.
    """
    from_slack = ('Slackbot' in request.headers.get('User-Agent'))
    logger.info(f"from_slack: {from_slack}")

    from_web = (request.form.get('client') == 'web')
    logger.info(f"from_web: {from_web}")

    title = request.form.get('title', None)
    if 'text' in request.form:
        # https://api.slack.com/interactivity/slash-commands#app_command_handling
        data = request.form['text'].strip()
    else:
        # For simple testing.
        data = request.data.decode('utf-8').strip()

    data = data.replace('`', '').strip()
    if data == "" and from_slack:
        msg = (
            "No link provided. Use one of the following formats:\n"
            "```/shortng my-filename https://clio-ng.janelia.org/...```\n\n"
            "```/shortng https://clio-ng.janelia.org/...```\n\n"
            "Alternatively, try the web interface:\n"
            f"{SHORTENER_URL}")
        raise ErrMsg(msg, from_slack)

    name_and_link = data.split(' ')
    if len(name_and_link) == 0:
        raise ErrMsg("Error: No link provided", from_slack)

    if len(name_and_link) == 1 or name_and_link[0] == '{':
        filename = request.form.get('filename', None)
        filename = filename or datetime.datetime.now().strftime('%Y-%m-%d.%H%M%S.%f')
        link = data
    else:
        filename = name_and_link[0]
        link = data[len(filename):].strip()

    if not filename.endswith('.json'):
        filename += '.json'

    # We don't even handle spaces via the slack UI, but spaces
    # might be present if the user used the web UI.  Replace them.
    filename = filename.replace(' ', '_')

    return filename, title, link, from_slack, from_web


def _parse_state(link, from_slack):
    """
    Extract the neuroglancer state JSON data from the given link.
    Raise ErrMsg if something went wrong.
    """
    if link.startswith('{'):
        try:
            state = json.loads(link)
            return 'https://clio-ng.janelia.org', state
        except ValueError as ex:
            msg = (
                "It appears that JSON was provided instead of "
                f"a link, but I couldn't parse the JSON:\n{link}"
            )
            raise ErrMsg(msg, from_slack) from ex

    try:
        url_base, encoded_json = link.split('#!')
        encoded_json = urllib.parse.unquote(encoded_json)
        state = json.loads(encoded_json)
    except ValueError as ex:
        if from_slack:
            link = f"```{link}```"
        msg = f"Could not parse link:\n\n{link}"
        logger.error(msg)
        raise ErrMsg(msg, from_slack) from ex

    if not (url_base.startswith('http://') or url_base.startswith('https://')):
        msg = "Error: Filename must not contain spaces, and links must start with http or https"
        logger.error(msg)
        raise ErrMsg(msg, from_slack)

    return url_base, state


def _upload_state(state, filename):
    """
    Upload the given JSON state to a file in our (hard-coded) google storage bucket.
    """
    # HACK:
    # I store the *contents* of the credentials in the environment
    # via the CloudRun settings, but the google API wants a filepath,
    # not a JSON string.
    # So I write the JSON text into a file before uploading.
    _fd, creds_path = tempfile.mkstemp('.json')
    with open(creds_path, 'w') as f:
        f.write(os.environ['GOOGLE_APPLICATION_CREDENTIALS_CONTENTS'])
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path

    state_string = json.dumps(state, indent=2)
    _upload_to_bucket(f'short/{filename}', state_string, SHORTNG_BUCKET)

    bucket_path = f'{SHORTNG_BUCKET}/short/{filename}'
    return bucket_path


def _upload_to_bucket(blob_name, blob_contents, bucket_name):
    """
    Upload a blob of data to the specified google storage bucket.
    """
    storage_client = storage.Client.from_service_account_json(
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
    bucket = storage_client.get_bucket(bucket_name)
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
            button {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 10px 20px;
                margin: 5px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
            }
            button:hover {
                background-color: #0056b3;
            }
        </style>
        """

    page = f"""
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
                    <button onclick="window.location.href='{download_url}'">View JSON</button>
                    <button onclick="window.location.href='shortener.html'">Start Over</button>
                </h4>
            </div>
        </body>
        </html>
        """
    return Response(page, 200, mimetype='text/html')
