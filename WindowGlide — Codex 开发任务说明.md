# WindowGlide

请帮我开发一个 Windows 11 桌面窗口增强工具，项目名称：

**WindowGlide**

目标是实现类似 PowerToys / Linux 桌面环境中 `Alt + 鼠标` 操作窗口的体验，并加入拖动时的视觉反馈。

这是我自己使用的 Windows 小工具。优先保证交互体验、稳定性和低资源占用，不要求限制在 Python 标准库；如果合适，可以使用 pip 安装第三方 Python 包。

## 一、核心功能

### 1. Alt + 鼠标左键：移动窗口

当用户：

`按住 Alt + 在任意窗口任意位置按住鼠标左键`

时：

不需要点击窗口标题栏，即可直接拖动整个窗口。

行为要求：

* 鼠标可以位于窗口客户区任意位置。
* 找到鼠标下真正需要操作的顶层窗口。
* 按住并移动鼠标时，窗口实时跟随。
* 松开鼠标左键后结束移动。
* 操作过程尽可能流畅，不应出现明显抖动、卡顿或窗口跳跃。
* 尽量保留 Windows 自身的窗口管理行为。
* 正确处理普通窗口、Electron/Chromium 应用等常见桌面应用。
* 不应误移动桌面、任务栏、开始菜单等系统 UI。
* 最大化窗口需要合理处理，不允许突然出现明显的位置跳变。
* 考虑多显示器环境。
* 考虑不同 DPI / 缩放比例。

优先研究使用 Win32 原生窗口移动机制，而不是简单地用 Python 高频循环不断调用 `SetWindowPos()`。

如果可以通过 Win32 的：

* `WM_NCLBUTTONDOWN`
* `HTCAPTION`
* `WM_SYSCOMMAND`
* `SC_MOVE`

或其他更合适的 Windows 原生机制实现，请优先采用手感最自然、兼容性最好的方案。

---

### 2. Alt + 鼠标右键：调整窗口大小

当用户：

`按住 Alt + 在任意窗口任意位置按住鼠标右键`

时：

无需把鼠标移动到窗口边框，即可 Resize 当前窗口。

需要根据鼠标按下时位于窗口中的区域自动判断 Resize 方向。

例如：

* 靠近左侧 → Left
* 靠近右侧 → Right
* 靠近顶部 → Top
* 靠近底部 → Bottom
* 左上区域 → TopLeft
* 右上区域 → TopRight
* 左下区域 → BottomLeft
* 右下区域 → BottomRight

不要求必须非常靠近真实窗口边缘。

更希望采用“窗口区域划分”的方式：

把窗口大致划分为九宫格，根据鼠标按下的位置确定 Resize 的边或角。

例如：

```text
┌────────┬────────┬────────┐
│   ↖    │   ↑    │   ↗    │
├────────┼────────┼────────┤
│   ←    │        │   →    │
├────────┼────────┼────────┤
│   ↙    │   ↓    │   ↘    │
└────────┴────────┴────────┘
```

中间区域可以根据鼠标距离最近的边决定 Resize 方向，或者设计一个更自然的规则。

优先使用 Windows 原生：

* `HTLEFT`
* `HTRIGHT`
* `HTTOP`
* `HTBOTTOM`
* `HTTOPLEFT`
* `HTTOPRIGHT`
* `HTBOTTOMLEFT`
* `HTBOTTOMRIGHT`

等机制，让 Windows 自己负责实际 Resize。

---

# 二、拖动时的视觉反馈

这是这个项目非常重要的一部分。

## 1. 黄色窗口边框

当进入 WindowGlide 操作状态后，在目标窗口外围显示一圈明显但不过分粗的**黄色高亮边框**。

要求：

* 黄色偏亮。
* 建议约 2～4 px，具体根据 DPI 调整。
* 圆角窗口尽可能适配 Windows 11 的窗口圆角。
* 边框必须实时跟随窗口移动或 Resize。
* 边框 Overlay 不能抢焦点。
* 不能拦截鼠标事件。
* 操作结束后立即消失。
* 不要修改目标程序自己的窗口内容。

优先考虑创建独立的透明 Overlay Window。

---

## 2. “玻璃覆盖”效果

拖动/Resize 过程中，让整个目标窗口视觉上稍微变白，类似：

**窗口上覆盖了一层很薄的白色磨砂玻璃。**

注意：

我不是要把目标窗口真的修改成白色，也不要修改目标窗口自身透明度。

