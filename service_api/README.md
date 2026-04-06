# Offline PPT Master FastAPI Service

## Start

```bash
uvicorn service_api.main:app --host 0.0.0.0 --port 8000

# 然后在浏览器打开同源页面，避免直接双击本地 frontend.html 带来的 Origin:null 文件上传问题
# http://127.0.0.1:8000/frontend
```

### 一键启动脚本

- Windows: `start_windows.bat`
- Ubuntu: `start_ubuntu.sh`

说明：

- 两个脚本不会创建 `.venv`
- 不会自动安装任何依赖
- 只检查当前环境中的 `python/python3` 与 `uvicorn` 是否可用
- 自动启动 FastAPI 服务
- Ubuntu 如需导入 `docx/epub/latex`，还需要系统安装 `pandoc`

## Frontend

当前默认前端为面向普通用户的上传页：

- 用户版页面：`service_api/frontend.html`
- 前端对接说明：`service_api/FRONTEND_GUIDE.md`

用户版页面默认只保留：

- 文件上传
- 样例风格选择
- 基础表单
- 任务状态
- 最终 `native_pptx` 下载

后端 API 仍然保留完整能力，但目录引用、素材浏览、日志和高级产物不在该页面主界面展示。

## Material Directories

- `service_data/materials/docs/`
- `service_data/materials/images/`

## Examples API

- `GET /api/v1/examples`
- `GET /api/v1/examples/{example_name}`
- `GET /api/v1/examples/{example_name}/download/{artifact_name}`

Examples are exposed as a read-only sample library.
Tasks may also pass `example_reference` to use one example as a style reference during generation.
If both `template_name` and `example_reference` are provided, the explicit template takes precedence and the example is treated as a secondary style hint.
The runtime now follows `template_name > style_mode -> default template > fallback renderer`.
When a template is available, SVG generation is template-skeleton driven (`cover/toc/content/ending`); `style_mode` mainly routes to a default template when the user did not pick one.
Template-family routing, placeholder contracts, family-level semantic overrides, and content-archetype layout parameters are now maintained in `service_api/template_contracts.json`.

## Auth

This service does not require frontend Bearer token authentication by default.
If authentication is needed, enforce it in the upstream gateway or forwarding service.

## Optional Trace Header

The upstream service may forward a user identifier header for tracing:

- `X-Request-User-Id`
- `X-User-Id`
- `X-Forwarded-User-Id`

If present, the value is recorded in task state and `run.log`.

## Docs

- Frontend integration: `service_api/FRONTEND_GUIDE.md`
- User frontend page: `service_api/frontend.html`
- Dedicated API deps: `api_requirements.txt`
