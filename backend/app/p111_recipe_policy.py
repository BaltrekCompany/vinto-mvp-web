"""P1-11 v3: comprobar cada material contra la receta del producto de la OT.
Sin fallback al catálogo global; las versiones 1/2 continúan bajo su contrato.
"""
from functools import lru_cache
import json
from pathlib import Path

from app.capture_errors import CaptureValidationError


@lru_cache(maxsize=1)
def recipe_codes():
    data = json.loads(Path(__file__).with_name("p111_material_codes.json").read_text(encoding="utf-8"))
    return {str(code): frozenset(str(item) for item in materials)
            for code, materials in data.items()}


def validate_p111_recipe(connection, *, form_version_id, article_version_id, values):
    version = connection.execute(
        "SELECT version_number FROM vinto_config.form_version WHERE id = %s",
        (form_version_id,),
    ).fetchone()
    if version is None:
        raise CaptureValidationError("La version del formulario no esta disponible")
    if version[0] < 3:
        return

    article = connection.execute(
        """SELECT a.code FROM vinto_master.article_version av
           JOIN vinto_master.article a ON a.id = av.article_id
           WHERE av.id = %s""", (article_version_id,),
    ).fetchone()
    if not article:
        raise CaptureValidationError("El articulo de la OT no esta disponible")
    allowed = recipe_codes().get(article[0])
    if not allowed:
        raise CaptureValidationError("El producto de la OT no tiene receta disponible")
    for number, row in enumerate(values.get("_groups", {}).get("bobinas", ()), start=1):
        material = row.get("tipo_material")
        if not isinstance(material, str) or material not in allowed:
            raise CaptureValidationError(
                f"_groups.bobinas[{number}].tipo_material: material ajeno a la receta del producto"
            )
