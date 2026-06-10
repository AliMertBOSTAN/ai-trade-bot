// ============================================================
//  Preload köprüsü. Renderer'a güvenli, sınırlı bir API açar.
//  Veri (REST/WS) renderer tarafında doğrudan engine'e bağlanır;
//  burada yalnızca main process gerektiren işlemler köprülenir.
// ============================================================
import { contextBridge, ipcRenderer } from 'electron'

const api = {
  /** Engine REST/WS taban URL'i (renderer fetch/WebSocket bunu kullanır) */
  getEngineUrl: (): Promise<string> => ipcRenderer.invoke('engine:url'),
  /** Python engine sürecini başlat (uvicorn) */
  spawnEngine: (): Promise<boolean> => ipcRenderer.invoke('engine:spawn'),
  /** Python engine sürecini durdur */
  killEngine: (): Promise<boolean> => ipcRenderer.invoke('engine:kill')
}

contextBridge.exposeInMainWorld('desktop', api)

export type DesktopApi = typeof api
