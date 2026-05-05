# 版本记录 v0.1.2

## 版本信息
- **版本号**: v0.1.2
- **发布日期**: 2026-05-05
- **Git 分支**: release/v0.1.2

## 主要更新

### 1. 新增纯混剪模式
- 无文案、无配音，直接生成 MP4 视频
- 使用 moviepy 进行视频拼接和导出
- 支持自定义输出路径

### 2. 双模式支持
- **完整视频模式**（原有功能）
  - AI 生成文案
  - TTS 配音
  - 输出剪映草稿
  
- **纯混剪模式**（新增功能）
  - 跳过文案和配音
  - 直接拼接素材
  - 导出 MP4 文件

### 3. GUI 界面优化
- 添加模式选择单选按钮
- 添加混剪输出路径设置
- 第二页添加滚动条支持
- 支持鼠标滚轮滚动
- 修复 LabelFrame 白色边框问题
- 更新步骤提示：素材选择 → 模式设置 → 生成视频

### 4. 批量生成增强
- 支持一次生成 1-10 个视频
- 每个视频使用不同的随机种子
- 确保每个视频的素材组合不同

### 5. 智能素材复用
- 优先使用历史上用得少的素材
- 同一视频内避免重复使用同一素材
- 记录使用次数，动态调整优先级

## 新增文件

### 核心功能文件
```
src/python_video_engine/video_exporter.py
```
- `VideoExporter` 类：视频拼接和 MP4 导出
- `VideoExportResult` 数据类：导出结果

### 文档文件
```
混剪模式说明.md
test_mix_mode.py
test_import.py
```

## 修改文件

### main.py
- 新增 `run_pipeline_mix()` 函数
- 更新 `App` 类：
  - 添加 `self.mode` 变量（模式选择）
  - 添加 `self.mix_output` 变量（混剪输出路径）
  - 添加 `_on_mode_changed()` 方法
  - 添加 `_change_mix_output()` 方法
  - 添加 `_ok_mix()` 方法
  - 更新 `_page2()` 添加滚动条和鼠标滚轮支持
  - 更新 `_style()` 修复 LabelFrame 样式
  - 更新 `_show()` 支持双模式显示
  - 更新 `_go2()` 验证不同模式的路径
  - 更新 `_run()` 和 `_worker()` 支持双模式执行

### src/python_video_engine/__init__.py
- 导出 `VideoExporter` 和 `VideoExportResult`

### README.md
- 添加 v0.1.2 更新说明
- 更新功能列表
- 更新文件结构说明
- 添加双模式使用说明

## 技术细节

### 视频导出参数
```python
codec="libx264"
audio_codec="aac"
fps=30
```

### 文件命名规则
```
{客户名称}_mix_{序号}_{时间戳}.mp4
例如：名点工贸_mix_1_20260505_143022.mp4
```

### 时长控制
- 15-30秒模式：目标 22.5 秒 ± 3 秒随机
- 30-60秒模式：目标 45 秒 ± 3 秒随机

### 素材片段时长
- 3-4 秒之间随机
- 素材不足 3 秒时使用实际时长

## 依赖要求

### 新增依赖
```
moviepy>=1.0.3,<2.0.0
```

### 系统依赖
- ffmpeg（moviepy 需要）

## 配置文件

### 用户配置保存位置
```
~/.jianying_auto_editor_settings.json
```

### 配置内容
```json
{
  "draft_box_path": "剪映草稿箱路径",
  "mix_output_path": "混剪输出路径"
}
```

## 测试方法

### GUI 测试
```bash
python main.py
```

### 快速测试脚本
```bash
python test_mix_mode.py
```

## 已知问题
无

## 向后兼容性
- ✅ 完全兼容 v0.1.1
- ✅ 原有完整视频模式功能不受影响
- ✅ 配置文件向后兼容

## 回滚方法

### 使用 Git 回滚
```bash
# 查看当前分支
git branch

# 切换到 v0.1.2 版本
git checkout release/v0.1.2

# 或者回退到上一个版本
git checkout release/v0.1.1
```

### 手动回滚
如果需要回滚到 v0.1.1：
1. 删除 `src/python_video_engine/video_exporter.py`
2. 恢复 `main.py` 到 v0.1.1 版本
3. 恢复 `src/python_video_engine/__init__.py` 到 v0.1.1 版本
4. 恢复 `README.md` 到 v0.1.1 版本

## 核心代码变更摘要

### VideoExporter 类（新增）
```python
class VideoExporter:
    def export(self, assembly_plan, video_index) -> VideoExportResult:
        # 加载视频片段
        # 拼接视频
        # 导出 MP4
```

### run_pipeline_mix 函数（新增）
```python
def run_pipeline_mix(base_path, client_name, target_duration_seconds, 
                     output_dir, progress, video_count):
    # 扫描素材
    # 组装片段
    # 导出 MP4
```

## 性能指标

### 混剪模式性能
- 30秒视频：约 10-30 秒生成时间
- 60秒视频：约 20-60 秒生成时间
- 批量生成：每个视频间隔 2 秒

### 完整视频模式性能（不变）
- 30秒视频：约 1-2 分钟（含 AI 生成和 TTS）
- 60秒视频：约 2-3 分钟

## 文件大小
- 混剪视频：约 10-50 MB/视频（取决于素材质量）
- 剪映草稿：约 5-20 MB/草稿

## 维护者
- 开发者：Claude (Anthropic)
- 日期：2026-05-05

## 下一步计划
- [ ] 添加更多视频时长选项（60-90秒、90-120秒）
- [ ] 支持自定义片段时长范围
- [ ] 添加视频转场效果
- [ ] 支持背景音乐添加
- [ ] 优化视频导出速度
