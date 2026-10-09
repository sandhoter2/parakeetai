// main.js — Electron main process
const { app, BrowserWindow, ipcMain, globalShortcut, screen, nativeTheme, session } = require('electron');
const path = require('path');
const Store = require('electron-store');

// Persistent encrypted store for auth credentials
const store = new Store({
  name: 'parakeetai-config',
  encryptionKey: 'parakeetai-local-key-v1',
  defaults: {
    baseUrl: 'https://parakeetai.onrender.com',
    token: '',
    username: '',
    plan: 'free',
    sessionLimit: 5,
    sessionsUsed: 0,
  }
});

let overlayWindow;
nativeTheme.themeSource = 'dark';

function createOverlay() {
  const { width } = screen.getPrimaryDisplay().workAreaSize;

  overlayWindow = new BrowserWindow({
    width: 420,
    height: 620,
    x: width - 440,
    y: 20,
    transparent: true,        // OS-level: desktop shows through
    frame: false,              // No browser chrome / title bar
    hasShadow: false,          // Critical on Mac: prevents black shadow box around transparent window
    alwaysOnTop: true,
    vibrancy: 'under-window',  // macOS native frosted glass effect
    visualEffectState: 'active',
    resizable: true,
    minWidth: 320,
    minHeight: 300,
    skipTaskbar: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  overlayWindow.loadFile('overlay.html');
  // Hide from screen capture (Zoom, Teams, OBS, macOS screenshot, etc.)
  overlayWindow.setContentProtection(true);
  // Stay on top across all macOS Spaces and full-screen apps
  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlayWindow.setAlwaysOnTop(true, 'floating');
}

app.whenReady().then(() => {
  // Grant microphone access to the overlay window
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const allowed = ['media', 'microphone', 'audioCapture', 'display-capture'];
    callback(allowed.includes(permission));
  });
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
    const allowed = ['media', 'microphone', 'audioCapture', 'display-capture'];
    return allowed.includes(permission);
  });
  // Allow getDisplayMedia() from the renderer (needed for screen audio capture)
  session.defaultSession.setDisplayMediaRequestHandler((request, callback) => {
    const { desktopCapturer } = require('electron');
    desktopCapturer.getSources({ types: ['screen'] }).then(sources => {
      if (sources.length > 0) callback({ video: sources[0] });
      else callback({});
    }).catch(() => callback({}));
  });

  createOverlay();

  // ⌘⇧Space → toggle show/hide
  globalShortcut.register('CommandOrControl+Shift+Space', () => {
    if (!overlayWindow) return;
    if (overlayWindow.isVisible()) {
      overlayWindow.hide();
    } else {
      overlayWindow.show();
      overlayWindow.focus();
    }
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

// IPC from renderer
ipcMain.on('hide-overlay',     () => overlayWindow?.hide());
ipcMain.on('minimize-overlay', () => overlayWindow?.minimize());
ipcMain.on('close-overlay',    () => { overlayWindow?.close(); overlayWindow = null; });
ipcMain.on('set-size',         (_, { w, h }) => overlayWindow?.setSize(w, h));
ipcMain.on('set-opacity',      (_, alpha) => overlayWindow?.setOpacity(alpha));
ipcMain.on('set-always-on-top',(_, on) => {
  if (!overlayWindow) return;
  overlayWindow.setAlwaysOnTop(on, on ? 'floating' : 'normal');
});

// Proxy Django HTTP calls through main process (avoids CORS)
ipcMain.handle('django-chat', async (_, { baseUrl, sessionId, token, question }) => {
  const { net } = require('electron');
  const url = `${baseUrl}/api/session/${sessionId}/chat/`;
  return new Promise((resolve, reject) => {
    const req = net.request({ method: 'POST', url });
    req.setHeader('Content-Type', 'application/json');
    req.setHeader('X-Ext-Token', token);
    let body = '';
    req.on('response', res => {
      res.on('data', chunk => { body += chunk.toString(); });
      res.on('end', () => {
        // Detect HTML error page from Django
        const trimmed = body.trimStart();
        if (trimmed.startsWith('<!') || trimmed.startsWith('<html')) {
          resolve({ text: '⚠ Django returned an HTML error page. Check the server is running and Session ID is correct.' });
          return;
        }
        // Parse SSE stream — handle both custom {"type":"text"} and
        // Claude native {"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}
        let text = '';
        body.split('\n').forEach(line => {
          if (!line.startsWith('data: ')) return;
          const raw = line.slice(6).trim();
          if (!raw || raw === '[DONE]') return;
          try {
            const d = JSON.parse(raw);
            if (d.type === 'text' && d.text) {
              text += d.text;
            } else if (d.type === 'content_block_delta' && d.delta?.type === 'text_delta') {
              text += d.delta.text || '';
            } else if (d.type === 'message_delta' && d.delta?.stop_reason) {
              // end of stream marker, nothing to do
            } else if (typeof d.text === 'string') {
              text += d.text; // fallback plain {text:"..."} shape
            }
          } catch (_) {}
        });
        resolve({ text: text.trim() || 'No response' });
      });
    });
    req.on('error', reject);
    req.write(JSON.stringify({ question }));
    req.end();
  });
});

ipcMain.handle('django-transcribe-audio', async (_, { baseUrl, sessionId, token, audioBase64, speakerType }) => {
  const http  = require('http');
  const https = require('https');
  const { URL } = require('url');

  const endpoint = new URL(`${baseUrl}/api/session/${sessionId}/transcribe/`);
  const transport = endpoint.protocol === 'https:' ? https : http;
  const audioBuf  = Buffer.from(audioBase64, 'base64');
  const boundary  = '----PkaiBoundary' + Date.now();

  const body = Buffer.concat([
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="audio"; filename="audio.webm"\r\nContent-Type: audio/webm\r\n\r\n`),
    audioBuf,
    Buffer.from(`\r\n--${boundary}\r\nContent-Disposition: form-data; name="speaker_type"\r\n\r\n${speakerType || 'microphone'}\r\n--${boundary}--\r\n`)
  ]);

  return new Promise((resolve, reject) => {
    const req = transport.request({
      hostname: endpoint.hostname,
      port:     endpoint.port || (endpoint.protocol === 'https:' ? 443 : 80),
      path:     endpoint.pathname + endpoint.search,
      method:   'POST',
      headers: {
        'Content-Type':   `multipart/form-data; boundary=${boundary}`,
        'X-Ext-Token':    token,
        'Content-Length': body.length
      }
    }, res => {
      let data = '';
      res.on('data', c => { data += c.toString(); });
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve({ text: data }); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
});

ipcMain.handle('django-transcript', async (_, { baseUrl, sessionId, token, content, speakerType }) => {
  const { net } = require('electron');
  const url = `${baseUrl}/api/session/${sessionId}/transcript/`;
  return new Promise((resolve, reject) => {
    const req = net.request({ method: 'POST', url });
    req.setHeader('Content-Type', 'application/json');
    req.setHeader('X-Ext-Token', token);
    req.on('response', res => { res.on('data', () => {}); res.on('end', resolve); });
    req.on('error', reject);
    req.write(JSON.stringify({ transcripts: [{ content, type: speakerType || 'microphone' }] }));
    req.end();
  });
});

// Desktop overlay login: POST {username, password} → {token, plan, session_limit, sessions_used}
ipcMain.handle('django-login', async (_, { baseUrl, username, password }) => {
  const { net } = require('electron');
  const url = `${baseUrl}/api/login/`;
  return new Promise((resolve, reject) => {
    const req = net.request({ method: 'POST', url });
    req.setHeader('Content-Type', 'application/json');
    let body = '';
    req.on('response', res => {
      res.on('data', chunk => { body += chunk.toString(); });
      res.on('end', () => {
        try {
          const data = JSON.parse(body);
          if (res.statusCode === 200) {
            // Persist credentials for next launch
            store.set('baseUrl', baseUrl);
            store.set('token', data.token);
            store.set('username', data.username || username);
            store.set('plan', data.plan || 'free');
            store.set('sessionLimit', data.session_limit ?? 5);
            store.set('sessionsUsed', data.sessions_used ?? 0);
          }
          resolve({ statusCode: res.statusCode, ...data });
        } catch {
          reject(new Error('Invalid JSON from login endpoint'));
        }
      });
    });
    req.on('error', reject);
    req.write(JSON.stringify({ username, password }));
    req.end();
  });
});

// Read / write persistent store from renderer
ipcMain.handle('store-get', (_, key) => store.get(key));
ipcMain.handle('store-set', (_, key, value) => { store.set(key, value); });

// Save raw audio chunks to ~/Documents/ParakeetAI/recordings/
ipcMain.handle('save-audio-chunk', async (_, { data, speakerType, timestamp }) => {
  const fs   = require('fs');
  const os   = require('os');
  const dir  = path.join(os.homedir(), 'Documents', 'ParakeetAI', 'recordings');
  fs.mkdirSync(dir, { recursive: true });
  const buf  = Buffer.from(data, 'base64');
  fs.writeFileSync(path.join(dir, `${speakerType}-${timestamp}.webm`), buf);
});

// Create a new session from the overlay
ipcMain.handle('django-new-session', async (_, { baseUrl, token, title, company, role }) => {
  const { net } = require('electron');
  const url = `${baseUrl}/api/session/new/`;
  return new Promise((resolve, reject) => {
    const req = net.request({ method: 'POST', url });
    req.setHeader('Content-Type', 'application/json');
    req.setHeader('X-Ext-Token', token);
    let body = '';
    req.on('response', res => {
      res.on('data', chunk => { body += chunk.toString(); });
      res.on('end', () => {
        try { resolve({ statusCode: res.statusCode, ...JSON.parse(body) }); }
        catch { reject(new Error('Invalid JSON response')); }
      });
    });
    req.on('error', reject);
    req.write(JSON.stringify({ title, company, role }));
    req.end();
  });
});

// Fetch /api/config/ through main process — avoids renderer CORS restrictions
ipcMain.handle('django-config', async (_, { baseUrl, token }) => {
  const { net } = require('electron');
  const url = `${baseUrl}/api/config/`;
  return new Promise((resolve, reject) => {
    const req = net.request({ method: 'GET', url });
    req.setHeader('X-Ext-Token', token);
    let body = '';
    req.on('response', res => {
      res.on('data', chunk => { body += chunk.toString(); });
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`HTTP ${res.statusCode}`));
          return;
        }
        try { resolve(JSON.parse(body)); }
        catch { reject(new Error('Invalid JSON response')); }
      });
    });
    req.on('error', reject);
    req.end();
  });
});
