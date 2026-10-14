import { candidateApi } from "@/lib/vinto/candidate-form-api";
import { P131 } from "@/lib/vinto/p1-31";

// Cliente de VINTO-P1-31 (candidato): operaciones genéricas de captura con el parser estricto de P1-31. Solo funciona contra un backend que publique el formulario para MP1 / MP3.
export const p131Api = candidateApi(P131);
