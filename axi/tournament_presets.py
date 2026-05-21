"""Tournament preset registry.

Each preset maps a short name to a factory that builds the tournament's
phase_fns list. Phases 2-6 register their own presets via @register_preset.
"""

PRESETS = {}


def register_preset(name):
    """Decorator: register a preset factory.

    The factory takes a Tournament and returns a tuple of
    (phase_fns: list[Callable], format_description: str).

    @register_preset("fast")
    def fast_preset(tournament):
        return [lambda t, players: SingleElimination(t, players, ...)], "Single elimination."
    """
    def decorator(fn):
        PRESETS[name] = fn
        return fn
    return decorator


def apply_preset(tournament, name):
    """Apply a preset by name. Mutates tournament.phase_fns and .format.
    Returns True on success, False if name not registered."""
    if name not in PRESETS:
        return False
    phase_fns, format_desc = PRESETS[name](tournament)
    tournament.phase_fns = phase_fns
    tournament.format = format_desc
    return True


def list_presets():
    return sorted(PRESETS.keys())
