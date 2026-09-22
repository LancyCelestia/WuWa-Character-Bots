# 语音合成 · 退避窗口与成功提交点

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.tts · 退避窗口与成功提交点

- 层级：一级 B06 → 二级 tts → 三级 `backoff-and-commit`
- 实现落点：`plugins/bot_unified_runtime/domains/media/capabilities/tts.py`、`plugins/bot_unified_runtime/domains/creation/tts`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

机械件（不占路由席位）：决定「什么算真成功、失败了冷却多久、故障要不要让管理员知道」。
三颗模块级状态（`_last_failure_at` / `_last_failure_reason`，加锁读写）配三个口：
`_record_failure` 进窗、`_backoff_reason` 出窗判定、`_clear_failure` 清零。

解决的问题有两层。第一层是冷却保护本身：曾经退避状态只写不读，引擎挂了每条请求
仍然白打整个读超时预算并占死一个 offload worker。第二层更阴——判定「成功」的位置：旧实现
在 `_request_tts` 收到 HTTP 200 且非空体时就抢跑清零，而静音指纹闸在调用方更后面
才判，于是引擎以「200 + 恰好一秒静音」伪装成功时，每一条坏请求都把上一轮失败抹掉，
冷却保护永不启动。现在清零时机与「算成功」的判据对齐。

## 怎么调用

- `tts.py:synthesize`：**唯一成功提交点**——产物过了结构体检 + 静音指纹 + 字节顶，
  并且 `write_bytes` 落盘成功之后才 `_clear_failure()`；落盘失败走异常分支，绝不清零。
- `tts.py:synthesize`：缓存查找之后、真请求之前调 `_backoff_reason()`，窗内直接快速
  失败（已合成过的句子照常复用缓存，冷却只省掉注定失败的那一次外呼）。
- `tts.py:_silence_trap_seconds`：静音陷阱三指纹同中的唯一判据（采样率 16000、
  时长恰一秒量级、样本峰值近全零），结构体检与退避归类都读它，禁第二份副本；
  命中即 `_record_failure`。
- `tts.py:_request_tts`：只有部署类失败进窗（连接/超时、5xx、空音频、httpx 缺失）；
  4xx 确定性拒绝与结构类坏字节不进窗（坏配置是持续性的，进窗只会让全员周期性吃到
  失真文案）。
- `domains/media/voice_health_probe.py:probe_voice_engine`：只读 TCP 探针（host/port
  解析自 `bot_tts_api_url`），零常驻线程、零后台轮询、绝不代启动或重启引擎（用户裁定
  U-17=C：引擎生命周期=人工脚本唯一入口）。不可达构造
  `OperationalIssue(kind="tts_service_unreachable", retryable=True)`，同窗内不重复
  构造（与中央告警抑制窗对齐，窗宽以中央件为准）；「上次不可达→本次可达」记为恢复沿、不告警。
- `voice_health_probe.py:voice_status_line`：`/bot status` 的语音行数据源，
  探针自身异常一律 fail-open 返回 unknown，不把业务链拖死。

## 开关与参数

- `_HEALTH_BACKOFF_SECONDS`（模块常量，秒数以该件定义为准）：冷却窗宽度，非配置键——刻意不留旋钮，
  调它要改代码走评审。
- `_SILENCE_RATE` / `_SILENCE_MIN_SECONDS` / `_SILENCE_MAX_SECONDS` /
  `_SILENCE_PEAK_AMPLITUDE`：静音指纹域值（采样率、时长窗与峰值门槛均以该件常量为准）。
- `bot_tts_timeout_seconds`（60）决定单次外呼最坏耗时，与窗宽共同决定失败风暴的密度。
- `bot_tts_enabled`：关时不请求也不探测。
- 告警抑制窗与错误卡冷却属中央件（B09 观测面），本域不自建第二套抑制。

## 失败时看到什么

- 窗内：用户看到不可达那条降级短句（「嗓子还没接上……稍后再叫我一次吧」），审计里是
  `服务不可达：退避冷却中（剩 N 秒）｜上次失败：<原始原因>`；窗满即放行，不存在永久
  拉黑。
- 窗外：真实故障原因随请求返回并按 `_FAILURE_KINDS` 前缀映射成对应 kind，原文进
  `safe_summary`（已打码），随 `CapabilityResult.operational_issue` 进中央告警链。
- 探针与退避是两条独立证据：探针说「端口不通」，退避说「最近一次真请求怎么死的」，
  两边同时异常才基本可判定引擎侧故障。

## 测试与验收

`tests/test_tts_health_backoff.py`（进窗/出窗/快速失败不刷新窗，防永久拉黑）、
`test_tts_backoff_commit_point.py`（200+静音不得清零、落盘失败不得清零、落盘成功才清零
三态互斥锁）、`test_tts_audio_gate.py`（正常产物不误判静音）、
`test_tts_failure_visibility.py`（每类失败必挂对应 kind，政策拒绝不挂）、
`test_voice_health_probe.py`（只读探测、恢复沿、同窗不重复、fail-open）。
真机：重启后 `python scripts/tts_offline_selfcheck.py` 与
`python scripts/tts_retcode_collect.py --json`；`docs/acceptance-manual.md` §6.6.11
的「引擎未起」「引擎假成功」两条。**注意现网实况**：本卡的提交点根修目前在工作树，
未 commit 未重启，重启前线上仍是 200 即清零的旧行为。
