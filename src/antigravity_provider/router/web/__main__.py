import sys
import logging
from antigravity_provider.router.web.server import run_server

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    run_server()
