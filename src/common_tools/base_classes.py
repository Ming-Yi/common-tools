__all__ = ["SingletonMeta", "StaticUtils"]


class SingletonMeta(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class StaticUtils(object):
    """
    A base class for static utility classes.
    - Cannot be instantiated.
    - Designed to be inherited by specific utility classes.
    """

    def __new__(cls, *args, **kwargs):
        if cls is StaticUtils:
            raise RuntimeError("StaticUtils is an abstract base and cannot be instantiated directly")
        return super().__new__(cls)
