// Keeps the images uploaded from this browser (IndexedDB, 14 days) so the review screen can
// draw bounding boxes on them. Nothing here talks to the network.

const DB_NAME = 'image-extraction-ui'
const STORE = 'source-images'
const MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000

interface StoredImage {
  blob: Blob
  savedAt: number
}

const objectUrls = new Map<string, string>()
let dbPromise: Promise<IDBDatabase | null> | null = null

const keyOf = (jobId: string, fileName: string) => `${jobId}::${fileName}`

function openDb(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      const request = indexedDB.open(DB_NAME, 1)
      request.onupgradeneeded = () => request.result.createObjectStore(STORE)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => resolve(null)
      request.onblocked = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
}

function prune(db: IDBDatabase): void {
  try {
    const cursorRequest = db.transaction(STORE, 'readwrite').objectStore(STORE).openCursor()
    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result
      if (!cursor) return
      const stored = cursor.value as StoredImage
      if (Date.now() - stored.savedAt > MAX_AGE_MS) cursor.delete()
      cursor.continue()
    }
  } catch {
    /* pruning is best effort */
  }
}

function database(): Promise<IDBDatabase | null> {
  dbPromise ??= openDb().then((db) => {
    if (db) prune(db)
    return db
  })
  return dbPromise
}

function remember(key: string, blob: Blob): string {
  const previous = objectUrls.get(key)
  if (previous) URL.revokeObjectURL(previous)
  const url = URL.createObjectURL(blob)
  objectUrls.set(key, url)
  return url
}

export async function rememberSourceImage(jobId: string, fileName: string, blob: Blob): Promise<string> {
  const key = keyOf(jobId, fileName)
  const url = remember(key, blob)
  const db = await database()
  if (db) {
    try {
      const stored: StoredImage = { blob, savedAt: Date.now() }
      db.transaction(STORE, 'readwrite').objectStore(STORE).put(stored, key)
    } catch {
      /* the in-memory copy still works for this session */
    }
  }
  return url
}

export async function loadSourceImage(jobId: string, fileName: string): Promise<string | null> {
  const key = keyOf(jobId, fileName)
  const cached = objectUrls.get(key)
  if (cached) return cached
  const db = await database()
  if (!db) return null
  return new Promise((resolve) => {
    try {
      const request = db.transaction(STORE, 'readonly').objectStore(STORE).get(key)
      request.onsuccess = () => {
        const stored = request.result as StoredImage | undefined
        resolve(stored ? remember(key, stored.blob) : null)
      }
      request.onerror = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
}
