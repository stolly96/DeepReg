from typing import Callable

BACKBONE_CLASS = "backbone_class"
LOSS_CLASS = "loss_class"
MODEL_CLASS = "model_class"
KNOWN_CATEGORIES = [BACKBONE_CLASS, LOSS_CLASS, MODEL_CLASS]


class Registry:
    """
    Registry maintains a dictionary which maps (category, key) to value.

    Multiple __init__.py files have been modified so that
    when executing `from deepreg.registry import REGISTRY`
    all classes have been registered.

    References:
    - https://github.com/ray-project/ray/blob/00ef1179c012719a17c147a5c3b36d6bdbe97195/python/ray/tune/registry.py#L108
    - https://github.com/open-mmlab/mmdetection/blob/master/mmdet/models/builder.py
    - https://github.com/open-mmlab/mmcv/blob/master/mmcv/utils/registry.py
    - https://towardsdatascience.com/whats-init-for-me-d70a312da583
    """

    def __init__(self):
        self._dict = {}

    def _register(self, category: str, key: str, value: Callable, force: bool):
        """
        Registers the value with the registry.
        """
        # sanity check
        if category not in KNOWN_CATEGORIES:
            raise ValueError(
                f"Unknown category {category} not among {KNOWN_CATEGORIES}"
            )
        if not force and self.contains(category=category, key=key):
            raise ValueError(
                f"Key {key} in category {category} has been registered with {self._dict[(category, key)]}"
            )
        # register value
        self._dict[(category, key)] = value

    def contains(self, category: str, key: str):
        return (category, key) in self._dict

    def get(self, category, key):
        if self.contains(category=category, key=key):
            return self._dict[(category, key)]
        raise ValueError(f"Key {key} in category {category} has not been registered.")

    def register(
        self, category: str, name: str, cls: Callable = None, force: bool = False
    ):
        """
        Register a py class.
        A record will be added to `self._dict`, whose key is the class
        name or the specified name, and value is the class itself.
        It can be used as a decorator or a normal function.

        :param category: The type of the category.
        :param name: The class name to be registered. If not specified, the class name will be used.
        :param force: Whether to override an existing class with the same name. Default: False.
        :param cls: Class to be registered.
        """
        # use it as a normal method: x.register_module(module=SomeClass)
        if cls is not None:
            self._register(category=category, key=name, value=cls, force=force)
            return cls

        # use it as a decorator: @x.register(name, category)
        def decorator(_cls):
            self._register(category=category, key=name, value=_cls, force=force)
            return _cls

        return decorator

    def register_backbone(self, name: str, cls: Callable = None, force: bool = False):
        return self.register(category=BACKBONE_CLASS, name=name, cls=cls, force=force)

    def get_backbone(self, key):
        return self.get(category=BACKBONE_CLASS, key=key)


REGISTRY = Registry()
