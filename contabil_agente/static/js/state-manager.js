/**
 * State Manager - Gerenciamento centralizado de estado da aplicação
 * @module StateManager
 */

class StateManager {
  constructor() {
    this._state = {
      session: {
        id: this.generateSessionId(),
        active: false,
        startTime: null
      },
      chat: {
        messages: [],
        isProcessing: false,
        history: []
      },
      voice: {
        enabled: false,
        listening: false,
        recognition: null
      },
      documents: {
        current: null,
        history: [],
        autoDownload: false
      },
      settings: {
        tone: 'neutro',
        autoDownload: false,
        voiceEnabled: false
      },
      ui: {
        badges: {
          calculo: false,
          pdf: false,
          assinatura: false
        }
      }
    };
    
    this._listeners = new Map();
    this._history = [];
    this.maxHistorySize = 100;
  }

  generateSessionId() {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * Get estado por path (ex: 'chat.isProcessing')
   */
  get(path) {
    return path.split('.').reduce((obj, key) => obj?.[key], this._state);
  }

  /**
   * Set estado e notifica listeners
   */
  set(path, value) {
    const keys = path.split('.');
    const last = keys.pop();
    const obj = keys.reduce((o, k) => o[k], this._state);
    
    const oldValue = obj[last];
    obj[last] = value;
    
    // Histórico de mudanças
    this._history.push({
      path,
      oldValue,
      newValue: value,
      timestamp: new Date().toISOString()
    });
    
    if (this._history.length > this.maxHistorySize) {
      this._history.shift();
    }
    
    this._notify(path, value, oldValue);
  }

  /**
   * Subscribe a mudanças em path específico
   */
  subscribe(path, callback) {
    if (!this._listeners.has(path)) {
      this._listeners.set(path, []);
    }
    this._listeners.get(path).push(callback);
    
    // Retorna função de unsubscribe
    return () => {
      const callbacks = this._listeners.get(path);
      const index = callbacks.indexOf(callback);
      if (index > -1) callbacks.splice(index, 1);
    };
  }

  /**
   * Notifica listeners
   */
  _notify(path, newValue, oldValue) {
    // Notifica listeners do path exato
    this._listeners.get(path)?.forEach(cb => cb(newValue, oldValue));
    
    // Notifica listeners de paths pai (ex: 'chat' quando 'chat.isProcessing' muda)
    const parts = path.split('.');
    for (let i = parts.length - 1; i > 0; i--) {
      const parentPath = parts.slice(0, i).join('.');
      this._listeners.get(parentPath)?.forEach(cb => cb(this.get(parentPath)));
    }
  }

  /**
   * Adiciona mensagem ao chat
   */
  addMessage(role, text, metadata = {}) {
    const message = {
      id: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      role,
      text,
      timestamp: new Date().toISOString(),
      metadata
    };
    
    const messages = this.get('chat.messages');
    messages.push(message);
    this.set('chat.messages', messages);
    
    return message;
  }

  /**
   * Limpa histórico de chat
   */
  clearChat() {
    this.set('chat.messages', []);
    this.set('chat.history', []);
  }

  /**
   * Persiste estado no localStorage
   */
  persist() {
    try {
      const persistData = {
        session: this._state.session,
        settings: this._state.settings,
        documents: this._state.documents.history,
        chatHistory: this._state.chat.messages.slice(-100) // Últimas 100
      };
      localStorage.setItem('appState', JSON.stringify(persistData));
    } catch (e) {
      console.error('Erro ao persistir estado:', e);
    }
  }

  /**
   * Carrega estado do localStorage
   */
  restore() {
    try {
      const data = localStorage.getItem('appState');
      if (!data) return;
      
      const parsed = JSON.parse(data);
      if (parsed.settings) this._state.settings = parsed.settings;
      if (parsed.chatHistory) this._state.chat.messages = parsed.chatHistory;
      if (parsed.documents) this._state.documents.history = parsed.documents;
      
      console.log('✅ Estado restaurado do localStorage');
    } catch (e) {
      console.error('Erro ao restaurar estado:', e);
    }
  }

  /**
   * Debug: mostra estado atual
   */
  debug() {
    console.log('📊 Estado Atual:', JSON.parse(JSON.stringify(this._state)));
    console.log('📜 Histórico de Mudanças:', this._history.slice(-10));
    console.log('👂 Listeners:', Array.from(this._listeners.keys()));
  }
}

// Export para uso em módulos
if (typeof module !== 'undefined' && module.exports) {
  module.exports = StateManager;
}
