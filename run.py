import os
import logging
from app import create_app

class IgnoreOptionsFilter(logging.Filter):
    def filter(self, record):
        return '"OPTIONS ' not in record.getMessage()

logging.getLogger('werkzeug').addFilter(IgnoreOptionsFilter())

app = create_app()

if __name__ == "__main__":
    if not os.path.exists("data"):
        os.makedirs("data")

    print("--> Iniciando Monitor de Nós Modular...")

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False
    )