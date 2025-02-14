flyem-shortener
===============

This service generates short URLs for `neuroglancer` views, which are encoded in very long URLs. This functionality was originally housed in a [repository on Neuroglancer Hub](https://github.com/neuroglancerhub/ngsupport) and was split off from it. This repository generates a container that can be used with Google's "Cloud Run" service to run the link shortener.

# Use

The website and API share these input parameters:

- `filename`: (optional): This is the name under which the link will be saved, and it will appear in the shortened URL. If omitted, it will be based on the date and time of the request.
- `title` (optional): If provided, this title will appear in the browser tab or browser title bar.
- `password` (optional): Optional password to allow editing (re-saving) the link with this `filename` indefinitely. See [Security](#security) below.
- `link` (`text` for the API): This field must contain the `neuroglancer` link in one of three forms:
    - the full `neuroglancer` link, copied from the `neuroglancer` application
    - the JSON state, either copied from `neuroglancer` or created programmatically
    - a previously shortened link, which will be re-saved under the new filename


## API

Code for accessing the API in Python looks like this:

```python
import requests

data = {
        "text": "neuroglancer link",
        "filename": "my-optional-filename",
        "title": "title for browser",
        "password": "myPassw0rd!",
        }
r = requests.post("link shortener URL", json=data)
print(f"link: {r.json()['link']}")
```

## Security

Links can be edited, meaning they can be re-saved with the same filename but a new link and/or title.

To prevent accidental or malicious editing, two mechanisms are in place:
- If an optional `password` is provided, later attempts to save the link with the same `filename` must also provide the `password` or they will fail.
- If a `password` was not provided, editing is only allowed for one week after the last successful edit.


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

To run the (minimal, incomplete) tests:

    cd flyem-shortener
    python -m unittest

