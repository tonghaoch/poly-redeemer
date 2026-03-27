export interface AppConfig {
  // -- Auth (from .env) --
  polymarketEmail: string;
  polymarketPassword: string;

  // -- Browser --
  headless: boolean;
  sessionDir: string; // persistent context directory

  // -- Login --
  loginCheckTimeout: number; // ms, time to detect login state
  mfaTimeout: number; // ms, wait for manual MFA completion

  // -- Claim flow --
  claimButtonTimeout: number; // ms, wait for "Claim" button
  confirmModalTimeout: number; // ms, wait for "Claim $X.XX" confirm button
  doneButtonTimeout: number; // ms, wait after confirm (on-chain tx)
  primaryButtonSelector: string; // CSS selector for action buttons

  // -- Scheduling --
  cronSchedule: string; // node-cron expression

  // -- URLs --
  portfolioUrl: string;
}