建议方案：

在目标窗口上方建立一个：

* 无边框
* Click-through
* 不获取焦点
* 半透明
* 白色
* 跟随目标窗口尺寸变化

的 Overlay。

透明度不要太高。

目标视觉效果大概类似：

```text
原窗口
+
10%～20% 左右的白色透明蒙层
=
窗口整体轻微泛白
```

具体透明度请做成配置项。

Overlay 必须：

* 不抢焦点
* 不阻挡鼠标
* 不影响目标窗口正常操作
* 不出现在 Alt+Tab 中
* 不出现在任务栏
* 不导致目标窗口失去焦点
* 尽量避免闪烁

操作结束后立即隐藏/销毁。

---

# 三、鼠标指针反馈

### 移动窗口时

Alt + 左键进入 Move 状态后：

鼠标指针变成类似 Windows：

**四方向移动**

的 Cursor。

类似：

`IDC_SIZEALL`

操作结束后恢复原 Cursor。

### Resize 时

Alt + 右键进入 Resize 后，根据 Resize 方向改变 Cursor：

* Left / Right → `IDC_SIZEWE`
* Top / Bottom → `IDC_SIZENS`
* TopLeft / BottomRight → `IDC_SIZENWSE`
* TopRight / BottomLeft → `IDC_SIZENESW`

结束后恢复正常鼠标指针。

---

# 四、状态设计

建议明确设计状态机：

```text
IDLE
  │
  ├── Alt + LButton
  │
  ▼
MOVING
  │
  └── LButton Up
        ↓
       IDLE

IDLE
  │
  ├── Alt + RButton
  │
  ▼
RESIZING
  │
  └── RButton Up
        ↓
       IDLE
```

进入 MOVING / RESIZING：

1. 确定目标 HWND
2. 显示黄色 Border
3. 显示白色 Glass Overlay
4. 修改 Cursor
5. 开始 Windows Move / Resize

退出状态：

1. 停止 Move / Resize
2. 隐藏 Overlay
3. 隐藏 Border
4. 恢复 Cursor
5. 清理状态

同时处理：

* Alt 中途松开
* Esc
* 目标窗口被关闭
* 目标窗口最小化
* 操作被 Windows 中断
* 脚本异常

不能出现 Overlay 残留在屏幕上的情况。

---

# 五、鼠标监听

需要全局监听：

* Alt
* Left Button
* Right Button
* Mouse Move
* Button Up

可以研究：

`SetWindowsHookEx(WH_MOUSE_LL)`

以及必要的键盘状态检测。

如果使用第三方库能够显著提高可靠性，也可以使用。

但是请优先考虑：

**Win32 API / ctypes + 少量成熟第三方库**

而不是依赖非常重的 GUI/自动化框架。

---

# 六、Overlay 技术选择

请自行研究最适合 Windows 11 的实现方式。

可以考虑：

* PySide6
* PyQt6
* Win32 layered window
* Direct2D
* DWM
* ctypes + Win32
* 其他合理方案

如果 PySide6 能明显简化：

* 透明 Overlay
* DPI
* 多屏
* 绘制黄色边框
* 半透明白色蒙层

则可以使用 PySide6。

但不要为了 GUI 框架而牺牲鼠标 Hook 和窗口操作的可靠性。

可以采用：

**Win32 API 负责窗口控制 + PySide6 负责 Overlay**

这样的混合架构。

---

# 七、配置

不要把参数全部写死。

建立配置，例如：

`config.json`

至少允许配置：

```json
{
  "modifier": "ALT",
  "move_button": "LEFT",
  "resize_button": "RIGHT",

  "border_width": 3,
  "border_color": "#FFD400",

  "glass_opacity": 0.14,

  "enable_border": true,
  "enable_glass": true,
  "enable_cursor_change": true
}
```

如果配置文件不存在，自动生成默认配置。

---

# 八、程序结构

不要把所有代码塞进一个巨大的 Python 文件。

建议类似：

```text
WindowGlide/
│
├─ main.py
├─ config.json
├─ requirements.txt
│
├─ windowglide/
│   ├─ __init__.py
│   ├─ hooks.py
│   ├─ window_manager.py
│   ├─ overlay.py
│   ├─ cursor.py
│   ├─ resize.py
│   ├─ config.py
│   └─ logging_setup.py
│
├─ tests/
│
└─ README.md
```

可以根据实际架构调整，不要求机械遵守。

---

# 九、日志

加入日志系统。

默认日志：

