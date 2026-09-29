import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VINTO | Captura Digital",
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
      <body className="antialiased">{children}</body>
    </html>
  );
}
