

import selectors


class PeaSelectorStorage(selectors._BaseSelectorImpl):

    def get_key_from_fileno(self, fileno):
        return self._fd_to_key.get(fileno, None)

    def register(self, *args, **kwargs):
        ret = super(PeaSelectorStorage, self).register(*args, **kwargs)
        return ret

    def unregister(self, *args, **kwargs):
        ret = super(PeaSelectorStorage, self).unregister(*args, **kwargs)
        return ret

    def select(self, *args, **kwargs):
        return



def main():
    return


if __name__ == "__main__":
    main()
