// ES6 module: voice_ws_client.js
// Usage:
// import VoiceWSClient from '/static/voice_ws_client.js';
// const client = new VoiceWSClient({ sessionId, urlBase: '', onTyping, onError, onLog });
// client.connect();

export default class VoiceWSClient {
  constructor({ sessionId = 'demo', urlBase = '', onTyping = null, onError = null, onLog = null } = {}) {
    this.sessionId = sessionId;
    this.urlBase = urlBase.replace(/\/$/, '');
    this.onTyping = onTyping || (() => {});
    this.onError = onError || (() => {});
    this.onLog = onLog || (() => {});

    this.ws = null;
    this.audioChunks = [];
    this.expectedMime = null; // 'audio/wav' or 'audio/mpeg'
    this.reconnectAttempts = 0;
    this.maxReconnect = 6;

    // Web Audio API
    this.audioCtx = null;
    this.source = null;

    // MediaSource progressive streaming
    this.mediaSource = null;
    this.sourceBuffer = null;
    this.bufferQueue = [];
    this.mediaAttached = false;
    // Optional external audio element to attach playback to
    this.audioElement = null;
  }

  _log(...args) { try { this.onLog(...args); } catch(e) { console.log(...args); } }
  _error(...args) { try { this.onError(...args); } catch(e) { console.error(...args); } }
  _typing(status){ try { this.onTyping(status); } catch(e) { /* noop */ } }

  get wsUrl(){
    const proto = (location.protocol === 'https:') ? 'wss://' : 'ws://';
    const host = location.host;
    return `${proto}${host}${this.urlBase}/ws/voice/${encodeURIComponent(this.sessionId)}`;
  }

  attachAudioElement(el){
    // Accept either selector or element
    if(typeof el === 'string') el = document.querySelector(el);
    if(!(el instanceof HTMLMediaElement)) return false;
    this.audioElement = el;
    return true;
  }

