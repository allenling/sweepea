

import os
import logging


from olive.app import OliveOly
from olive.common import OliveAppConfig


def run():
    logging.basicConfig(level=os.environ.get("log_level", "info").upper(),
                        format="[%(asctime)s.%(msecs)03d]%(levelname)s %(process)d_%(thread)d[%(filename)s.%(funcName)s:%(lineno)d] %(message)s",
                        )
    config = OliveAppConfig.from_env()
    app = OliveOly(config)
    app.start()
    return


def main():
    run()
    return


if __name__ == "__main__":
    main()
