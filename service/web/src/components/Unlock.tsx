import { useEffect, useRef, useState } from 'react'
import { clearApiKey, getApiKey, getVersion, setApiKey } from '../api'

/**
 * API-key gate screen. Shown when no key is stored yet, or again after the API
 * answered 401 (the key was cleared). Unlocking stores the key and verifies it
 * against GET /v1/version; "Continue without a key" only works when the server
 * really has auth disabled (IMAGE_ENGINE_API_KEY unset).
 */
export function UnlockScreen({ onUnlocked }: { onUnlocked: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const unlock = async () => {
    setBusy(true)
    setError(null)
    setApiKey(key)
    try {
      await getVersion()
      onUnlocked()
    } catch {
      clearApiKey()
      setError('This API key was rejected. Check it and try again.')
    } finally {
      setBusy(false)
    }
  }

  const skip = async () => {
    setBusy(true)
    setError(null)
    const stored = getApiKey()
    clearApiKey()
    try {
      await getVersion()
      onUnlocked()
    } catch {
      setApiKey(stored)
      setError('This server requires an API key. Enter it to continue.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="unlock-screen" role="dialog" aria-modal="true" aria-labelledby="unlock-title">
      <form
        className="unlock-card"
        onSubmit={(e) => {
          e.preventDefault()
          if (key.trim() !== '') void unlock()
        }}
      >
        <h1 id="unlock-title">This API is locked</h1>
        <p>Enter the API key to use the Image Extraction Engine.</p>
        <input
          ref={inputRef}
          className="edit-input"
          type="password"
          aria-label="API key"
          placeholder="API key"
          value={key}
          disabled={busy}
          autoComplete="current-password"
          onChange={(e) => setKey(e.target.value)}
        />
        {error && (
          <p className="unlock-error" role="alert">
            {error}
          </p>
        )}
        <div className="unlock-actions">
          <button className="btn btn-primary" type="submit" disabled={busy || key.trim() === ''}>
            {busy ? 'Checking…' : 'Unlock'}
          </button>
          <button className="btn btn-quiet" type="button" disabled={busy} onClick={() => void skip()}>
            Continue without a key
          </button>
        </div>
      </form>
    </div>
  )
}
