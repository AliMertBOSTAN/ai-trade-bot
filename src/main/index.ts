// ============================================================
//  Electron main process.
//  - Pencereyi oluşturur
//  - Python engine'i (uvicorn) çocuk süreç olarak başlatır/durdurur
//  - Renderer ile IPC köprüsü (engine süreç kontrolü)
//  Veri akışı (REST + WebSocket) renderer'dan doğrudan engine'e gider;
//  engine CORS açıktır ve tarayıcı bağlamı WebSocket'i destekler.
// ============================================================
import { app, shell, BrowserWindow, ipcMain, session } from 'electron'
import { join } from 'node:path'
import { spawn, execFile, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import { get as httpGet } from 'node:http'
import { config as loadEnv } from 'dotenv'
import { is } from '@electron-toolkit/utils'

// Proje kökündeki .env'i Electron ana sürecine de yükle (Python tarafı ayrıca okur).
// Böylece AUTO_START_ENGINE / ENGINE_PYTHON / ENGINE_URL ayarları .env'den çalışır.
loadEnv()

const ENGINE_URL = process.env.ENGINE_URL ?? 'http://127.0.0.1:8787'
// Engine'i uygulamayla birlikte otomatik başlat/durdur. Kapatmak için: AUTO_START_ENGINE=0
const AUTO_START_ENGINE = process.env.AUTO_START_ENGINE !== '0'
let engineProc: ChildProcess | null = null
let engineOwned = false // bu süreci biz mi başlattık? (dışarıda çalışan uvicorn'u ÖLDÜRME)
let win: BrowserWindow | null = null

/** Proje kökü (engine/ klasörünü içeren dizin). */
function projectRoot(): string {
  // dev: electron-vite proje kökünden çalışır; prod/preview: getAppPath proje kökü
  return is.dev ? process.cwd() : app.getAppPath()
}

/** Python yorumlayıcısını seç: ENGINE_PYTHON > .venv > sistem python. */
function resolvePython(root: string): string {
  if (process.env.ENGINE_PYTHON) return process.env.ENGINE_PYTHON
  const win = process.platform === 'win32'
  const venv = win
    ? join(root, '.venv', 'Scripts', 'python.exe')
    : join(root, '.venv', 'bin', 'python')
  if (existsSync(venv)) return venv
  return win ? 'python' : 'python3'
}

/** Engine ayakta mı? (zaten çalışan uvicorn'u ikinci kez başlatmamak için.) */
function pingEngine(timeoutMs = 1500): Promise<boolean> {
  return new Promise((resolve) => {
    const req = httpGet(`${ENGINE_URL}/state`, (res) => {
      res.resume()
      resolve((res.statusCode ?? 500) < 500)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(timeoutMs, () => {
      req.destroy()
      resolve(false)
    })
  })
}

async function startEngine(): Promise<void> {
  if (engineProc) return
  // Dışarıda elle başlatılmış bir engine varsa ona dokunma
  if (await pingEngine()) {
    console.log('[engine] zaten çalışıyor (port 8787) — yeni süreç başlatılmadı')
    return
  }
  const root = projectRoot()
  const py = resolvePython(root)
  console.log(`[engine] başlatılıyor: ${py}  (kök: ${root})`)
  const proc = spawn(py, ['-m', 'uvicorn', 'engine.app:app', '--port', '8787'], {
    cwd: root,
    env: process.env
  })
  engineProc = proc
  engineOwned = true
  proc.stdout?.on('data', (d) => console.log('[engine]', d.toString().trim()))
  proc.stderr?.on('data', (d) => console.log('[engine]', d.toString().trim()))
  proc.on('error', (err) => {
    console.error(
      `[engine] başlatılamadı: ${err.message}\n` +
        '  -> Python/uvicorn kurulu mu? `pip install -r engine/requirements.txt` ' +
        'veya .venv oluşturun. Farklı yorumlayıcı için ENGINE_PYTHON ayarlayın.'
    )
    engineProc = null
    engineOwned = false
  })
  proc.on('exit', (code) => {
    console.log('[engine] çıkış kodu', code)
    engineProc = null
    engineOwned = false
  })
}

function stopEngine(): void {
  const proc = engineProc
  engineProc = null
  // Yalnızca bizim başlattığımız süreci durdur
  if (!proc || !engineOwned) return
  engineOwned = false
  const pid = proc.pid
  if (process.platform === 'win32' && pid) {
    // Windows: uvicorn + tüm alt süreçleri zorla kapat (SIGTERM güvenilir değil)
    execFile('taskkill', ['/pid', String(pid), '/T', '/F'], () => {})
  } else {
    proc.kill('SIGTERM')
  }
}

// Content-Security-Policy'yi response header olarak uygula.
// Dev'de Vite, inline React-refresh preamble + HMR websocket'i (ws://localhost)
// kullandığından gevşek; prod'da (paketlenmiş bundle) sıkı tutulur.
function applyContentSecurityPolicy(): void {
  const csp = is.dev
    ? [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self' http://localhost:* ws://localhost:* http://127.0.0.1:8787 ws://127.0.0.1:8787"
      ].join('; ')
    : [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self' http://127.0.0.1:8787 ws://127.0.0.1:8787"
      ].join('; ')

  session.defaultSession.webRequest.onHeadersReceived((details, cb) => {
    cb({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [csp]
      }
    })
  })
}

function createWindow(): void {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    show: false,
    backgroundColor: '#0b0e14',
    title: 'AI Trade Bot',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true
    }
  })

  win.on('ready-to-show', () => win?.show())
  win.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

// ---- IPC: engine süreç kontrolü + URL ----
ipcMain.handle('engine:url', () => ENGINE_URL)
ipcMain.handle('engine:spawn', () => {
  startEngine()
  return true
})
ipcMain.handle('engine:kill', () => {
  stopEngine()
  return true
})

app.whenReady().then(() => {
  applyContentSecurityPolicy()
  // Engine'i uygulamayla birlikte otomatik başlat (varsayılan açık; AUTO_START_ENGINE=0 ile kapatılır)
  if (AUTO_START_ENGINE) void startEngine()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      if (AUTO_START_ENGINE) void startEngine() // macOS: dock'tan yeniden açılışta engine'i de geri getir
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  stopEngine()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', stopEngine)
