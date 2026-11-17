import type { Metadata } from "next";
import { OfflineRegistration } from "@/components/vinto/offline-registration";
import "./globals.css";

export const metadata: Metadata = {
  title: "VINTO | Captura Digital",
  manifest: "/manifest.webmanifest",
  description: "MVP autónomo para registros digitales de Producción y Calidad.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body className="antialiased"><OfflineRegistration />{children}</body>
    </html>
  );
}
