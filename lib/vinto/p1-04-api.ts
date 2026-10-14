import { candidateApi } from "@/lib/vinto/candidate-form-api";
import { P104 } from "@/lib/vinto/p1-04";

// Cliente de VINTO-P1-04 (candidato): operaciones genéricas de captura con el parser estricto de P1-04. Solo funciona contra un backend que publique el formulario para MP1 / MP3.
export const p104Api = candidateApi(P104);
