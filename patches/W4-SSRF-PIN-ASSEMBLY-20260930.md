# W4 · 解析钉定「装配面」口径说明（缺口④＝本体已修，铺开**未做**）

落笔＝2026-10-01（续 2026-09-30 那波「SSRF 钉定与渲染腿」孤儿补丁；文件名沿用被收尾的
事故卷宗日期，不随本席到场日改）。

席位：W4（写面＝`domains/files/sources/downloader.py`、`domains/render/render_backends.py`、
`domains/link_parse/fetchers/playwright_backend.py`、`domains/food/capabilities/eat.py`、
`domains/link_parse/parsers/http_util.py`、`domains/link_parse/parsers/ssrf_guard.py`
＋该族 5 枚锁）。本件只定一件事的口径：**「钉定件存在」≠「缺口④收口」**，
防止台账/HANDBOOK 把纸面读成现实。定位一律按**符号名**（行号会漂移）。

---

## §1 结论一句话

`downloader.build_pinning_handlers()`（治 DNS rebinding 的「判后即弃」）全树调用点
**只有一处**：`eat._guarded_image_opener`（菜品封面取图腿）。解析链咽喉
`http_util._build_opener`、`notes` 图片腿、`vision_describe`、`media_archive`、
meme 监听器（httpx 腿）、渲染 ORB 代捞腿、中央 `download()`/`probe()`（yt-dlp 自带
传输层）**一律未装** ⇒ 生产主面的 rebinding 窗口今天**零改善**。入口咽喉
`check_download_url`（判协议/黑名单/全部解析结果）与逐跳落点复查
`ssrf_guard.check_fetch_landing` 的覆盖面不变，那是另一件事，别混着记。

## §2 在册清单（与代码/锁三处同批）

同一份清单存在于三处，改一处必须改其余两处，否则锁红：

1. `downloader.build_pinning_handlers` docstring 的「装配面现状」段；
2. 本件；
3. `tests/test_downloader_connect_pin.py::_PINNING_ASSEMBLY_ROSTER`
   （`test_pinning_assembly_roster_is_the_recorded_one` 用 AST **现算**全树调用点比对，
   不缓存、不读文档正文）。

| 腿 | 在装 | 未装的原因 / 修法归属 |
|---|---|---|
| `food/capabilities/eat.py::_guarded_image_opener` | ✅ | 缺口②那批一起装的 |
| `link_parse/parsers/http_util.py::_build_opener` | ❌ | 装上撞 **3 枚跨席锁**（§3），要连着改那三把尺的替身形 ⇒ 归解析链席位，本席不越界合并 |
| `media/ingest/vision_describe.py`、`media/capabilities/media_archive.py`、`meme/sources/meme_library_listener.py`（httpx 形态另算） | ❌ | **W5 写面**（§5） |
| `notes` 图片腿 | ❌ | 非本席文件域；该腿已有逐跳护栏（`_GuardedShortLinkRedirectHandler`），只缺同一次解析 |
| `render/render_backends.py::_ORB_FETCH_OPENER` | ❌（**本席裁定维持**） | 首行 `ProxyHandler({})` 已强制直连、命中域是固定大厂域、每图一次解析压在出卡延迟上；理由全文在该件 docstring |
| 中央 `download()` / `probe()` | ❌ | yt-dlp 有自己的传输层与重定向路径，urllib 件挂不上去；要钉得走 yt-dlp 侧连接钩子（`check_download_url_resolved` docstring 已登记为已知残余） |

## §3 实测数据（为什么不铺开）

把 `build_pinning_handlers()` 装进 `http_util._build_opener` 后现跑相关面：

```
3 failed, 35 passed in 5.76s
FAILED tests/test_auditfix_parsers.py::test_resolve_short_link_via_local_redirect_server
FAILED tests/test_credential_health_probe_throat.py::test_cross_host_redirect_strips_cookie_from_probe
FAILED tests/test_credential_health_probe_throat.py::test_same_host_redirect_keeps_cookie_from_probe
```

那三把尺拿 `127.0.0.1` / `localhost` 上的真监听器当「两个不同 host」的替身；钉定件
在建连前就把本机目标判死（`ParseHttpError: GET http://127.0.0.1:<port>/start failed:
RejectedUrlError`，探针腿则被消化成 `state='network_error'`）。**判据是对的、测试替身
不兼容**——修法是把那三把尺改成打桩传输层，属解析链/凭证席的写面，不是本席能顺手
吃进来的（多代理并发按文件域互斥，见 AGENTS 规则 7）。

## §4 装的时候两个坑（给后续席，代码注释里同样在册）

- **a) 双 `HTTPSHandler` 陷阱**：`_build_opener(verify_ssl=False)` 自带
  `HTTPSHandler(context=unverified)`。`OpenerDirector` 取**第一个** `https_open`，
  钉定件必须长成 `_PinningHTTPSHandler(context=同一个 ctx)` 顶上去；直接追加会
  要么丢钉、要么把「不校验证书」悄悄改成「校验」＝行为漂移。
- **b) 装了 ≠ 在钉**：`_connect_target_is_proxied` 判不清一律按「代理在场」不钉
  （保守向，红线保持）。本机 `getproxies()` 现值＝
  `{'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890', 'no': 'localhost,127.0.0.1'}`
  （Clash 档，台账 #71★）⇒ 公网目标全程**不钉**，只有 `NO_PROXY` 命中域（本机/局域网）
  才进钉定支。所以验收要按当轮代理态现算，缺省代理件的 `trust_env` 回落语义一律不动。

## §5 W5 / 解析链席要接的腿（点名）

1. 解析链席：`http_util._build_opener`（含 §3 三把尺的替身改造 + §4a 的 context 形）；
2. W5：`vision_describe` 取图腿、`media_archive` 下载腿（各自已有逐跳护栏，补同一册
   地址即可）；meme 监听器是 httpx 腿，urllib 件用不上，要另想连接级方案，别硬套；
3. 任一条落地都要同批改 §2 三处清单，否则
   `test_pinning_assembly_roster_is_the_recorded_one` 当场红（这是故意的）。

## §6 复跑证据

```bash
cd <仓库>/ChatBot/ChatBot
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
  tests/test_downloader_connect_pin.py tests/test_render_backend_ssrf.py \
  tests/test_render_orb_route_ssrf.py tests/test_render_orb_fetch_hop_ssrf.py \
  tests/test_mermaid_local_asset.py tests/test_eat_image_ssrf_hop.py \
  tests/test_playwright_goto_ssrf_gate.py tests/test_render_image_cache.py \
  -q -p no:cacheprovider --basetemp="$TEMP/qoder-w4/bt"
```

RED-证明（新锁不是永真式）：把 `_pick_pinned_addresses` 临时退化回「只交一枚」，
`test_downloader_connect_pin.py` 的 ⑥ 三枚当场 `3 failed`，恢复后全绿。
