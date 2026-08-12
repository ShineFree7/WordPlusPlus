# 部署到 PythonAnywhere

## 第 1 步：上传 deploy.zip

1. 打开 https://www.pythonanywhere.com 并登录（用户名 qiwenci）
2. 进入 **Files** 页面
3. 把 `deploy.zip` 上传到 `/home/qiwenci/` 目录下

## 第 2 步：打开 Bash 控制台

1. 进入 **Consoles** 页面
2. 点 **Start a new console** → **Bash**
3. 逐条粘贴执行：

```bash
cd /home/qiwenci
unzip -o deploy.zip -d wordapp
cd wordapp
python3.10 -m venv venv
venv/bin/pip install flask
```

## 第 3 步：创建网站

1. 进入 **Web** 页面
2. 点 **Add a new web app**
3. 选 **Manual configuration**
4. Python 版本选 **3.10**
5. 虚拟环境填：`/home/qiwenci/wordapp/venv`
6. 源码目录填：`/home/qiwenci/wordapp`
7. 完成后编辑 WSGI 文件，内容改为：

```python
import sys
sys.path.insert(0, "/home/qiwenci/wordapp")
from app import app as application
```

8. 点 **Reload**

## 完成

打开：

```
https://qiwenci.pythonanywhere.com
```

第一个注册的手机号是管理员，最多 7 个账号。
