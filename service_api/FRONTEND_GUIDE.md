# 前端对接文档

## 概览

当前仓库默认提供一个面向普通用户的上传页：

- 页面文件：`service_api/frontend.html`
- 页面定位：上传文档、选样例风格、查看状态、下载最终 PPT

后端 API 仍然保留完整能力，但用户版页面默认只走这条主链路：

1. 调用 `GET /api/v1/examples` 获取样例风格
2. 调用 `GET /api/v1/templates` 获取模板列表
3. 调用 `POST /api/v1/tasks` 以 `multipart/form-data` 创建任务
4. 轮询 `GET /api/v1/tasks/{task_id}` 获取状态
5. 任务完成后调用 `GET /api/v1/tasks/{task_id}/artifacts`
6. 找到 `native_pptx`
7. 调用 `GET /api/v1/tasks/{task_id}/download/native_pptx` 下载最终文件

所有 `/api/v1/*` 接口默认不要求前端显式传 Bearer Token。  
如果有鉴权要求，建议在上游网关或转发服务处理。

## 用户版页面默认交互

### 保留的表单字段

- `project_name`
- `canvas_format`
- `example_reference`
- `template_name`
- `prefer_style`
- `audience`
- `use_case`
- `core_message`
- `source_files`
- `image_files`

### 页面不再默认暴露

- `source_mode=path`
- `GET /api/v1/materials` 的素材浏览
- 完整产物列表
- 运行日志区
- `svg_pptx / design_spec / svg_output / svg_final / run_log` 主界面下载入口

### 页面默认隐藏但仍提交的字段

- `notes_style = formal`
- `output_formats = ["native_pptx", "svg_pptx"]`

## 基本概念

### 任务状态 `status`

- `queued`：已接收，等待执行
- `running`：正在执行
- `succeeded`：执行成功
- `failed`：执行失败
- `cancelled`：已取消

### 任务阶段 `stage`

- `queued`
- `ingest`
- `strategist`
- `executor_svg`
- `executor_notes`
- `postprocess`
- `export`
- `completed`
- `failed`
- `cancelled`

### 可选链路追踪请求头

上游系统如果希望把当前用户透传给 PPT 服务，可选传以下任一请求头：

- `X-Request-User-Id`
- `X-User-Id`
- `X-Forwarded-User-Id`

如果传了，后端会把用户 ID 记录到任务状态和 `run.log`。

## 1. 查看样例库

### 请求

```http
GET /api/v1/examples
```

### 说明

- 这是只读样例库
- 用户版页面会把它作为“选风格”入口
- `example_reference` 由用户手动选择
- `style_tag` 和 `recommended_template` 是系统解析结果，不是用户输入

## 2. 查看模板列表

### 请求

```http
GET /api/v1/templates
```

### 说明

- 页面会把模板名展示为下拉选项
- 字段优先级建议使用：`template_name > example_reference > auto`
- 如果用户同时选择了 `template_name` 和 `example_reference`，前端应保留模板值，并提示样例仅作辅助风格参考，不覆盖模板
- 后端主链路已改为模板骨架驱动：显式模板直接驱动 `cover/toc/content/ending` 骨架；未选模板时先由 `style_mode` 路由默认模板，再按模板骨架生成

## 3. 创建任务

用户版页面默认固定使用：

- `source_mode = upload`

请求类型：

```http
POST /api/v1/tasks
Content-Type: multipart/form-data
```

### 表单字段

- `source_mode=upload`
- `project_name`
- `canvas_format`
- `template_name`：可选
- `example_reference`：可选
- `style_source`
- `audience`：可选
- `use_case`：可选
- `core_message`：可选
- `prefer_style`
- `notes_style`：固定 `formal`
- `output_formats`：固定 `["native_pptx","svg_pptx"]`
- `source_files`：一个或多个源文档
- `image_files`：零个或多个图片

### 响应

```json
{
  "task_id": "2e9f7b1d9a4f4ef18f0e4bb7aa7f0f43",
  "status": "queued",
  "stage": "queued"
}
```

## 4. 查询任务状态

### 请求

```http
GET /api/v1/tasks/{task_id}
```

### 用户版页面关心的字段

- `status`
- `stage`
- `created_at`
- `updated_at`
- `error`

### 前端建议

- 轮询间隔建议 `2-5 秒`
- 当 `status` 变成 `succeeded`、`failed`、`cancelled` 时停止轮询
- 如果失败，优先展示 `error`

## 5. 获取任务产物

### 请求

```http
GET /api/v1/tasks/{task_id}/artifacts
```

### 用户版页面默认只关心

- `native_pptx`

如果还需要内部或调试产物，可由其他页面或上游系统再单独接入。

## 6. 下载最终 PPT

### 请求

```http
GET /api/v1/tasks/{task_id}/download/native_pptx
```

### 说明

- 用户版页面只突出展示 `native_pptx`
- 如果任务完成但没有该产物，页面应提示“未找到最终 PPT 文件”

## 7. 取消任务

### 请求

```http
POST /api/v1/tasks/{task_id}/cancel
```

## 限制说明

- 用户版页面默认不支持目录引用
- 不支持 URL 输入
- 不支持 AI 图片生成
- 样例库是只读的
- `example_reference` 只作为风格参考，不表示复用原样例内容
- `style_mode` 的职责是路由默认模板，不再作为主渲染入口；主渲染入口是项目 `templates/` 下的模板骨架
- 页面角色按 `cover / toc / chapter / content / ending` 选骨架，内容页再由 `content_archetype` 决定模板内容区内的排版方式
- 模板族路由、占位符契约、模板族语义覆盖规则以及 `content_archetype` 布局参数由后端配置文件 `service_api/template_contracts.json` 统一维护
- `svg_pptx`、`design_spec`、日志等仍保留在后端，但不在用户版主界面展示
