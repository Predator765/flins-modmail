import logging
import os
from threading import Thread

from flask import Flask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("keep_alive")

app = Flask(__name__)


@app.route("/")
@app.route("/<path:_p>")
def _alive(_p=""):
    return (
        "<!doctype html><html><head><title>Modmail Bot</title></head>"
        "<body style='font-family:sans-serif;background:#0e1014;color:#dbdee1;"
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
        "<div style='text-align:center'>"
        "<h1>Bot is running</h1>"
        "</div></body></html>"
    )


def run_server():
    from waitress import serve
    port = int(os.environ.get("PORT", 5000))
    logger.info("Keep-alive server started on port %d", port)
    serve(app, host="0.0.0.0", port=port, threads=2)


def keep_alive():
    thread = Thread(target=run_server, daemon=True)
    thread.start()
