/**
 * Prisma client singleton.
 *
 * Next.js hot-reloads modules in dev, which would otherwise spin up a new
 * PrismaClient (and a new connection pool) on every reload until Postgres
 * refuses connections. Caching it on globalThis avoids that.
 */
import { PrismaClient } from "@prisma/client";

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined;
};

export const db =
  globalForPrisma.prisma ??
  new PrismaClient({
    log: process.env.NODE_ENV === "development" ? ["query", "error", "warn"] : ["error"],
  });

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = db;
