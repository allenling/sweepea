

import os
from urllib.parse import urlparse
import uuid
import json


def json_dumps(data, indent=None):
    return json.dumps(data, ensure_ascii=False, indent=indent)


def get_uuid4_str():
    return str(uuid.uuid4())


def get_filename_from_url(url):
    parsed_url = urlparse(url)
    file_name = os.path.basename(parsed_url.path)
    return file_name


def main():
    return


if __name__ == "__main__":
    main()
