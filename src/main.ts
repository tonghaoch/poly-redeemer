import type { Page } from "playwright"
import { chromium } from "playwright"
import cron from "node-cron"
import { config } from "./config.js"
import { isLoginRequired, performLogin } from "./auth.js"
import { runClaimCycle } from "./claimer.js"
import { log, warn, error } from "./logger.js"

// ---------------------------------------------------------------------------
// Scan — single claim cycle with overlap guard
// ---------------------------------------------------------------------------

let isRunning = false

async function scan(page: Page): Promise<void> {
  if (isRunning) {
    warn("Previous scan still running, skipping this cycle")
    return
  }

  isRunning = true
  try {
    log("Starting claim scan...")
    const claimed = await runClaimCycle(page, config)
    log(`Scan complete. Claimed: ${claimed}`)
  } catch (err) {
    error(`Scan failed: ${err}`)
  } finally {
    isRunning = false
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  log("Starting poly-redeemer...")
  log(`  Schedule : ${config.cronSchedule}`)
  log(`  Session  : ${config.sessionDir}`)
  log(`  Headless : ${config.headless}`)

  // 1. Launch browser with persistent context
  const context = await chromium.launchPersistentContext(config.sessionDir, {
    headless: config.headless,
    viewport: { width: 1280, height: 800 },
    locale: "en-US",
    args: ["--disable-blink-features=AutomationControlled"],
  })
  const page = context.pages()[0] ?? (await context.newPage())

  // 2. Graceful shutdown on SIGINT / SIGTERM
  const shutdown = async () => {
    log("Shutting down...")
    await context.close()
    process.exit(0)
  }
  process.on("SIGINT", shutdown)
  process.on("SIGTERM", shutdown)

  // 3. Navigate to portfolio and handle login if needed
  log("Navigating to portfolio...")
  try {
    await page.goto(config.portfolioUrl, {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    })
  } catch {
    warn("Page load slow — continuing anyway")
  }

  if (await isLoginRequired(page, config)) {
    await performLogin(page, config)
  }

  // 4. Immediate first scan
  await scan(page)

  // 5. Schedule subsequent scans via cron
  cron.schedule(config.cronSchedule, () => void scan(page))
  log(`Cron scheduled (${config.cronSchedule}). Ctrl+C to stop.`)
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

main().catch((err) => {
  error(`Fatal: ${err}`)
  process.exit(1)
})