  connect(){
    if(this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    this._log('connecting to', this.wsUrl);
    try{
      this.ws = new WebSocket(this.wsUrl);
      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = () => {
        this._log('ws open');
        this.reconnectAttempts = 0;
      };

      this.ws.onmessage = async (evt) => {
        if(typeof evt.data === 'string'){
          this._handleText(evt.data);
        } else {
          await this._handleBinary(evt.data);
        }
      };

      this.ws.onclose = (ev) => {
        this._log('ws closed', ev.code, ev.reason);
        this._typing(false);
        this._reconnectWithBackoff();
      };

      this.ws.onerror = (e) => {
        this._error('ws error', e);
        this._typing(false);
      };
    }catch(e){
      this._error('connect failed', e);
      this._reconnectWithBackoff();
    }
  }

  close(){
    if(this.ws) try{ this.ws.close(); }catch(e){}
    this.ws = null;
  }

  _reconnectWithBackoff(){
    if(this.reconnectAttempts >= this.maxReconnect) {
      this._error('Max reconnect attempts reached');
      return;
    }
    this.reconnectAttempts += 1;
    const delay = Math.min(30000, 500 * Math.pow(2, this.reconnectAttempts));
    this._log(`reconnect in ${delay}ms`);
    setTimeout(()=> this.connect(), delay);
  }

  _handleText(raw){
    let msg = null;
    try{ msg = JSON.parse(raw); }catch(e){ this._log('text:', raw); return; }
    this._log('event', msg);
    const ev = msg.event;
    if(ev === 'persona_typing'){
      const status = !!msg.status;
      this._typing(status);
    } else if(ev === 'audio_ready'){
      // try detect mime from filepath extension
      const fp = msg.filepath || msg.file || '';
      if(fp.match(/\.mp3$/i) || fp.match(/\.mpeg$/i)) this.expectedMime = 'audio/mpeg';
      else if(fp.match(/\.wav$/i)) this.expectedMime = 'audio/wav';
      else if(msg.mime) this.expectedMime = msg.mime;
      else this.expectedMime = this.expectedMime || 'audio/wav';
      this._log('detected mime', this.expectedMime);
      // reset chunk buffer for new asset
      this.audioChunks = [];
      // Prepare MediaSource when appropriate (prefer audio/mpeg)
      if(this.expectedMime === 'audio/mpeg' && window.MediaSource){
        this._initMediaSource(this.expectedMime);
      } else {
        // reset any MediaSource if MIME incompatible
        this._teardownMediaSource();
      }
    } else if(ev === 'audio_stream_end'){
      this._log('stream finished');
      // signal end of stream for MediaSource if present
      if(this.mediaSource && this.mediaSource.readyState === 'open'){
        try{ this.mediaSource.endOfStream(); }catch(e){ this._log('endOfStream failed', e); }
      } else {
        this._playCollectedAudio();
      }
    } else if(ev === 'error'){
      this._error('server error', msg.message || JSON.stringify(msg));
    } else if(ev === 'transcription_result'){
      this._log('transcription', msg.result);
    } else {
      this._log('unhandled event', msg);
    }
  }

  async _handleBinary(data){
    // push raw ArrayBuffer chunk
    try{
      this._log('binary chunk', data.byteLength);
      // If MediaSource is active and supported for this mime, feed queue
      if(this.mediaSource && this.sourceBuffer){
        this.bufferQueue.push(new Uint8Array(data));
        this._flushBufferQueue();
      } else {
        // fallback: collect chunks for blob playback
        this.audioChunks.push(data);
      }
    }catch(e){ this._error('binary handle error', e); }
  }

  _initMediaSource(mime){
    try{
      if(!window.MediaSource) return;
      if(this.mediaSource) return; // already initialized

      this.mediaSource = new MediaSource();
      const url = URL.createObjectURL(this.mediaSource);
      let audioEl = this.audioElement || document.createElement('audio');
      audioEl.controls = true;
      if(!this.audioElement){
        audioEl.style.display = 'none';
        document.body.appendChild(audioEl);
      }
      audioEl.src = url;
      this.audioElement = audioEl;

      this.mediaSource.addEventListener('sourceopen', () => {
        try{
          // For MP3 streams, many browsers accept 'audio/mpeg'
          const codec = mime === 'audio/mpeg' ? 'audio/mpeg' : mime;
          if(this.mediaSource && this.mediaSource.readyState === 'open'){
            this.sourceBuffer = this.mediaSource.addSourceBuffer(codec);
            this.sourceBuffer.addEventListener('updateend', () => this._flushBufferQueue());
            this.sourceBuffer.addEventListener('error', (e) => this._error('sourceBuffer error', e));
            // start playing as soon as possible
            this.audioElement.play().catch(()=>{});
          }
        }catch(e){
          this._log('sourceopen error', e);
        }
      });
    }catch(e){ this._error('initMediaSource failed', e); }
  }

  _teardownMediaSource(){
    try{
      if(this.sourceBuffer){
        try{ this.sourceBuffer.abort(); }catch(e){}
        this.sourceBuffer = null;
      }
      if(this.mediaSource){
        try{ if(this.mediaSource.readyState === 'open') this.mediaSource.endOfStream(); }catch(e){}
        this.mediaSource = null;
      }
      // do not remove audioElement to avoid UI surprises
      this.bufferQueue = [];
    }catch(e){ this._log('teardownMediaSource error', e); }
  }

  _flushBufferQueue(){
    if(!this.sourceBuffer) return;
    if(this.sourceBuffer.updating) return;
    if(!this.bufferQueue.length) return;

    const next = this.bufferQueue.shift();
    try{
      this.sourceBuffer.appendBuffer(next);
    }catch(e){
      this._error('appendBuffer failed', e);
      // push back and try later
      this.bufferQueue.unshift(next);
    }
  }

  async _playCollectedAudio(){
    if(!this.audioChunks.length){ this._log('no audio to play'); return; }

    // assemble blob and use Web Audio API to decode and play
    const mime = this.expectedMime || 'audio/wav';
    const blob = new Blob(this.audioChunks, { type: mime });

    try{
      if(!this.audioCtx) this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();

      const arrayBuffer = await blob.arrayBuffer();
      // decodeAudioData is async and won't block UI
      const audioBuffer = await this.audioCtx.decodeAudioData(arrayBuffer);

      const src = this.audioCtx.createBufferSource();
      src.buffer = audioBuffer;
      src.connect(this.audioCtx.destination);
      src.start(0);
      // keep reference so it isn't GC'd immediately
      this.source = src;
      this._log('playing audio');
    }catch(e){
      this._error('play failed, falling back to blob URL', e);
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.play().catch(err => this._error('audio element play failed', err));
    } finally{
      // reset buffer for next stream
      this.audioChunks = [];
      this.expectedMime = null;
    }
  }

  sendSynthesize(text, { stream = true, filename = null } = {}){
    if(!this.ws || this.ws.readyState !== WebSocket.OPEN){ this._error('ws not connected'); return; }
    const payload = { action: 'synthesize', text: text, stream: !!stream };
    if(filename) payload.filename = filename;
    try{ this.ws.send(JSON.stringify(payload)); }
    catch(e){ this._error('send failed', e); }
  }

  async startMicrophone(){
    // Simple mic permission check and error handling
    try{
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Not implementing streaming mic to server here; just confirm availability
      this._log('microphone ready');
      stream.getTracks().forEach(t => t.stop());
      return { status: 'ok' };
    }catch(e){
      this._error('microphone access failed', e);
      return { status: 'error', error: String(e) };
    }
  }
}
