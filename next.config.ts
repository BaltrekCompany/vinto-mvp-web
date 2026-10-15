import type { NextConfig } from "next";

// CLOUD-01B-1 (spike aislado, rama spike/cloud-01b1-vinext-standalone): activa la salida Node.js standalone
// documentada por vinext (node_modules/vinext/README.md:126-134,591) para comprobar si el frontend puede
// ejecutarse sin Cloudflare Workers. No se usa en main; cambio exclusivo de esta rama de prueba.
const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
