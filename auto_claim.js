// poly-redeemer browser script
// 在 Polymarket 页面的 browser console 中粘贴运行
// 自动检测并点击 Claim 按钮，由 Polymarket 代付 gas
//
// 使用方法:
//   1. 打开 https://polymarket.com/portfolio
//   2. F12 打开 DevTools → Console
//   3. 粘贴此脚本并回车
//   4. 脚本会每 60 秒扫描一次，发现 Claim 按钮自动点击
//   5. 输入 stopAutoRedeem() 停止

;(function () {
  const SCAN_INTERVAL_MS = 60000 // 60 秒扫描一次
  const CONFIRM_DELAY_MS = 5000 // 等弹窗渲染
  const DONE_DELAY_MS = 10000 // 等链上交易完成

  // 三步流程，按钮共享 class 特征，文本不同:
  //   Step 1: "Claim"         — 列表中的初始按钮
  //   Step 2: "Claim $2.00"   — 弹窗中的确认按钮
  //   Step 3: "Done"          — 交易完成后关闭弹窗
  const SELECTOR = 'button[class*="bg-button-primary-bg"]'

  function findButton(textMatch) {
    for (const btn of document.querySelectorAll(SELECTOR)) {
      if (btn.disabled) continue
      const text = btn.textContent.trim()
      if (textMatch(text)) return btn
    }
    return null
  }

  function log(msg) {
    console.log(`[${new Date().toLocaleTimeString()}] ${msg}`)
  }

  function scan() {
    // Step 1: 找 "Claim" 按钮（精确匹配，排除 "Claim $X.XX"）
    const claimBtn = findButton((t) => t === "Claim")
    if (!claimBtn) return

    log("Found Claim button, clicking...")
    claimBtn.click()

    // Step 2: 等弹窗出现，点击 "Claim $X.XX" 确认按钮
    setTimeout(() => {
      const confirmBtn = findButton((t) => t.startsWith("Claim $"))
      if (confirmBtn) {
        log(`Confirming: "${confirmBtn.textContent.trim()}"`)
        confirmBtn.click()
      } else {
        log("Confirm button not found, will retry next scan")
        return
      }

      // Step 3: 等交易完成，点击 "Done" 关闭弹窗
      setTimeout(() => {
        const doneBtn = findButton((t) => t === "Done")
        if (doneBtn) {
          log("Clicking Done")
          doneBtn.click()
        } else {
          log("Done button not found, will close on next scan")
        }
      }, DONE_DELAY_MS)
    }, CONFIRM_DELAY_MS)
  }

  const intervalId = setInterval(scan, SCAN_INTERVAL_MS)

  window.stopAutoRedeem = function () {
    clearInterval(intervalId)
    log("Stopped.")
  }

  log(`AutoRedeem started (every ${SCAN_INTERVAL_MS / 1000}s)`)
  log("Run stopAutoRedeem() to stop.")
  scan()
})()
