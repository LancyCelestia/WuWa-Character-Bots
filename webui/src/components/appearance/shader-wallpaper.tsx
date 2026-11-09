// 程序化壁纸（UI3 追加一/二）：WebGL 片元着色器现场生成，**0 字节传输**。
//
// 用户服务器是 2C2T / 2G RAM / 20GB 月流量，所以默认皮肤绝不能是任何媒体文件。
// 这里画的是「海面辉光 + 缓慢流动的釉瑚色带」，参数全部来自外观总线写的 CSS 变量
// （颜色、速度、强度），所以用户调光斑/配色时它也跟着变——但本组件自己不设任何数值默认。
//
// 降级：拿不到 WebGL → 不渲染（由调用方回落到纯 CSS 渐变底，同样 0 字节）。
// 动效：`--mo-play: paused`（动效总开关关）时只画第一帧，不再 requestAnimationFrame。
import { useEffect, useRef } from 'react';

const VERT = `
attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

// 三团高斯光斑在深色底上缓慢漂移，按屏幕比例拉伸；颜色取外观总线的 --au-a/b/c。
const FRAG = `
precision mediump float;
uniform vec2 uRes;
uniform float uTime;
uniform vec3 uA;
uniform vec3 uB;
uniform vec3 uC;

float blob(vec2 uv, vec2 c, float r) {
  vec2 d = uv - c;
  return exp(-dot(d, d) / (r * r));
}

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  float aspect = uRes.x / max(uRes.y, 1.0);
  vec2 p = vec2((uv.x - 0.5) * aspect, uv.y - 0.5);
  float t = uTime * 0.06;
  vec3 col = vec3(0.055, 0.075, 0.125);
  col += uA * 0.55 * blob(p, vec2(-0.42 + 0.16 * sin(t * 1.3), 0.30 + 0.12 * cos(t * 1.1)), 0.55);
  col += uB * 0.48 * blob(p, vec2(0.38 + 0.14 * cos(t * 0.9), -0.18 + 0.16 * sin(t * 1.7)), 0.62);
  col += uC * 0.42 * blob(p, vec2(0.05 + 0.22 * sin(t * 0.7), -0.34 + 0.10 * cos(t * 1.9)), 0.50);
  // 细微波纹：让静态帧也有海面质感（成本 = 一次 sin）。
  col += 0.018 * sin((p.x * 26.0 + p.y * 18.0) + uTime * 0.35);
  gl_FragColor = vec4(col, 1.0);
}
`;

function compile(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

/** 从根元素读一个 `rgb(r g b)` 变量（外观总线写的形态）；读不到回落中性色。 */
function readRgb(style: CSSStyleDeclaration, name: string, fallback: [number, number, number]) {
  const raw = style.getPropertyValue(name).trim();
  const m = /(\d{1,3})\D+(\d{1,3})\D+(\d{1,3})/.exec(raw);
  if (!m) return fallback.map((v) => v / 255) as [number, number, number];
  return [Number(m[1]) / 255, Number(m[2]) / 255, Number(m[3]) / 255] as [number, number, number];
}

export function ShaderWallpaper({ paused }: { paused: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext('webgl', { antialias: false, alpha: false, powerPreference: 'low-power' });
    if (!gl) return;

    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    const program = gl.createProgram();
    if (!vs || !fs || !program) return;
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(program, 'aPos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(program, 'uRes');
    const uTime = gl.getUniformLocation(program, 'uTime');
    const uA = gl.getUniformLocation(program, 'uA');
    const uB = gl.getUniformLocation(program, 'uB');
    const uC = gl.getUniformLocation(program, 'uC');

    // 像素比压到 ≤1.5：整屏着色器在手机上按 devicePixelRatio 跑会直接烤 GPU。
    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      const w = Math.max(1, Math.floor(window.innerWidth * ratio * 0.5));
      const h = Math.max(1, Math.floor(window.innerHeight * ratio * 0.5));
      canvas.width = w;
      canvas.height = h;
      gl.viewport(0, 0, w, h);
      gl.uniform2f(uRes, w, h);
    };
    resize();
    window.addEventListener('resize', resize);

    const rootStyle = getComputedStyle(document.documentElement);
    gl.uniform3fv(uA, readRgb(rootStyle, '--au-a', [88, 186, 232]));
    gl.uniform3fv(uB, readRgb(rootStyle, '--au-b', [150, 118, 236]));
    gl.uniform3fv(uC, readRgb(rootStyle, '--au-c', [96, 150, 224]));

    let raf = 0;
    const start = performance.now();
    const draw = (now: number) => {
      gl.uniform1f(uTime, (now - start) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (!paused) raf = requestAnimationFrame(draw);
    };
    draw(performance.now());

    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      // 主动丢上下文：不丢会撞浏览器 16 个 WebGL context 上限（切页十几次后整页变黑）。
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    };
  }, [paused]);

  return <canvas ref={canvasRef} className='wp-shader' aria-hidden />;
}
