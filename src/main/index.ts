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
import { spawn, ChildProcessWithoutNullStreams } from 'node:child_process'
import { is } from '@electron-toolkit/utils'

const ENGINE_URL = process.env.ENGINE_URL ?? 'http://127.0.0.1:8787'
let engineProc: ChildProcessWithoutNullStreams | null = null
let win: BrowserWindow | null = null

function startEngine(): void {
  if (engineProc) return
  // proje kökünden: python -m uvicorn engine.app:app --port 8787
  const cwd = join(app.getAppPath(), '..', '..') // out/main -> proje kökü (dev'de ayarlanır)
  const py = process.platform === 'win32' ? 'python' : 'python3'
  engineProc = spawn(py, ['-m', 'uvicorn', 'engine.app:app', '--port', '8787'], {
    cwd: is.dev ? process.cwd() : cwd,
    env: process.env
  }) as ChildProcessWithoutNullStreams
  engineProc.stdout.on('data', (d) => console.log('[engine]', d.toString().trim()))
  engineProc.stderr.on('data', (d) => console.log('[engine]', d.toString().trim()))
  engineProc.on('exit', (code) => {
    console.log('[engine] çıkış kodu', code)
    engineProc = null
  })
}

function stopEngine(): void {
  engineProc?.kill()
  engineProc = null
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
  // İsteğe bağlı: engine'i otomatik başlat (AUTO_START_ENGINE=1)
  if (process.env.AUTO_START_ENGINE === '1') startEngine()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  stopEngine()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', stopEngine)
