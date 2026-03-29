# 用户项目工作区

本目录用于存储开发中的项目。

## 新建项目

```bash
python3 skills/ppt-master/scripts/project_manager.py init my_project --format ppt169
```

## 目录结构

A typical project usually contains the following:

```
project_name_format_YYYYMMDD/
├── README.md
├── design_spec.md
├── sources/
│   ├── Raw files / URL archives / Converted Markdown
│   └── *_files/                  # Markdown companion resource directory (e.g., images)
├── images/                       # Image assets used by the project
├── notes/
│   ├── 01_xxx.md
│   ├── 02_xxx.md
│   └── total.md
├── svg_output/
│   ├── 01_xxx.svg
│   └── ...
├── svg_final/
│   ├── 01_xxx.svg
│   └── ...
├── templates/                    # Project-level templates (if any)
├── *.pptx
└── image_analysis.csv            # Optional, image scan analysis results
```

Projects can remain at different stages and do not necessarily have all artifacts at once. For example:

- 仅完成 sources/ 资源归档与设计规格及内容大纲（design_spec）
- 已生成 svg_output/，但尚未执行后处理流程
- svg_final/、notes/ 与 *.pptx 均已完成

## 注意事项

- 本目录下内容已通过 .gitignore 排除版本控制
- 完成后的项目可移动至 examples/ 目录用于共享展示
- 工作区外的文件默认执行复制操作；工作区内的文件直接移动至项目 sources/ 目录
