"""Listas DEPENDIENTES de una versión de formulario (MF-12B, MD_Ejec 17): una opción de un campo solo es válida si el valor de OTRO campo del mismo formulario la permite.

Hoy solo VINTO-P1-04 desde la versión 2 (registro de consumo de fibra): «origen» y «presentacion» según «material», con los catálogos del MVP anterior (textos literales, que son los valores guardados).
La lista COMPLETA de opciones de cada campo sigue viviendo en la definición publicada (vinto_config.field_option) y la sigue validando `capture_service`; aquí solo se restringe la COMBINACIÓN.

Por qué en código y no en `vinto_config.field_option_dependency`: la tabla existe desde 0001, pero ni el importador ni sus roles la escriben (vinto_reference no tiene INSERT sobre ella) y habilitarlo exigiría
cambiar privilegios de la base de producción. Una prueba comprueba que estas reglas y las opciones del seed coinciden.

Solo se aplica a las versiones indicadas: las anteriores (y cualquier otro formulario) no cambian.
"""

MATERIAL_ORIGENES = {"Fibra larga": ("Laja", "Susano", "Dorado"), "Fibra corta": ("Laja", "Cóndor"), "Recorte": ("Sauce Rancho", "Máquina")}
MATERIAL_PRESENTACIONES = {"Fibra larga": ("Caja", "Fardo"), "Fibra corta": ("Caja", "Fardo"), "Recorte": ("Fardo",)}

# código de formulario -> (primera versión a la que aplica, [(campo dependiente, campo padre, {valor del padre: valores permitidos})])
RULES = {
    "VINTO-P1-04": (2, (("origen", "material", MATERIAL_ORIGENES), ("presentacion", "material", MATERIAL_PRESENTACIONES))),
}


def check(form_code, version_number, clean) -> list[str]:
    """Problemas de la combinación de `clean` (valores ya normalizados); vacío si no hay regla para esa versión o si todo es válido. Nunca devuelve el valor recibido."""
    rule = RULES.get(form_code)
    if rule is None or version_number < rule[0]:
        return []
    problems = []
    for child, parent, allowed in rule[1]:
        value, parent_value = clean.get(child), clean.get(parent)
        if value is None or parent_value is None:
            continue  # lo ausente o inválido ya lo informa la validación de la definición (obligatorios, lista cerrada)
        if value not in allowed.get(parent_value, ()):
            problems.append(f"{child}: no corresponde al valor elegido en {parent}")
    return problems
