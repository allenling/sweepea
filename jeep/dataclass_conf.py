
import os
import json
import dataclasses
import types
import typing

from .common_utils import json_dumps


def dataclass_from_dict(klass, d):
    # https://stackoverflow.com/a/54769644/3197067
    try:
        data = {}
        alias = False
        alias_list = False
        if isinstance(klass, types.GenericAlias):
            alias = True
            if typing.get_origin(klass) == list:
                alias_list = True
                klass = typing.get_args(klass)[0]
        fieldtypes = {f.name: f.type for f in dataclasses.fields(klass)}
        if alias and alias_list:
            ret = []
            for item in d:
                ret.append(dataclass_from_dict(klass, item))
            return ret
        else:
            s1 = set(d.keys())
            s2 = set(fieldtypes.keys())
            missing = s2 - s1
            if missing:
                raise KeyError(f"缺少 keys {missing}")
            for f in d:
                data[f] = dataclass_from_dict(fieldtypes[f], d[f])
        d = klass(**data)
    except TypeError:
        pass  # Not a dataclass field
    return d


class ConfigAbs:
    env_prefix = None

    @classmethod
    def from_dict(cls, d):
        return dataclass_from_dict(cls, d)

    def to_dict(self):
        return dataclasses.asdict(self)

    def to_str(self):
        return json_dumps(self.to_dict())

    @classmethod
    def from_str(cls, val):
        return cls(**json.loads(val))

    @classmethod
    def from_str_to_dict(cls, val):
        return cls.from_str(val).to_dict()

    @classmethod
    def get_keys(cls):
        return list(cls.__dataclass_fields__.keys())

    @classmethod
    def from_env(cls, prefix=None):
        p = cls.env_prefix
        if prefix:
            p = f"{prefix}:{p}"
        ret = {}
        fs = dataclasses.fields(cls)
        for f in fs:
            if issubclass(f.type, ConfigAbs):
                val = f.type.from_env(p)
            else:
                key = f"{p}.{f.name}"
                val = os.environ.get(key, None)
                if not val:
                    continue
            ret[f.name] = val
        return cls(**ret)




def main():
    return


if __name__ == "__main__":
    main()
