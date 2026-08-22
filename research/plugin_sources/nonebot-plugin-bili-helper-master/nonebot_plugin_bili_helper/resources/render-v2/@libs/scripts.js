{
  window.ScriptsModule = {};
  const exports = window.ScriptsModule;

  const module = { exports };
  const exportAs = o => Object.assign(module.exports, o);

  exportAs({ createScript });
  async function createScript({
    id = '',
    src = '',
    type = 'text/javascript',
    content = '',
    parent = document.body,
    attr = {},
  }) {
    const script = document.createElement('script');
    script.id = id;
    script.type = type;
    Object.entries(attr).forEach(([key, value]) => script.setAttribute(key, value));
    return new Promise((resolve, reject) => {
      if (src) {
        script.src = src;
        script.onload = resolve;
        script.onerror = () => {
          const errMsg = `Failed to load script: ${script.src || 'unknown source'}`;
          reject(new Error(errMsg));
        };
      } else if (content) {
        script.innerHTML = content;
        window.setTimeout(resolve, 0);
      }
      parent.appendChild(script);
    });
  }

  exportAs({ loadTemplate });
  async function loadTemplate(src = '') {
    const text = await fetch(src).then((res) => res.text());
    createScript({ id: `${src}`, type: 'text/html', content: text });
  }

  exportAs({ loadTemplates });
  async function loadTemplates(list = [], cb = null) {
    await list.reduce((p, src) => p.then(() => {
      loadTemplate(src);
    }), Promise.resolve());
    cb?.();
  }
}
