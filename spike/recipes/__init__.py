"""calma.spike.recipes — the lifted 626-recipe trusted catalog from the previous engine (the one piece the
rebuild guide says to lift: the recompute/validity *math*). recipes_legacy.py + numeric.py are verbatim
pure-stdlib; adapter.py maps the new captured canonical inputs onto each recipe's `required_tags` so they
plug into recompute_any (catalog → recipes → store → synth).
"""
from . import adapter  # noqa: F401
