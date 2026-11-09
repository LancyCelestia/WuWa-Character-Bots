// 气泡场画布（算法来自参考站 daniya.top 的 `main.js` 第 219-352 行，见
// `lib/effects/bubble-field.ts` 的纯函数面与逐条常数注释）。
//
// 参考站只有一条 canvas2d 路径；本仓按用户要求「两条路都走」：
//   · WebGL2 可用且是 full 档 → 走 GL 点精灵（一份 shader，无依赖）
//   · 否则 → canvas2d 的径向渐变（参考站原样）
// 两条路共用同一份「算下一帧」（纯函数），所以**换路径不换画面**。
//
// 🔴 性能纪律（用户服务器 2C2T / 2G RAM）：
//   · `IntersectionObserver` 不可用时直接不看——但这里用可见性 + 页面 hidden **双停**
//     （参考站也是两条都做；它只停 rAF，本仓还额外把钱花在 0 上：off 档根本不建画布）
//   · DPR 封顶 2（参考站 `Math.min(devicePixelRatio || 1, 2)` 同值）
//   · 不在滚动事件里做事——只有 rAF 一条驱动
import { useEffect, useRef } from 'react';

import {
  type BubbleFrame,
  type Pop,
  burstAt,
  fieldCount,
  respawn,
  spawnBubble,
  stepBubble,
  stepPops,
} from '@/lib/effects/bubble-field';
import { type MotionFacts, pickParticlePath } from '@/lib/effects/motion-tier';

const GL_VERT = `#version 300 es
in vec2 aPos;
in float aR;
in vec3 aColor;
in float aAlpha;
uniform vec2 uRes;
out vec3 vColor;
out float vAlpha;
void main() {
  // 像素坐标 → NDC。半径换算成点的直径（gl_PointSize 是像素）。
  vec2 ndc = (aPos / uRes) * 2.0 - 1.0;
  gl_Position = vec4(ndc.x, -ndc.y, 0.0, 1.0);
  gl_PointSize = aR * 2.0;
  vColor = aColor;
  vAlpha = aAlpha;
}`;

const GL_FRAG = `#version 300 es
precision mediump float;
in vec3 vColor;
in float vAlpha;
out vec4 outColor;
void main() {
  // 点精灵内部坐标 [0,1]：到中心的距离决定径向衰减（参考站是 createRadialGradient，
  // 中心偏左上 0.34/0.38 处最亮 —— 这里用同一偏心量算高光）。
  vec2 c = gl_PointCoord - vec2(0.5);
  vec2 hi = c + vec2(-0.34, -0.38) * 0.5;
  float d = length(c) * 2.0;
  float hiD = length(hi) * 2.0;
  if (d > 1.0) discard;
  float body = (1.0 - d) * (1.0 - d) * vAlpha * 0.42;
  float rim = smoothstep(0.72, 1.0, d) * vAlpha * 0.5;
  float spec = (1.0 - hiD) * (1.0 - hiD) * vAlpha * 0.55;
  float a = clamp(body + rim + spec, 0.0, 1.0);
  outColor = vec4(vColor, a);
}`;

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader | null {
  const sh = gl.createShader(type);
  if (!sh) return null;
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    gl.deleteShader(sh);
    return null;
  }
  return sh;
}

export interface BubbleFieldProps {
  facts: MotionFacts;
  /** 外观页可调的粒子上限（`0` = 关掉）。 */
  cap?: number;
}

