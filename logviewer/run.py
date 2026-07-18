import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("FLASK_ENV") == "development"

    if debug:
        app.run(host="0.0.0.0", port=port, debug=True)
    else:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=4)
