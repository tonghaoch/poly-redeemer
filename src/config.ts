import path from "node:path"
import { fileURLToPath } from "node:url"
import dotenv from "dotenv"
import type { AppConfig } from "./types.js"

dotenv.config()

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export const config: AppConfig = {
  // -- Auth (from .env) --
  polymarketEmail: process.env.POLYMARKET_EMAIL ?? "",
  polymarketPassword: process.env.POLYMARKET_PASSWORD ?? "",

  // -- Browser --
  headless: false,
  sessionDir: path.resolve(__dirname, "..", ".playwright-session"),

  // -- Login --
  loginCheckTimeout: 5_000, // 5s to detect login state
  mfaTimeout: 300_000, // 5min for manual MFA completion

  // -- Claim flow --
  claimButtonTimeout: 10_000, // 10s to find "Claim" button
  confirmModalTimeout: 15_000, // 15s for confirm modal
  doneButtonTimeout: 30_000, // 30s wait after confirm (on-chain tx)
  primaryButtonSelector: 'button[class*="bg-button-primary-bg"]',

  // -- Scheduling --
  cronSchedule: "*/10 * * * *", // every 10 minutes

  // -- URLs --
  portfolioUrl: "https://polymarket.com/portfolio",
}