`logs/windowglide.log`

记录：

* 程序启动
* Hook 注册
* Move 开始/结束
* Resize 开始/结束
* HWND
* Window title
* Resize direction
* Overlay 创建/销毁
* API 调用失败
* Exception

不要在 Mouse Move 的每一帧疯狂写日志。

---

# 十、退出机制

后台运行后必须有可靠的退出方式。

第一版至少支持：

`Ctrl + Alt + Shift + Q`

安全退出 WindowGlide。

退出时必须：

* Unhook
* 清理 Overlay
* 恢复 Cursor
* 清理资源
* 正常结束 Python 进程

后续可以考虑 System Tray，但第一版不是必须。

---

# 十一、开机自启动

程序完成后提供 Windows 用户级开机自启动方案。

优先考虑：

`shell:startup`

通过快捷方式运行：

`pythonw.exe main.py`

不要要求管理员权限。

同时提供：

* enable_autostart.py
* disable_autostart.py

或者其他简单可靠的用户级实现。

不要尝试绕过任何 Windows / 企业权限策略。

---

# 十二、权限边界

程序按照普通用户权限运行。

如果目标窗口是管理员权限，而 WindowGlide 没有管理员权限：

**不要尝试绕过 Windows UIPI / UAC。**

这种情况下允许操作失败，并写入日志。

WindowGlide 本身不要求管理员权限。

---

# 十三、性能要求

这是一个需要全天后台运行的小工具。

目标：

* IDLE 时 CPU 基本接近 0%
* 不进行高频无意义 polling
* 内存占用合理
* 不影响鼠标正常操作
* 不增加明显输入延迟
* Hook callback 必须非常轻量
* 不在 Hook callback 中执行耗时任务

Overlay 更新也不要无意义地以超高 FPS 刷新。

---

# 十四、开发方式

不要一次性写完整项目然后宣布完成。

请按照下面顺序开发并实际运行测试。

## Phase 1

首先只实现：

`Alt + 左键 → Move Window`

不要 Overlay。

验证基本窗口移动机制。

## Phase 2

加入：

`Alt + 右键 → Resize Window`

验证八方向 Resize。

## Phase 3

加入：

* 黄色 Border
* 白色 Glass Overlay
* Cursor

## Phase 4

处理：

* 最大化窗口
* 多显示器
* DPI
* Electron / Chromium
* 常见 Windows 应用
* 异常清理

## Phase 5

加入：

* config
* logging
* autostart
* README

每个 Phase 完成后：

1. 实际运行程序。
2. 检查 Python Exception。
3. 检查日志。
4. 做能够自动完成的测试。
5. 告诉我需要我人工验证哪些交互。

涉及真实鼠标拖动手感的地方不要假装已经验证。

如果需要我手动测试，请明确告诉我：

“现在请测试 Alt + 左键拖动 Chrome 窗口，并告诉我出现什么现象。”

然后根据我的反馈继续修改。

---

# 十五、第一阶段暂时不要做 AutoHotkey 功能

WindowGlide 后续还会整合另一套功能：

我之前通过 AutoHotkey 实现过：

* 当前窗口最小化
* 最近最小化窗口栈
* 恢复最近最小化窗口
* 最大化当前窗口
* 触摸板手势通过 Windows 快捷键调用

但是：

**当前版本先不要实现这些功能。**

先把：

**Alt + Mouse Move / Resize**

做到足够稳定、足够接近 PowerToys 的体验。

等这一部分测试满意以后，再把 AutoHotkey 那套功能作为 WindowGlide 的第二模块加入。

---

# 十六、最终体验目标

我希望 WindowGlide 启动后，日常使用是：

按住：

**Alt + 左键**

鼠标位于窗口任何位置都可以直接“抓住”窗口。

此时：

* 鼠标变成四方向移动 Cursor
* 窗口外围出现黄色高亮边框
* 窗口覆盖一层轻微白色玻璃效果
* 拖动非常流畅

松开鼠标：

* 黄色边框消失
* 白色蒙层消失
* Cursor 恢复

按住：

**Alt + 右键**

则：

* 根据鼠标位置决定 Resize 方向
* Cursor 显示对应 Resize 图标
* 黄色边框出现
* 白色 Glass 出现
* 可以自然调整窗口大小

整体目标：

**视觉上有明显反馈，但不要花哨；操作手感优先于动画效果。**

如果视觉效果与窗口拖动性能冲突：

**优先保证窗口拖动流畅。**
