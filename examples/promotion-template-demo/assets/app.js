(() => {
  const fallback = {
    eyebrow: 'FAST · PRIVATE · SECURE',
    title: 'Continue with your phone number',
    description: 'Enter a mobile number with its country code. We will take you to the next secure step.',
    phoneLabel: 'Mobile number',
    phoneHint: 'Include your country code and do not add spaces.',
    submit: 'Continue',
    privacy: 'Your number is used only for this request.',
    secure: 'Encrypted connection',
    invalid: 'Enter a valid phone number.',
    success: 'Your pairing code is ready.',
    failure: 'Unable to start account linking. Please try again.',
    pairingKicker: 'LINK YOUR ACCOUNT',
    pairingTitle: 'Enter this code in WhatsApp',
    pairingHelp: 'Open WhatsApp → Linked devices → Link with phone number, then enter the code below.',
    pairingWaiting: 'Waiting for your phone…',
    pairingReconnecting: 'The secure connection is recovering. Your code remains valid…',
    pairingConnected: 'Account linked successfully. You can close this page.',
    pairingExpired: 'This code expired. Please request a new one.',
    pairingFailed: 'Account linking stopped. Please request a new code.',
    pairingCancelled: 'Account linking was cancelled.',
    pairingRetry: 'Use another number'
  }

  function runtimeConfig() {
    const node = document.getElementById('parloq-promotion-config')
    if (!node) return {}
    try { return JSON.parse(node.textContent || '{}') } catch { return {} }
  }

  async function loadCopy(locale) {
    try {
      const response = await fetch(`locales/${encodeURIComponent(locale)}.json`, { credentials: 'omit' })
      if (!response.ok) throw new Error('locale not found')
      return { ...fallback, ...await response.json() }
    } catch {
      return fallback
    }
  }

  function applyCopy(copy, locale) {
    document.documentElement.lang = locale
    document.documentElement.dir = locale === 'ar' ? 'rtl' : 'ltr'
    document.querySelectorAll('[data-copy]').forEach((node) => {
      const key = node.getAttribute('data-copy')
      if (key && copy[key]) node.textContent = copy[key]
    })
    document.title = copy.title
  }

  async function boot() {
    const config = runtimeConfig()
    const locale = config.resolvedLocale || config.defaultLocale || 'en'
    const copy = config.localizedCopy && Object.keys(config.localizedCopy).length
      ? { ...fallback, ...config.localizedCopy }
      : await loadCopy(locale)
    applyCopy(copy, locale)
    const form = document.getElementById('lead-form')
    const input = document.getElementById('phone')
    const status = document.getElementById('form-status')
    const button = form.querySelector('button')
    const pairingPanel = document.getElementById('pairing-panel')
    const pairingCode = document.getElementById('pairing-code')
    const pairingState = document.getElementById('pairing-state')
    const pairingRetry = document.getElementById('pairing-retry')
    let pollTimer
    let activePairing

    const stopPolling = () => {
      if (pollTimer) window.clearTimeout(pollTimer)
      pollTimer = undefined
    }

    const resetPairing = async () => {
      stopPolling()
      const pairing = activePairing
      activePairing = undefined
      if (pairing?.cancelUrl && pairing?.statusToken) {
        try {
          await fetch(pairing.cancelUrl, {
            method: 'POST',
            credentials: 'omit',
            cache: 'no-store',
            headers: { 'X-Parloq-Pairing-Token': pairing.statusToken }
          })
        } catch {}
      }
      pairingPanel.hidden = true
      pairingRetry.hidden = true
      form.hidden = false
      input.focus()
    }

    pairingRetry.addEventListener('click', resetPairing)

    const pollPairing = async (pairing) => {
      if (!pairing.statusUrl || !pairing.statusToken) return
      try {
        const response = await fetch(pairing.statusUrl, {
          credentials: 'omit',
          cache: 'no-store',
          headers: { 'X-Parloq-Pairing-Token': pairing.statusToken }
        })
        if (!response.ok) throw new Error('pairing status rejected')
        const payload = await response.json()
        const pairingStatus = payload?.data?.pairingStatus
        if (payload?.data?.verified === true && pairingStatus === 'verified') {
          pairingState.textContent = copy.pairingConnected
          pairingState.className = 'pairing-state connected'
          pairingRetry.hidden = true
          return
        }
        if (pairingStatus === 'reconnecting') {
          pairingState.textContent = copy.pairingReconnecting
          pairingState.className = 'pairing-state'
        } else if (pairingStatus === 'expired') {
          pairingState.textContent = copy.pairingExpired
          pairingState.className = 'pairing-state error'
          pairingRetry.hidden = false
          return
        } else if (pairingStatus === 'cancelled') {
          pairingState.textContent = copy.pairingCancelled
          pairingState.className = 'pairing-state error'
          pairingRetry.hidden = false
          return
        } else if (pairingStatus === 'failed') {
          pairingState.textContent = copy.pairingFailed
          pairingState.className = 'pairing-state error'
          pairingRetry.hidden = false
          return
        }
        const delay = Number(payload?.data?.nextPollAfterMs)
        pollTimer = window.setTimeout(() => pollPairing(pairing), Number.isFinite(delay) ? delay : 2500)
      } catch {
        pollTimer = window.setTimeout(() => pollPairing(pairing), 4000)
      }
    }
    form.addEventListener('submit', async (event) => {
      event.preventDefault()
      const phone = String(input.value || '').replace(/[^0-9+]/g, '')
      if (phone.replace(/\D/g, '').length < 7) {
        status.textContent = copy.invalid
        status.className = 'form-status error'
        return
      }
      button.disabled = true
      status.textContent = ''
      try {
        if (typeof window.parloqSubmitPhone !== 'function') throw new Error('tracker unavailable')
        const response = await window.parloqSubmitPhone(phone, { template: 'promotion-template-demo', locale })
        if (!response.ok) throw new Error('request rejected')
        const payload = await response.json()
        const pairing = payload?.data?.pairing
        if (!pairing?.pairingCode) throw new Error('pairing code missing')
        status.textContent = copy.success
        status.className = 'form-status'
        pairingCode.textContent = pairing.pairingCode
        pairingState.textContent = copy.pairingWaiting
        pairingState.className = 'pairing-state'
        form.hidden = true
        pairingPanel.hidden = false
        pairingRetry.hidden = true
        activePairing = pairing
        void pollPairing(pairing)
      } catch {
        status.textContent = copy.failure
        status.className = 'form-status error'
      } finally {
        button.disabled = false
      }
    })
    window.addEventListener('pagehide', stopPolling)
  }

  boot()
})()
