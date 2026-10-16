/**
 * Rate Limiter - Controla frequência de requisições
 * @module RateLimiter
 */

class RateLimiter {
  constructor(maxRequests = 20, windowMs = 60000) {
    this.maxRequests = maxRequests;
    this.windowMs = windowMs;
    this.requests = [];
    this.lastRequestTime = 0;
    this.cooldownMs = 500;
  }

  /**
   * Verifica se pode fazer requisição
   */
  canMakeRequest() {
    const now = Date.now();
    
    // Debounce: evitar múltiplos cliques rápidos
    if (now - this.lastRequestTime < this.cooldownMs) {
      console.warn(`⏳ Aguarde ${this.cooldownMs}ms entre requisições`);
      return false;
    }
    
    // Limpar requisições antigas
    this.requests = this.requests.filter(timestamp => 
      timestamp > now - this.windowMs
    );
    
    // Verificar limite
    if (this.requests.length >= this.maxRequests) {
      const oldestRequest = Math.min(...this.requests);
      const waitTime = Math.ceil((oldestRequest + this.windowMs - now) / 1000);
      console.warn(`⚠️ Limite de ${this.maxRequests} requisições atingido. Aguarde ${waitTime}s`);
      return false;
    }
    
    return true;
  }

  /**
   * Registra nova requisição
   */
  recordRequest() {
    const now = Date.now();
    this.requests.push(now);
    this.lastRequestTime = now;
  }

  /**
   * Reseta contador
   */
  reset() {
    this.requests = [];
    this.lastRequestTime = 0;
  }

  /**
   * Status atual
   */
  getStatus() {
    const now = Date.now();
    const activeRequests = this.requests.filter(t => t > now - this.windowMs);
    
    return {
      current: activeRequests.length,
      max: this.maxRequests,
      windowMs: this.windowMs,
      canRequest: this.canMakeRequest(),
      nextAvailableIn: activeRequests.length >= this.maxRequests 
        ? Math.max(0, Math.min(...activeRequests) + this.windowMs - now)
        : 0
    };
  }
}

// Export para uso em módulos
if (typeof module !== 'undefined' && module.exports) {
  module.exports = RateLimiter;
}
