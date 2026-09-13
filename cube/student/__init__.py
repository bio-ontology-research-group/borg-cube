"""Student-facing flows (onboarding, weekly check-in pack, advisor context).

Everything here is Robert-facing unless contacts.yaml holds a grant; even then the only
outbound path is an approval item, never a send (ADR-0009). The dossier itself is
``cube student <slug>`` in cube.commands.student and is not duplicated here.
"""
