// preload.js — secure bridge between renderer and main process
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('parakeet', {
  hide:                ()        => ipcRenderer.send('hide-overlay'),
  minimize:            ()        => ipcRenderer.send('minimize-overlay'),
  close:               ()        => ipcRenderer.send('close-overlay'),
  setOpacity:          (alpha)   => ipcRenderer.send('set-opacity', alpha),
  setAlwaysOnTop:      (on)      => ipcRenderer.send('set-always-on-top', on),
  djangoChat:          (payload) => ipcRenderer.invoke('django-chat', payload),
  djangoConfig:        (payload) => ipcRenderer.invoke('django-config', payload),
  djangoTranscript:    (payload) => ipcRenderer.invoke('django-transcript', payload),
  djangoTranscribeAudio:(payload)=> ipcRenderer.invoke('django-transcribe-audio', payload),
  djangoLogin:         (payload) => ipcRenderer.invoke('django-login', payload),
  djangoNewSession:    (payload) => ipcRenderer.invoke('django-new-session', payload),
  storeGet:            (key)     => ipcRenderer.invoke('store-get', key),
  storeSet:            (key, v)  => ipcRenderer.invoke('store-set', key, v),
  saveAudioChunk:      (payload) => ipcRenderer.invoke('save-audio-chunk', payload),
});
