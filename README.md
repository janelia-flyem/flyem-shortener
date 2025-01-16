flyem-shortener
===============

**in progress**

This service generates short URLs for neuroglancer views, which are encoded in very long URLs. This functionality was originally housed in a [repository on Neuroglancer Hub](https://github.com/neuroglancerhub/ngsupport) and was split off from it. This repository generates a container that can be used with Google's "Cloud Run" service to run the link shortener.

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

