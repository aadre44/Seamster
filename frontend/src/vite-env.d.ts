/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API base URL. Defaults to '/api' (Vite dev proxy / same-origin deploy). */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
