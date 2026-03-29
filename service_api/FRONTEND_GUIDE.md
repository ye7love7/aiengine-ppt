# 前端对接文档

## 概览

这是一个用于离线部署环境的异步 PPT 生成服务。
前端推荐接入流程：

1. 如果用户需要浏览服务器素材，先调用 `GET /api/v1/materials`
2. 如果用户需要浏览样例库，调用 `GET /api/v1/examples`
3. 调用 `POST /api/v1/tasks` 创建任务
4. 轮询 `GET /api/v1/tasks/{task_id}` 获取任务状态
5. 任务完成后调用 `GET /api/v1/tasks/{task_id}/artifacts`
6. 调用 `GET /api/v1/tasks/{task_id}/download/{artifact_name}` 下载产物

所有 `/api/v1/*` 接口默认不要求前端显式传 Bearer Token。
如果你有鉴权要求，建议在上游网关或转发服务处理。

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

## 1. 查看可用素材

### 请求

```http
GET /api/v1/materials
```

### 响应

```json
{
  "docs": [
    {
      "path": "quarterly/report.md",
      "size_bytes": 12034
    }
  ],
  "images": [
    {
      "path": "branding/cover.png",
      "size_bytes": 542122
    }
  ]
}
```

### 说明

- `docs[].path` 相对于 `service_data/materials/docs/`
- `images[].path` 相对于 `service_data/materials/images/`
- 在 `source_mode=path` 时，这些相对路径可直接传入创建任务接口

## 2. 查看样例库

### 请求

```http
GET /api/v1/examples
```

### 响应

```json
{
  "examples": [
    {
      "name": "ppt169_谷歌风_google_annual_report",
      "title": "ppt169_谷歌风_google_annual_report",
      "relative_path": "examples/ppt169_谷歌风_google_annual_report",
      "page_count": 10,
      "image_count": 0,
      "has_design_spec": true,
      "has_readme": true,
      "has_native_pptx": true,
      "has_svg_pptx": false,
      "suggested_style": "consulting",
      "summary": "Google 2025 annual work report template..."
    }
  ]
}
```

### 说明

- 这是只读样例库，适合做案例浏览和风格参考
- `suggested_style` 是服务端根据样例名称推断的推荐风格

## 3. 查看单个样例详情

### 请求

```http
GET /api/v1/examples/{example_name}
```

### 响应

```json
{
  "example": {
    "name": "ppt169_谷歌风_google_annual_report",
    "page_count": 10,
    "suggested_style": "consulting"
  },
  "artifacts": [
    {
      "name": "design_spec",
      "kind": "file",
      "relative_path": "C:\\...\\examples\\...\\design_spec.md",
      "size_bytes": 12000
    }
  ],
  "preview": {
    "readme_excerpt": "...",
    "design_spec_excerpt": "..."
  }
}
```

## 4. 下载样例产物

### 请求

```http
GET /api/v1/examples/{example_name}/download/{artifact_name}
```

### 常见 `artifact_name`

- `readme`
- `design_spec`
- `native_pptx`
- `svg_pptx`
- `svg_output`
- `svg_final`
- `images`

### 说明

- 如果目标是文件，后端直接返回文件流
- 如果目标是目录，后端自动打包成 zip

## 5. 创建任务

支持两种模式：

- `source_mode=path`：引用服务器已有素材
- `source_mode=upload`：前端直接上传文件

还支持一个可选字段：

- `example_reference`：指定某个样例名称，作为风格参考

### 路径模式

```http
POST /api/v1/tasks
Content-Type: application/json
```

```json
{
  "source_mode": "path",
  "project_name": "q3_report",
  "canvas_format": "ppt169",
  "template_name": null,
  "example_reference": "ppt169_谷歌风_google_annual_report",
  "audience": "管理层",
  "use_case": "季度经营汇报",
  "core_message": "突出增长、问题与后续动作",
  "prefer_style": "auto",
  "notes_style": "formal",
  "output_formats": ["native_pptx", "svg_pptx"],
  "source_files": ["quarterly/report.md"],
  "image_files": ["branding/cover.png"]
}
```

### 上传模式

请求类型是 `multipart/form-data`

字段说明：

- `source_mode=upload`
- `project_name`
- `canvas_format`
- `template_name`：可选
- `example_reference`：可选
- `audience`：可选
- `use_case`：可选
- `core_message`：可选
- `prefer_style`：`general | consulting | consulting_top | auto`
- `notes_style`
- `output_formats`：JSON 字符串或逗号分隔字符串
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

## 6. 查询任务状态

### 请求

```http
GET /api/v1/tasks/{task_id}
```

### 关键字段

- `status`
- `stage`
- `request`
- `upstream_user_id`
- `project_path`
- `log_path`
- `error`
- `artifacts`

### 前端建议

- 轮询间隔建议 `2-5 秒`
- 当 `status` 变成 `succeeded`、`failed`、`cancelled` 时停止轮询
- 如果失败，优先展示 `error`

## 7. 获取任务产物

### 请求

```http
GET /api/v1/tasks/{task_id}/artifacts
```

### 常见产物

- `native_pptx`
- `svg_pptx`
- `design_spec`
- `svg_output`
- `svg_final`
- `notes`
- `run_log`

## 8. 下载任务产物

### 请求

```http
GET /api/v1/tasks/{task_id}/download/{artifact_name}
```

## 9. 取消任务

### 请求

```http
POST /api/v1/tasks/{task_id}/cancel
```

## 页面建议

建议前端至少包含这几个区域：

- 素材浏览区
- 样例库浏览区
- 任务创建表单
- 任务进度区
- 产物下载区
- 运行日志区

## 限制说明

- 不支持 URL 输入
- 不支持 AI 图片生成
- 样例库是只读的
- `example_reference` 只作为风格参考，不表示复用原样例内容
