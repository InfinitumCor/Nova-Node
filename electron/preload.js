const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('novaAPI', {
    platform: process.platform,
});
