# 贡献指南

感谢你对租赁租房合同审核 Agent 项目的关注！我们欢迎各种形式的贡献。

## 如何贡献

### 报告问题

如果你发现了 bug 或有新的功能建议，请在 GitHub 上提交 Issue。

### 提交代码

1. **Fork 本仓库**
2. **创建特性分支** (`git checkout -b feature/AmazingFeature`)
3. **提交更改** (`git commit -m 'Add some AmazingFeature'`)
4. **推送到分支** (`git push origin feature/AmazingFeature`)
5. **提交 Pull Request**

### 开发环境设置

#### 后端开发

```powershell
cd backend
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 前端开发

```powershell
cd frontend
npm install
npm run dev
```

### 代码规范

- Python 代码遵循 PEP 8 规范
- Vue 代码遵循项目现有的代码风格
- 提交信息请使用清晰的描述

### 提交信息规范

请使用以下格式：

```
<type>(<scope>): <subject>

<body>

<footer>
```

类型（type）：
- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档更新
- `style`: 代码格式调整（不影响功能）
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具相关

示例：
```
feat(review): 添加城市本地化审查功能

支持根据不同城市的租赁规范进行差异化审查
```

## 行为准则

- 尊重所有贡献者
- 保持友好和建设性的讨论
- 关注最适合项目的方案

## 联系方式

如有问题，请通过 GitHub Issues 联系我们。
