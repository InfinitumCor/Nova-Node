// Nova Public — Electron Main Process
// Frameless, dark, orb centered. Consumer-facing companion.

const { app, BrowserWindow } = require('electron');
const path = require('path');

let mainWindow = null;

app.commandLine.appendSwitch('disable-http-cache');

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 900,
        height: 700,
        frame: false,
        backgroundColor: '#040a0e',
        icon: path.join(__dirname, 'icon.png'),
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
        },
    });

    mainWindow.loadFile(path.join(__dirname, 'index.html'));
    mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
