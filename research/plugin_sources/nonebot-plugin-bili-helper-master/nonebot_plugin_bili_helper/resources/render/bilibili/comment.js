import fs from 'node:fs';

import {
  Renderer,
} from '../@libs/renderer-node.js';
import {
  numberReadable,
  bilibiliReplies,
} from '../@formatters/bilibili.js';

function main(savePath, videoInfoJson = '', commentsJson = '') {
  if (!savePath) {
    console.error('缺少参数: 保存路径');
    return;
  }
  const templateName = 'bilibili/comment';
  const videoInfo = JSON.parse(fs.readFileSync(videoInfoJson, 'utf8'));
  const comments = JSON.parse(fs.readFileSync(commentsJson, 'utf8'));
  comments.data.replies = comments.data.replies.slice(0, 3);

  const nowHour = new Date().getHours();
  const theme = (nowHour >= 7 && nowHour <= 19) ? 'light' : 'dark';
  const renderer = new Renderer(templateName, {
    renderScale: 100,
  });

  const shareUrl = `https://b23.tv/${videoInfo.data.bvid}`;

  const html = renderer.render({
    Type: '视频',
    CommentsData: bilibiliReplies(comments, { theme }),
    CommentLength: numberReadable(videoInfo.data.stat.reply, '无法获取'),
    share_url: shareUrl,
    Clarity: '?',
    VideoSize: '?',
    ImageLength: 0,
    shareurl: shareUrl,
  }, { theme: theme });
  if (!html) {
    console.error('渲染失败');
    return;
  }
  fs.writeFileSync(savePath, html);
}

const args = process.argv.slice(2);
main(...args);
