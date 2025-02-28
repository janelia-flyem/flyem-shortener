flyem-shortener
===============

This service generates short URLs for `neuroglancer` views, which are encoded in very long URLs. This functionality was originally housed in a [repository on Neuroglancer Hub](https://github.com/neuroglancerhub/ngsupport) and was split off from it. This repository generates a container that can be used with Google's "Cloud Run" service to run the link shortener.

# Use

The website and API share these input parameters:

- `link` (`text` for the API): This field must contain the `neuroglancer` link in one of three forms:
    - the full `neuroglancer` link, copied from the `neuroglancer` application
    - the JSON state, either copied from `neuroglancer` or created programmatically
    - a previously shortened link, which will be re-saved under the new filename
- `title` (optional): If provided, this title will appear in the browser tab or browser title bar. It will replace whatever title was specified in the input link.
- `filename`: (optional): This is the name under which the link will be saved, and it will appear in the shortened URL. If omitted, the generated filename will be based on the date and time of the request.
- `password` (optional): Optional password to allow editing (re-saving) the link with this `filename` indefinitely. See [Security](#security) below.

The `filename`, `title`, and `text` (link) fields of the web form can be prepopulated through query parameters on the URL (eg, `shortener.html?filename=my-shortened-link`). 

## API

Code for accessing the API via Python looks like this:

```python
import requests

data = {
        "text": "http://neuroglancer-url/long-json-here.json",
        "filename": "my-optional-filename",
        "title": "optional title for browser",
        "password": "myOptionalPassw0rd!",
        }
r = requests.post("http://link.shortener.URL/shortng", json=data)
print(f"link: {r.json()['link']}")
```

## Security

Links can be edited, meaning they can be re-saved with the same filename but a new link and/or title.

To prevent accidental or malicious editing, two mechanisms are in place:
- If an optional `password` is provided, later attempts to save the link with the same `filename` must also provide the `password` or they will fail.
- If a `password` was not provided, editing is only allowed for one week after the last successful edit. The time length is configurable when building the container by editing the `EDIT_EXPIRATION` variable in `shortng.py`.


# Build and deploy

To build and upload the container with Google Cloudbuild registry:

    gcloud builds submit --tag gcr.io/flyem-private/flyem-shortener

To build FASTER using the most recent container as the cache:

    gcloud builds submit --config cloudbuild.yaml


Alteratively, just use docker to build locally.

    docker build . -t gcr.io/flyem-private/flyem-shortener

Then to push to the Google Artifact Registry, you need to authenticate with Google cloud and configure Docker use those credentials:

    gcloud auth login
    gcloud auth configure-docker     # first time only

Then:

    docker push gcr.io/flyem-private/flyem-shortener


NOTE: None of the above commands will actually DEPLOY the container.
      The easiest way to do that is via the google cloud console.

# Testing

To run the (minimal, incomplete) tests:

    pip install pytest
    cd flyem-shortener
    pytest test

This must be done in an environment with the project's Python dependencies, and the Google Cloud credentials should be in `GOOGLE_APPLICATION_CREDENTIALS`.

To just run the server locally, try this:

    export GOOGLE_APPLICATION_CREDENTIALS_CONTENTS=$(cat $GOOGLE_APPLICATION_CREDENTIALS)
    gunicorn --bind 0.0.0.0:8080 --workers 4 --threads 2 shortener.app:app

...and then navigate to `http://localhost:8080` in a browser.
