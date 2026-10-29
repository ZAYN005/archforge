'use strict';

const { contextBridge } = require('electron');

// @req FR-5
// exposeDesktopBridge() -> void: exposes a minimal frozen desktop API through
// contextBridge. The renderer stays sandboxed (contextIsolation on, node
// integration off), so only this tiny, read-only surface is available.
function exposeDesktopBridge() {
  contextBridge.exposeInMainWorld('desktop', Object.freeze({
    platform: process.platform,
    version: process.version,
  }));
}

exposeDesktopBridge();

module.exports = { exposeDesktopBridge };
