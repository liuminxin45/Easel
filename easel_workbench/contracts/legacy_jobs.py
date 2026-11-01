"""The existing fixed-thread job vocabulary; distinct from native turn states."""

KINDS = {'create', 'change', 'feedback', 'accept', 'reject'}
ACTIVE = {'queued', 'dispatching', 'running', 'uncertain', 'needs_desktop', 'parked'}
