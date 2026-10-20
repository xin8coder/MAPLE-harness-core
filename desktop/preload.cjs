'use strict'
const { contextBridge, ipcRenderer } = require('electron')
contextBridge.exposeInMainWorld('mapleConnection', {
  read: () => ipcRenderer.invoke('maple:connection'),
  connect: value => ipcRenderer.invoke('maple:connect', value),
})
