

import os
import logging
import threading
import importlib


logger = logging.getLogger(__file__)


def import_and_run(func, *args, **kwargs):
    logger.debug(f"import_and_run, pid: {os.getpid()}, thread id {threading.get_ident()}")
    path_list = func.split(".")
    func_module, func_name = ".".join(path_list[:-1]), path_list[-1]
    m = importlib.import_module(func_module)
    func = getattr(m, func_name)
    func(*args, **kwargs)
    return




def main():
    return


if __name__ == "__main__":
    main()
