/**
 * Memory Manager - Gerencia uso de memória e limpeza
 * @module MemoryManager
 */

class MemoryManager {
  constructor(config = {}) {
    this.config = {
      maxDOMMessages: config.maxDOMMessages || 200,
      maxAuditLogs: config.maxAuditLogs || 100,
      maxLocalStorageSize: config.maxLocalStorageSize || 5 * 1024 * 1024, // 5MB
      cleanupInterval: config.cleanupInterval || 300000, // 5 minutos
      ...config
    };
    
    this.cleanupTimer = null;
    this.stats = {
      lastCleanup: null,
      messagesRemoved: 0,
      logsRemoved: 0,
      bytesFreed: 0
    };
  }

  /**
   * Inicia monitoramento automático
   */
  start() {
    if (this.cleanupTimer) {
      console.warn('⚠️ Memory Manager já está ativo');
      return;
    }

    console.log('🧹 Memory Manager iniciado');
    this.cleanup(); // Limpeza imediata
    
    this.cleanupTimer = setInterval(() => {
      this.cleanup();
    }, this.config.cleanupInterval);
  }

  /**
   * Para monitoramento
   */
  stop() {
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer);
      this.cleanupTimer = null;
      console.log('🛑 Memory Manager pausado');
    }
  }

  /**
   * Executa limpeza completa
   */
  cleanup() {
    const startTime = performance.now();
    let totalRemoved = 0;

    // 1. Limpar mensagens antigas do DOM
    totalRemoved += this.cleanupDOMMessages();

    // 2. Limpar logs de auditoria
    totalRemoved += this.cleanupAuditLogs();

    // 3. Limpar localStorage se exceder limite
    this.cleanupLocalStorage();

    // 4. Forçar garbage collection (se disponível)
    if (window.gc) {
      window.gc();
    }

    const duration = (performance.now() - startTime).toFixed(2);
    this.stats.lastCleanup = new Date().toISOString();

    console.log(`🧹 Limpeza completa: ${totalRemoved} itens removidos em ${duration}ms`);
  }

  /**
   * Remove mensagens antigas do DOM
   */
  cleanupDOMMessages() {
    const chatContainer = document.getElementById('chat-messages');
    if (!chatContainer) return 0;

    const messages = chatContainer.querySelectorAll('.message-bubble');
    const toRemove = Math.max(0, messages.length - this.config.maxDOMMessages);

    if (toRemove > 0) {
      for (let i = 0; i < toRemove; i++) {
        messages[i].remove();
      }
      this.stats.messagesRemoved += toRemove;
      console.log(`📝 ${toRemove} mensagens antigas removidas`);
    }

    return toRemove;
  }

  /**
   * Remove logs de auditoria antigos
   */
  cleanupAuditLogs() {
    const auditContainer = document.getElementById('audit-log-container');
    if (!auditContainer) return 0;

    const logs = Array.from(auditContainer.children);
    const toRemove = Math.max(0, logs.length - this.config.maxAuditLogs);

    if (toRemove > 0) {
      logs.slice(-toRemove).forEach(log => log.remove());
      this.stats.logsRemoved += toRemove;
      console.log(`📋 ${toRemove} logs de auditoria removidos`);
    }

    return toRemove;
  }

  /**
   * Limpa localStorage se exceder limite
   */
  cleanupLocalStorage() {
    try {
      const totalSize = this.getLocalStorageSize();
      
      if (totalSize > this.config.maxLocalStorageSize) {
        console.warn(`⚠️ localStorage excedeu ${(this.config.maxLocalStorageSize / 1024 / 1024).toFixed(2)}MB`);
        
        // Remover histórico de chat mais antigo
        const chatHistory = JSON.parse(localStorage.getItem('chatHistory') || '[]');
        if (chatHistory.length > 50) {
          const reduced = chatHistory.slice(-50);
          localStorage.setItem('chatHistory', JSON.stringify(reduced));
          console.log(`📦 Histórico de chat reduzido: ${chatHistory.length} → 50 mensagens`);
        }
        
        // Remover logs de auditoria antigos
        if (localStorage.getItem('auditLogs')) {
          localStorage.removeItem('auditLogs');
          console.log('🗑️ Logs de auditoria removidos do localStorage');
        }
      }
    } catch (e) {
      console.error('Erro ao limpar localStorage:', e);
    }
  }

  /**
   * Calcula tamanho do localStorage
   */
  getLocalStorageSize() {
    let total = 0;
    for (let key in localStorage) {
      if (localStorage.hasOwnProperty(key)) {
        total += localStorage[key].length + key.length;
      }
    }
    return total * 2; // UTF-16: 2 bytes por char
  }

  /**
   * Estatísticas de memória
   */
  getStats() {
    const lsSize = this.getLocalStorageSize();
    const domMessages = document.querySelectorAll('.message-bubble').length;
    const auditLogs = document.querySelectorAll('.audit-entry').length;

    return {
      ...this.stats,
      current: {
        localStorageSize: lsSize,
        localStorageMB: (lsSize / 1024 / 1024).toFixed(2),
        domMessages,
        auditLogs,
        memoryUsage: performance.memory?.usedJSHeapSize 
          ? (performance.memory.usedJSHeapSize / 1024 / 1024).toFixed(2) + 'MB'
          : 'N/A'
      }
    };
  }

  /**
   * Debug: mostra uso de memória
   */
  debug() {
    console.table(this.getStats());
  }
}

// Export para uso em módulos
if (typeof module !== 'undefined' && module.exports) {
  module.exports = MemoryManager;
}
