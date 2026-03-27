import readline from "node:readline"
import type { Page } from "playwright"
import type { AppConfig } from "./types.js"
import { log, warn, error } from "./logger.js"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Block until the user presses Enter in the terminal. */
function promptUser(message: string): Promise<void> {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    })
    rl.question(message, () => {
      rl.close()
      resolve()
    })
  })
}

/** Prompt the user to complete login manually in the browser. */
async function waitForManualLogin(): Promise<void> {
  log("Waiting for manual login... Complete login in the browser window.")
  await promptUser("Press Enter after logging in manually...")
}

// ---------------------------------------------------------------------------
// Login detection
// ---------------------------------------------------------------------------

/**
 * Detect whether the user needs to log in.
 * Races the email input (#magic-email-input) against portfolio content.
 */
export async function isLoginRequired(
  page: Page,
  config: AppConfig,
): Promise<boolean> {
  try {
    const result = await Promise.race([
      page
        .locator("#magic-email-input")
        .waitFor({ state: "visible", timeout: config.loginCheckTimeout })
        .then(() => "login" as const),
      page
        .locator('[data-testid="portfolio"]')
        .or(page.locator('text="Your Portfolio"'))
        .or(page.locator('text="Portfolio value"'))
        .or(page.locator('text="Positions"'))
        .first()
        .waitFor({ state: "visible", timeout: config.loginCheckTimeout })
        .then(() => "portfolio" as const),
      new Promise<"timeout">((resolve) =>
        setTimeout(() => resolve("timeout"), config.loginCheckTimeout + 1_000),
      ),
    ])

    if (result === "login") {
      log("Login required — detected email input")
      return true
    }
    if (result === "portfolio") {
      log("Already logged in — portfolio content detected")
      return false
    }

    // Timeout fallback: check URL
    if (page.url().includes("/login") || page.url().includes("/auth")) {
      return true
    }

    warn("Could not determine login state — assuming login needed")
    return true
  } catch {
    warn("Login check error — assuming login needed")
    return true
  }
}

// ---------------------------------------------------------------------------
// Login flow
// ---------------------------------------------------------------------------

/**
 * Login flow: auto-fill email → Continue → manual email code & MFA.
 * Falls back to fully manual login if credentials are missing or auto-fill fails.
 */
export async function performLogin(
  page: Page,
  config: AppConfig,
): Promise<void> {
  if (!config.polymarketEmail) {
    log("No email in .env — please log in manually in the browser window")
    await waitForManualLogin()
    return
  }

  log("Starting login flow...")

  // 1. Fill email and click Continue
  try {
    const emailInput = page.locator("#magic-email-input")
    await emailInput.waitFor({ state: "visible", timeout: 10_000 })
    await emailInput.fill(config.polymarketEmail)
    log("Email entered")

    // Wait for Continue button to become enabled
    const continueBtn = page
      .locator('button[type="submit"]')
      .filter({ hasText: /^Continue$/ })
      .first()

    await continueBtn.waitFor({ state: "visible", timeout: 5_000 })
    await page.waitForFunction(
      (sel) => {
        const btn = document.querySelector(sel)
        return btn && !btn.hasAttribute("disabled")
      },
      'button[type="submit"]',
      { timeout: 5_000 },
    )
    await continueBtn.click()
    log("Clicked Continue")
  } catch (err) {
    error(`Auto-fill failed: ${err}`)
    await waitForManualLogin()
    return
  }

  // 2. Manual step: email verification code + MFA
  log("========================================")
  log("Please complete the following in the browser:")
  log("  1. Enter the verification code from your email")
  log("  2. Complete MFA if prompted")
  log("========================================")

  await promptUser("Press Enter after completing login in the browser...")
  log("Login confirmed by user")
}
