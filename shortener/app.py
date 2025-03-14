import sys
import logging

from flask import Flask
from flask_cors import CORS


def configure_default_logging():
    """
    Simple logging configuration.
    Useful for interactive terminal sessions.
    """
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s %(message)s')
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    logging.captureWarnings(True)


configure_default_logging()
logger = logging.getLogger(__name__)
app = Flask(__name__)

# No limit on form size (e.g. very long links)
app.config['MAX_FORM_MEMORY_SIZE'] = None

# TODO: Limit origin list here: CORS(app, origins=[...])
#CORS(app, origins=[r'.*\.janelia\.org', r'neuroglancer-demo\.appspot\.com'], supports_credentials=True)
CORS(app)


@app.route('/shortng', methods=['POST'])
def _shortng():
    from shortener.shortng import shortng
    return shortng()


@app.route('/')
@app.route('/shortener.html')
def _shortener():
    from shortener.shortng import shortener
    return shortener()


if __name__ == "__main__":
    print("Debug launch on http://0.0.0.0:8000")
    app.run(host='0.0.0.0', port=8000, debug=True)
