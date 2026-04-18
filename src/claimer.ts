import type { Page } from "playwright"
import type { AppConfig } from "./types.js"
import { log, warn, error } from "./logger.js"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function tryDismissModal(page: Page): Promise<void> {
  try {
    await page.keyboard.press("Escape")
    await page.waitForTimeout(1_000)
  } catch {
    // ignore — modal may already be gone
  }
}

// ---------------------------------------------------------------------------
// Claim cycle
// ---------------------------------------------------------------------------

/**
 * Run one full claim cycle on the portfolio page.
 * Finds all "Claim" buttons and processes them sequentially.
 * Returns the number of positions successfully claimed.
 */
export async function runClaimCycle(
  page: Page,
  config: AppConfig,
): Promise<number> {
  let claimed = 0

  // Navigate to portfolio
  try {
    await page.goto(config.portfolioUrl, {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    })
  } catch {
    warn("Page load timeout — continuing with partial load")
  }

  // Wait for SPA content to render
  await page.waitForTimeout(3_000)

  // Process all available Claim buttons one by one
  while (true) {
    const claimBtn = page
      .locator(config.primaryButtonSelector)
      .filter({ hasText: /^Claim$/ })
      .first()

    if ((await claimBtn.count()) === 0) {
      if (claimed === 0) log("No Claim buttons found")
      break
    }

    try {
      // Step 1: Click the initial "Claim" button
      log("Found Claim button, clicking...")
      await claimBtn.click()

      // Step 2: Wait for confirm modal, click "Claim $X.XX"
      const confirmBtn = page
        .locator(config.primaryButtonSelector)
        .filter({ hasText: /^Claim \$\d/ })
        .first()

      await confirmBtn.waitFor({
        state: "visible",
        timeout: config.confirmModalTimeout,
      })

      const text = await confirmBtn.textContent()
      log(`Confirming: "${text}"`)
      await confirmBtn.click()

      // Step 3: Wait for on-chain tx to settle
      log(`Waiting ${config.doneButtonTimeout / 1_000}s for on-chain transaction...`)
      await page.waitForTimeout(config.doneButtonTimeout)

      claimed++
      log(`Claim #${claimed} completed`)

      // Brief pause before looking for the next Claim button
      await page.waitForTimeout(2_000)
    } catch (err) {
      error(`Claim flow failed: ${err}`)
      await tryDismissModal(page)
      break
    }
  }

  return claimed
}
