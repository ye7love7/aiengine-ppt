# Frontend / Gateway 对接说明

这份文档面向主项目后端或网关服务。典型接入方式是：

- 主项目接收用户请求
- 主项目把请求转发到本服务 `service_api`
- 主项目轮询任务状态并回传给自己的前端

当前服务的主链路已经支持两种输入模式：

- `upload`：上传源文件
- `inline`：直接传入纯文本 / Markdown / 提纲内容

## 1. 总体流程

标准调用顺序：

1. `GET /api/v1/examples`
2. `GET /api/v1/templates`
3. `POST /api/v1/tasks`
4. 轮询 `GET /api/v1/tasks/{task_id}`
5. 成功后调用 `GET /api/v1/tasks/{task_id}/artifacts`
6. 下载 `GET /api/v1/tasks/{task_id}/download/native_pptx`

主项目如果不需要样例库或模板列表，也可以只调用：

1. `POST /api/v1/tasks`
2. `GET /api/v1/tasks/{task_id}`
3. `GET /api/v1/tasks/{task_id}/download/native_pptx`

## 2. 模板与样例优先级

控制逻辑固定为：

- `template_name > example_reference > auto`

含义：

- 用户显式选择 `template_name` 时，最终按模板骨架驱动生成
- 用户未选模板但选择了 `example_reference` 时，会按样例强参考锁定风格，并路由到样例推荐模板
- 两者都没有时，系统根据内容自动判断风格并路由默认模板

如果同时传了：

- `template_name`
- `example_reference`

则行为是：

- 模板优先
- 样例只作为辅助风格参考，不覆盖模板

## 3. 创建任务

接口：

```http
POST /api/v1/tasks
```

支持两种请求形态：

- `application/json`
- `multipart/form-data`

### 3.1 JSON 模式

适合主项目后端已经拿到文本内容，不再需要上传文件。

#### `path` 模式

```json
{
  "source_mode": "path",
  "project_name": "demo",
  "canvas_format": "ppt169",
  "template_name": "exhibit",
  "example_reference": null,
  "style_source": "prompt_reference",
  "audience": "领导",
  "use_case": "汇报",
  "core_message": "总结重点",
  "prefer_style": "auto",
  "notes_style": "formal",
  "output_formats": ["native_pptx", "svg_pptx"],
  "source_files": ["sample.md"],
  "image_files": []
}
```

#### `inline` 模式

这是本次新增的直贴文本能力，推荐主项目后端优先使用。

```json
{
  "source_mode": "inline",
  "project_name": "demo",
  "canvas_format": "ppt169",
  "template_name": null,
  "example_reference": "ppt169_像素风_git_introduction",
  "style_source": "example_strong",
  "audience": "领导",
  "use_case": "汇报",
  "core_message": null,
  "prefer_style": "auto",
  "notes_style": "formal",
  "output_formats": ["native_pptx", "svg_pptx"],
  "source_text": "# 汇报提纲\n\n这里直接放 Markdown 或纯文本"
}
```

规则：

- `source_mode=inline` 时必须提供非空 `source_text`
- `source_text` 推荐直接传 UTF-8 文本
- 文本内容可以是：
  - Markdown
  - Word 复制出的纯文本
  - 汇报提纲
  - 已清洗的网页正文

### 3.2 Multipart 模式

适合浏览器直接上传文件，或主项目需要同时上传图片。

#### `upload` 模式

字段：

- `source_mode=upload`
- `project_name`
- `canvas_format`
- `template_name`
- `example_reference`
- `style_source`
- `audience`
- `use_case`
- `core_message`
- `prefer_style`
- `notes_style`
- `output_formats`
- `source_files`
- `image_files`

#### `inline` 模式

如果主项目要同时传文本和图片，也可以用 multipart：

- `source_mode=inline`
- `source_text`
- `image_files`

说明：

- `inline` 模式下不要求 `source_files`
- `image_files` 仍会被保存并参与生成

## 4. 字段说明

### 基本字段

- `project_name`
  - 可空
  - 为空时服务端自动生成

- `canvas_format`
  - 当前常用值：`ppt169`、`ppt43`

- `audience`
  - 可空
  - 例如：`领导`、`客户`、`专家`

- `use_case`
  - 可空
  - 例如：`汇报`、`答辩`、`宣讲`

- `core_message`
  - 可空
  - 用于强调想表达的核心结论

### 风格相关

- `template_name`
  - 显式模板约束
  - 一旦提供，优先级最高

- `example_reference`
  - 样例参考
  - 主要用于风格锁定和模板路由

- `style_source`
  - 常用值：
    - `prompt_reference`
    - `example_strong`
  - 推荐规则：
    - 有 `example_reference` 时传 `example_strong`
    - 没有样例时传 `prompt_reference`

- `prefer_style`
  - 常用值：
    - `auto`
    - `general`
    - `consulting`
    - `consulting_top`

### 输出相关

- `notes_style`
  - 当前建议固定 `formal`

- `output_formats`
  - 当前建议固定：
    - `["native_pptx", "svg_pptx"]`

## 5. 任务状态

接口：

```http
GET /api/v1/tasks/{task_id}
```

常见 `status`：

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

常见 `stage`：

- `queued`
- `ingest`
- `strategist`
- `executor_svg`
- `executor_notes`
- `postprocess`
- `export`
- `completed`

建议：

- 轮询间隔 2 到 5 秒
- 当 `status` 进入 `succeeded / failed / cancelled` 时停止轮询

## 6. 获取产物与下载

产物列表：

```http
GET /api/v1/tasks/{task_id}/artifacts
```

最终下载：

```http
GET /api/v1/tasks/{task_id}/download/native_pptx
```

主项目如果只关心最终 PPT，只需要读取：

- `native_pptx`

## 7. 透传用户 ID

如果主项目希望把上游用户身份记录到本服务，可传以下任一请求头：

- `X-Request-User-Id`
- `X-User-Id`
- `X-Forwarded-User-Id`

服务端会把它记录到：

- 任务状态
- `run.log`

## 8. 错误处理建议

### 常见 400

- `Example not found`
  - 样例名无效

- `Inline requests require non-empty source_text`
  - `source_mode=inline` 但没传有效文本

- `No valid uploaded source files were received`
  - `source_mode=upload` 但没有有效上传源文件，或文件是 0 B

### 常见 404

- `Task not found`
- `Artifact not found`

## 9. 推荐给主项目后端的接法

如果主项目本身已经能拿到用户输入文本，推荐直接走：

- `source_mode=inline`
- `source_text=<正文>`

原因：

- 不必先人为生成临时 docx/md 再上传
- 能减少一次文件落地和转换
- 与当前服务内部逻辑一致，因为最终也会统一转成文本语料进入 Strategist / Executor

只有在以下场景再使用 `upload`：

- 用户确实上传了原始 docx/pdf
- 主项目不想自己提取文本
- 需要保留原始文件作为输入来源

## 10. 当前边界

- 本服务已经支持模板骨架驱动生成
- `template_name` 是主模板约束，不再只是提示字段
- `style_mode` 的职责主要是路由默认模板，不再是主渲染入口
- `inline` 模式会进入与上传模式相同的主生成链路

如果主项目需要，我也可以再补一份更偏“转发服务接入”的示例代码，分别给：

- Python / FastAPI
- Node / Express
- Java / Spring Boot
