const RESET = "\x1b[0m"
const BLUE = "\x1b[34m"
const YELLOW = "\x1b[33m"
const RED = "\x1b[31m"
const GRAY = "\x1b[90m"

function ts(): string {
  return `${GRAY}[${new Date().toLocaleTimeString()}]${RESET}`
}

export function log(msg: string): void {
  console.log(`${ts()} ${BLUE}[INFO]${RESET} ${msg}`)
}

export function warn(msg: string): void {
  console.warn(`${ts()} ${YELLOW}[WARN]${RESET} ${msg}`)
}

export function error(msg: string): void {
  console.error(`${ts()} ${RED}[ERROR]${RESET} ${msg}`)
}
