import { type ReactNode } from "react";
import { TRPCProvider } from "@/lib/trpc";
import "./globals.css";

export const metadata = {
  title: "AI Marketplace",
  description: "A marketplace for AI agents and tools.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        {/* Everything inside can use the typed `api.*` hooks. */}
        <TRPCProvider>{children}</TRPCProvider>
      </body>
    </html>
  );
}
