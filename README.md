# 词加加 WordPlusPlus

一个手机号登录的背单词网站：每天 30 个新词 + 艾宾浩斯复习，支持自定义词库和单词配图。

## 功能

- 手机号 + 密码注册登录，每个账号独立保存数据
- 1800 个单词，每天 30 个新词
- 艾宾浩斯复习：第 1、2、4、7、15、30 天
- 随机乱序背词，答错循环复习直到全部答对
- 选择题 / 手打答案 / 自测三种模式
- 自定义词库，可添加单词或短语
- 单词配图，从手机相册添加
- 管理员可管理注册名额和账号

## 技术栈

- Python / Flask
- SQLite
- HTML / CSS / JavaScript

## 本地运行

```bash
pip install -r requirements.txt
python app.py
```

默认端口：8002

## 部署

见 [DEPLOY.md](DEPLOY.md)。

## 文件说明

- `app.py`：后端登录、数据、管理员接口
- `index.html`：前端页面（包含 1800 词数据）
- `requirements.txt`：依赖
- `DEPLOY.md`：部署到 PythonAnywhere 的步骤
