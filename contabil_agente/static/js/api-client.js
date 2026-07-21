/**
 * API Client - Gerencia todas comunicações com backend
 * @module APIClient
 */

class APIClient {
  constructor(baseURL = '') {
    this.baseURL = baseURL;
    this.maxRetries = 3;
  }

  /**
   * Fetch com retry automático e exponential backoff
   */
  async fetchWithRetry(url, options, maxRetries = this.maxRetries) {
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const response = await fetch(url, options);
        
        if (response.ok) return response;
        
        // Retry em erros 5xx
        if (response.status >= 500 && attempt < maxRetries - 1) {
          const delay = Math.pow(2, attempt) * 1000;
          console.warn(`⚠️ HTTP ${response.status}. Tentativa ${attempt + 2}/${maxRetries} em ${delay/1000}s...`);
          await this.delay(delay);
          continue;
        }
        
        return response;
      } catch (error) {
        if (attempt < maxRetries - 1) {
          const delay = Math.pow(2, attempt) * 1000;
          console.error(`❌ Erro: ${error.message}. Retentando em ${delay/1000}s...`);
          await this.delay(delay);
          continue;
        }
        throw error;
      }
    }
  }

  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Envia mensagem para chat
   */
  async sendChatMessage(message, sessionId, tone = 'neutro') {
    return this.fetchWithRetry(`${this.baseURL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({
        mensagem: message,
        session_id: sessionId,
        tone: tone
      })
    });
  }

  /**
   * Verifica saúde do backend
   */
  async checkHealth() {
    try {
      const response = await fetch(`${this.baseURL}/api/health`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' }
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  /**
   * Download de documento
   */
  async downloadDocument(filename) {
    const response = await fetch(`${this.baseURL}/api/documents/${filename}`, {
      method: 'GET'
    });
    
    if (!response.ok) {
      throw new Error(`Erro ao baixar documento: ${response.status}`);
    }
    
    return response.blob();
  }

  /**
   * Upload de arquivo
   */
  async uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    return this.fetchWithRetry(`${this.baseURL}/api/upload`, {
      method: 'POST',
      body: formData
    });
  }
}

// Export para uso em módulos
if (typeof module !== 'undefined' && module.exports) {
  module.exports = APIClient;
}
