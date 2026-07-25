"""User interface."""

from . import panels

_MODULES = (panels,)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()
