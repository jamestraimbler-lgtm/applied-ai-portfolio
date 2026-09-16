/**
 * Access key encryption — AES-256-GCM using Node's built-in crypto.
 *
 * Keys are encrypted at rest in accessKeyCipher and decrypted just-in-time
 * for display to active subscribers. The encryption key is derived from
 * process.env.ACCESS_KEY_ENCRYPTION_SECRET (a 32-byte hex string = 64 chars).
 */
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

const ALGO = "aes-256-gcm" as const;
const IV_BYTES = 12; // GCM standard
const TAG_BYTES = 16;

function getKey(): Buffer {
  const hex = process.env.ACCESS_KEY_ENCRYPTION_SECRET;
  if (!hex) {
    throw new Error(
      "ACCESS_KEY_ENCRYPTION_SECRET is not set. Generate one with: node -e \"console.log(require('crypto').randomBytes(32).toString('hex'))\"",
    );
  }
  if (hex.length !== 64) {
    throw new Error(
      `ACCESS_KEY_ENCRYPTION_SECRET must be 64 hex chars (32 bytes), got ${hex.length} chars.`,
    );
  }
  return Buffer.from(hex, "hex");
}

/** Generate a readable marketplace access key. */
export function generateAccessKey(): string {
  return "mk_live_" + randomBytes(16).toString("hex");
}

/** SHA-256 hash of a plaintext key (hex). Deterministic + one-way for DB lookup. */
export function hashAccessKey(plaintext: string): string {
  return createHash("sha256").update(plaintext).digest("hex");
}

/** Encrypt a plaintext key. Returns "iv:tag:ciphertext" (all base64). */
export function encryptAccessKey(plaintext: string): string {
  const key = getKey();
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv(ALGO, key, iv);

  const encrypted = Buffer.concat([
    cipher.update(plaintext, "utf8"),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();

  return [
    iv.toString("base64"),
    tag.toString("base64"),
    encrypted.toString("base64"),
  ].join(":");
}

/** Decrypt an "iv:tag:ciphertext" cipher string back to plaintext. */
export function decryptAccessKey(cipherStr: string): string {
  const key = getKey();
  const parts = cipherStr.split(":");
  if (parts.length !== 3) {
    throw new Error("Invalid access key cipher format.");
  }

  const iv = Buffer.from(parts[0]!, "base64");
  const tag = Buffer.from(parts[1]!, "base64");
  const encrypted = Buffer.from(parts[2]!, "base64");

  if (iv.length !== IV_BYTES || tag.length !== TAG_BYTES) {
    throw new Error("Invalid access key cipher: bad IV or tag length.");
  }

  const decipher = createDecipheriv(ALGO, key, iv);
  decipher.setAuthTag(tag);

  return decipher.update(encrypted) + decipher.final("utf8");
}
