const { app, BrowserWindow, ipcMain, Menu, screen, session } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const portArgument = process.argv.find(argument => argument.startsWith('--studio-port='));
const port = Number(portArgument?.slice('--studio-port='.length));
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  console.error('请使用 start-windows.cmd 启动豆姐锐评室。');
  app.exit(2);
  return;
}

const origin = `http://127.0.0.1:${port}`;
const focusOnly = process.argv.includes('--studio-focus');
const readyFile = process.argv.find(arg => arg.startsWith('--studio-ready-file='))?.slice('--studio-ready-file='.length);
const ownerPid = Number(process.argv.find(arg => arg.startsWith('--studio-owner='))?.slice('--studio-owner='.length));
app.setName('豆姐锐评室');
const profile = path.join(app.getPath('appData'), 'DoujieStudio', String(port));
fs.mkdirSync(profile, { recursive: true });
app.setPath('userData', profile);
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
let director;
let stage;
let lastStageBounds;
let portraitSize;

function stageBounds() {
  const display = lastStageBounds ? screen.getDisplayMatching(lastStageBounds) : screen.getPrimaryDisplay();
  const area = display.workArea;
  const { width, height } = portraitSize;
  const maxX = area.x + area.width - width, maxY = area.y + area.height - height;
  return {
    width, height,
    x: Math.max(area.x, Math.min(maxX, lastStageBounds?.x ?? maxX - 8)),
    y: Math.max(area.y, Math.min(maxY, lastStageBounds?.y ?? area.y + 8)),
  };
}

function focus(win) {
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function loadWindow(win, route) {
  const url = origin + route;
  const contents = win.webContents;
  // Renderer actions have no authority to create browsers, windows, or off-app navigation.
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  const restrictNavigation = event => {
    if (event.url !== url) event.preventDefault();
  };
  contents.on('will-frame-navigate', restrictNavigation);
  contents.on('will-redirect', restrictNavigation);
  win.once('ready-to-show', () => { if (!win.isDestroyed()) win.show(); });
  return win.loadURL(url).then(() => {
    if (win.isDestroyed()) return false;
    if (!win.isVisible()) win.show();
    return true;
  }).catch(error => {
    if (!win.isDestroyed()) console.error('演播室页面加载失败：', error.message);
    return false;
  });
}

const webPreferences = {
  contextIsolation: true, sandbox: true, nodeIntegration: false, backgroundThrottling: false,
};

function openStage() {
  if (stage && !stage.isDestroyed()) {
    focus(stage);
    return true;
  }
  const bounds = stageBounds();
  stage = new BrowserWindow({
    ...bounds, title: '豆姐 · 直播舞台', backgroundColor: '#102425', useContentSize: true,
    show: false, frame: false, thickFrame: false, roundedCorners: false, hasShadow: false,
    resizable: false, maximizable: false, fullscreenable: false, webPreferences,
  });
  stage.setContentSize(bounds.width, bounds.height);
  stage.on('close', () => { lastStageBounds = stage.getBounds(); });
  stage.on('closed', () => { stage = null; });
  return loadWindow(stage, '/stage.html');
}

async function createStudio() {
  Menu.setApplicationMenu(null);
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  const area = screen.getPrimaryDisplay().workArea;
  const unit = Math.max(1, Math.min(50, Math.floor(area.width / 9), Math.floor(area.height / 16)));
  portraitSize = { width: 9 * unit, height: 16 * unit };
  director = new BrowserWindow({
    ...portraitSize, x: area.x + Math.min(8, area.width - portraitSize.width), y: stageBounds().y,
    resizable: false, maximizable: false, fullscreenable: false,
    title: '豆姐锐评室 · 导播台', backgroundColor: '#f4f1ea', show: false,
    webPreferences: { ...webPreferences, preload: path.join(__dirname, 'preload.cjs') },
  });
  director.on('closed', () => { director = null; app.quit(); });
  ipcMain.handle('doujie:open-stage', event => {
    if (!director || event.sender !== director.webContents || event.senderFrame?.url !== origin + '/') return false;
    return openStage();
  });
  const loaded = await Promise.all([loadWindow(director, '/'), openStage()]);
  if (loaded.every(Boolean)) {
    if (readyFile) fs.writeFileSync(readyFile, 'ready');
  } else {
    app.exit(1);
  }
}

const focusRequest = focusOnly && readyFile ? { focusFile: readyFile } : {};
if (!app.requestSingleInstanceLock(focusRequest)) {
  app.quit();
} else if (focusOnly) {
  // The port is occupied by a different process. Do not load its pages or start a second studio.
  app.exit(2);
} else {
  app.on('second-instance', (_event, _argv, _cwd, request) => {
    if (!director || director.isDestroyed()) return;
    focus(director);
    const file = request?.focusFile;
    if (typeof file === 'string' && path.basename(file) === 'Electron' &&
        path.basename(path.dirname(file)).startsWith('doujie-launch-') &&
        path.relative(app.getPath('temp'), path.resolve(path.dirname(file), '..')) === '') {
      try { fs.writeFileSync(file, 'focused', { flag: 'wx' }); } catch { /* launcher may already be closed */ }
    }
  });
  app.on('window-all-closed', () => app.quit());
  if (process.argv.includes('--studio-parent')) {
    // A Windows GUI process can see a closed console stream while its launcher is still alive.
    if (Number.isSafeInteger(ownerPid) && ownerPid > 0) {
      setInterval(() => {
        try { process.kill(ownerPid, 0); } catch (error) { if (error.code === 'ESRCH') app.quit(); }
      }, 1000).unref();
    } else {
      process.stdin.on('end', () => app.quit());
    }
    process.stdin.on('error', () => {});
    process.stdin.on('data', data => { if (data.toString().trim() === 'quit') app.quit(); });
    process.stdin.resume();
  }
  app.whenReady().then(createStudio).catch(error => { console.error(error); app.exit(1); });
}