/** 全站背景气泡场。`off` 档返回 `null`（连 <canvas> 都不进 DOM）。 */
export function BubbleField({ facts, cap }: BubbleFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const path = pickParticlePath(facts);
  const count = fieldCount(facts.viewportWidth);
  const budget = cap === 0 ? 0 : Math.min(count, cap ?? count);

  useEffect(() => {
    if (path === 'none' || budget === 0) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rand = Math.random;
    let width = 0;
    let height = 0;
    let bubbles: BubbleFrame[] = [];
    let pops: Pop[] = [];
    let t = 0;
    let raf = 0;
    let running = true;

    const ctx2d = path === 'canvas2d' ? canvas.getContext('2d') : null;
    const gl = path === 'webgl' ? canvas.getContext('webgl2', { alpha: true, antialias: false }) : null;
    let prog: WebGLProgram | null = null;
    let buf: WebGLBuffer | null = null;
    let vao: WebGLVertexArrayObject | null = null;
    let uRes: WebGLUniformLocation | null = null;
    let floats: Float32Array = new Float32Array(0);

    if (gl) {
      const v = compile(gl, gl.VERTEX_SHADER, GL_VERT);
      const f = compile(gl, gl.FRAGMENT_SHADER, GL_FRAG);
      if (v && f) {
        prog = gl.createProgram();
        if (prog) {
          gl.attachShader(prog, v);
          gl.attachShader(prog, f);
          gl.linkProgram(prog);
          if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) prog = null;
        }
      }
      if (v) gl.deleteShader(v);
      if (f) gl.deleteShader(f);
      if (prog) {
        buf = gl.createBuffer();
        vao = gl.createVertexArray();
        uRes = gl.getUniformLocation(prog, 'uRes');
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      }
    }

    const layout = () => {
      const rect = canvas.getBoundingClientRect();
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      if (ctx2d) ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (gl) gl.viewport(0, 0, canvas.width, canvas.height);
      bubbles = [];
      for (let i = 0; i < budget; i += 1) bubbles.push({ ...spawnBubble(rand, width, height, true), alpha: 0 });
    };

    const drawGl = () => {
      if (!gl || !prog || !buf || !vao) return;
      const need = bubbles.length * 7;
      if (floats.length !== need) floats = new Float32Array(need);
      for (let i = 0; i < bubbles.length; i += 1) {
        const b = bubbles[i];
        const base = i * 7;
        floats[base] = b.x;
        floats[base + 1] = b.y;
        floats[base + 2] = b.r;
        floats[base + 3] = b.c[0] / 255;
        floats[base + 4] = b.c[1] / 255;
        floats[base + 5] = b.c[2] / 255;
        floats[base + 6] = b.alpha;
      }
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(prog);
      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, floats, gl.DYNAMIC_DRAW);
      const stride = 7 * 4;
      const attr = (name: string, size: number, offset: number) => {
        const loc = gl.getAttribLocation(prog as WebGLProgram, name);
        if (loc < 0) return;
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride, offset);
      };
      attr('aPos', 2, 0);
      attr('aR', 1, 8);
      attr('aColor', 3, 12);
      attr('aAlpha', 1, 24);
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.drawArrays(gl.POINTS, 0, bubbles.length);
      gl.bindVertexArray(null);
    };

    const draw2d = () => {
      if (!ctx2d) return;
      ctx2d.clearRect(0, 0, width, height);
      for (const p of pops) {
        ctx2d.beginPath();
        ctx2d.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        const [r, g, b] = p.c;
        ctx2d.strokeStyle = `rgba(${r},${g},${b},${p.alpha})`;
        ctx2d.lineWidth = 1;
        ctx2d.stroke();
      }
      for (const b of bubbles) {
        const [r, g, b2] = b.c;
        const a = b.alpha;
        const grad = ctx2d.createRadialGradient(
          b.x - b.r * 0.34,
          b.y - b.r * 0.38,
          b.r * 0.1,
          b.x,
          b.y,
          b.r
        );
        grad.addColorStop(0, `rgba(255,255,255,${(a * 0.55).toFixed(3)})`);
        grad.addColorStop(0.42, `rgba(${r},${g},${b2},${(a * 0.42).toFixed(3)})`);
        grad.addColorStop(1, `rgba(${r},${g},${b2},0)`);
        ctx2d.beginPath();
        ctx2d.arc(b.x, b.y, b.r, 0, Math.PI * 2);
        ctx2d.fillStyle = grad;
        ctx2d.fill();
        ctx2d.beginPath();
        ctx2d.arc(b.x, b.y, b.r, 0, Math.PI * 2);
        ctx2d.strokeStyle = `rgba(${r},${g},${b2},${(a * 0.5).toFixed(3)})`;
        ctx2d.lineWidth = 0.8;
        ctx2d.stroke();
        ctx2d.beginPath();
        ctx2d.arc(b.x - b.r * 0.34, b.y - b.r * 0.38, Math.max(0.6, b.r * 0.16), 0, Math.PI * 2);
        ctx2d.fillStyle = `rgba(255,255,255,${(a * 0.7).toFixed(3)})`;
        ctx2d.fill();
      }
    };

    const frame = () => {
      t += 1;
      const next: BubbleFrame[] = [];
      for (const b of bubbles) {
        const s = stepBubble(b, t, height);
        next.push(s);
        // 回收：越顶或寿终就从底部重新排队（新气泡的 alpha 用基准值，不继承上一颗）。
        if (respawn(s)) {
          const fresh = spawnBubble(rand, width, height, false);
          next[next.length - 1] = { ...fresh, alpha: fresh.a };
        }
      }
      bubbles = next;
      pops = stepPops(pops);
      if (gl) drawGl();
      else draw2d();
      if (running) raf = window.requestAnimationFrame(frame);
    };

    const onPointerDown = (e: PointerEvent) => {
      // 参考站只认细指针；本仓同判据。点击落在可交互元素上时不爆（免得点按钮还冒泡）。
      const target = e.target as HTMLElement | null;
      if (target && target.closest('a, button, input, select, textarea, [role="button"]')) return;
      pops = [...pops, burstAt(e.clientX, e.clientY, rand)];
    };

    const stop = () => {
      running = false;
      if (raf) window.cancelAnimationFrame(raf);
      raf = 0;
    };
    const start = () => {
      if (running) return;
      running = true;
      raf = window.requestAnimationFrame(frame);
    };

    const onVisibility = () => {
      if (document.hidden) stop();
      else start();
    };

    layout();
    raf = window.requestAnimationFrame(frame);
    window.addEventListener('resize', layout);
    window.addEventListener('pointerdown', onPointerDown, { passive: true });
    document.addEventListener('visibilitychange', onVisibility);
    // 滚出视口就停（参考站用 IntersectionObserver 观察 hero；本仓背景层常驻，
    // 但外层容器被 display:none（省流 / 动效关闭）时同样该停）。
    const io =
      typeof IntersectionObserver === 'function'
        ? new IntersectionObserver(
            (entries) => {
              for (const e of entries) {
                if (e.isIntersecting) start();
                else stop();
              }
            },
            { threshold: 0.01 }
          )
        : null;
    io?.observe(canvas);

    return () => {
      stop();
      io?.disconnect();
      window.removeEventListener('resize', layout);
      window.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('visibilitychange', onVisibility);
      if (gl) {
        if (prog) gl.deleteProgram(prog);
        if (buf) gl.deleteBuffer(buf);
        if (vao) gl.deleteVertexArray(vao);
      }
    };
  }, [path, budget]);

  if (path === 'none' || budget === 0) return null;
  return <canvas ref={canvasRef} className='bubble-field' aria-hidden />;
}
