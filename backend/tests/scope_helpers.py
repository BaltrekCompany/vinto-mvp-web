"""Explicit internal caller for service-level tests.

The service functions require an explicit `sectors=` scope (there is no permissive default: omitting it is a TypeError). Service tests exercise
the domain logic without a user, so they act as an authorized INTERNAL caller that asks for the full operational scope on purpose. The scope is
resolved at call time, so tests that patch the operational sectors keep working. Tests of the authorization itself pass their own `sectors=`.

The proxy forwards attribute writes to the real module, so `patch.object(proxy, "_now", ...)` patches the module exactly as before.
"""

import functools
import inspect

from app import sectors


def _wrap(function):
    @functools.wraps(function)
    def with_full_scope(*args, **kwargs):
        kwargs.setdefault("sectors", sectors.operational_sector_codes())
        return function(*args, **kwargs)
    with_full_scope._internal_original = function
    return with_full_scope


class _Internal:
    def __init__(self, module):
        object.__setattr__(self, "_module", module)

    def __getattr__(self, name):
        attribute = getattr(self._module, name)
        if inspect.isfunction(attribute) and "sectors" in inspect.signature(attribute).parameters:
            return _wrap(attribute)
        return attribute

    def __setattr__(self, name, value):
        setattr(self._module, name, value._internal_original if inspect.isfunction(value) and hasattr(value, "_internal_original") else value)  # restoring a patched function never installs the wrapper

    def __delattr__(self, name):
        delattr(self._module, name)


def internal(module):
    return _Internal(module)
