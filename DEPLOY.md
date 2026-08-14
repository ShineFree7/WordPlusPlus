# 部署到 PythonAnywhere

## 第 0 步：先备份旧数据库

上线新版本前，先把服务器上现有的 `official.db` 下载备份一份，万一出错可以恢复：

1. 打开 https://www.pythonanywhere.com 并登录（用户名 qiwenci）
2. 进入 **Files** 页面
3. 找到 `/home/qiwenci/wordapp/official.db`，下载到本地保存
4. 确认旧账号、学习进度、自定义词库都在这个备份里

## 第 1 步：上传新版代码

1. 把 `deploy.zip` 上传到 `/home/qiwenci/` 目录下
2. 进入 **Consoles** 页面
3. 点 **Start a new console** → **Bash**
4. 逐条粘贴执行：

```bash
cd /home/qiwenci
unzip -o deploy.zip -d wordapp
cd wordapp
python3.10 -m venv venv
venv/bin/pip install flask
```

> 不要删除服务器上已有的 `official.db`，新版会自动给旧表补字段，不重建表。
> 首次启动时，会自动清除所有账号 state 里的旧图片数据（`wordImages`），释放数据库空间。

## 第 2 步：配置管理员手机号

在 Bash 里创建 `admin_phone.txt`，把 `13xxxxxxxxx` 换成你自己的 11 位手机号：

```bash
cd /home/qiwenci/wordapp
echo '13xxxxxxxxx' > admin_phone.txt
```

规则：

- 只有这个手机号是管理员，启动时会自动把其他账号降为普通用户
- 新注册的人一律是普通用户，不再“第一个注册者是管理员”
- 没有“转移管理员 / 添加第二个管理员”功能
- 注册管理员账号时，密码必须至少 12 位，包含大小写字母、数字和符号

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

先用你自己的手机号注册（密码按管理员要求设强密码），然后到“设置 → 管理员”里：

- 想换密码就在“设置 → 修改密码”里改，管理员也一样，比如 `WoyaoKaobenke7!`
- 查看数据库大小、注册人数 / 名额、每人词库数 / 单词数
- 看“总用量 / 免费额度”的百分比：默认免费额度按 PythonAnywhere 免费版 512 MB 计算，达到 70% 变黄、90% 变红
- 如果以后换了套餐或服务器，额度变了，可以用环境变量 `FREE_STORAGE_MB` 修改（例如 `FREE_STORAGE_MB=1024`）
- 把名额改成实际人数，或填 0 表示不限
- 给每个同学账号写备注（姓名 / 来源）
- 维护全局释义修正

如果之后要再次更新代码，重复“第 0 步备份”和“第 1 步上传”，`official.db` 保留不动即可。
