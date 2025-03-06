FROM python:3.12

# this container was originally based on centos:8; the python image
#   is debian; not sure if the encoding and timezone lines are needed,
#   but I've left them in

# Set an encoding to make things work smoothly.
ENV LANG=en_US.UTF-8

# Set timezone to EST/EDT
RUN rm /etc/localtime \
 && ln -s /usr/share/zoneinfo/EST5EDT /etc/localtime

# Technically we don't need to copy requirements.in,
# but it might be nice to see when debugging.
COPY requirements.in .

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy local code to the container image.
ENV APP_HOME=/shortener-home
WORKDIR $APP_HOME
COPY shortener ${APP_HOME}/shortener

ENV PYTHONPATH=${APP_HOME}

# Run the web service on container startup. Here we use the gunicorn
# webserver, with one worker process and 8 threads.
# For environments with multiple CPU cores, increase the number of workers
# to be equal to the cores available.
#
#   Note
#   ----
#
#   For some reason we're seeing an error:
#
#       Invalid ENTRYPOINT. [name: "gcr.io/flyem-private/ngsupport@sha256:cd0581de54ec430af44f959716379527ec1b116aa93602c14bc09ed6372c31cd" error: "Invalid command \"/bin/sh\": file not found" ].
#
#   And one way to fix it might be to use the 'exec' form of the CMD directive:
#   https://stackoverflow.com/questions/62158782/invalid-command-bin-sh-file-not-found
#
#   Unfortunately, that means we can't use environment variables ($FLYEM_ENV, $PORT).
#   So I'm hard-coding them for now.
#

CMD ["/usr/local/bin/gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "--threads", "2", "shortener.app:app"]

