import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import template from 'art-template';

const dirname = path.dirname(fileURLToPath(import.meta.url));

// const resPath = path.join(dirname, '../..');
const resPath = '../..';
const tplDirPath = path.join(dirname, '../../template');

export const status = {
  currentCommitId: 'latest',
};

export const Version = {
  BotName: 'Bocchi',
  BotVersion: '1.0.0',
  pluginName: 'kkkkkk',
  version: '1.9.0 - mod',
};

export const basePaths = {
  douyin: 'douyin/html',
  bilibili: 'bilibili/html',
  admin: 'admin/html',
  kuaishou: 'kuaishou/html',
  help: 'help/html',
  version: 'version/html'
};

export class Renderer {
  platform;
  saveId;
  templatePath = '';
  renderScale = 100;

  /**
   * 
   * @param {String} templateName 
   * @param {Object} options 
   * @param {Number} options.renderScale 渲染缩放比例，默认为 100 (百分比)
   */
  constructor(templateName = '', options = {}) {
    const [platform, saveId] = templateName.split('/');
    this.platform = platform || '';
    this.saveId = saveId || 'index';
    this.templatePath = `${basePaths[platform]}/${saveId}`;
    this.renderScale = options.renderScale || 100;
  }

  /**
   * @param {object} params 模板参数
   * @param {object} options 渲染参数
   * @param {'light' |'dark'} options.theme 主题，默认 light
   */
  render(params = {}, options = {}) {
    const { platform, saveId, templatePath, renderScale } = this;
    const theme = options.theme || 'light';

    function scale(pct = 1) {
      const scale = Math.min(2, Math.max(0.5, Number(renderScale) / 100));
      pct = pct * scale;
      return `style=transform:scale(${pct})`;
    }

    const tplFile = `${tplDirPath}/${templatePath}.html`;
    const baseParams = {
      // 资源路径
      _res_path: resPath.replace(/\\/g, '/') + '/',
      // 布局模板路径
      _layout_path: path.join(tplDirPath, 'extend').replace(/\\/g, '/') + '/',
      // 默认布局文件路径
      defaultLayout: path.join(tplDirPath, 'extend', 'html', 'default.html').replace(/\\/g, '/'),
      sys: {
        scale: scale(params?.scale ?? 1),
      },
      copyright: `<span class="name">${Version.BotName}</span><span class="version">${Version.BotVersion}</span> 
          & <span class="name">${Version.pluginName}</span><span class="version">${Version.version}</span>
          & <span class="name">Id</span><span class="version">${status.currentCommitId}</span>`,
      pageGotoParams: {
        waitUntil: 'load',
      },
      useDarkTheme: theme === 'dark',
      pluResPath: resPath.replace(/\\/g, '/') + '/',
      resPath: `${resPath}/`,
      tplFile: tplFile,
      saveId: saveId,
    };
    console.log('渲染参数:', baseParams);
    const data = {
      ...baseParams,
      ...params,
    };

    const task = {
      tplFile,
      saveId,
      data,
      html: '',
    };

    try {
      task.html = fs.readFileSync(tplFile, 'utf8')
      // task.html = document.getElementById(tplFile).innerHTML;
    } catch (error) {
      console.error(`加载html错误：${templatePath} (${tplFile})`, error);
      return false;
    }

    console.info(`渲染模板 ${platform}:${saveId}，主题 ${theme}`);
    return template.render(task.html, task.data);
  }
}
