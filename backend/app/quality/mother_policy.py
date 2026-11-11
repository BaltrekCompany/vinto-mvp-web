"""Política ADITIVA y cerrada de los controles propios de madres P1-07.

No modifica los vínculos INMUTABLES de versiones F3 (MP1/MP3) ni el
checksum del bundle de referencia. No concede acceso: requiere además
quality.capture, sector y concesión activa (MF-13).
"""
MOTHER_MACHINE_CODES = frozenset({"COPASA", "BELOIT", "OVER"})
MOTHER_FORM_CODES = frozenset({
    "VINTO-P1-19", "VINTO-P1-20", "VINTO-P1-21",
    "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28",
})


def allows_mother_form(machine_code: str, form_code: str) -> bool:
    return machine_code in MOTHER_MACHINE_CODES and form_code in MOTHER_FORM_CODES
