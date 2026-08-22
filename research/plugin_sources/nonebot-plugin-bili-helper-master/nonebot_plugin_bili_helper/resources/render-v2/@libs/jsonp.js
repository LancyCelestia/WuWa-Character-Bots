{
  window.JsonPModule = {};
  const exports = window.JsonPModule;

  const module = { exports };
  const exportAs = o => Object.assign(module.exports, o);

  class JsonPBusyLock {
    #busy = false
    #queue = []

    async lock() {
      if (this.#busy) {
        await new Promise((resolve) => {
          this.#queue.push(resolve);
        });
      }
      this.#busy = true;
    }

    unlock() {
      this.#busy = false;
      const next = this.#queue.shift();
      if (next) {
        next();
      }
    }
  }

  const jsonPBusyLock = new JsonPBusyLock();
  const jsonPCallback = {
    name: 'jsonp_callback',
    waitingCallback: null,
    bind(target) {
      target[this.name] = (...args) => {
        if (this.waitingCallback) {
          this.waitingCallback(...args);
          this.waitingCallback = null;
        }
      };
    },
    register(cb) {
      this.waitingCallback = cb;
    },
  };
  jsonPCallback.bind(window);

  exportAs({ fetchJsonP });
  async function fetchJsonP(src = '') {
    await jsonPBusyLock.lock();
    return new Promise((resolve, reject) => {
      jsonPCallback.register(resolve);
      const script = document.createElement('script');
      script.src = src;
      script.onerror = (e) => {
        document.body.removeChild(script);
        jsonPBusyLock.unlock();
        console.error('JSONP加载错误:', e);
        reject(new Error(`JSONP加载失败: ${src}`));
      }
      script.onload = () => {
        document.body.removeChild(script);
        jsonPBusyLock.unlock();
      };
      document.body.appendChild(script);
    });
  }
}