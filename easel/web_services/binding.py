"""Bind shared native function code to one explicit application context.

Function bodies have one source. A host gets isolated roots, stores and process
registries without changing environment variables or shared module globals.
The native app binds into its own namespace to retain its public test hooks.
"""
from types import FunctionType, SimpleNamespace


def bind_functions(module, exports, context=None, *, into=None):
    namespace = dict(vars(module)) if into is None else into
    if into is not None:
        for name, value in vars(module).items():
            if not name.startswith('__'):
                namespace.setdefault(name, value)
    if context:
        namespace.update(context)
    for name in exports:
        if context is not None and name in context:
            continue
        value = getattr(module, name)
        if isinstance(value, FunctionType) and value.__module__ == module.__name__:
            bound = FunctionType(value.__code__, namespace, value.__name__,
                                 value.__defaults__, value.__closure__)
            bound.__kwdefaults__ = value.__kwdefaults__
            bound.__annotations__ = dict(value.__annotations__)
            bound.__doc__ = value.__doc__
            bound.__dict__.update(value.__dict__)
            namespace[name] = bound
        elif context is None or name not in context:
            namespace[name] = value
    return SimpleNamespace(**{name: value for name, value in namespace.items()
                              if not name.startswith('__')}, namespace=namespace)
