# Offline PPT Master FastAPI Service

## Start

```bash
uvicorn service_api.main:app --host 0.0.0.0 --port 8000

# 然后在浏览器打开同源页面，避免直接双击本地 frontend.html 带来的 Origin:null 文件上传问题
# http://127.0.0.1:8000/frontend
```

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
