"""CV-P113-01: valida el material seleccionado para P1-13 v3.
La autoridad del articulo es la linea de OT, nunca el payload. Se reutiliza el
catalogo por articulo auditado para P1-11, que conserva TODOS los materiales de
MFRutaMaterialOP (sin filtrar MaterialUso).
"""
from app.capture_errors import CaptureValidationError
from app.p111_recipe_policy import recipe_codes


def validate_p113_recipe(connection, *, form_version_id, article_version_id, values):
    row = connection.execute(
        "SELECT version_number FROM vinto_config.form_version WHERE id = %s",
        (form_version_id,),
    ).fetchone()
    if row is None:
        raise CaptureValidationError("P1-13: version no disponible")
    if row[0] < 3:
        return  # contrato historico v1/v2 inalterado
    article = connection.execute(
        """SELECT a.code FROM vinto_master.article_version av
           JOIN vinto_master.article a ON a.id = av.article_id
           WHERE av.id = %s""", (article_version_id,),
    ).fetchone()
    if article is None:
        raise CaptureValidationError("P1-13: articulo de la OT no disponible")
    allowed = recipe_codes().get(article[0])
    if not allowed:
        raise CaptureValidationError("P1-13: el articulo no tiene receta homologada")
    chosen = values.get("tipo_bobina")
    if not isinstance(chosen, str) or chosen not in allowed:
        raise CaptureValidationError("P1-13: material no pertenece a la receta de la OT")
