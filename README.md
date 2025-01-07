flyem-shortener
===============

**in progress**

This service generates short URLs for neuroglancer views, which are encoded in very long URLs.

This functionality was originally housed in a [repository on Neuroglancer Hub](https://github.com/neuroglancerhub/ngsupport) and is being split off from it.





## Original README:

Serverless utilties to support neuroglancer-based proofreading,
based on Google's "Cloud Run" service.

This directory contains the setup for a container that can be used with
Google's "Cloud Run" service to run various serverless cloud functions
that support our neuroglancer-based proofreading protocols, such as
generating meshes on-the-fly (and storing them to DVID).

To build and upload container with Google Cloudbuild registry:

    gcloud builds submit --tag gcr.io/flyem-private/ngsupport

To build FASTER using the most recent container as the cache:

    gcloud builds submit --config cloudbuild.yaml

NOTE: Neither of the above commands will actually DEPLOY the container.
      The easiest way to do that is via the google cloud console.


Alteratively, just use docker to build locally:

    docker build . -t gcr.io/flyem-private/ngsupport
    docker push  gcr.io/flyem-private/ngsupport
