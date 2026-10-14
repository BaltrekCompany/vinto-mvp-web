import { candidateApi } from "@/lib/vinto/candidate-form-api";
import { P105 } from "@/lib/vinto/p1-05";

// Cliente de VINTO-P1-05 (candidato): operaciones genéricas de captura con el parser estricto de P1-05. Solo funciona contra un backend que publique el formulario para MP1 / MP3.
export const p105Api = candidateApi(P105);
