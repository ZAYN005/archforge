'use strict';

const path = require('path');
const { app, BrowserWindow } = require('electron');

// @req FR-5
// createWindow() -> BrowserWindow: creates the Electron BrowserWindow and
// loads the app URL from the running Express server.
function createWindow(port) {
  const win = new BrowserWindow({
    width: 1100,
    height: 750,
    title: 'Space Fractions',
    autoHideMenuBar: true,
    backgroundColor: '#05071a',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.once('ready-to-show', () => win.show());
  win.loadURL(`http://127.0.0.1:${port}/`);

  return win;
}

// @req C-1 FR-5
// Start the Express server in-process on a free port, point the durable data
// file at the userData directory, then open a native window around it.
async function boot() {
  // Store data in the user data directory for durability across launches.
  process.env.DATA_FILE = path.join(app.getPath('userData'), 'store.json');

  const { start } = require('../src/server');
  const { port } = await start(0);

  createWindow(port);
}

app.whenReady().then(boot);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    process.env.DATA_FILE = path.join(app.getPath('userData'), 'store.json');
    require('../src/server').start(0).then(({ port }) => createWindow(port));
  }
});

module.exports = { createWindow };
